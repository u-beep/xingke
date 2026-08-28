"""体重记录存储模块。

使用 PostgreSQL 持久化存储体重记录，支持历史查询和趋势分析。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class WeightRecord:
    """体重记录数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    weight_kg: float = 0.0
    body_fat_pct: Optional[float] = None
    waist_cm: Optional[float] = None
    hip_cm: Optional[float] = None
    recorded_at: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "weight_kg": self.weight_kg,
            "body_fat_pct": self.body_fat_pct,
            "waist_cm": self.waist_cm,
            "hip_cm": self.hip_cm,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "notes": self.notes,
        }


class WeightStore:
    """体重记录存储器。"""

    def add_record(self, record: WeightRecord) -> Optional[int]:
        """添加体重记录，返回记录ID。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO weight_records
                    (user_id, weight_kg, body_fat_pct, waist_cm, hip_cm, recorded_at, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    record.user_id, record.weight_kg, record.body_fat_pct,
                    record.waist_cm, record.hip_cm,
                    record.recorded_at or datetime.now(), record.notes,
                ))
                row = cur.fetchone()
                record_id = row[0] if row else None
                logger.info("体重记录已添加: user=%s weight=%.1fkg id=%s",
                            record.user_id, record.weight_kg, record_id)
                return record_id
        except Exception as exc:
            logger.error("添加体重记录失败: %s", exc)
            return None

    def get_history(
        self,
        user_id: str,
        days: int = 30,
        limit: int = 100,
    ) -> List[WeightRecord]:
        """查询用户体重历史。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute("""
                    SELECT id, user_id, weight_kg, body_fat_pct, waist_cm, hip_cm, recorded_at, notes
                    FROM weight_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询体重历史失败: %s", exc)
            return []

    def get_latest(self, user_id: str) -> Optional[WeightRecord]:
        """获取用户最新体重记录。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, user_id, weight_kg, body_fat_pct, waist_cm, hip_cm, recorded_at, notes
                    FROM weight_records
                    WHERE user_id = %s
                    ORDER BY recorded_at DESC
                    LIMIT 1
                """, (user_id,))
                row = cur.fetchone()
                return self._row_to_record(row) if row else None
        except Exception as exc:
            logger.error("查询最新体重失败: %s", exc)
            return None

    def get_stats(self, user_id: str, days: int = 7) -> dict:
        """获取体重统计（变化、平均值等）。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute("""
                    SELECT
                        MIN(weight_kg) as min_weight,
                        MAX(weight_kg) as max_weight,
                        AVG(weight_kg) as avg_weight,
                        COUNT(*) as count,
                        (SELECT weight_kg FROM weight_records
                         WHERE user_id = %s AND recorded_at >= %s
                         ORDER BY recorded_at DESC LIMIT 1) as latest,
                        (SELECT weight_kg FROM weight_records
                         WHERE user_id = %s AND recorded_at >= %s
                         ORDER BY recorded_at ASC LIMIT 1) as earliest
                    FROM weight_records
                    WHERE user_id = %s AND recorded_at >= %s
                """, (user_id, since, user_id, since, user_id, since))
                row = cur.fetchone()
                if not row or row[0] is None:
                    return {}
                min_w, max_w, avg_w, count, latest, earliest = row
                change = (latest - earliest) if latest and earliest else 0
                return {
                    "min_weight": round(min_w, 1) if min_w else None,
                    "max_weight": round(max_w, 1) if max_w else None,
                    "avg_weight": round(avg_w, 1) if avg_w else None,
                    "count": count,
                    "latest_weight": round(latest, 1) if latest else None,
                    "change": round(change, 1),
                    "period_days": days,
                }
        except Exception as exc:
            logger.error("查询体重统计失败: %s", exc)
            return {}

    @staticmethod
    def _row_to_record(row) -> WeightRecord:
        return WeightRecord(
            id=row[0],
            user_id=row[1],
            weight_kg=row[2],
            body_fat_pct=row[3],
            waist_cm=row[4],
            hip_cm=row[5],
            recorded_at=row[6],
            notes=row[7],
        )
