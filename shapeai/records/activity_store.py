"""活动与群聊存储模块。

数据模型（5 张表）:
  activities        — 锻炼活动（篮球/跑步/羽毛球...）
  activity_groups   — 活动群聊（与活动一一对应, 创建活动时自动建群）
  activity_members  — 活动参与者（含角色: owner 管理员 / member 普通成员）
  activity_messages — 群聊消息
  （activities.group_id 外键关联 activity_groups.id, 无需额外关联表）

关键流程:
  创建活动 -> 自动建群 + 创建者以 owner 身份入群
  用户加入活动 -> 自动写入群聊成员表
  成员在群聊发消息 -> 写入 activity_messages
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)

# 支持的运动类型（前端下拉选项与后端校验保持一致）
ACTIVITY_SPORT_TYPES = [
    "篮球", "足球", "羽毛球", "乒乓球", "网球",
    "跑步", "骑行", "游泳", "健身", "瑜伽",
    "徒步", "爬山", "滑板", "跳绳", "排球", "其他",
]

# 活动状态
ACTIVITY_STATUS = ["open", "full", "closed", "finished"]

# ─── 数据类 ───


@dataclass
class Activity:
    """锻炼活动。"""
    id: Optional[int] = None
    title: str = ""
    sport_type: str = ""            # 篮球/跑步/羽毛球/...
    city: str = ""                  # 城市
    district: str = ""              # 行政区
    location: str = ""              # 具体地点
    start_time: Optional[datetime] = None  # 活动时间
    max_participants: int = 10      # 人数上限
    description: str = ""           # 活动描述
    creator_id: str = ""            # 发起者 user_id (= username)
    status: str = "open"            # open/full/closed/finished
    group_id: Optional[int] = None  # 关联群聊
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "sport_type": self.sport_type,
            "city": self.city,
            "district": self.district,
            "location": self.location,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "max_participants": self.max_participants,
            "description": self.description,
            "creator_id": self.creator_id,
            "status": self.status,
            "group_id": self.group_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ActivityGroup:
    """活动群聊（与活动一一对应）。"""
    id: Optional[int] = None
    activity_id: Optional[int] = None
    group_name: str = ""
    announcement: str = ""           # 群公告
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "group_name": self.group_name,
            "announcement": self.announcement,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ActivityMember:
    """活动成员（同时也是群聊成员）。"""
    id: Optional[int] = None
    activity_id: Optional[int] = None
    user_id: str = ""
    role: str = "member"             # owner: 管理员(发起者) / member: 普通成员
    nickname: Optional[str] = None   # 冗余昵称, 便于列表展示
    joined_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "user_id": self.user_id,
            "role": self.role,
            "nickname": self.nickname or self.user_id,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


@dataclass
class ActivityMessage:
    """群聊消息。"""
    id: Optional[int] = None
    group_id: Optional[int] = None
    sender_id: str = ""
    sender_nickname: Optional[str] = None
    content: str = ""
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "sender_id": self.sender_id,
            "sender_nickname": self.sender_nickname or self.sender_id,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 建表 SQL（供 migrate.py 与 Store 复用） ───

ACTIVITY_SCHEMA_SQL = """
-- ─── 活动模块建表 SQL ───

