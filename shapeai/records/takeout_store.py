"""外卖菜品与订单存储模块。

包含两张表：
  takeout_dishes — 外卖菜品库（含图片链接 + 营养信息）
  takeout_orders — 用户确认下单的外卖订单

下单时调用 ``place_order`` 会同步向 ``diet_records`` 写入一条
``source='order'`` 的饮食记录，由 ``include_in_stats`` 决定是否计入
当日热量/蛋白质统计。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


# ─── 数据类 ───

@dataclass
class TakeoutDish:
    """外卖菜品。"""
    id: Optional[int] = None
    dish_name: str = ""
    category: str = ""
    description: str = ""
    amount_g: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    price: float = 0.0
    image_url: Optional[str] = None
    available: bool = True
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dish_name": self.dish_name,
            "category": self.category,
            "description": self.description,
            "amount_g": self.amount_g,
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "price": self.price,
            "image_url": self.image_url,
            "available": self.available,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class TakeoutOrder:
    """外卖订单。"""
    id: Optional[int] = None
    user_id: str = ""
    dish_id: Optional[int] = None
    dish_name: str = ""
    quantity: int = 1
    meal_type: str = "lunch"
    include_in_stats: bool = True
    order_status: str = "confirmed"
    total_calories: float = 0.0
    total_protein_g: float = 0.0
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    # 关联字段（来自 join takeout_dishes，仅查询时填充）
    image_url: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "dish_id": self.dish_id,
            "dish_name": self.dish_name,
            "quantity": self.quantity,
            "meal_type": self.meal_type,
            "include_in_stats": self.include_in_stats,
            "order_status": self.order_status,
            "total_calories": self.total_calories,
            "total_protein_g": self.total_protein_g,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "image_url": self.image_url,
            "category": self.category,
            "price": self.price,
        }


# ─── 内置外卖菜品（初始菜单） ───

BUILTIN_DISHES = [
    # 轻食沙拉
    ("鸡胸肉牛油果沙拉", "轻食沙拉", "鸡胸肉、牛油果、生菜、紫甘蓝、低脂沙拉酱",
     320, 380, 32.0, 18.0, 14.0, 38, "salad"),
    ("金枪鱼蔬菜沙拉", "轻食沙拉", "水浸金枪鱼、混合生菜、小番茄、黄瓜",
     280, 260, 28.0, 10.0, 8.0, 32, "salad"),
    ("三文鱼藜麦沙拉", "轻食沙拉", "烟熏三文鱼、藜麦、牛油果、樱桃萝卜",
     300, 420, 26.0, 22.0, 18.0, 48, "salad"),
    # 主食
    ("糙米饭", "主食", "蒸熟糙米饭，富含膳食纤维",
     150, 170, 3.8, 35.0, 1.2, 5, "rice"),
    ("红薯杂粮饭", "主食", "红薯、糙米、紫米蒸制",
     180, 200, 4.0, 42.0, 0.8, 8, "rice"),
    # 高蛋白
    ("香煎鸡胸肉", "高蛋白", "黑胡椒鸡胸肉，少油煎制",
     150, 220, 38.0, 2.0, 6.0, 28, "chicken"),
    ("清蒸鲈鱼", "高蛋白", "新鲜鲈鱼清蒸，葱姜调味",
     200, 220, 32.0, 2.0, 7.0, 58, "fish"),
    ("白灼虾", "高蛋白", "鲜虾白灼，搭配低脂蘸料",
     180, 180, 30.0, 1.5, 4.0, 68, "shrimp"),
    ("牛排", "高蛋白", "西冷牛排，五分熟",
     200, 460, 42.0, 0, 32.0, 88, "steak"),
    # 主菜
    ("番茄牛肉面", "主菜", "番茄、牛肉、手擀面",
     350, 520, 24.0, 62.0, 16.0, 32, "noodle"),
    ("咖喱鸡肉饭", "主菜", "咖喱鸡肉配白米饭",
     380, 580, 22.0, 78.0, 18.0, 28, "rice"),
    ("麻辣鸡丝凉面", "主菜", "鸡丝、黄瓜、花生酱拌凉面",
     300, 460, 22.0, 58.0, 14.0, 22, "noodle"),
    # 汤品
    ("番茄蛋花汤", "汤品", "番茄、鸡蛋、香菜",
     250, 95, 6.5, 8.0, 4.5, 12, "soup"),
    ("冬瓜虾仁汤", "汤品", "冬瓜、鲜虾仁",
     250, 110, 9.0, 6.0, 4.5, 18, "soup"),
    # 加餐
    ("无糖酸奶", "加餐", "原味无糖酸奶 200g",
     200, 120, 12.0, 10.0, 3.5, 9, "yogurt"),
    ("混合坚果", "加餐", "巴旦木、核桃、腰果 30g",
     30, 180, 6.0, 6.0, 16.0, 12, "nuts"),
    ("水煮蛋", "加餐", "水煮鸡蛋一只",
     50, 78, 6.5, 0.6, 5.5, 3, "egg"),
]


# ─── 图片占位 URL（基于 dicebear / picsum，仅 demo） ───

_DISH_IMAGE_BASE = "https://picsum.photos/seed/{slug}/400/300"


def _build_image_url(slug: str) -> str:
    return _DISH_IMAGE_BASE.format(slug=slug)


# ─── 存储类 ───

class TakeoutStore:
    """外卖菜品 + 订单 存储管理。"""

    def __init__(self):
        self._ensure_tables()
        self._seed_builtin_dishes()

    def _ensure_tables(self):
        """确保两张表存在（与 migrate.py 中的定义保持一致）。

        同时为 diet_records 表补充 source/order_id/include_in_stats 三个
        新列（ALTER TABLE IF NOT EXISTS），保证下单流程能正常同步写入
        当日饮食记录。
        """
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS takeout_dishes (
                        id              BIGSERIAL PRIMARY KEY,
                        dish_name       VARCHAR(128) NOT NULL,
                        category        VARCHAR(64) DEFAULT '',
                        description     TEXT DEFAULT '',
                        amount_g        FLOAT,
                        calories        FLOAT,
                        protein_g       FLOAT,
                        carbs_g         FLOAT,
                        fat_g           FLOAT,
                        price           FLOAT DEFAULT 0,
                        image_url       VARCHAR(512),
                        available       BOOLEAN DEFAULT TRUE,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_takeout_dishes_category
                    ON takeout_dishes (category)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_takeout_dishes_available
                    ON takeout_dishes (available)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS takeout_orders (
                        id              BIGSERIAL PRIMARY KEY,
                        user_id         VARCHAR(64) NOT NULL,
                        dish_id         BIGINT NOT NULL REFERENCES takeout_dishes(id) ON DELETE CASCADE,
                        dish_name       VARCHAR(128) NOT NULL,
                        quantity        INTEGER NOT NULL DEFAULT 1,
                        meal_type       VARCHAR(32) NOT NULL DEFAULT 'lunch',
                        include_in_stats BOOLEAN NOT NULL DEFAULT TRUE,
                        order_status    VARCHAR(32) NOT NULL DEFAULT 'confirmed',
                        total_calories  FLOAT DEFAULT 0,
                        total_protein_g FLOAT DEFAULT 0,
                        notes           TEXT,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_takeout_orders_user_time
                    ON takeout_orders (user_id, created_at DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_takeout_orders_status
                    ON takeout_orders (order_status)
                """)

                # 同步给 diet_records 表补充新列（与 migrate.py 中的 ALTER 语句一致）
                cur.execute("""
                    ALTER TABLE diet_records
                    ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'chat'
                """)
                cur.execute("""
                    ALTER TABLE diet_records
                    ADD COLUMN IF NOT EXISTS order_id BIGINT
                """)
                cur.execute("""
                    ALTER TABLE diet_records
                    ADD COLUMN IF NOT EXISTS include_in_stats BOOLEAN DEFAULT TRUE
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_diet_records_source
                    ON diet_records (source)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_diet_records_include_stats
                    ON diet_records (include_in_stats)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_diet_records_order_id
                    ON diet_records (order_id)
                """)
        except Exception as exc:
            logger.error("创建外卖菜品/订单表失败: %s", exc)

    def _seed_builtin_dishes(self):
        """填充内置外卖菜单（仅首次）。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("SELECT COUNT(*) FROM takeout_dishes")
                if cur.fetchone()[0] > 0:
                    return
                for name, cat, desc, amt, cal, pro, carb, fat, price, slug in BUILTIN_DISHES:
                    cur.execute("""
                        INSERT INTO takeout_dishes
                            (dish_name, category, description, amount_g, calories,
                             protein_g, carbs_g, fat_g, price, image_url, available)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    """, (name, cat, desc, amt, cal, pro, carb, fat, price,
                          _build_image_url(slug)))
            logger.info("已填充 %d 条内置外卖菜品", len(BUILTIN_DISHES))
        except Exception as exc:
            logger.error("填充外卖菜单失败: %s", exc)

    # ─── 菜品 CRUD ───

    def list_dishes(
        self,
        category: Optional[str] = None,
        only_available: bool = True,
    ) -> List[TakeoutDish]:
        """获取外卖菜单，可按分类过滤。"""
        try:
            with pg_cursor(commit=False) as cur:
                clauses = []
                params: list = []
                if category:
                    clauses.append("category = %s")
                    params.append(category)
                if only_available:
                    clauses.append("available = TRUE")
                where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
                cur.execute(f"""
                    SELECT id, dish_name, category, description, amount_g, calories,
                           protein_g, carbs_g, fat_g, price, image_url, available, created_at
                    FROM takeout_dishes{where}
                    ORDER BY category, dish_name
                """, params)
                rows = cur.fetchall()
                return [self._row_to_dish(r) for r in rows]
        except Exception as exc:
            logger.error("查询外卖菜品失败: %s", exc)
            return []

    def get_dish(self, dish_id: int) -> Optional[TakeoutDish]:
        """按 ID 获取菜品。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, dish_name, category, description, amount_g, calories,
                           protein_g, carbs_g, fat_g, price, image_url, available, created_at
                    FROM takeout_dishes WHERE id = %s
                """, (dish_id,))
                r = cur.fetchone()
                return self._row_to_dish(r) if r else None
        except Exception as exc:
            logger.error("查询外卖菜品失败: %s", exc)
            return None

    def list_categories(self) -> List[str]:
        """获取菜品分类列表。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT DISTINCT category FROM takeout_dishes
                    WHERE available = TRUE AND category <> ''
                    ORDER BY category
                """)
                return [r[0] for r in cur.fetchall()]
        except Exception as exc:
            logger.error("查询外卖分类失败: %s", exc)
            return []

    # ─── 订单 CRUD ───

    def place_order(
        self,
        user_id: str,
        dish_id: int,
        quantity: int = 1,
        meal_type: str = "lunch",
        include_in_stats: bool = True,
        notes: Optional[str] = None,
    ) -> Optional[int]:
        """下单：写入 takeout_orders + 同步写入 diet_records（source='order'）。

        Args:
            include_in_stats: 用户自主决定是否计入当日热量/蛋白质统计。
        Returns:
            order_id（成功） / None（失败）
        """
        dish = self.get_dish(dish_id)
        if not dish:
            logger.warning("下单失败：菜品不存在 dish_id=%s", dish_id)
            return None
        if quantity <= 0:
            quantity = 1

        qty = quantity
        total_cal = (dish.calories or 0) * qty
        total_pro = (dish.protein_g or 0) * qty
        total_carbs = (dish.carbs_g or 0) * qty
        total_fat = (dish.fat_g or 0) * qty
        total_amt = (dish.amount_g or 0) * qty

        try:
            with pg_cursor(commit=True) as cur:
                # 1) 写入订单
                cur.execute("""
                    INSERT INTO takeout_orders
                        (user_id, dish_id, dish_name, quantity, meal_type,
                         include_in_stats, order_status, total_calories, total_protein_g, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', %s, %s, %s)
                    RETURNING id
                """, (
                    user_id, dish_id, dish.dish_name, qty, meal_type,
                    include_in_stats, round(total_cal, 1), round(total_pro, 1), notes,
                ))
                row = cur.fetchone()
                order_id = row[0] if row else None

                if order_id is None:
                    return None

                # 2) 同步写入当日饮食记录（统一同步）
                #    source='order'，order_id=order_id，include_in_stats=用户勾选结果
                food_name = dish.dish_name
                if qty > 1:
                    food_name = f"{dish.dish_name} x{qty}"
                cur.execute("""
                    INSERT INTO diet_records
                        (user_id, meal_type, food_name, amount_g, calories,
                         protein_g, carbs_g, fat_g, recorded_at, image_url,
                         source, order_id, include_in_stats)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, 'order', %s, %s)
                    RETURNING id
                """, (
                    user_id, meal_type, food_name, total_amt or None,
                    round(total_cal, 1), round(total_pro, 1),
                    round(total_carbs, 1), round(total_fat, 1),
                    dish.image_url, order_id, include_in_stats,
                ))
                logger.info(
                    "外卖订单已下单 user=%s dish=%s qty=%d order_id=%s include_stats=%s",
                    user_id, dish.dish_name, qty, order_id, include_in_stats,
                )
                return order_id
        except Exception as exc:
            logger.error("外卖下单失败: %s", exc)
            return None

    def get_today_orders(self, user_id: str) -> List[TakeoutOrder]:
        """获取用户今日外卖订单。"""
        try:
            with pg_cursor(commit=False) as cur:
                today_start = datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                cur.execute("""
                    SELECT o.id, o.user_id, o.dish_id, o.dish_name, o.quantity,
                           o.meal_type, o.include_in_stats, o.order_status,
                           o.total_calories, o.total_protein_g, o.notes, o.created_at,
                           d.image_url, d.category, d.price
                    FROM takeout_orders o
                    LEFT JOIN takeout_dishes d ON d.id = o.dish_id
                    WHERE o.user_id = %s AND o.created_at >= %s
                    ORDER BY o.created_at DESC
                """, (user_id, today_start))
                rows = cur.fetchall()
                return [self._row_to_order(r) for r in rows]
        except Exception as exc:
            logger.error("查询今日外卖订单失败: %s", exc)
            return []

    def get_history_orders(
        self, user_id: str, days: int = 30, limit: int = 200,
    ) -> List[TakeoutOrder]:
        """查询外卖订单历史。"""
        try:
            with pg_cursor(commit=False) as cur:
                since = datetime.now() - timedelta(days=days)
                cur.execute("""
                    SELECT o.id, o.user_id, o.dish_id, o.dish_name, o.quantity,
                           o.meal_type, o.include_in_stats, o.order_status,
                           o.total_calories, o.total_protein_g, o.notes, o.created_at,
                           d.image_url, d.category, d.price
                    FROM takeout_orders o
                    LEFT JOIN takeout_dishes d ON d.id = o.dish_id
                    WHERE o.user_id = %s AND o.created_at >= %s
                    ORDER BY o.created_at DESC
                    LIMIT %s
                """, (user_id, since, limit))
                rows = cur.fetchall()
                return [self._row_to_order(r) for r in rows]
        except Exception as exc:
            logger.error("查询外卖订单历史失败: %s", exc)
            return []

    def cancel_order(self, user_id: str, order_id: int) -> bool:
        """取消订单：将状态置为 cancelled，并删除关联的饮食记录。

        这样取消后当日热量统计会自动剔除该外卖。
        """
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE takeout_orders
                    SET order_status = 'cancelled'
                    WHERE id = %s AND user_id = %s AND order_status = 'confirmed'
                """, (order_id, user_id))
                updated = cur.rowcount > 0
                if updated:
                    cur.execute("""
                        DELETE FROM diet_records
                        WHERE order_id = %s AND source = 'order'
                    """, (order_id,))
                    logger.info(
                        "外卖订单已取消 user=%s order_id=%s 关联饮食记录已删除",
                        user_id, order_id,
                    )
                return updated
        except Exception as exc:
            logger.error("取消外卖订单失败: %s", exc)
            return False

    def get_today_summary(self, user_id: str) -> dict:
        """获取用户今日外卖订单汇总。"""
        try:
            with pg_cursor(commit=False) as cur:
                today_start = datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                cur.execute("""
                    SELECT
                        COUNT(*) AS order_count,
                        COALESCE(SUM(total_calories), 0) AS total_calories,
                        COALESCE(SUM(total_protein_g), 0) AS total_protein,
                        COALESCE(SUM(CASE WHEN include_in_stats THEN total_calories ELSE 0 END), 0) AS stats_calories,
                        COALESCE(SUM(CASE WHEN include_in_stats THEN total_protein_g ELSE 0 END), 0) AS stats_protein
                    FROM takeout_orders
                    WHERE user_id = %s AND created_at >= %s AND order_status = 'confirmed'
                """, (user_id, today_start))
                row = cur.fetchone()
                return {
                    "order_count": row[0],
                    "total_calories": round(row[1], 1),
                    "total_protein_g": round(row[2], 1),
                    "stats_calories": round(row[3], 1),
                    "stats_protein_g": round(row[4], 1),
                }
        except Exception as exc:
            logger.error("查询今日外卖汇总失败: %s", exc)
            return {}

    # ─── 工具方法 ───

    @staticmethod
    def _row_to_dish(row) -> TakeoutDish:
        return TakeoutDish(
            id=row[0], dish_name=row[1], category=row[2], description=row[3],
            amount_g=row[4], calories=row[5], protein_g=row[6],
            carbs_g=row[7], fat_g=row[8], price=row[9], image_url=row[10],
            available=row[11], created_at=row[12],
        )

    @staticmethod
    def _row_to_order(row) -> TakeoutOrder:
        return TakeoutOrder(
            id=row[0], user_id=row[1], dish_id=row[2], dish_name=row[3],
            quantity=row[4], meal_type=row[5], include_in_stats=row[6],
            order_status=row[7], total_calories=row[8], total_protein_g=row[9],
            notes=row[10], created_at=row[11],
            image_url=row[12], category=row[13], price=row[14],
        )
