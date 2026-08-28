"""运动记录存储模块。

使用 PostgreSQL 持久化存储运动记录，支持按日/周查询和统计。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class ExerciseRecord:
    """运动记录数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    exercise_name: str = ""
    exercise_type: Optional[str] = None  # 有氧/力量/核心/柔韧/休息
    duration_min: Optional[int] = None
    calories_burned: Optional[float] = None
    completed: bool = True
    scheduled_date: Optional[date] = None
    recorded_at: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "exercise_name": self.exercise_name,
            "exercise_type": self.exercise_type,
            "duration_min": self.duration_min,
            "calories_burned": self.calories_burned,
            "completed": self.completed,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "notes": self.notes,
        }


class ExerciseStore:
    """运动记录存储器。"""

    def add_record(self, record: ExerciseRecord) -> Optional[int]:
        """添加运动记录。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO exercise_records
                    (user_id, exercise_name, exercise_type, duration_min, calories_burned,
                     completed, scheduled_date, recorded_at, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    record.user_id, record.exercise_name, record.exercise_type,
                    record.duration_min, record.calories_burned, record.completed,
                    record.scheduled_date or date.today(),
                    record.recorded_at or datetime.now(), record.notes,
                ))
                row = cur.fetchone()
                record_id = row[0] if row else None
                logger.info("运动记录已添加: user=%s exercise=%s id=%s",
                            record.user_id, record.exercise_name, record_id)
                return record_id
        except Exception as exc:
            logger.error("添加运动记录失败: %s", exc)
            return None

    def get_today_records(self, user_id: str) -> List[ExerciseRecord]:
        """获取今日运动记录。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = date.today()
                cur.execute("""
                    SELECT id, user_id, exercise_name, exercise_type, duration_min,
                           calories_burned, completed, scheduled_date, recorded_at, notes
                    FROM exercise_records
                    WHERE user_id = %s AND scheduled_date = %s
                    ORDER BY recorded_at DESC
                """, (user_id, today))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询今日运动失败: %s", exc)
            return []

    def get_week_records(self, user_id: str) -> List[ExerciseRecord]:
        """获取本周运动记录。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = date.today()
                week_start = today - timedelta(days=today.weekday())
                cur.execute("""
                    SELECT id, user_id, exercise_name, exercise_type, duration_min,
                           calories_burned, completed, scheduled_date, recorded_at, notes
                    FROM exercise_records
                    WHERE user_id = %s AND scheduled_date >= %s
                    ORDER BY scheduled_date DESC, recorded_at DESC
                """, (user_id, week_start))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询本周运动失败: %s", exc)
            return []

    def get_history(
        self,
        user_id: str,
        days: int = 30,
        limit: int = 200,
    ) -> List[ExerciseRecord]:
        """查询运动历史。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = date.today() - timedelta(days=days)
                cur.execute("""
                    SELECT id, user_id, exercise_name, exercise_type, duration_min,
                           calories_burned, completed, scheduled_date, recorded_at, notes
                    FROM exercise_records
                    WHERE user_id = %s AND scheduled_date >= %s
                    ORDER BY scheduled_date DESC, recorded_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询运动历史失败: %s", exc)
            return []

    def get_week_summary(self, user_id: str) -> dict:
        """获取本周运动统计。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = date.today()
                week_start = today - timedelta(days=today.weekday())
                cur.execute("""
                    SELECT
                        COUNT(*) as total_count,
                        COUNT(*) FILTER (WHERE completed = TRUE) as completed_count,
                        COALESCE(SUM(duration_min), 0) as total_duration,
                        COALESCE(SUM(calories_burned), 0) as total_calories
                    FROM exercise_records
                    WHERE user_id = %s AND scheduled_date >= %s
                """, (user_id, week_start))
                row = cur.fetchone()
                total, completed, duration, calories = row
                return {
                    "total_count": total,
                    "completed_count": completed,
                    "completion_rate": round(completed / total * 100, 1) if total else 0,
                    "total_duration_min": duration,
                    "total_calories_burned": round(calories, 1),
                }
        except Exception as exc:
            logger.error("查询运动统计失败: %s", exc)
            return {}

    @staticmethod
    def _row_to_record(row) -> ExerciseRecord:
        return ExerciseRecord(
            id=row[0], user_id=row[1], exercise_name=row[2], exercise_type=row[3],
            duration_min=row[4], calories_burned=row[5], completed=row[6],
            scheduled_date=row[7], recorded_at=row[8], notes=row[9],
        )
