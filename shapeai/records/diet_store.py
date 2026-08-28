"""饮食记录存储模块。

使用 PostgreSQL 持久化存储饮食记录，支持按日/餐查询和热量统计。

饮食来源（source）分两种：
  'chat'  — 用户在对话中上报的食物（默认）
  'order' — 用户确认下单的外卖订单（由 TakeoutStore.place_order 同步写入）

统计接口（get_today_summary / get_summary_by_date）默认仅汇总
``include_in_stats = TRUE`` 的记录，对应用户未勾选"不计入统计"的外卖订单
会被自动剔除，但保留在历史记录中可见。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class DietRecord:
    """饮食记录数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    meal_type: str = ""  # breakfast / lunch / dinner / snack
    food_name: str = ""
    amount_g: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    recorded_at: Optional[datetime] = None
    image_url: Optional[str] = None
    # 来源与统计开关（migrate.py 新增字段）
    source: str = "chat"            # 'chat' / 'order'
    order_id: Optional[int] = None  # 关联 takeout_orders.id，仅 source='order' 时有值
    include_in_stats: bool = True   # 是否计入当日热量/蛋白质统计

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "meal_type": self.meal_type,
            "food_name": self.food_name,
            "amount_g": self.amount_g,
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "image_url": self.image_url,
            "source": self.source,
            "order_id": self.order_id,
            "include_in_stats": self.include_in_stats,
        }


# 列顺序（与 _row_to_record 保持一致）— 用于新增字段未存在时的回退
_RECORD_COLUMNS = (
    "id, user_id, meal_type, food_name, amount_g, calories, "
    "protein_g, carbs_g, fat_g, recorded_at, image_url"
)


