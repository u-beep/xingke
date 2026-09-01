"""会话持久化存储 — PostgreSQL + Redis 双层。

PostgreSQL 持久化会话元数据和消息历史，
Redis 缓存热会话（短期记忆 + 最近消息），加速读取。

架构:
  sessions 表       — 会话元数据 (id, user_id, created_at, memory, user_profile)
  messages 表       — 消息历史 (id, session_id, role, name, args, content, ...)
  Redis shapeai:session:{id}  — 热缓存 (完整 session JSON，TTL 1小时)

写入流程: save() → 写 Redis 缓存 + UPSERT PostgreSQL
读取流程: load() → 先查 Redis → 未命中查 PostgreSQL → 回填 Redis
"""

import json
import uuid
import logging
from datetime import datetime, timezone

from ..config import SESSIONS_DIR

logger = logging.getLogger(__name__)


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    """生成新的会话 ID。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def create_session(user_id: str = "anonymous", user_profile: dict | None = None) -> dict:
    """创建新会话。"""
    return {
        "id": new_session_id(),
        "user_id": user_id,
        "created_at": now_iso(),
        "history": [],
        "memory": {
            "short_term": [],      # 单轮对话上下文
            "mid_term": {},        # 近期健康状态
            "long_term": {},       # 用户画像标签
        },
        "user_profile": user_profile or {},
    }


class SessionStore:
    """PostgreSQL + Redis 双层会话存储。

    自动检测数据库是否可用：
    - 可用时使用 PostgreSQL + Redis
    - 不可用时回退到文件系统（兼容旧逻辑）
    """

    def __init__(self, root=None):
        """初始化会话存储。

        Args:
            root: 文件系统回退目录（数据库不可用时使用）
        """
        from pathlib import Path
        self.root = Path(root) if root else SESSIONS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

        self._db_mode = False
        try:
            from ..database import pg_cursor, redis_client
            # 测试连接
            with pg_cursor(commit=False) as cur:
                cur.execute("SELECT 1")
            redis_client().ping()
            self._db_mode = True
            logger.info("SessionStore 使用 PostgreSQL + Redis 模式")
        except Exception as exc:
            logger.warning("SessionStore 回退到文件系统模式: %s", exc)

    # ─── 内部工具 ───

    @staticmethod
    def _redis_key(session_id: str) -> str:
        return f"shapeai:session:{session_id}"

    @staticmethod
    def _redis_client():
        from ..database import redis_client
        return redis_client()

    @staticmethod
    def _pg_cursor(commit=True):
        from ..database import pg_cursor
        return pg_cursor(commit=commit)

    # ─── 核心方法 ───

    def path(self, session_id: str):
        """文件系统路径（回退模式使用）。"""
        return self.root / f"{session_id}.json"

    def save(self, session: dict):
        """保存会话。

        数据库模式:
        1. UPSERT sessions 表 (memory, user_profile)
        2. 写入 messages 表 (只追加新增的消息)
        3. 写 Redis 缓存 (完整 session JSON, TTL 1h)
        """
        if not self._db_mode:
            return self._save_file(session)

        session_id = session["id"]

        # 1. Redis 缓存
        try:
            r = self._redis_client()
            r.setex(
                self._redis_key(session_id),
                3600,
                json.dumps(session, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning("Redis 缓存写入失败: %s", exc)

        # 2. PostgreSQL 持久化
        try:
            with self._pg_cursor() as cur:
                # UPSERT 会话
                cur.execute("""
                    INSERT INTO sessions (id, user_id, created_at, memory, user_profile)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        memory = EXCLUDED.memory,
                        user_profile = EXCLUDED.user_profile
                """, (
                    session_id,
                    session.get("user_id", "anonymous"),
                    session.get("created_at", now_iso()),
                    json.dumps(session.get("memory", {}), ensure_ascii=False),
                    json.dumps(session.get("user_profile", {}), ensure_ascii=False),
                ))

                # 同步消息：先删除旧的再插入全部（history 为空时同样删除，
                # 否则 clear_history 置空历史后旧消息仍留在库中，缓存失效后"复活"）
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
                history = session.get("history", [])
                if history:
                    args_list = []
                    for msg in history:
                        args_list.append((
                            session_id,
                            msg.get("role", ""),
                            msg.get("name"),
                            json.dumps(msg.get("args", {}), ensure_ascii=False),
                            msg.get("content", ""),
                            msg.get("retry", False),
                        ))
                    cur.executemany("""
                        INSERT INTO messages (session_id, role, name, args, content, is_retry)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, args_list)
        except Exception as exc:
            logger.error("PostgreSQL 保存会话失败: %s", exc)
            raise

        return self.path(session_id)

    def load(self, session_id: str) -> dict:
        """恢复会话。

        先查 Redis 缓存 → 未命中查 PostgreSQL → 回填 Redis
        """
        if not self._db_mode:
            return self._load_file(session_id)

        # 1. Redis 缓存
        try:
            r = self._redis_client()
            cached = r.get(self._redis_key(session_id))
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning("Redis 缓存读取失败: %s", exc)

        # 2. PostgreSQL 查询
        try:
            with self._pg_cursor(commit=False) as cur:
                # 查会话元数据
                cur.execute("""
                    SELECT id, user_id, created_at, memory, user_profile
                    FROM sessions WHERE id = %s
                """, (session_id,))
                row = cur.fetchone()
                if row is None:
                    raise FileNotFoundError(f"会话 {session_id} 不存在")

                # 查消息历史
                cur.execute("""
                    SELECT role, name, args, content, is_retry
                    FROM messages WHERE session_id = %s
                    ORDER BY id ASC
                """, (session_id,))
                msg_rows = cur.fetchall()

            # 组装 session 字典
            session = {
                "id": row[0],
                "user_id": row[1],
                "created_at": row[2].isoformat() if row[2] else now_iso(),
                "memory": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
                "user_profile": row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
                "history": [],
            }
            for m in msg_rows:
                msg = {"role": m[0], "content": m[3] or ""}
                if m[1]:
                    msg["name"] = m[1]
                if m[2]:
                    msg["args"] = m[2] if isinstance(m[2], dict) else json.loads(m[2] or "{}")
                if m[4]:
                    msg["retry"] = True
                session["history"].append(msg)

            # 3. 回填 Redis
            try:
                r = self._redis_client()
                r.setex(self._redis_key(session_id), 3600,
                        json.dumps(session, ensure_ascii=False))
            except Exception:
                pass

            return session
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.error("PostgreSQL 加载会话失败: %s", exc)
            raise

    def delete(self, session_id: str) -> bool:
        """删除会话。"""
        if not self._db_mode:
            path = self.path(session_id)
            if path.exists():
                path.unlink()
                return True
            return False

        # 删 Redis
        try:
            self._redis_client().delete(self._redis_key(session_id))
        except Exception:
            pass

        # 删 PostgreSQL (ON DELETE CASCADE 会自动删 messages)
        try:
            with self._pg_cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
                return cur.rowcount > 0
        except Exception as exc:
            logger.error("PostgreSQL 删除会话失败: %s", exc)
            return False

    def list_sessions(self, user_id: str | None = None) -> list[dict]:
        """列出所有会话摘要。"""
        if not self._db_mode:
            return self._list_sessions_file(user_id)

        try:
            with self._pg_cursor(commit=False) as cur:
                if user_id:
                    cur.execute("""
                        SELECT s.id, s.user_id, s.created_at, COUNT(m.id) as msg_count
                        FROM sessions s LEFT JOIN messages m ON s.id = m.session_id
                        WHERE s.user_id = %s
                        GROUP BY s.id, s.user_id, s.created_at
                        ORDER BY s.created_at DESC
                    """, (user_id,))
                else:
                    cur.execute("""
                        SELECT s.id, s.user_id, s.created_at, COUNT(m.id) as msg_count
                        FROM sessions s LEFT JOIN messages m ON s.id = m.session_id
                        GROUP BY s.id, s.user_id, s.created_at
                        ORDER BY s.created_at DESC
                    """)
                rows = cur.fetchall()

            return [{
                "id": row[0],
                "user_id": row[1],
                "created_at": row[2].isoformat() if row[2] else "",
                "message_count": row[3],
            } for row in rows]
        except Exception as exc:
            logger.error("PostgreSQL 列出会话失败: %s", exc)
            return []

    def list_by_date(self, user_id: str, date_str: str | None = None) -> list[dict]:
        """按日期列出会话摘要。

        Args:
            user_id: 用户ID
            date_str: 日期字符串 YYYY-MM-DD（本地日期），None 时默认今天
        Returns:
            会话摘要列表
        """
        from datetime import datetime, timedelta, timezone
        # 服务器本地时区（aware），用于把"本地当天 0 点 ~ 次日 0 点"正确映射到 UTC
        local_tz = datetime.now().astimezone().tzinfo
        if date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=local_tz)
        else:
            target_date = datetime.now(local_tz)
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        # PG created_at 列是 timestamptz（存 UTC），用 aware 时间比较避免被当作 UTC 解释错区间
        day_start_utc = day_start.astimezone(timezone.utc)
        day_end_utc = day_end.astimezone(timezone.utc)

        if not self._db_mode:
            # 文件系统模式：按 created_at 过滤（created_at 是 UTC，需转本地时间比较）
            sessions = self._list_sessions_file(user_id)
            result = []
            for s in sessions:
                try:
                    created = s["created_at"]
                    if not created:
                        continue
                    # 解析 ISO 时间（可能带时区）
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    # 转成本地时间
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    else:
                        # 无时区信息，假设是 UTC
                        dt = dt.replace(tzinfo=timezone.utc).astimezone()
                    # 用 aware 比较（day_start/day_end 也是 aware）
                    if day_start <= dt < day_end:
                        result.append(s)
                except Exception:
                    continue
            return result

        try:
            with self._pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT s.id, s.user_id, s.created_at, COUNT(m.id) as msg_count
                    FROM sessions s LEFT JOIN messages m ON s.id = m.session_id
                    WHERE s.user_id = %s AND s.created_at >= %s AND s.created_at < %s
                    GROUP BY s.id, s.user_id, s.created_at
                    ORDER BY s.created_at ASC
                """, (user_id, day_start_utc, day_end_utc))
                rows = cur.fetchall()

            return [{
                "id": row[0],
                "user_id": row[1],
                "created_at": row[2].isoformat() if row[2] else "",
                "message_count": row[3],
            } for row in rows]
        except Exception as exc:
            logger.error("PostgreSQL 按日期列出会话失败: %s", exc)
            return []

    def get_or_create_today(self, user_id: str, user_profile: dict | None = None) -> dict:
        """获取或创建当天的会话（合并所有当天会话的消息）。

        如果今天已有会话，按创建时间顺序合并所有会话的消息历史。
        如果今天没有会话，返回空会话（不创建新会话），
        前端拿到空历史后会发问候，用户发消息时才创建新会话。

        Args:
            user_id: 用户ID
            user_profile: 用户画像
        Returns:
            会话字典（合并后的完整历史）
        """
        today_sessions = self.list_by_date(user_id)

        if not today_sessions:
            # 今天没有对话，返回空会话（不创建新会话）
            # 前端发消息时 /send 会自动创建新会话
            session = create_session(user_id, user_profile)
            # 不保存到数据库，仅返回空会话供前端使用
            logger.info("今天无对话，返回空会话供前端展示")
            return session

        # 合并所有当天会话的消息
        merged_history = []
        latest_session = None
        latest_memory = {}
        latest_profile = {}

        for sess_summary in today_sessions:
            try:
                sess = self.load(sess_summary["id"])
                history = sess.get("history", [])
                merged_history.extend(history)
                # 使用最新会话的记忆和画像
                latest_session = sess
                latest_memory = sess.get("memory", {})
                latest_profile = sess.get("user_profile", {})
            except Exception as exc:
                logger.warning("加载会话 %s 失败: %s", sess_summary["id"], exc)
                continue

        if not latest_session:
            # 所有会话都加载失败，创建新会话
            session = create_session(user_id, user_profile)
            self.save(session)
            return session

        # 构建合并后的会话（使用最新会话的 ID，这样后续对话会追加到最新会话）
        merged_session = {
            "id": latest_session["id"],
            "user_id": user_id,
            "created_at": latest_session.get("created_at", now_iso()),
            "history": merged_history,
            "memory": latest_memory,
            "user_profile": latest_profile,
        }

        logger.info("合并当天会话: %d 个会话, %d 条消息, 使用会话 %s",
                    len(today_sessions), len(merged_history), latest_session["id"])
        return merged_session

    def get_by_date(self, user_id: str, date_str: str) -> dict:
        """按日期获取合并后的会话历史（与 get_or_create_today 相同格式）。

        Args:
            user_id: 用户ID
            date_str: 日期字符串 YYYY-MM-DD
        Returns:
            会话字典（合并后的完整历史）
        """
        sessions = self.list_by_date(user_id, date_str)
        if not sessions:
            return {
                "id": "",
                "user_id": user_id,
                "created_at": "",
                "history": [],
                "memory": {},
                "user_profile": {},
            }

        merged_history = []
        latest_session = None
        latest_memory = {}
        latest_profile = {}

        for sess_summary in sessions:
            try:
                sess = self.load(sess_summary["id"])
                merged_history.extend(sess.get("history", []))
                latest_session = sess
                latest_memory = sess.get("memory", {})
                latest_profile = sess.get("user_profile", {})
            except Exception as exc:
                logger.warning("加载会话 %s 失败: %s", sess_summary["id"], exc)
                continue

        if not latest_session:
            return {
                "id": "",
                "user_id": user_id,
                "created_at": "",
                "history": [],
                "memory": {},
                "user_profile": {},
            }

        merged_session = {
            "id": latest_session["id"],
            "user_id": user_id,
            "created_at": latest_session.get("created_at", now_iso()),
            "history": merged_history,
            "memory": latest_memory,
            "user_profile": latest_profile,
        }
        logger.info("合并 %s 会话: %d 个会话, %d 条消息",
                    date_str, len(sessions), len(merged_history))
        return merged_session

    def latest(self, user_id: str | None = None) -> str | None:
        """获取最近的会话 ID。"""
        sessions = self.list_sessions(user_id)
        return sessions[0]["id"] if sessions else None

    def clear_history(self, session_id: str) -> dict:
        """清空会话历史但保留会话。"""
        session = self.load(session_id)
        session["history"] = []
        session["memory"]["short_term"] = []
        self.save(session)
        return session

    def clear_by_date(self, user_id: str, date_str: str | None = None) -> list[str]:
        """清空用户指定日期的所有会话历史（当天可能存在多个会话）。

        Args:
            user_id: 用户ID
            date_str: 日期字符串 YYYY-MM-DD，None 时默认今天
        Returns:
            成功清空的会话 ID 列表
        """
        sessions = self.list_by_date(user_id, date_str)
        cleared_ids: list[str] = []
        for summary in sessions:
            try:
                self.clear_history(summary["id"])
                cleared_ids.append(summary["id"])
            except Exception as exc:
                logger.warning("清空会话 %s 失败: %s", summary["id"], exc)
        logger.info("按日期清空会话: user=%s date=%s 清空 %d/%d 个会话",
                    user_id, date_str or "今天", len(cleared_ids), len(sessions))
        return cleared_ids

    # ─── 文件系统回退方法 ───

    def _save_file(self, session: dict):
        import json
        path = self.path(session["id"])
        path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _load_file(self, session_id: str) -> dict:
        import json
        path = self.path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"会话 {session_id} 不存在")
        return json.loads(path.read_text(encoding="utf-8"))

    def _list_sessions_file(self, user_id: str | None = None) -> list[dict]:
        import json
        sessions = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if user_id and data.get("user_id") != user_id:
                    continue
                sessions.append({
                    "id": data["id"],
                    "user_id": data.get("user_id", "anonymous"),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("history", [])),
                })
            except Exception:
                continue
        return sessions
