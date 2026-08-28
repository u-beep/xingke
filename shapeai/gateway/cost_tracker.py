"""Token 消耗统计与额度管控 — PostgreSQL 持久化版。

按用户、接口、场景维度统计 Token 消耗，
支持单用户每日调用上限和单月额度限制。

数据存储:
  PostgreSQL usage_records 表 — 持久化所有调用记录
  内存缓存 — 高频查询结果缓存，避免频繁查库
"""

import time
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """单次调用用量记录。"""
    user_id: str
    endpoint: str
    scene: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: float = field(default_factory=time.time)


class CostTracker:
    """Token 消耗追踪器。

    线程安全，支持按用户/接口/场景维度统计。
    可配置每日/每月调用上限。

    数据库可用时：写入 PostgreSQL，查询也走 PostgreSQL。
    数据库不可用时：回退到内存列表。
    """

    def __init__(self, daily_limit: int = 0, monthly_limit: int = 0):
        """初始化成本追踪器。

        Args:
            daily_limit: 单用户每日 Token 上限，0 表示不限制
            monthly_limit: 单用户每月 Token 上限，0 表示不限制
        """
        self._lock = Lock()
        self._records: list[UsageRecord] = []  # 内存回退
        self._daily_limit = daily_limit
        self._monthly_limit = monthly_limit

        self._db_mode = False
        try:
            from ..database import pg_cursor
            with pg_cursor(commit=False) as cur:
                cur.execute("SELECT 1")
            self._db_mode = True
            logger.info("CostTracker 使用 PostgreSQL 模式")
        except Exception as exc:
            logger.warning("CostTracker 回退到内存模式: %s", exc)

    def record(self, user_id: str, endpoint: str, scene: str, model: str,
               input_tokens: int, output_tokens: int) -> UsageRecord:
        """记录一次模型调用用量。"""
        total = input_tokens + output_tokens
        record = UsageRecord(
            user_id=user_id, endpoint=endpoint, scene=scene, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total,
        )

        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor() as cur:
                    cur.execute("""
                        INSERT INTO usage_records
                            (user_id, endpoint, scene, model, input_tokens, output_tokens, total_tokens)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (user_id, endpoint, scene, model, input_tokens, output_tokens, total))
            except Exception as exc:
                logger.error("PostgreSQL 记录用量失败，回退内存: %s", exc)
                with self._lock:
                    self._records.append(record)
        else:
            with self._lock:
                self._records.append(record)

        return record

    def check_quota(self, user_id: str) -> tuple[bool, str]:
        """检查用户是否还有调用额度。"""
        if self._daily_limit <= 0 and self._monthly_limit <= 0:
            return True, ""

        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("""
                        SELECT COALESCE(SUM(total_tokens), 0)
                        FROM usage_records
                        WHERE user_id = %s AND created_at > now() - interval '1 day'
                    """, (user_id,))
                    daily_total = cur.fetchone()[0]

                    cur.execute("""
                        SELECT COALESCE(SUM(total_tokens), 0)
                        FROM usage_records
                        WHERE user_id = %s AND created_at > now() - interval '30 days'
                    """, (user_id,))
                    monthly_total = cur.fetchone()[0]
            except Exception as exc:
                logger.error("PostgreSQL 额度查询失败，回退内存: %s", exc)
                return self._check_quota_memory(user_id)
        else:
            return self._check_quota_memory(user_id)

        if self._daily_limit > 0 and daily_total >= self._daily_limit:
            return False, f"今日Token额度已用尽({daily_total}/{self._daily_limit})"
        if self._monthly_limit > 0 and monthly_total >= self._monthly_limit:
            return False, f"本月Token额度已用尽({monthly_total}/{self._monthly_limit})"
        return True, ""

    def _check_quota_memory(self, user_id: str) -> tuple[bool, str]:
        """内存模式额度检查。"""
        now = time.time()
        day_ago = now - 86400
        month_ago = now - 86400 * 30

        with self._lock:
            daily_total = sum(r.total_tokens for r in self._records
                              if r.user_id == user_id and r.timestamp > day_ago)
            monthly_total = sum(r.total_tokens for r in self._records
                                if r.user_id == user_id and r.timestamp > month_ago)

        if self._daily_limit > 0 and daily_total >= self._daily_limit:
            return False, f"今日Token额度已用尽({daily_total}/{self._daily_limit})"
        if self._monthly_limit > 0 and monthly_total >= self._monthly_limit:
            return False, f"本月Token额度已用尽({monthly_total}/{self._monthly_limit})"
        return True, ""

    def get_user_stats(self, user_id: str) -> dict:
        """获取用户用量统计。"""
        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("""
                        SELECT COUNT(*), COALESCE(SUM(total_tokens),0),
                               COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0)
                        FROM usage_records WHERE user_id = %s
                    """, (user_id,))
                    row = cur.fetchone()

                    cur.execute("""
                        SELECT scene, COALESCE(SUM(total_tokens),0)
                        FROM usage_records WHERE user_id = %s
                        GROUP BY scene
                    """, (user_id,))
                    scene_rows = cur.fetchall()

                return {
                    "total_calls": row[0],
                    "total_tokens": row[1],
                    "total_input_tokens": row[2],
                    "total_output_tokens": row[3],
                    "by_scene": {r[0] or "unknown": r[1] for r in scene_rows},
                }
            except Exception as exc:
                logger.error("PostgreSQL 用户统计失败: %s", exc)

        # 内存回退
        with self._lock:
            user_records = [r for r in self._records if r.user_id == user_id]
        return {
            "total_calls": len(user_records),
            "total_tokens": sum(r.total_tokens for r in user_records),
            "total_input_tokens": sum(r.input_tokens for r in user_records),
            "total_output_tokens": sum(r.output_tokens for r in user_records),
            "by_scene": dict(defaultdict(int, {
                scene: sum(r.total_tokens for r in user_records if r.scene == scene)
                for scene in {r.scene for r in user_records}
            })),
        }

    def get_global_stats(self) -> dict:
        """获取全局用量统计。"""
        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("""
                        SELECT COUNT(*), COALESCE(SUM(total_tokens),0)
                        FROM usage_records
                    """)
                    row = cur.fetchone()

                    cur.execute("""
                        SELECT model, COALESCE(SUM(total_tokens),0)
                        FROM usage_records GROUP BY model
                    """)
                    model_rows = cur.fetchall()

                    cur.execute("""
                        SELECT user_id, COALESCE(SUM(total_tokens),0)
                        FROM usage_records GROUP BY user_id
                    """)
                    user_rows = cur.fetchall()

                return {
                    "total_calls": row[0],
                    "total_tokens": row[1],
                    "by_model": {r[0] or "unknown": r[1] for r in model_rows},
                    "by_user": {r[0] or "unknown": r[1] for r in user_rows},
                }
            except Exception as exc:
                logger.error("PostgreSQL 全局统计失败: %s", exc)

        # 内存回退
        with self._lock:
            records = list(self._records)
        return {
            "total_calls": len(records),
            "total_tokens": sum(r.total_tokens for r in records),
            "by_model": dict(defaultdict(int, {
                model: sum(r.total_tokens for r in records if r.model == model)
                for model in {r.model for r in records}
            })),
            "by_user": dict(defaultdict(int, {
                uid: sum(r.total_tokens for r in records if r.user_id == uid)
                for uid in {r.user_id for r in records}
            })),
        }

    def get_call_log(self, limit: int = 100) -> list[dict]:
        """获取最近调用日志。"""
        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("""
                        SELECT user_id, endpoint, scene, model,
                               input_tokens, output_tokens, total_tokens, created_at
                        FROM usage_records
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()

                return [{
                    "user_id": r[0],
                    "endpoint": r[1],
                    "scene": r[2],
                    "model": r[3],
                    "input_tokens": r[4],
                    "output_tokens": r[5],
                    "total_tokens": r[6],
                    "timestamp": r[7].timestamp() if r[7] else 0,
                } for r in rows]
            except Exception as exc:
                logger.error("PostgreSQL 调用日志查询失败: %s", exc)

        # 内存回退
        with self._lock:
            records = list(self._records[-limit:])
        return [{
            "user_id": r.user_id,
            "endpoint": r.endpoint,
            "scene": r.scene,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_tokens": r.total_tokens,
            "timestamp": r.timestamp,
        } for r in records]
