"""运动计划存储模块。

使用 PostgreSQL 存储用户每日运动计划，支持按日期查询和热量计算。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)

# ─── 运动类型 MET 值（代谢当量，用于计算热量消耗）───
# MET × 体重(kg) × 时长(h) = 消耗热量(kcal)
EXERCISE_MET = {
    # 有氧运动
    "跑步": 9.8,
    "快走": 4.3,
    "游泳": 8.0,
    "骑车": 7.5,
    "跳绳": 12.0,
    "椭圆机": 5.0,
    "划船机": 7.0,
    "爬楼梯": 8.8,
    "健身操": 6.0,
    "跳舞": 5.5,
    "羽毛球": 5.5,
    "篮球": 6.5,
    "足球": 7.0,
    "乒乓球": 4.0,
    "网球": 7.3,
    # 力量训练
    "杠铃深蹲": 6.0,
    "硬拉": 6.0,
    "卧推": 5.0,
    "哑铃训练": 4.5,
    "器械训练": 4.5,
    "俯卧撑": 3.8,
    "引体向上": 4.0,
    # 无氧/核心
    "HIIT": 10.0,
    "波比跳": 9.0,
    "平板支撑": 3.5,
    "卷腹": 3.5,
    "俄罗斯转体": 4.0,
}


@dataclass
class ExercisePlanItem:
    """运动计划单项。"""
    id: Optional[int] = None
    user_id: str = ""
    plan_date: str = ""  # YYYY-MM-DD
    exercise_type: str = ""  # cardio / strength / anaerobic
    exercise_name: str = ""
    duration_min: int = 30
    calories_burned: Optional[float] = None
    completed: bool = False
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan_date": self.plan_date,
            "exercise_type": self.exercise_type,
            "exercise_name": self.exercise_name,
            "duration_min": self.duration_min,
            "calories_burned": self.calories_burned,
            "completed": self.completed,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class ExercisePlanStore:
    """运动计划存储。"""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """确保表存在。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS exercise_plans (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(64) NOT NULL,
                        plan_date DATE NOT NULL,
                        exercise_type VARCHAR(32) NOT NULL DEFAULT 'cardio',
                        exercise_name VARCHAR(128) NOT NULL,
                        duration_min INTEGER NOT NULL DEFAULT 30,
                        calories_burned FLOAT DEFAULT 0,
                        completed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_exercise_plans_user_date
                    ON exercise_plans(user_id, plan_date)
                """)
        except Exception as exc:
            logger.error("创建 exercise_plans 表失败: %s", exc)

    @staticmethod
    def calc_calories(exercise_name: str, duration_min: int, weight_kg: float = 71.5) -> float:
        """根据运动名称和时长计算热量消耗。

        公式: MET × 体重(kg) × 时长(h) = kcal
        """
        met = EXERCISE_MET.get(exercise_name, 5.0)  # 默认 MET=5
        hours = duration_min / 60.0
        return round(met * weight_kg * hours, 1)

    def add_item(self, item: ExercisePlanItem) -> Optional[int]:
        """添加运动计划项。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO exercise_plans
                        (user_id, plan_date, exercise_type, exercise_name, duration_min, calories_burned, completed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    item.user_id,
                    item.plan_date,
                    item.exercise_type,
                    item.exercise_name,
                    item.duration_min,
                    item.calories_burned or self.calc_calories(item.exercise_name, item.duration_min),
                    item.completed,
                ))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as exc:
            logger.error("添加运动计划失败: %s", exc)
            return None

    def get_today_items(self, user_id: str) -> List[ExercisePlanItem]:
        """获取今日运动计划。"""
        return self.get_items_by_date(user_id, datetime.now().strftime("%Y-%m-%d"))

    def get_items_by_date(self, user_id: str, date_str: str) -> List[ExercisePlanItem]:
        """按日期获取运动计划。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, user_id, plan_date, exercise_type, exercise_name,
                           duration_min, calories_burned, completed, created_at
                    FROM exercise_plans
                    WHERE user_id = %s AND plan_date = %s
                    ORDER BY created_at ASC
                """, (user_id, date_str))
                rows = cur.fetchall()
                return [ExercisePlanItem(
                    id=r[0], user_id=r[1], plan_date=r[2].isoformat() if r[2] else "",
                    exercise_type=r[3], exercise_name=r[4],
                    duration_min=r[5], calories_burned=r[6], completed=r[7],
                    created_at=r[8],
                ) for r in rows]
        except Exception as exc:
            logger.error("查询运动计划失败: %s", exc)
            return []

    def delete_item(self, item_id: int) -> bool:
        """删除运动计划项。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("DELETE FROM exercise_plans WHERE id = %s", (item_id,))
                return cur.rowcount > 0
        except Exception as exc:
            logger.error("删除运动计划失败: %s", exc)
            return False

    def clear_today(self, user_id: str):
        """清空今日运动计划。"""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("DELETE FROM exercise_plans WHERE user_id = %s AND plan_date = %s",
                            (user_id, today))
        except Exception as exc:
            logger.error("清空运动计划失败: %s", exc)

    def get_summary(self, user_id: str, date_str: str = None) -> dict:
        """获取指定日期的运动计划统计。"""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        items = self.get_items_by_date(user_id, date_str)
        total_calories = sum(i.calories_burned or 0 for i in items)
        total_duration = sum(i.duration_min for i in items)
        return {
            "total_calories": round(total_calories, 1),
            "total_duration": total_duration,
            "item_count": len(items),
            "items": [i.to_dict() for i in items],
        }
