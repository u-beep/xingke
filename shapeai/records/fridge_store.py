"""冰箱食材存储模块。

表 ``fridge_items`` 存储用户冰箱内的食材库存：
  - 拍照识别入库：``merge_or_add`` 按 name+unit 合并或新建
  - 手动增删改查：``add_item`` / ``update_item`` / ``delete_item``
  - 菜谱扣减：``deduct_ingredients`` 按用料精确+模糊匹配扣减库存

图片以 MinIO 对象 key 形式存储（``image_object_key``），
``to_dict`` 派生 ``image_url`` 指向 ``GET /api/v1/fridge/items/{id}/image``，
前端直接用相对 URL 取图（走 Vite 代理，无 CORS）。
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class FridgeItem:
    """冰箱食材项。"""
    id: Optional[int] = None
    user_id: str = ""
    name: str = ""
    category: str = ""
    quantity_g: float = 0.0
    unit: str = "g"
    calories: Optional[float] = None       # 每100g热量参考
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    image_object_key: Optional[str] = None  # MinIO 对象 key
    recognized_at: Optional[datetime] = None
    notes: Optional[str] = None
    shelf_life_days: Optional[float] = None  # 保质期天数(支持小数,0.5=12h)
    stored_at: Optional[datetime] = None      # 放入冰箱时间(精度到分钟)
    expires_at: Optional[datetime] = None     # 预计过期时间(=stored_at+shelf_life_days)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        image_url = f"/api/v1/fridge/items/{self.id}/image" if (self.id and self.image_object_key) else None
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "category": self.category,
            "quantity_g": self.quantity_g,
            "unit": self.unit,
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "image_object_key": self.image_object_key,
            "image_url": image_url,
            "recognized_at": self.recognized_at.isoformat() if self.recognized_at else None,
            "notes": self.notes,
            "shelf_life_days": self.shelf_life_days,
            "stored_at": _iso_minute(self.stored_at),
            "expires_at": _iso_minute(self.expires_at),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _iso_minute(dt: Optional[datetime]) -> Optional[str]:
    """ISO 格式到分钟(去掉秒/微秒),满足"时间精确到分钟"要求。"""
    if not dt:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


# 允许 update_item 修改的字段白名单（image_object_key 不在此列）
_UPDATABLE_FIELDS = {
    "name", "category", "quantity_g", "unit",
    "calories", "protein_g", "carbs_g", "fat_g", "notes",
    "shelf_life_days",
}

_COLUMNS = (
    "id, user_id, name, category, quantity_g, unit, "
    "calories, protein_g, carbs_g, fat_g, "
    "image_object_key, recognized_at, notes, "
    "shelf_life_days, stored_at, expires_at, "
    "created_at, updated_at"
)


class FridgeStore:
    """冰箱食材存储管理。"""

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """确保 fridge_items 表存在（与 migrate.py 定义保持一致）。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fridge_items (
                        id               BIGSERIAL PRIMARY KEY,
                        user_id          VARCHAR(64) NOT NULL,
                        name             VARCHAR(128) NOT NULL,
                        category         VARCHAR(64) DEFAULT '',
                        quantity_g       FLOAT NOT NULL DEFAULT 0,
                        unit             VARCHAR(16) DEFAULT 'g',
                        calories         FLOAT,
                        protein_g        FLOAT,
                        carbs_g          FLOAT,
                        fat_g            FLOAT,
                        image_object_key VARCHAR(256),
                        recognized_at    TIMESTAMPTZ,
                        notes            TEXT,
                        shelf_life_days  FLOAT,
                        stored_at        TIMESTAMPTZ,
                        expires_at       TIMESTAMPTZ,
                        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                # 升级已有表(新增列,幂等)
                cur.execute(
                    "ALTER TABLE fridge_items ADD COLUMN IF NOT EXISTS shelf_life_days FLOAT"
                )
                cur.execute(
                    "ALTER TABLE fridge_items ADD COLUMN IF NOT EXISTS stored_at TIMESTAMPTZ"
                )
                cur.execute(
                    "ALTER TABLE fridge_items ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
                )
                # 回填:历史数据缺 stored_at 时用 created_at,有 shelf_life_days 时算 expires_at
                cur.execute("""
                    UPDATE fridge_items
                    SET stored_at = COALESCE(stored_at, date_trunc('minute', created_at)),
                        expires_at = COALESCE(expires_at,
                            CASE WHEN shelf_life_days IS NOT NULL
                                 THEN date_trunc('minute', created_at)
                                      + (shelf_life_days * interval '1 day')
                                 ELSE NULL END)
                    WHERE stored_at IS NULL
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fridge_items_user_time
                    ON fridge_items (user_id, created_at DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fridge_items_user_name
                    ON fridge_items (user_id, name)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fridge_items_user_cat
                    ON fridge_items (user_id, category)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fridge_items_user_expires
                    ON fridge_items (user_id, expires_at)
                """)
                # 菜谱扣减→热量摄入日志(按自然日统计)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fridge_meal_log (
                        id              BIGSERIAL PRIMARY KEY,
                        user_id         VARCHAR(64) NOT NULL,
                        recipe_name     VARCHAR(256) NOT NULL,
                        total_calories  FLOAT DEFAULT 0,
                        consumed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                        ingredients_summary TEXT,
                        recipe_json     JSONB,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_meal_log_user_day
                    ON fridge_meal_log (user_id, consumed_at DESC)
                """)
        except Exception as exc:
            logger.error("创建冰箱食材表失败: %s", exc)

    # ─── 菜谱摄入日志(按自然日统计) ───

    def add_meal_log(
        self,
        user_id: str,
        recipe_name: str,
        total_calories: float,
        ingredients_summary: Optional[str] = None,
        recipe: Optional[dict] = None,
    ) -> Optional[int]:
        """记录一餐的菜品与摄入热量(确认菜谱扣减时调用)。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO fridge_meal_log
                        (user_id, recipe_name, total_calories, ingredients_summary, recipe_json)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    user_id, recipe_name, round(total_calories, 1),
                    ingredients_summary,
                    json.dumps(recipe, ensure_ascii=False) if recipe else None,
                ))
                row = cur.fetchone()
                mid = row[0] if row else None
                logger.info("已记录餐次: user=%s recipe=%s cal=%.1f id=%s",
                            user_id, recipe_name, total_calories, mid)
                return mid
        except Exception as exc:
            logger.error("记录餐次失败: %s", exc)
            return None

    def list_meal_logs(
        self,
        user_id: str,
        date: Optional[datetime] = None,
    ) -> list[dict]:
        """按本地自然日查询餐次日志。date 为空时默认今天。返回按时间倒序。

        consumed_at 为真 UTC(timestamptz)，用「本地日界转 UTC 的区间」比较，
        避免 DB session TimeZone(UTC) 与本地时区(+8) 在凌晨时段错位。
        显示时间转换为本地时区。
        """
        local_tz = datetime.now().astimezone().tzinfo
        target = date or datetime.now()
        day_start = target.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=local_tz,
        )
        day_end = day_start + timedelta(days=1)
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    SELECT id, recipe_name, total_calories, consumed_at,
                           ingredients_summary
                    FROM fridge_meal_log
                    WHERE user_id = %s AND consumed_at >= %s AND consumed_at < %s
                    ORDER BY consumed_at DESC
                """, (user_id, day_start, day_end))
                rows = cur.fetchall()
                logs = []
                for r in rows:
                    # timestamptz 转 UTC → 本地，输出精确到分钟
                    consumed = r[3].astimezone(local_tz) if r[3] else None
                    logs.append({
                        "id": r[0],
                        "recipe_name": r[1],
                        "total_calories": r[2],
                        "consumed_at": _iso_minute(consumed),
                        "ingredients_summary": r[4],
                    })
                return logs
        except Exception as exc:
            logger.error("查询餐次日志失败: %s", exc)
            return []

    # ─── 查询 ───

    def list_items(self, user_id: str, category: Optional[str] = None) -> List[FridgeItem]:
        """获取用户冰箱食材列表，可按分类过滤。"""
        try:
            with pg_cursor(commit=False) as cur:
                if category:
                    cur.execute(f"""
                        SELECT {_COLUMNS}
                        FROM fridge_items
                        WHERE user_id = %s AND category = %s
                        ORDER BY created_at DESC
                    """, (user_id, category))
                else:
                    cur.execute(f"""
                        SELECT {_COLUMNS}
                        FROM fridge_items
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                    """, (user_id,))
                rows = cur.fetchall()
                return [self._row_to_item(r) for r in rows]
        except Exception as exc:
            logger.error("查询冰箱食材失败: %s", exc)
            return []

    def list_categories(self, user_id: str) -> List[str]:
        """获取用户冰箱中出现的分类列表。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT DISTINCT category FROM fridge_items
                    WHERE user_id = %s AND category <> ''
                    ORDER BY category
                """, (user_id,))
                return [r[0] for r in cur.fetchall()]
        except Exception as exc:
            logger.error("查询冰箱分类失败: %s", exc)
            return []

    def get_item(self, user_id: str, item_id: int) -> Optional[FridgeItem]:
        """按 ID 获取单个食材。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute(f"""
                    SELECT {_COLUMNS}
                    FROM fridge_items
                    WHERE id = %s AND user_id = %s
                """, (item_id, user_id))
                row = cur.fetchone()
                return self._row_to_item(row) if row else None
        except Exception as exc:
            logger.error("查询冰箱食材失败: %s", exc)
            return None

    # ─── 增删改 ───

    def add_item(self, item: FridgeItem) -> Optional[int]:
        """新增食材。

        - ``stored_at`` 默认取当前时间(截断到分钟)
        - ``expires_at`` 由 ``shelf_life_days`` 自动计算(若提供)
        """
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO fridge_items
                        (user_id, name, category, quantity_g, unit,
                         calories, protein_g, carbs_g, fat_g,
                         image_object_key, recognized_at, notes,
                         shelf_life_days, stored_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            date_trunc('minute', COALESCE(%s, now())),
                            CASE WHEN %s IS NOT NULL
                                 THEN date_trunc('minute', COALESCE(%s, now()))
                                      + (%s * interval '1 day')
                                 ELSE NULL END)
                    RETURNING id
                """, (
                    item.user_id, item.name, item.category or "",
                    item.quantity_g or 0, item.unit or "g",
                    item.calories, item.protein_g, item.carbs_g, item.fat_g,
                    item.image_object_key,
                    item.recognized_at or datetime.now(),
                    item.notes,
                    item.shelf_life_days,
                    item.stored_at,
                    item.shelf_life_days,
                    item.stored_at,
                    item.shelf_life_days,
                ))
                row = cur.fetchone()
                item_id = row[0] if row else None
                logger.info("冰箱食材已添加: user=%s name=%s id=%s shelf_life=%s",
                            item.user_id, item.name, item_id, item.shelf_life_days)
                return item_id
        except Exception as exc:
            logger.error("添加冰箱食材失败: %s", exc)
            return None

    def update_item(self, user_id: str, item_id: int, fields: dict) -> Optional[FridgeItem]:
        """更新食材（仅白名单字段）。

        若更新 ``shelf_life_days``,自动重算 ``expires_at = stored_at + shelf_life_days`` 天。
        """
        # 过滤出允许更新的字段(shelf_life_days 允许置空:显式传 None 才清空)
        updates = {}
        for k, v in fields.items():
            if k not in _UPDATABLE_FIELDS:
                continue
            if k == "shelf_life_days":
                updates[k] = v  # 允许 None(清空保质期)
            elif v is not None:
                updates[k] = v
        if not updates:
            return self.get_item(user_id, item_id)
        try:
            with pg_cursor(commit=True) as cur:
                set_parts = [f"{k} = %s" for k in updates]
                params = list(updates.values())
                # 若改了保质期,同步重算 expires_at
                if "shelf_life_days" in updates:
                    sld = updates["shelf_life_days"]
                    set_parts.append(
                        "expires_at = CASE WHEN %s IS NOT NULL "
                        "THEN date_trunc('minute', COALESCE(stored_at, created_at)) "
                        "     + (%s * interval '1 day') "
                        "ELSE NULL END"
                    )
                    params.append(sld)
                    params.append(sld)
                set_parts.append("updated_at = now()")
                params.extend([item_id, user_id])
                cur.execute(
                    f"UPDATE fridge_items SET {', '.join(set_parts)} "
                    f"WHERE id = %s AND user_id = %s",
                    params,
                )
                if cur.rowcount == 0:
                    return None
                cur.execute(
                    f"SELECT {_COLUMNS} FROM fridge_items WHERE id = %s AND user_id = %s",
                    (item_id, user_id),
                )
                row = cur.fetchone()
                return self._row_to_item(row) if row else None
        except Exception as exc:
            logger.error("更新冰箱食材失败: %s", exc)
            return None

    def delete_item(self, user_id: str, item_id: int) -> bool:
        """删除食材。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM fridge_items WHERE id = %s AND user_id = %s",
                    (item_id, user_id),
                )
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info("冰箱食材已删除: user=%s id=%s", user_id, item_id)
                return deleted
        except Exception as exc:
            logger.error("删除冰箱食材失败: %s", exc)
            return False

    # ─── 拍照识别入库 ───

    def merge_or_add(
        self,
        user_id: str,
        name: str,
        unit: str,
        quantity_g: float,
        category: str = "",
        nutrition: Optional[dict] = None,
        image_object_key: Optional[str] = None,
        notes: Optional[str] = None,
        shelf_life_days: Optional[float] = None,
    ) -> Optional[int]:
        """按 name+unit 合并库存或新建。

        命中已有同名同单位食材 → 累加 quantity_g；
        否则插入新行。同一张照片识别出的多个食材共享 image_object_key。

        保质期:
        - 新建: stored_at = now(到分钟), expires_at = stored_at + shelf_life_days 天
        - 合并: 保留旧 stored_at(最早放入),若传入新 shelf_life_days 则重算 expires_at
        """
        if not name or quantity_g is None:
            return None
        nutrition = nutrition or {}
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    SELECT id, quantity_g FROM fridge_items
                    WHERE user_id = %s AND name = %s AND unit = %s
                    ORDER BY created_at DESC LIMIT 1
                """, (user_id, name, unit or "g"))
                row = cur.fetchone()
                now = datetime.now()
                if row:
                    item_id, cur_qty = row[0], (row[1] or 0)
                    # 合并:若传入新保质期,重算 expires_at(基于旧 stored_at)
                    if shelf_life_days is not None:
                        cur.execute("""
                            UPDATE fridge_items
                            SET quantity_g = %s, image_object_key = COALESCE(%s, image_object_key),
                                category = COALESCE(NULLIF(%s, ''), category),
                                calories = COALESCE(%s, calories),
                                protein_g = COALESCE(%s, protein_g),
                                carbs_g = COALESCE(%s, carbs_g),
                                fat_g = COALESCE(%s, fat_g),
                                shelf_life_days = %s,
                                expires_at = date_trunc('minute', COALESCE(stored_at, created_at))
                                    + (%s * interval '1 day'),
                                updated_at = %s
                            WHERE id = %s
                        """, (
                            round(cur_qty + quantity_g, 1),
                            image_object_key,
                            category,
                            nutrition.get("calories"),
                            nutrition.get("protein_g"),
                            nutrition.get("carbs_g"),
                            nutrition.get("fat_g"),
                            shelf_life_days, shelf_life_days,
                            now, item_id,
                        ))
                    else:
                        cur.execute("""
                            UPDATE fridge_items
                            SET quantity_g = %s, image_object_key = COALESCE(%s, image_object_key),
                                category = COALESCE(NULLIF(%s, ''), category),
                                calories = COALESCE(%s, calories),
                                protein_g = COALESCE(%s, protein_g),
                                carbs_g = COALESCE(%s, carbs_g),
                                fat_g = COALESCE(%s, fat_g),
                                updated_at = %s
                            WHERE id = %s
                        """, (
                            round(cur_qty + quantity_g, 1),
                            image_object_key,
                            category,
                            nutrition.get("calories"),
                            nutrition.get("protein_g"),
                            nutrition.get("carbs_g"),
                            nutrition.get("fat_g"),
                            now, item_id,
                        ))
                    return item_id
                # 新建
                cur.execute("""
                    INSERT INTO fridge_items
                        (user_id, name, category, quantity_g, unit,
                         calories, protein_g, carbs_g, fat_g,
                         image_object_key, recognized_at, notes,
                         shelf_life_days, stored_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            date_trunc('minute', now()),
                            CASE WHEN %s IS NOT NULL
                                 THEN date_trunc('minute', now()) + (%s * interval '1 day')
                                 ELSE NULL END)
                    RETURNING id
                """, (
                    user_id, name, category or "", round(quantity_g, 1), unit or "g",
                    nutrition.get("calories"), nutrition.get("protein_g"),
                    nutrition.get("carbs_g"), nutrition.get("fat_g"),
                    image_object_key, now, notes,
                    shelf_life_days,
                    shelf_life_days, shelf_life_days,
                ))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as exc:
            logger.error("合并/新增冰箱食材失败: %s", exc)
            return None

    # ─── 菜谱扣减 ───

    def deduct_ingredients(self, user_id: str, usages: list[dict]) -> dict:
        """按菜谱用料扣减冰箱库存。

        匹配优先级：name+unit 精确 → name 任意 unit → 名称子串模糊。
        状态：ok(足额扣减) / insufficient(不足,扣尽可用) / missing(冰箱无此食材)。
        不删除 0 量行（保留图片/历史）。
        """
        deducted: list[dict] = []
        insufficient: list[dict] = []
        missing: list[dict] = []

        try:
            with pg_cursor(commit=True) as cur:
                for usage in usages:
                    name = (usage.get("name") or "").strip()
                    amount = float(usage.get("amount_g") or 0)
                    unit = usage.get("unit") or "g"
                    if not name or amount <= 0:
                        continue

                    # 1) name+unit 精确
                    cur.execute("""
                        SELECT id, quantity_g, unit FROM fridge_items
                        WHERE user_id = %s AND name = %s AND unit = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, (user_id, name, unit))
                    row = cur.fetchone()
                    match_way = "exact"

                    # 2) name 任意 unit
                    if not row:
                        cur.execute("""
                            SELECT id, quantity_g, unit FROM fridge_items
                            WHERE user_id = %s AND name = %s
                            ORDER BY created_at DESC LIMIT 1
                        """, (user_id, name))
                        row = cur.fetchone()
                        match_way = "name"

                    # 3) 子串模糊（recipe name 含 fridge name 或反之）
                    if not row:
                        cur.execute("""
                            SELECT id, name, quantity_g, unit FROM fridge_items
                            WHERE user_id = %s
                        """, (user_id,))
                        candidates = cur.fetchall()
                        for cid, cname, cqty, cunit in candidates:
                            if not cname:
                                continue
                            if name in cname or cname in name:
                                row = (cid, cqty, cunit)
                                match_way = "fuzzy"
                                break

                    entry = {
                        "name": name, "requested": round(amount, 1),
                        "unit": unit, "match": match_way,
                    }
                    if not row:
                        entry["available"] = 0
                        entry["deducted"] = 0
                        entry["status"] = "missing"
                        missing.append(entry)
                        continue

                    item_id, avail_qty, item_unit = row[0], (row[1] or 0), (row[2] or "g")
                    entry["unit"] = item_unit
                    if avail_qty >= amount:
                        deduct = amount
                        status = "ok"
                    else:
                        deduct = avail_qty
                        status = "insufficient"
                    entry["available"] = round(avail_qty, 1)
                    entry["deducted"] = round(deduct, 1)
                    entry["status"] = status
                    entry["item_id"] = item_id
                    # 每100g热量(供上层按菜谱用量算理论摄入)
                    entry["calories_per_100g"] = cal_per100
                    # 该项实际摄入热量 = 扣减量 * 每100g热量 / 100
                    if cal_per100 and deduct > 0:
                        entry["calories"] = round(cal_per100 * deduct / 100, 1)
                    else:
                        entry["calories"] = 0

                    cur.execute("""
                        UPDATE fridge_items
                        SET quantity_g = GREATEST(0, quantity_g - %s), updated_at = now()
                        WHERE id = %s
                    """, (round(deduct, 1), item_id))

                    deducted.append(entry)
                    if status == "insufficient":
                        insufficient.append(entry)

            return {
                "success": True,
                "deducted": deducted,
                "insufficient": insufficient,
                "missing": missing,
            }
        except Exception as exc:
            logger.error("菜谱扣减失败: %s", exc)
            return {
                "success": False,
                "deducted": deducted,
                "insufficient": insufficient,
                "missing": missing,
                "error": str(exc),
            }

    # ─── 工具 ───

    @staticmethod
    def _row_to_item(row) -> FridgeItem:
        return FridgeItem(
            id=row[0], user_id=row[1], name=row[2], category=row[3],
            quantity_g=row[4], unit=row[5], calories=row[6], protein_g=row[7],
            carbs_g=row[8], fat_g=row[9], image_object_key=row[10],
            recognized_at=row[11], notes=row[12],
            shelf_life_days=row[13], stored_at=row[14], expires_at=row[15],
            created_at=row[16], updated_at=row[17],
        )
