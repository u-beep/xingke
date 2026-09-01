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

    def _get_goal_ml(self, user_id: str) -> int:
        """获取用户每日饮水目标：优先用户自定义（Profile.water_intake_ml），回退默认值。"""
        try:
            from ..user_profile import ProfileStore
            profile = ProfileStore().get(user_id)
            if profile and profile.water_intake_ml and profile.water_intake_ml > 0:
                return int(profile.water_intake_ml)
        except Exception as exc:
            logger.warning("读取用户饮水目标失败，回退默认值: %s", exc)
        return DEFAULT_DAILY_GOAL_ML

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

    def set_today_total(self, user_id: str, total_ml: float) -> bool:
        """手动设置今日饮水总量。

        - 新值大于当前总量：补录差值（drink_type='manual'）
        - 新值小于当前总量：清空今日记录后插入单条手动记录（类型细分丢失）
        """
        try:
            summary = self.get_today_summary(user_id)
            current = float(summary.get("total_ml") or 0)
            target = max(0.0, float(total_ml))
            diff = round(target - current, 1)
            if abs(diff) < 0.5:
                return True
            if diff > 0:
                return self.add_record(HydrationRecord(
                    user_id=user_id,
                    amount_ml=diff,
                    drink_type="manual",
                    notes="手动补录",
                )) is not None
            # diff < 0：清空今日记录，重建单条
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            with pg_cursor() as cur:
                cur.execute(
                    "DELETE FROM hydration_records WHERE user_id = %s AND recorded_at >= %s",
                    (user_id, today),
                )
            if target > 0:
                return self.add_record(HydrationRecord(
                    user_id=user_id,
                    amount_ml=target,
                    drink_type="manual",
                    notes="手动调整",
                )) is not None
            return True
        except Exception as exc:
            logger.error("设置今日饮水总量失败: %s", exc)
            return False

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

                goal_ml = self._get_goal_ml(user_id)
                return {
                    "total_ml": round(float(total_ml), 1),
                    "record_count": int(count),
                    "goal_ml": goal_ml,
                    "remaining_ml": max(0.0, goal_ml - float(total_ml)),
                    "percentage": min(100.0, round(float(total_ml) / goal_ml * 100, 1)),
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

                goal_ml = self._get_goal_ml(user_id)
                return {
                    "total_ml": round(float(total_ml), 1),
                    "record_count": int(count),
                    "goal_ml": goal_ml,
                    "remaining_ml": max(0.0, goal_ml - float(total_ml)),
                    "percentage": min(100.0, round(float(total_ml) / goal_ml * 100, 1)),
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