-- 锻炼活动表
CREATE TABLE IF NOT EXISTS activities (
    id              BIGSERIAL PRIMARY KEY,
    title           VARCHAR(128) NOT NULL,                -- 活动名称
    sport_type      VARCHAR(32)  NOT NULL,                -- 运动类型(篮球/跑步/...)
    city            VARCHAR(64)  NOT NULL DEFAULT '',     -- 城市
    district        VARCHAR(64)  NOT NULL DEFAULT '',     -- 行政区
    location        VARCHAR(256) NOT NULL DEFAULT '',     -- 具体地点
    start_time      TIMESTAMPTZ  NOT NULL,                -- 活动时间
    max_participants INTEGER      NOT NULL DEFAULT 10,    -- 人数上限
    description     TEXT         NOT NULL DEFAULT '',     -- 活动描述
    creator_id      VARCHAR(64)  NOT NULL,                -- 发起者 user_id
    status          VARCHAR(16)  NOT NULL DEFAULT 'open', -- open/full/closed/finished
    group_id        BIGINT,                               -- 关联群聊(创建群后回填)
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activities_city_district ON activities (city, district);
CREATE INDEX IF NOT EXISTS idx_activities_sport_type   ON activities (sport_type);
CREATE INDEX IF NOT EXISTS idx_activities_start_time   ON activities (start_time DESC);
CREATE INDEX IF NOT EXISTS idx_activities_status       ON activities (status);
CREATE INDEX IF NOT EXISTS idx_activities_creator      ON activities (creator_id);

-- 活动群聊表（与活动一一对应）
CREATE TABLE IF NOT EXISTS activity_groups (
    id            BIGSERIAL PRIMARY KEY,
    activity_id   BIGINT       NOT NULL UNIQUE REFERENCES activities(id) ON DELETE CASCADE,
    group_name    VARCHAR(128) NOT NULL,
    announcement  TEXT         NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activity_groups_activity ON activity_groups (activity_id);

-- 活动成员表（创建者 owner + 加入者 member）
CREATE TABLE IF NOT EXISTS activity_members (
    id           BIGSERIAL PRIMARY KEY,
    activity_id  BIGINT      NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id      VARCHAR(64) NOT NULL,
    role         VARCHAR(16) NOT NULL DEFAULT 'member',  -- owner/member
    nickname     VARCHAR(64),
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (activity_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_members_activity ON activity_members (activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_members_user     ON activity_members (user_id);

-- 群聊消息表
CREATE TABLE IF NOT EXISTS activity_messages (
    id              BIGSERIAL PRIMARY KEY,
    group_id        BIGINT       NOT NULL REFERENCES activity_groups(id) ON DELETE CASCADE,
    sender_id       VARCHAR(64)  NOT NULL,
    sender_nickname VARCHAR(64),
    content         TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activity_messages_group_time ON activity_messages (group_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_messages_sender     ON activity_messages (sender_id);

-- 回填活动 -> 群聊外键（建群后由应用层写入 group_id）
ALTER TABLE activities
    ADD COLUMN IF NOT EXISTS group_id BIGINT REFERENCES activity_groups(id) ON DELETE SET NULL;
"""


class ActivityError(Exception):
    """活动业务异常（带错误码, 供路由层转 HTTP 状态）。"""

    def __init__(self, message: str, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.code = code


# ─── 存储类 ───

class ActivityStore:
    """活动 + 群聊 存储。"""

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """确保活动模块 5 张表存在（与 migrate.py 保持一致）。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute(ACTIVITY_SCHEMA_SQL)
        except Exception as exc:
            logger.error("创建活动模块表失败: %s", exc)

    # ─── 活动 CRUD ───

    def create_activity(
        self,
        creator_id: str,
        title: str,
        sport_type: str,
        city: str,
        district: str,
        location: str,
        start_time: datetime,
        max_participants: int,
        description: str = "",
        creator_nickname: Optional[str] = None,
    ) -> Optional[Activity]:
        """创建活动: 事务内 建活动 -> 建群 -> 回填 group_id -> 创建者入群(owner)。

        Raises:
            ActivityError: 字段不合法
        """
        title = (title or "").strip()
        if not title:
            raise ActivityError("活动名称不能为空")
        if sport_type not in ACTIVITY_SPORT_TYPES:
            raise ActivityError(f"不支持的运动类型: {sport_type}")
        if not city.strip():
            raise ActivityError("城市不能为空")
        if max_participants < 1 or max_participants > 500:
            raise ActivityError("人数上限须在 1-500 之间")
        if start_time is None:
            raise ActivityError("活动时间不能为空")

        try:
            with pg_cursor(commit=True) as cur:
                # 1) 建活动
                cur.execute("""
                    INSERT INTO activities
                        (title, sport_type, city, district, location, start_time,
                         max_participants, description, creator_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
                    RETURNING id, created_at
                """, (title, sport_type, city.strip(), (district or "").strip(),
                      (location or "").strip(), start_time,
                      max_participants, (description or "").strip(), creator_id))
                row = cur.fetchone()
                activity_id, created_at = row[0], row[1]

                # 2) 自动建群（群名与活动同名）
                cur.execute("""
                    INSERT INTO activity_groups (activity_id, group_name)
                    VALUES (%s, %s)
                    RETURNING id
                """, (activity_id, title))
                group_id = cur.fetchone()[0]

                # 3) 回填活动 group_id
                cur.execute("""
                    UPDATE activities SET group_id = %s WHERE id = %s
                """, (group_id, activity_id))

                # 4) 创建者入群, role=owner
                cur.execute("""
                    INSERT INTO activity_members (activity_id, user_id, role, nickname)
                    VALUES (%s, %s, 'owner', %s)
                    ON CONFLICT (activity_id, user_id) DO NOTHING
                """, (activity_id, creator_id, creator_nickname or creator_id))

                logger.info(
                    "活动已创建 id=%s title=%s creator=%s group_id=%s",
                    activity_id, title, creator_id, group_id,
                )
            # 事务提交后再读取（避免读到未提交数据）
            return self.get_activity(activity_id)
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("创建活动失败: %s", exc)
            raise ActivityError("创建活动失败，请稍后重试", "server_error")

    def update_activity(
        self,
        activity_id: int,
        user_id: str,
        **fields,
    ) -> Activity:
        """管理员修改活动（同步更新群名）。

        Raises:
            ActivityError: 无权限 / 活动不存在 / 字段不合法
        """
        activity = self.get_activity(activity_id)
        if not activity:
            raise ActivityError("活动不存在", "not_found")
        self._require_owner(activity_id, user_id)

        allowed = {"title", "sport_type", "city", "district", "location",
                   "start_time", "max_participants", "description", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "title" in updates:
            if not str(updates["title"]).strip():
                raise ActivityError("活动名称不能为空")
        if "sport_type" in updates and updates["sport_type"] not in ACTIVITY_SPORT_TYPES:
            raise ActivityError(f"不支持的运动类型: {updates['sport_type']}")
        if "max_participants" in updates:
            mp = updates["max_participants"]
            if not isinstance(mp, int) or mp < 1 or mp > 500:
                raise ActivityError("人数上限须在 1-500 之间")
            current = self.count_members(activity_id)
            if mp < current:
                raise ActivityError(f"人数上限({mp})不能小于当前已加入人数({current})")

        try:
            with pg_cursor(commit=True) as cur:
                if updates:
                    set_clause = ", ".join(f"{k} = %s" for k in updates)
                    cur.execute(
                        f"UPDATE activities SET {set_clause} WHERE id = %s",
                        (*updates.values(), activity_id),
                    )
                # 群名跟随活动名
                if "title" in updates:
                    cur.execute("""
                        UPDATE activity_groups SET group_name = %s WHERE activity_id = %s
                    """, (updates["title"], activity_id))
            # 事务提交后再读取
            updated = self.get_activity(activity_id)
            logger.info("活动已更新 id=%s by=%s", activity_id, user_id)
            return updated
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("更新活动失败: %s", exc)
            raise ActivityError("更新活动失败", "server_error")

    def delete_activity(self, activity_id: int, user_id: str) -> bool:
        """删除活动（仅发起者; 级联删除群聊/成员/消息）。"""
        activity = self.get_activity(activity_id)
        if not activity:
            raise ActivityError("活动不存在", "not_found")
        self._require_owner(activity_id, user_id)
        try:
            with pg_cursor(commit=True) as cur:
                # 先清 activities.group_id 引用, 让级联删除顺畅
                cur.execute("""
                    UPDATE activities SET group_id = NULL WHERE id = %s
                """, (activity_id,))
                cur.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
            logger.info("活动已删除 id=%s by=%s", activity_id, user_id)
            return True
        except Exception as exc:
            logger.error("删除活动失败: %s", exc)
            raise ActivityError("删除活动失败", "server_error")

    def get_activity(self, activity_id: int) -> Optional[Activity]:
        """按 ID 获取活动。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, title, sport_type, city, district, location,
                           start_time, max_participants, description,
                           creator_id, status, group_id, created_at
                    FROM activities WHERE id = %s
                """, (activity_id,))
                r = cur.fetchone()
                return self._row_to_activity(r) if r else None
        except Exception as exc:
            logger.error("查询活动失败: %s", exc)
            return None

    def list_activities(
        self,
        city: Optional[str] = None,
        district: Optional[str] = None,
        sport_type: Optional[str] = None,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        only_mine: bool = False,
        user_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """活动列表（带实时加入人数, 按开始时间倒序）。

        Returns:
            [{"activity": {...}, "member_count": n}, ...]
        """
        clauses, params = [], []
        if city:
            clauses.append("a.city = %s")
            params.append(city)
        if district:
            clauses.append("a.district = %s")
            params.append(district)
        if sport_type:
            clauses.append("a.sport_type = %s")
            params.append(sport_type)
        if status:
            clauses.append("a.status = %s")
            params.append(status)
        if keyword:
            clauses.append("(a.title ILIKE %s OR a.description ILIKE %s OR a.location ILIKE %s)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        if only_mine and user_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM activity_members m "
                "WHERE m.activity_id = a.id AND m.user_id = %s)"
            )
            params.append(user_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT a.id, a.title, a.sport_type, a.city, a.district, a.location,
                   a.start_time, a.max_participants, a.description,
                   a.creator_id, a.status, a.group_id, a.created_at,
                   (SELECT COUNT(*) FROM activity_members m WHERE m.activity_id = a.id) AS member_count
            FROM activities a{where}
            ORDER BY a.start_time DESC
            LIMIT %s OFFSET %s
        """
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                results = []
                for r in rows:
                    act = self._row_to_activity(r[:13])
                    results.append({
                        "activity": act.to_dict() if act else None,
                        "member_count": r[13],
                    })
                return results
        except Exception as exc:
            logger.error("查询活动列表失败: %s", exc)
            return []

    def list_districts(self, city: Optional[str] = None) -> List[str]:
        """获取有活动的城市/行政区列表（用于筛选项）。"""
        try:
            with pg_cursor(commit=False) as cur:
                if city:
                    cur.execute("""
                        SELECT DISTINCT district FROM activities
                        WHERE city = %s AND district <> '' ORDER BY district
                    """, (city,))
                else:
                    cur.execute("""
                        SELECT DISTINCT city FROM activities
                        WHERE city <> '' ORDER BY city
                    """)
                return [r[0] for r in cur.fetchall()]
        except Exception as exc:
            logger.error("查询城市/行政区失败: %s", exc)
            return []

    # ─── 成员管理 ───

    def join_activity(self, activity_id: int, user_id: str, nickname: Optional[str] = None) -> dict:
        """加入活动（= 加入群聊）。满员/已加入/关闭时抛 ActivityError。"""
        activity = self.get_activity(activity_id)
        if not activity:
            raise ActivityError("活动不存在", "not_found")
        if activity.status not in ("open",):
            raise ActivityError("该活动当前不可加入", "forbidden")

        try:
            with pg_cursor(commit=True) as cur:
                # 人数校验（原子, 防并发超员）
                cur.execute("""
                    SELECT COUNT(*) FROM activity_members WHERE activity_id = %s
                """, (activity_id,))
                count = cur.fetchone()[0]
                if count >= activity.max_participants:
                    raise ActivityError("活动人数已满", "full")
                cur.execute("""
                    INSERT INTO activity_members (activity_id, user_id, role, nickname)
                    VALUES (%s, %s, 'member', %s)
                    ON CONFLICT (activity_id, user_id) DO NOTHING
                """, (activity_id, user_id, nickname or user_id))
                inserted = cur.rowcount > 0
                if not inserted:
                    raise ActivityError("你已经加入过该活动", "conflict")
                # 满员时自动置 full
                if count + 1 >= activity.max_participants:
                    cur.execute("""
                        UPDATE activities SET status = 'full' WHERE id = %s AND status = 'open'
                    """, (activity_id,))
            logger.info("用户加入活动 id=%s user=%s", activity_id, user_id)
            return {
                "success": True,
                "activity_id": activity_id,
                "group_id": activity.group_id,
                "member_count": count + 1,
            }
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("加入活动失败: %s", exc)
            raise ActivityError("加入活动失败", "server_error")

    def leave_activity(self, activity_id: int, user_id: str) -> dict:
        """退出活动（发起者不可退出）。"""
        activity = self.get_activity(activity_id)
        if not activity:
            raise ActivityError("活动不存在", "not_found")
        if activity.creator_id == user_id:
            raise ActivityError("发起者不能退出自己的活动，可选择解散活动", "forbidden")
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    DELETE FROM activity_members
                    WHERE activity_id = %s AND user_id = %s
                """, (activity_id, user_id))
                deleted = cur.rowcount > 0
                if deleted:
                    # 有空位时回滚 full -> open
                    cur.execute("""
                        UPDATE activities SET status = 'open'
                        WHERE id = %s AND status = 'full'
                    """, (activity_id,))
            if not deleted:
                raise ActivityError("你尚未加入该活动", "not_found")
            logger.info("用户退出活动 id=%s user=%s", activity_id, user_id)
            return {"success": True, "activity_id": activity_id}
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("退出活动失败: %s", exc)
            raise ActivityError("退出活动失败", "server_error")

    def remove_member(self, activity_id: int, operator_id: str, target_user_id: str) -> dict:
        """管理员移除成员（不可移除自己/其他管理员）。"""
        activity = self.get_activity(activity_id)
        if not activity:
            raise ActivityError("活动不存在", "not_found")
        self._require_owner(activity_id, operator_id)
        if target_user_id == operator_id:
            raise ActivityError("不能移除自己", "bad_request")
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    DELETE FROM activity_members
                    WHERE activity_id = %s AND user_id = %s AND role = 'member'
                """, (activity_id, target_user_id))
                deleted = cur.rowcount > 0
                if deleted:
                    cur.execute("""
                        UPDATE activities SET status = 'open'
                        WHERE id = %s AND status = 'full'
                    """, (activity_id,))
            if not deleted:
                raise ActivityError("该成员不存在或无权移除", "not_found")
            logger.info("成员被移除 id=%s user=%s by=%s", activity_id, target_user_id, operator_id)
            return {"success": True, "activity_id": activity_id, "removed": target_user_id}
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("移除成员失败: %s", exc)
            raise ActivityError("移除成员失败", "server_error")

    def list_members(self, activity_id: int) -> List[ActivityMember]:
        """成员列表（owner 在前）。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, activity_id, user_id, role, nickname, joined_at
                    FROM activity_members
                    WHERE activity_id = %s
                    ORDER BY role ASC, joined_at ASC
                """, (activity_id,))
                return [
                    ActivityMember(
                        id=r[0], activity_id=r[1], user_id=r[2],
                        role=r[3], nickname=r[4], joined_at=r[5],
                    )
                    for r in cur.fetchall()
                ]
        except Exception as exc:
            logger.error("查询成员列表失败: %s", exc)
            return []

    def count_members(self, activity_id: int) -> int:
        """当前成员数。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM activity_members WHERE activity_id = %s
                """, (activity_id,))
                return cur.fetchone()[0]
        except Exception as exc:
            logger.error("统计成员数失败: %s", exc)
            return 0

    def get_member(self, activity_id: int, user_id: str) -> Optional[ActivityMember]:
        """查询单个成员（判断是否已加入/是否管理员）。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, activity_id, user_id, role, nickname, joined_at
                    FROM activity_members
                    WHERE activity_id = %s AND user_id = %s
                """, (activity_id, user_id))
                r = cur.fetchone()
                if not r:
                    return None
                return ActivityMember(
                    id=r[0], activity_id=r[1], user_id=r[2],
                    role=r[3], nickname=r[4], joined_at=r[5],
                )
        except Exception as exc:
            logger.error("查询成员失败: %s", exc)
            return None

    def _require_owner(self, activity_id: int, user_id: str):
        """校验 user_id 是活动 owner, 否则抛 403。"""
        member = self.get_member(activity_id, user_id)
        if not member or member.role != "owner":
            raise ActivityError("仅活动发起者可执行此操作", "forbidden")

    # ─── 群聊 ───

    def get_group_by_activity(self, activity_id: int) -> Optional[ActivityGroup]:
        """活动对应的群聊。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, activity_id, group_name, announcement, created_at
                    FROM activity_groups WHERE activity_id = %s
                """, (activity_id,))
                r = cur.fetchone()
                if not r:
                    return None
                return ActivityGroup(
                    id=r[0], activity_id=r[1], group_name=r[2],
                    announcement=r[3], created_at=r[4],
                )
        except Exception as exc:
            logger.error("查询群聊失败: %s", exc)
            return None

    def update_group(
        self, activity_id: int, operator_id: str,
        group_name: Optional[str] = None,
        announcement: Optional[str] = None,
    ) -> ActivityGroup:
        """管理员修改群信息（群名/群公告）。"""
        group = self.get_group_by_activity(activity_id)
        if not group:
            raise ActivityError("群聊不存在", "not_found")
        self._require_owner(activity_id, operator_id)
        updates, params = [], []
        if group_name is not None and group_name.strip():
            updates.append("group_name = %s")
            params.append(group_name.strip())
        if announcement is not None:
            updates.append("announcement = %s")
            params.append(announcement.strip())
        if updates:
            try:
                with pg_cursor(commit=True) as cur:
                    cur.execute(
                        f"UPDATE activity_groups SET {', '.join(updates)} WHERE id = %s",
                        (*params, group.id),
                    )
            except Exception as exc:
                logger.error("更新群信息失败: %s", exc)
                raise ActivityError("更新群信息失败", "server_error")
        return self.get_group_by_activity(activity_id)

    def send_message(
        self, group_id: int, sender_id: str, content: str,
        sender_nickname: Optional[str] = None,
    ) -> Optional[ActivityMessage]:
        """发送群聊消息（仅成员可发）。"""
        content = (content or "").strip()
        if not content:
            raise ActivityError("消息内容不能为空")
        if len(content) > 2000:
            raise ActivityError("消息长度不能超过 2000 字")
        # 通过群找活动, 校验成员身份
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT activity_id FROM activity_groups WHERE id = %s
                """, (group_id,))
                row = cur.fetchone()
                if not row:
                    raise ActivityError("群聊不存在", "not_found")
                activity_id = row[0]
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("查询群聊失败: %s", exc)
            raise ActivityError("发送失败", "server_error")

        member = self.get_member(activity_id, sender_id)
        if not member:
            raise ActivityError("仅活动成员可发送消息", "forbidden")

        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO activity_messages
                        (group_id, sender_id, sender_nickname, content)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, group_id, sender_id, sender_nickname, content, created_at
                """, (group_id, sender_id, member.nickname or sender_id, content))
                r = cur.fetchone()
                logger.info("群聊消息 group=%s sender=%s", group_id, sender_id)
                return ActivityMessage(
                    id=r[0], group_id=r[1], sender_id=r[2],
                    sender_nickname=r[3], content=r[4], created_at=r[5],
                )
        except ActivityError:
            raise
        except Exception as exc:
            logger.error("发送群聊消息失败: %s", exc)
            raise ActivityError("发送消息失败", "server_error")

    def list_messages(
        self, group_id: int, user_id: str,
        before_id: Optional[int] = None, limit: int = 50,
    ) -> List[ActivityMessage]:
        """拉取群聊消息（仅成员可看; 支持按 before_id 翻页）。"""
        # 校验成员身份
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT activity_id FROM activity_groups WHERE id = %s
                """, (group_id,))
                row = cur.fetchone()
                if not row:
                    return []
                if not self.get_member(row[0], user_id):
                    return []
        except Exception as exc:
            logger.error("查询群聊失败: %s", exc)
            return []

        clauses = ["group_id = %s"]
        params: list = [group_id]
        if before_id:
            clauses.append("id < %s")
            params.append(before_id)
        params.append(limit)
        sql = f"""
            SELECT id, group_id, sender_id, sender_nickname, content, created_at
            FROM activity_messages
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT %s
        """
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                # 时间正序返回
                return [
                    ActivityMessage(
                        id=r[0], group_id=r[1], sender_id=r[2],
                        sender_nickname=r[3], content=r[4], created_at=r[5],
                    )
                    for r in reversed(rows)
                ]
        except Exception as exc:
            logger.error("查询群聊消息失败: %s", exc)
            return []

    def list_my_activities(self, user_id: str) -> List[dict]:
        """我加入/发起的活动（含 role）。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT a.id, a.title, a.sport_type, a.city, a.district, a.location,
                           a.start_time, a.max_participants, a.description,
                           a.creator_id, a.status, a.group_id, a.created_at,
                           m.role,
                           (SELECT COUNT(*) FROM activity_members m2
                            WHERE m2.activity_id = a.id) AS member_count
                    FROM activities a
                    JOIN activity_members m ON m.activity_id = a.id
                    WHERE m.user_id = %s
                    ORDER BY a.start_time DESC
                """, (user_id,))
                rows = cur.fetchall()
                results = []
                for r in rows:
                    act = self._row_to_activity(r[:13])
                    results.append({
                        "activity": act.to_dict() if act else None,
                        "role": r[13],
                        "member_count": r[14],
                    })
                return results
        except Exception as exc:
            logger.error("查询我的活动失败: %s", exc)
            return []

    # ─── 工具 ───

    @staticmethod
    def _row_to_activity(row) -> Optional[Activity]:
        if not row:
            return None
        return Activity(
            id=row[0], title=row[1], sport_type=row[2], city=row[3],
            district=row[4], location=row[5], start_time=row[6],
            max_participants=row[7], description=row[8], creator_id=row[9],
            status=row[10], group_id=row[11], created_at=row[12],
        )
