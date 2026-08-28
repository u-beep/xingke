"""饮水记录存储模块。

使用 PostgreSQL 持久化饮水记录，支持按日查询和当日总量统计。
饮水数据用于前端水杯可视化展示：水位 = 当日累计 ml / 目标 ml。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)

# 默认每日饮水目标（毫升），用于计算水杯填充百分比
DEFAULT_DAILY_GOAL_ML = 2000


@dataclass
class HydrationRecord:
    """饮水记录数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    amount_ml: float = 0.0
    drink_type: str = "water"  # water / tea / coffee / juice / soup ...
    notes: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount_ml": self.amount_ml,
            "drink_type": self.drink_type,
            "notes": self.notes,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class HydrationStore:
    """饮水记录存储器。"""

    def add_record(self, record: HydrationRecord) -> Optional[int]:
        """添加饮水记录。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO hydration_records
                    (user_id, amount_ml, drink_type, notes, recorded_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    record.user_id,
                    record.amount_ml,
                    record.drink_type or "water",
                    record.notes,
                    record.recorded_at or datetime.now(),
                ))
                row = cur.fetchone()
                record_id = row[0] if row else None
                logger.info("饮水记录已添加: user=%s amount=%sml id=%s",
                            record.user_id, record.amount_ml, record_id)
                return record_id
        except Exception as exc:
            logger.error("添加饮水记录失败: %s", exc)
            return None

    def get_today_records(self, user_id: str) -> List[HydrationRecord]:
        """获取今日饮水记录。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute("""
                    SELECT id, user_id, amount_ml, drink_type, notes, recorded_at
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                """, (user_id, today))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询今日饮水记录失败: %s", exc)
            return []

    def get_today_summary(self, user_id: str) -> dict:
        """获取今日饮水统计。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute("""
                    SELECT
                        COALESCE(SUM(amount_ml), 0) as total_ml,
                        COUNT(*) as record_count
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s
                """, (user_id, today))
                row = cur.fetchone()
                total_ml, count = row

                # 按饮料类型分组
                cur.execute("""
                    SELECT drink_type, COALESCE(SUM(amount_ml), 0) as ml
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s
                    GROUP BY drink_type
                """, (user_id, today))
                type_stats = {r[0]: float(r[1]) for r in cur.fetchall()}

                return {
                    "total_ml": round(float(total_ml), 1),
                    "record_count": int(count),
                    "goal_ml": DEFAULT_DAILY_GOAL_ML,
                    "remaining_ml": max(0.0, DEFAULT_DAILY_GOAL_ML - float(total_ml)),
                    "percentage": min(100.0, round(float(total_ml) / DEFAULT_DAILY_GOAL_ML * 100, 1)),
                    "type_breakdown": type_stats,
                }
        except Exception as exc:
            logger.error("查询今日饮水统计失败: %s", exc)
            return {}

    def get_summary_by_date(self, user_id: str, date_str: str) -> dict:
        """获取指定日期的饮水统计。

        Args:
            user_id: 用户ID
            date_str: 日期字符串 YYYY-MM-DD
        """
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT
                        COALESCE(SUM(amount_ml), 0) as total_ml,
                        COUNT(*) as record_count
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                """, (user_id, day_start, day_end))
                row = cur.fetchone()
                total_ml, count = row

                cur.execute("""
                    SELECT drink_type, COALESCE(SUM(amount_ml), 0) as ml
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                    GROUP BY drink_type
                """, (user_id, day_start, day_end))
                type_stats = {r[0]: float(r[1]) for r in cur.fetchall()}

                return {
                    "total_ml": round(float(total_ml), 1),
                    "record_count": int(count),
                    "goal_ml": DEFAULT_DAILY_GOAL_ML,
                    "remaining_ml": max(0.0, DEFAULT_DAILY_GOAL_ML - float(total_ml)),
                    "percentage": min(100.0, round(float(total_ml) / DEFAULT_DAILY_GOAL_ML * 100, 1)),
                    "type_breakdown": type_stats,
                }
        except Exception as exc:
            logger.error("查询 %s 饮水统计失败: %s", date_str, exc)
            return {}

    def get_history(self, user_id: str, days: int = 30, limit: int = 200) -> List[HydrationRecord]:
        """查询饮水历史。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute("""
                    SELECT id, user_id, amount_ml, drink_type, notes, recorded_at
                    FROM hydration_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询饮水历史失败: %s", exc)
            return []

    @staticmethod
    def _row_to_record(row) -> HydrationRecord:
        return HydrationRecord(
            id=row[0],
            user_id=row[1],
            amount_ml=float(row[2]) if row[2] is not None else 0.0,
            drink_type=row[3] or "water",
            notes=row[4],
            recorded_at=row[5],
        )
