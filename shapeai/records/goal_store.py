"""用户目标存储模块。

使用 PostgreSQL 持久化存储用户目标，支持进度追踪。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class UserGoal:
    """用户目标数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    goal_type: str = ""  # weight_loss / body_fat / muscle_gain / exercise_frequency
    target_value: float = 0.0
    current_value: Optional[float] = None
    unit: Optional[str] = None
    start_value: Optional[float] = None
    deadline: Optional[date] = None
    status: str = "active"  # active / achieved / abandoned
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "goal_type": self.goal_type,
            "target_value": self.target_value,
            "current_value": self.current_value,
            "unit": self.unit,
            "start_value": self.start_value,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def progress_percentage(self) -> float:
        """计算目标完成百分比。"""
        if self.start_value is None or self.current_value is None:
            return 0.0
        if self.target_value == self.start_value:
            return 100.0 if self.current_value == self.target_value else 0.0
        progress = (self.start_value - self.current_value) / (self.start_value - self.target_value)
        return max(0.0, min(100.0, progress * 100))


class GoalStore:
    """用户目标存储器。"""

    def create_goal(self, goal: UserGoal) -> Optional[int]:
        """创建新目标。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO user_goals
                    (user_id, goal_type, target_value, current_value, unit,
                     start_value, deadline, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    RETURNING id
                """, (
                    goal.user_id, goal.goal_type, goal.target_value,
                    goal.current_value, goal.unit, goal.start_value,
                    goal.deadline, goal.status,
                ))
                row = cur.fetchone()
                goal_id = row[0] if row else None
                logger.info("目标已创建: user=%s type=%s id=%s",
                            goal.user_id, goal.goal_type, goal_id)
                return goal_id
        except Exception as exc:
            logger.error("创建目标失败: %s", exc)
            return None

    def update_goal(self, goal_id: int, updates: dict) -> bool:
        """更新目标。"""
        allowed = {"target_value", "current_value", "unit", "start_value",
                   "deadline", "status"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        try:
            with pg_cursor() as cur:
                set_clause = ", ".join(f"{k} = %s" for k in fields.keys())
                values = list(fields.values()) + [goal_id]
                cur.execute(f"""
                    UPDATE user_goals
                    SET {set_clause}, updated_at = now()
                    WHERE id = %s
                """, values)
                return True
        except Exception as exc:
            logger.error("更新目标失败: %s", exc)
            return False

    def get_user_goals(self, user_id: str, status: Optional[str] = None) -> List[UserGoal]:
        """获取用户目标列表。"""
        try:
            with pg_cursor(commit=False) as cur:
                if status:
                    cur.execute("""
                        SELECT id, user_id, goal_type, target_value, current_value,
                               unit, start_value, deadline, status, created_at, updated_at
                        FROM user_goals
                        WHERE user_id = %s AND status = %s
                        ORDER BY created_at DESC
                    """, (user_id, status))
                else:
                    cur.execute("""
                        SELECT id, user_id, goal_type, target_value, current_value,
                               unit, start_value, deadline, status, created_at, updated_at
                        FROM user_goals
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                    """, (user_id,))
                rows = cur.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except Exception as exc:
            logger.error("查询目标失败: %s", exc)
            return []

    def get_progress_summary(self, user_id: str) -> dict:
        """获取目标进度汇总。"""
        goals = self.get_user_goals(user_id, status="active")
        if not goals:
            return {"active_goals": 0, "goals": []}

        result = []
        for g in goals:
            d = g.to_dict()
            d["progress_percentage"] = round(g.progress_percentage(), 1)
            result.append(d)

        return {
            "active_goals": len(result),
            "goals": result,
        }

    @staticmethod
    def _row_to_goal(row) -> UserGoal:
        return UserGoal(
            id=row[0], user_id=row[1], goal_type=row[2], target_value=row[3],
            current_value=row[4], unit=row[5], start_value=row[6],
            deadline=row[7], status=row[8], created_at=row[9], updated_at=row[10],
        )