class DietStore:
    """饮食记录存储器。"""

    def add_record(self, record: DietRecord) -> Optional[int]:
        """添加饮食记录（对话上报来源，source 默认为 'chat'）。

        若 diet_records 表尚未迁移新列（source/order_id/include_in_stats），
        自动回退到旧版 INSERT（保证向后兼容）。
        """
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO diet_records
                    (user_id, meal_type, food_name, amount_g, calories,
                     protein_g, carbs_g, fat_g, recorded_at, image_url,
                     source, order_id, include_in_stats)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    record.user_id, record.meal_type, record.food_name,
                    record.amount_g, record.calories, record.protein_g,
                    record.carbs_g, record.fat_g,
                    record.recorded_at or datetime.now(), record.image_url,
                    record.source or "chat", record.order_id,
                    record.include_in_stats if record.include_in_stats is not None else True,
                ))
                row = cur.fetchone()
                record_id = row[0] if row else None
                logger.info("饮食记录已添加: user=%s food=%s id=%s source=%s",
                            record.user_id, record.food_name, record_id,
                            record.source or "chat")
                return record_id
        except Exception as exc:
            # 新列不存在时回退到旧版 INSERT（保证向后兼容）
            logger.warning("新版饮食记录 INSERT 失败，回退到旧版: %s", str(exc)[:200])
            try:
                with pg_cursor() as cur:
                    cur.execute("""
                        INSERT INTO diet_records
                        (user_id, meal_type, food_name, amount_g, calories,
                         protein_g, carbs_g, fat_g, recorded_at, image_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        record.user_id, record.meal_type, record.food_name,
                        record.amount_g, record.calories, record.protein_g,
                        record.carbs_g, record.fat_g,
                        record.recorded_at or datetime.now(), record.image_url,
                    ))
                    row = cur.fetchone()
                    return row[0] if row else None
            except Exception as exc2:
                logger.error("添加饮食记录失败: %s", exc2)
                return None

    def get_today_records(self, user_id: str) -> List[DietRecord]:
        """获取今日饮食记录（包含对话 + 外卖订单两类来源）。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute("""
                    SELECT id, user_id, meal_type, food_name, amount_g, calories,
                           protein_g, carbs_g, fat_g, recorded_at, image_url,
                           source, order_id, include_in_stats
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                """, (user_id, today))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询今日饮食失败: %s", exc)
            return self._fallback_today_records(user_id)

    def get_records_by_date(self, user_id: str, date_str: str) -> List[DietRecord]:
        """获取指定自然日(YYYY-MM-DD)的饮食记录（外卖 + 对话两类来源，含未计入统计的）。"""
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
            day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, user_id, meal_type, food_name, amount_g, calories,
                           protein_g, carbs_g, fat_g, recorded_at, image_url,
                           source, order_id, include_in_stats
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                    ORDER BY recorded_at DESC
                """, (user_id, day_start, day_end))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询指定日期饮食记录失败: %s", exc)
            return []

    def get_history(
        self,
        user_id: str,
        days: int = 30,
        limit: int = 200,
    ) -> List[DietRecord]:
        """查询饮食历史。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute("""
                    SELECT id, user_id, meal_type, food_name, amount_g, calories,
                           protein_g, carbs_g, fat_g, recorded_at, image_url,
                           source, order_id, include_in_stats
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            logger.error("查询饮食历史失败: %s", exc)
            return self._fallback_history(user_id, days, limit)

    def get_today_summary(self, user_id: str) -> dict:
        """获取今日饮食统计（仅汇总 include_in_stats = TRUE 的记录）。

        若 include_in_stats 列尚未迁移，回退为汇总全部今日记录。
        """
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute("""
                    SELECT
                        COALESCE(SUM(calories), 0) as total_calories,
                        COALESCE(SUM(protein_g), 0) as total_protein,
                        COALESCE(SUM(carbs_g), 0) as total_carbs,
                        COALESCE(SUM(fat_g), 0) as total_fat,
                        COUNT(*) as record_count
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                      AND include_in_stats = TRUE
                """, (user_id, today))
                row = cur.fetchone()
                total_cal, total_protein, total_carbs, total_fat, count = row

                # 按餐统计
                cur.execute("""
                    SELECT meal_type, COALESCE(SUM(calories), 0) as cal
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                      AND include_in_stats = TRUE
                    GROUP BY meal_type
                """, (user_id, today))
                meal_stats = {r[0]: r[1] for r in cur.fetchall()}

                # 来源分布
                cur.execute("""
                    SELECT source, COALESCE(SUM(calories), 0) as cal,
                           COALESCE(SUM(protein_g), 0) as protein
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    GROUP BY source
                """, (user_id, today))
                source_breakdown = {
                    r[0]: {"calories": round(r[1], 1), "protein_g": round(r[2], 1)}
                    for r in cur.fetchall()
                }

                return {
                    "total_calories": round(total_cal, 1),
                    "total_protein_g": round(total_protein, 1),
                    "total_carbs_g": round(total_carbs, 1),
                    "total_fat_g": round(total_fat, 1),
                    "record_count": count,
                    "meal_breakdown": meal_stats,
                    "source_breakdown": source_breakdown,
                }
        except Exception as exc:
            logger.warning("今日饮食统计查询失败，回退到旧版: %s", str(exc)[:200])
            return self._fallback_today_summary(user_id)

    def get_summary_by_date(self, user_id: str, date_str: str) -> dict:
        """获取指定日期的饮食统计。

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
                        COALESCE(SUM(calories), 0) as total_calories,
                        COALESCE(SUM(protein_g), 0) as total_protein,
                        COALESCE(SUM(carbs_g), 0) as total_carbs,
                        COALESCE(SUM(fat_g), 0) as total_fat,
                        COUNT(*) as record_count
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                      AND include_in_stats = TRUE
                """, (user_id, day_start, day_end))
                row = cur.fetchone()
                total_cal, total_protein, total_carbs, total_fat, count = row

                cur.execute("""
                    SELECT meal_type, COALESCE(SUM(calories), 0) as cal
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                      AND include_in_stats = TRUE
                    GROUP BY meal_type
                """, (user_id, day_start, day_end))
                meal_stats = {r[0]: r[1] for r in cur.fetchall()}

                cur.execute("""
                    SELECT source, COALESCE(SUM(calories), 0) as cal,
                           COALESCE(SUM(protein_g), 0) as protein
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                    GROUP BY source
                """, (user_id, day_start, day_end))
                source_breakdown = {
                    r[0]: {"calories": round(r[1], 1), "protein_g": round(r[2], 1)}
                    for r in cur.fetchall()
                }

                return {
                    "total_calories": round(total_cal, 1),
                    "total_protein_g": round(total_protein, 1),
                    "total_carbs_g": round(total_carbs, 1),
                    "total_fat_g": round(total_fat, 1),
                    "record_count": count,
                    "meal_breakdown": meal_stats,
                    "source_breakdown": source_breakdown,
                }
        except Exception as exc:
            logger.warning("%s 饮食统计查询失败，回退到旧版: %s", date_str, str(exc)[:200])
            return self._fallback_summary_by_date(user_id, date_str)

    # ─── 兼容性回退查询（如果新字段尚未迁移） ───

    def _fallback_today_records(self, user_id: str) -> List[DietRecord]:
        """旧表结构（无 source/order_id/include_in_stats）的回退查询。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute(f"""
                    SELECT {_RECORD_COLUMNS}
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                """, (user_id, today))
                rows = cur.fetchall()
                return [self._row_to_record_legacy(row) for row in rows]
        except Exception as exc:
            logger.error("回退查询今日饮食失败: %s", exc)
            return []

    def _fallback_history(
        self, user_id: str, days: int = 30, limit: int = 200,
    ) -> List[DietRecord]:
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute(f"""
                    SELECT {_RECORD_COLUMNS}
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_record_legacy(row) for row in rows]
        except Exception as exc:
            logger.error("回退查询饮食历史失败: %s", exc)
            return []

    def _fallback_today_summary(self, user_id: str) -> dict:
        """旧表结构回退：汇总今日全部记录（无 include_in_stats 过滤）。"""
        try:
            with pg_cursor(commit=False) as cur:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cur.execute("""
                    SELECT
                        COALESCE(SUM(calories), 0) as total_calories,
                        COALESCE(SUM(protein_g), 0) as total_protein,
                        COALESCE(SUM(carbs_g), 0) as total_carbs,
                        COALESCE(SUM(fat_g), 0) as total_fat,
                        COUNT(*) as record_count
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                """, (user_id, today))
                total_cal, total_protein, total_carbs, total_fat, count = cur.fetchone()

                cur.execute("""
                    SELECT meal_type, COALESCE(SUM(calories), 0) as cal
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s
                    GROUP BY meal_type
                """, (user_id, today))
                meal_stats = {r[0]: r[1] for r in cur.fetchall()}

                return {
                    "total_calories": round(total_cal, 1),
                    "total_protein_g": round(total_protein, 1),
                    "total_carbs_g": round(total_carbs, 1),
                    "total_fat_g": round(total_fat, 1),
                    "record_count": count,
                    "meal_breakdown": meal_stats,
                    "source_breakdown": {},
                }
        except Exception as exc:
            logger.error("回退查询今日饮食统计失败: %s", exc)
            return {}

    def _fallback_summary_by_date(self, user_id: str, date_str: str) -> dict:
        """旧表结构回退：汇总指定日期全部记录（无 include_in_stats 过滤）。"""
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT
                        COALESCE(SUM(calories), 0) as total_calories,
                        COALESCE(SUM(protein_g), 0) as total_protein,
                        COALESCE(SUM(carbs_g), 0) as total_carbs,
                        COALESCE(SUM(fat_g), 0) as total_fat,
                        COUNT(*) as record_count
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                """, (user_id, day_start, day_end))
                total_cal, total_protein, total_carbs, total_fat, count = cur.fetchone()

                cur.execute("""
                    SELECT meal_type, COALESCE(SUM(calories), 0) as cal
                    FROM diet_records
                    WHERE user_id = %s AND recorded_at >= %s AND recorded_at < %s
                    GROUP BY meal_type
                """, (user_id, day_start, day_end))
                meal_stats = {r[0]: r[1] for r in cur.fetchall()}

                return {
                    "total_calories": round(total_cal, 1),
                    "total_protein_g": round(total_protein, 1),
                    "total_carbs_g": round(total_carbs, 1),
                    "total_fat_g": round(total_fat, 1),
                    "record_count": count,
                    "meal_breakdown": meal_stats,
                    "source_breakdown": {},
                }
        except Exception as exc:
            logger.error("回退查询 %s 饮食统计失败: %s", date_str, exc)
            return {}

    @staticmethod
    def _row_to_record(row) -> DietRecord:
        """新版行映射（含 source/order_id/include_in_stats）。"""
        return DietRecord(
            id=row[0], user_id=row[1], meal_type=row[2], food_name=row[3],
            amount_g=row[4], calories=row[5], protein_g=row[6],
            carbs_g=row[7], fat_g=row[8], recorded_at=row[9], image_url=row[10],
            source=row[11] if len(row) > 11 else "chat",
            order_id=row[12] if len(row) > 12 else None,
            include_in_stats=row[13] if len(row) > 13 else True,
        )

    @staticmethod
    def _row_to_record_legacy(row) -> DietRecord:
        """旧版行映射（无新字段）。"""
        return DietRecord(
            id=row[0], user_id=row[1], meal_type=row[2], food_name=row[3],
            amount_g=row[4], calories=row[5], protein_g=row[6],
            carbs_g=row[7], fat_g=row[8], recorded_at=row[9], image_url=row[10],
            source="chat", order_id=None, include_in_stats=True,
        )
