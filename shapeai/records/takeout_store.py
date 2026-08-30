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
class TakeoutShop:
    """外卖店家。"""
    id: Optional[int] = None
    shop_name: str = ""
    category: str = ""          # 品类标签（炸鸡汉堡/中式快餐/...）
    monthly_sales: int = 0       # 月售单数
    delivery_minutes: int = 30   # 预计送达分钟
    min_order_price: float = 0.0 # 起送价
    delivery_fee: float = 0.0    # 配送费
    rating: float = 4.5          # 评分
    logo_url: Optional[str] = None
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "shop_name": self.shop_name,
            "category": self.category,
            "monthly_sales": self.monthly_sales,
            "delivery_minutes": self.delivery_minutes,
            "min_order_price": self.min_order_price,
            "delivery_fee": self.delivery_fee,
            "rating": self.rating,
            "logo_url": self.logo_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class TakeoutDish:
    """外卖菜品。"""
    id: Optional[int] = None
    dish_name: str = ""
    shop_name: str = ""          # 所属店家
    category: str = ""          # 店内分类（汉堡/炸鸡小食/...）
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
            "shop_name": self.shop_name,
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
    shop_name: str = ""          # 下单时快照的店家名
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
            "shop_name": self.shop_name,
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


# ─── 图片：菜品/店家真实食物图（按关键词匹配, 已下载到前端 public/dishes/） ───

# 关键词 -> 本地图片文件名（/dishes/kw_<关键词>.jpg）
# 图片来自 Flickr CC 搜索, 按食物关键词匹配, 与菜名语义一致

def _build_image_url(slug: str) -> str:
    """菜品图片: 前端静态资源 /dishes/kw_<slug>.jpg。"""
    return f"/dishes/kw_{slug}.jpg"


def _build_shop_logo_url(slug: str) -> str:
    """店家门头/Logo: 前端静态资源 /dishes/kw_<slug>.jpg。"""
    return f"/dishes/kw_{slug}.jpg"


# ─── 内置连锁店家（模仿美团外卖的连锁快餐品牌维度） ───
# 字段: (店家名, 品类标签, 月售, 配送时长min, 起送价, 配送费, 评分, logo关键词)

BUILTIN_SHOPS = [
    ("肯德基", "炸鸡汉堡", 8600, 30, 20, 4, 4.8, "chicken"),
    ("麦当劳", "炸鸡汉堡", 9200, 25, 20, 5, 4.7, "burger"),
    ("老乡鸡", "中式快餐", 5400, 35, 20, 3, 4.6, "bento"),
    ("沙县小吃", "中式快餐", 3200, 30, 15, 2, 4.4, "noodle"),
    ("兰州拉面", "面食", 4100, 32, 15, 2, 4.5, "noodle"),
    ("麦当劳·麦咖啡", "咖啡茶饮", 2800, 20, 15, 3, 4.6, "coffee"),
    ("瑞幸咖啡", "咖啡茶饮", 7300, 25, 15, 3, 4.7, "coffee"),
    ("喜茶", "咖啡茶饮", 6500, 35, 20, 4, 4.8, "milktea"),
    ("海底捞火锅外送", "火锅", 2200, 45, 60, 8, 4.9, "hotpot"),
    ("永和大王", "中式快餐", 3600, 30, 20, 3, 4.5, "congee"),
    ("吉野家", "日式简餐", 2900, 30, 25, 4, 4.6, "bento"),
    ("乡村基", "中式快餐", 3100, 35, 20, 3, 4.5, "rice"),
]


# ─── 内置外卖菜品（初始菜单, 以店家为维度组织; 图片关键词与菜名匹配） ───
# 字段: (菜名, 所属店家, 店内分类, 描述, 克数, 热量, 蛋白, 碳水, 脂肪, 价格, 图片关键词)

BUILTIN_DISHES = [
    # ── 肯德基 ──
    ("香辣鸡腿堡", "肯德基", "汉堡", "经典香辣鸡腿堡，微辣多汁", 220, 590, 26.0, 56.0, 28.0, 19.5, "chicken"),
    ("新奥尔良烤鸡腿堡", "肯德基", "汉堡", "甜辣烤鸡腿肉，黑胡椒酱", 215, 560, 27.0, 55.0, 25.0, 20.5, "chicken"),
    ("吮指原味鸡(1块)", "肯德基", "炸鸡小食", "经典吮指原味鸡块", 110, 280, 17.0, 12.0, 18.0, 11.5, "chicken"),
    ("香辣鸡翅(2块)", "肯德基", "炸鸡小食", "外豚里嫩，辣度适中", 100, 240, 15.0, 10.0, 15.0, 10.0, "chicken"),
    ("葡式蛋挞(1个)", "肯德基", "甜品小食", "酥皮蛋液馅，甜而不腻", 55, 200, 3.5, 22.0, 11.0, 7.0, "egg"),
    ("九珍果汁", "肯德基", "饮品", "多种果汁混合，酸甜清爽", 350, 150, 0, 38.0, 0, 11.0, "juice"),

    # ── 麦当劳 ──
    ("巨无霸", "麦当劳", "汉堡", "双层牛肉饼，特制酱料", 219, 550, 26.0, 42.0, 28.0, 24.5, "burger"),
    ("麦辣鸡腿堡", "麦当劳", "汉堡", "辣味鸡腿排，麦门经典", 195, 520, 24.0, 47.0, 24.0, 22.0, "chicken"),
    ("薯条(中)", "麦当劳", "炸鸡小食", "金黄香脆薯条", 117, 340, 4.0, 44.0, 16.0, 12.0, "fries"),
    ("麦乐鸡(5块)", "麦当劳", "炸鸡小食", "外豚内嫩鸡块配蘸酱", 95, 250, 13.0, 20.0, 13.0, 12.5, "chicken"),
    ("圆筒冰淇淋", "麦当劳", "甜品小食", "香浓牛乳圆筒", 85, 200, 3.5, 32.0, 6.0, 5.0, "icecream"),

    # ── 老乡鸡 ──
    ("肥西老母鸡汤", "老乡鸡", "招牌汤品", "慢炖老母鸡汤，原汁原味", 400, 180, 18.0, 4.0, 8.0, 16.0, "soup"),
    ("香辣鸡杂饭", "老乡鸡", "招牌套餐", "香辣鸡杂+米饭+小菜", 550, 680, 30.0, 82.0, 20.0, 26.0, "bento"),
    ("梅菜扣肉饭", "老乡鸡", "招牌套餐", "梅菜扣肉+米饭+小菜", 560, 720, 25.0, 85.0, 26.0, 27.0, "bento"),
    ("葱油鸡饭", "老乡鸡", "招牌套餐", "葱油鸡+米饭+小菜", 520, 590, 32.0, 70.0, 17.0, 25.0, "bento"),
    ("农家蒸蛋", "老乡鸡", "小菜", "口感嫩滑的蒸水蛋", 180, 110, 8.0, 6.0, 6.5, 6.0, "egg"),

    # ── 沙县小吃 ──
    ("飘香拌面", "沙县小吃", "面食", "花生酱拌面，香气扑鼻", 300, 520, 12.0, 78.0, 18.0, 9.0, "noodle"),
    ("柳叶蒸饺(8个)", "沙县小吃", "面食", "皮薄馅足的蒸饺", 240, 380, 14.0, 48.0, 12.0, 10.0, "dumpling"),
    ("炖罐排骨汤", "沙县小吃", "汤品", "清炖排骨罐汤", 350, 220, 16.0, 6.0, 13.0, 13.0, "soup"),
    ("扁食(馄饨)汤", "沙县小吃", "汤品", "皮薄馅嫩的馄饨", 320, 280, 13.0, 34.0, 9.0, 9.0, "wonton"),

    # ── 兰州拉面 ──
    ("牛肉拉面(小碗)", "兰州拉面", "面食", "一清二白三红四绿五黄", 400, 480, 22.0, 65.0, 14.0, 16.0, "noodle"),
    ("牛肉拉面(大碗)", "兰州拉面", "面食", "分量十足，面香汤浓", 600, 680, 30.0, 92.0, 20.0, 19.0, "noodle"),
    ("牛肉炒面片", "兰州拉面", "面食", "手工面片爆炒牛肉", 450, 620, 25.0, 76.0, 22.0, 20.0, "noodle"),
    ("凉拌黄瓜", "兰州拉面", "小菜", "清爽解腻小菜", 150, 60, 1.2, 10.0, 0.3, 6.0, "salad"),

    # ── 麦咖啡 ──
    ("拿铁(大杯)", "麦当劳·麦咖啡", "咖啡", "浓缩咖啡+蒸煮牛奶", 473, 190, 12.0, 18.0, 7.0, 25.0, "coffee"),
    ("美式咖啡(大杯)", "麦当劳·麦咖啡", "咖啡", "香醇回甘，零负担", 473, 15, 1.0, 3.0, 0, 21.0, "coffee"),
    ("燕麦拿铁", "麦当劳·麦咖啡", "咖啡", "燕麦奶拿铁，谷物香浓", 473, 220, 8.0, 30.0, 6.0, 28.0, "coffee"),

    # ── 瑞幸咖啡 ──
    ("生椰拿铁", "瑞幸咖啡", "咖啡", "浓缩+椰浆，椰香浓郁", 480, 223, 4.0, 34.0, 7.0, 18.0, "coffee"),
    ("标准美式", "瑞幸咖啡", "咖啡", "IIAC金奖豆，香醇顺滑", 355, 5, 1.0, 1.0, 0, 16.0, "coffee"),
    ("橙C美式", "瑞幸咖啡", "咖啡", "鲜橙汁+美式，维C满满", 355, 110, 1.5, 25.0, 0.3, 19.0, "coffee"),
    ("厚乳拿铁", "瑞幸咖啡", "咖啡", "冷萃厚牛乳拿铁", 480, 252, 9.0, 27.0, 11.0, 22.0, "coffee"),

    # ── 喜茶 ──
    ("多肉葡萄", "喜茶", "招牌果茶", "当季葡萄+芝士奶盖", 500, 265, 5.0, 52.0, 5.0, 25.0, "milktea"),
    ("芝芝莓莓", "喜茶", "招牌果茶", "草莓+芝士奶盖，酸甜平衡", 500, 250, 5.0, 50.0, 4.5, 25.0, "milktea"),
    ("烤黑糖波波牛乳", "喜茶", "招牌奶茶", "黑糖珍珠+鲜牛乳", 500, 355, 8.0, 62.0, 9.0, 19.0, "bubbletea"),
    ("满杯红柚", "喜茶", "招牌果茶", "西柚粒+绿茶，清新解腻", 500, 160, 1.5, 38.0, 0.5, 20.0, "milktea"),

    # ── 海底捞火锅外送 ──
    ("番茄牛腩锅(小锅)", "海底捞火锅外送", "锅底", "浓郁番茄牛腩锅底", 900, 650, 35.0, 45.0, 28.0, 88.0, "hotpot"),
    ("招牌番茄锅(小锅)", "海底捞火锅外送", "锅底", "酸甜开胃番茄锅底", 900, 320, 8.0, 40.0, 12.0, 68.0, "hotpot"),
    ("精品肥牛(半份)", "海底捞火锅外送", "涮品肉类", "雪花纹理肥牛卷", 150, 320, 16.0, 2.0, 27.0, 39.0, "beef"),
    ("鲜切黄牛肉(半份)", "海底捞火锅外送", "涮品肉类", "现切黄牛后腿肉", 150, 200, 22.0, 2.0, 11.0, 42.0, "beef"),
    ("手工鲜虾滑(半份)", "海底捞火锅外送", "涮品海鲜", "手打青虾滑，Q弹鲜甜", 150, 150, 16.0, 8.0, 7.0, 36.0, "shrimp"),
    ("捞派毛肚(半份)", "海底捞火锅外送", "涮品肉类", "七上八下，脆爽弹牙", 150, 180, 20.0, 4.0, 10.0, 39.0, "hotpot"),

    # ── 永和大王 ──
    ("现磨醇豆浆", "永和大王", "早餐经典", "每日现磨，香浓顺滑", 500, 180, 8.0, 14.0, 8.0, 6.0, "soyamilk"),
    ("安心油条", "永和大王", "早餐经典", "无矾配方，现炸酥脆", 80, 270, 5.0, 34.0, 12.0, 4.0, "youtiao"),
    ("卤肉饭(大碗)", "永和大王", "招牌套餐", "酱香卤肉+卤蛋+米饭", 520, 640, 22.0, 82.0, 20.0, 24.0, "bento"),
    ("牛肉冬粉汤", "永和大王", "汤面", "清炖牛肉+冬粉", 480, 380, 22.0, 52.0, 8.0, 26.0, "noodle"),
    ("鲜肉大馄饨", "永和大王", "汤面", "皮薄馅大，汤头清甜", 400, 420, 18.0, 48.0, 15.0, 18.0, "wonton"),

    # ── 吉野家 ──
    ("招牌牛肉饭(中碗)", "吉野家", "招牌盖饭", "肥牛+洋葱+秘制酱汁", 480, 650, 25.0, 85.0, 20.0, 27.0, "rice"),
    ("照烧鸡腿饭", "吉野家", "招牌盖饭", "照烧鸡腿排+温泉蛋", 500, 620, 30.0, 76.0, 18.0, 28.0, "bento"),
    ("寿喜锅牛肉饭", "吉野家", "招牌盖饭", "寿喜烧风味肥牛饭", 490, 680, 26.0, 82.0, 24.0, 30.0, "rice"),
    ("茶碗蒸", "吉野家", "小食", "日式嫩滑蒸蛋", 120, 90, 6.0, 6.0, 4.5, 8.0, "egg"),

    # ── 乡村基 ──
    ("香菇滑鸡饭", "乡村基", "招牌套餐", "香菇滑鸡+米饭+时蔬", 540, 610, 28.0, 78.0, 18.0, 24.0, "bento"),
    ("宫保鸡丁饭", "乡村基", "招牌套餐", "宫保鸡丁+米饭+时蔬", 540, 680, 26.0, 82.0, 22.0, 24.0, "kungpao"),
    ("双椒牛肉饭", "乡村基", "招牌套餐", "双椒牛肉+米饭+时蔬", 550, 700, 28.0, 80.0, 24.0, 26.0, "beef"),
    ("酸菜肉丝面", "乡村基", "面食", "酸菜开胃，肉丝满盖", 450, 520, 18.0, 72.0, 16.0, 18.0, "noodle"),
]


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
                    CREATE TABLE IF NOT EXISTS takeout_shops (
                        id                BIGSERIAL PRIMARY KEY,
                        shop_name         VARCHAR(128) NOT NULL UNIQUE,
                        category          VARCHAR(64) DEFAULT '',
                        monthly_sales     INTEGER DEFAULT 0,
                        delivery_minutes  INTEGER DEFAULT 30,
                        min_order_price   FLOAT DEFAULT 0,
                        delivery_fee      FLOAT DEFAULT 0,
                        rating            FLOAT DEFAULT 4.5,
                        logo_url          VARCHAR(512),
                        created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_takeout_shops_category
                    ON takeout_shops (category)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS takeout_dishes (
                        id              BIGSERIAL PRIMARY KEY,
                        dish_name       VARCHAR(128) NOT NULL,
                        shop_name       VARCHAR(128) DEFAULT '' REFERENCES takeout_shops(shop_name) ON DELETE CASCADE,
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
                    CREATE INDEX IF NOT EXISTS idx_takeout_dishes_shop
                    ON takeout_dishes (shop_name)
                """)
                # 旧表补列（存量库平滑升级）
                cur.execute("""
                    ALTER TABLE takeout_dishes
                    ADD COLUMN IF NOT EXISTS shop_name VARCHAR(128) DEFAULT '' REFERENCES takeout_shops(shop_name) ON DELETE CASCADE
                """)
                cur.execute("""
                    ALTER TABLE takeout_orders
                    ADD COLUMN IF NOT EXISTS shop_name VARCHAR(128) DEFAULT ''
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
                        shop_name       VARCHAR(128) DEFAULT '',
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
        """填充内置连锁店家 + 菜单（仅首次; 可强制重建）。"""
        try:
            with pg_cursor(commit=True) as cur:
                # 店家表若为空则播种
                cur.execute("SELECT COUNT(*) FROM takeout_shops")
                if cur.fetchone()[0] == 0:
                    for name, cat, sales, dmin, minp, fee, rating, slug in BUILTIN_SHOPS:
                        cur.execute("""
                            INSERT INTO takeout_shops
                                (shop_name, category, monthly_sales, delivery_minutes,
                                 min_order_price, delivery_fee, rating, logo_url)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (shop_name) DO NOTHING
                        """, (name, cat, sales, dmin, minp, fee, rating,
                              _build_shop_logo_url(slug)))
                    logger.info("已填充 %d 家内置连锁店家", len(BUILTIN_SHOPS))

                cur.execute("SELECT COUNT(*) FROM takeout_dishes")
                if cur.fetchone()[0] > 0:
                    return
                for name, shop, cat, desc, amt, cal, pro, carb, fat, price, slug in BUILTIN_DISHES:
                    cur.execute("""
                        INSERT INTO takeout_dishes
                            (dish_name, shop_name, category, description, amount_g, calories,
                             protein_g, carbs_g, fat_g, price, image_url, available)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    """, (name, shop, cat, desc, amt, cal, pro, carb, fat, price,
                          _build_image_url(slug)))
                logger.info("已填充 %d 条内置外卖菜品", len(BUILTIN_DISHES))
        except Exception as exc:
            logger.error("填充外卖菜单失败: %s", exc)

    # ─── 菜品 CRUD ───

    def list_dishes(
        self,
        category: Optional[str] = None,
        only_available: bool = True,
        shop_name: Optional[str] = None,
    ) -> List[TakeoutDish]:
        """获取外卖菜单，可按店内分类/店家过滤。"""
        try:
            with pg_cursor(commit=False) as cur:
                clauses = []
                params: list = []
                if category:
                    clauses.append("category = %s")
                    params.append(category)
                if shop_name:
                    clauses.append("shop_name = %s")
                    params.append(shop_name)
                if only_available:
                    clauses.append("available = TRUE")
                where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
                cur.execute(f"""
                    SELECT id, dish_name, shop_name, category, description, amount_g, calories,
                           protein_g, carbs_g, fat_g, price, image_url, available, created_at
                    FROM takeout_dishes{where}
                    ORDER BY shop_name, category, dish_name
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
                    SELECT id, dish_name, shop_name, category, description, amount_g, calories,
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

    # ─── 店家查询 ───

    def list_shops(self, category: Optional[str] = None) -> List[TakeoutShop]:
        """获取店家列表（仿美团首页店列），可按品类过滤。"""
        try:
            with pg_cursor(commit=False) as cur:
                if category:
                    cur.execute("""
                        SELECT id, shop_name, category, monthly_sales, delivery_minutes,
                               min_order_price, delivery_fee, rating, logo_url, created_at
                        FROM takeout_shops
                        WHERE category = %s
                        ORDER BY monthly_sales DESC
                    """, (category,))
                else:
                    cur.execute("""
                        SELECT id, shop_name, category, monthly_sales, delivery_minutes,
                               min_order_price, delivery_fee, rating, logo_url, created_at
                        FROM takeout_shops
                        ORDER BY monthly_sales DESC
                    """)
                return [self._row_to_shop(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("查询外卖店家失败: %s", exc)
            return []

    def get_shop(self, shop_name: str) -> Optional[TakeoutShop]:
        """按名称获取店家。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, shop_name, category, monthly_sales, delivery_minutes,
                           min_order_price, delivery_fee, rating, logo_url, created_at
                    FROM takeout_shops WHERE shop_name = %s
                """, (shop_name,))
                r = cur.fetchone()
                return self._row_to_shop(r) if r else None
        except Exception as exc:
            logger.error("查询外卖店家失败: %s", exc)
            return None

    def list_shop_categories(self) -> List[str]:
        """获取店家品类标签列表（炸鸡汉堡/中式快餐/...）。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT DISTINCT category FROM takeout_shops
                    WHERE category <> '' ORDER BY category
                """)
                return [r[0] for r in cur.fetchall()]
        except Exception as exc:
            logger.error("查询店家品类失败: %s", exc)
            return []

    @staticmethod
    def _row_to_shop(row) -> TakeoutShop:
        return TakeoutShop(
            id=row[0], shop_name=row[1], category=row[2], monthly_sales=row[3],
            delivery_minutes=row[4], min_order_price=row[5], delivery_fee=row[6],
            rating=row[7], logo_url=row[8], created_at=row[9],
        )

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
                # 1) 写入订单（含店家名快照）
                cur.execute("""
                    INSERT INTO takeout_orders
                        (user_id, dish_id, dish_name, shop_name, quantity, meal_type,
                         include_in_stats, order_status, total_calories, total_protein_g, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed', %s, %s, %s)
                    RETURNING id
                """, (
                    user_id, dish_id, dish.dish_name, dish.shop_name or "", qty, meal_type,
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
                    SELECT o.id, o.user_id, o.dish_id, o.dish_name, o.shop_name, o.quantity,
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
                    SELECT o.id, o.user_id, o.dish_id, o.dish_name, o.shop_name, o.quantity,
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
            id=row[0], dish_name=row[1], shop_name=row[2], category=row[3], description=row[4],
            amount_g=row[5], calories=row[6], protein_g=row[7],
            carbs_g=row[8], fat_g=row[9], price=row[10], image_url=row[11],
            available=row[12], created_at=row[13],
        )

    @staticmethod
    def _row_to_order(row) -> TakeoutOrder:
        return TakeoutOrder(
            id=row[0], user_id=row[1], dish_id=row[2], dish_name=row[3],
            shop_name=row[4] or "",
            quantity=row[5], meal_type=row[6], include_in_stats=row[7],
            order_status=row[8], total_calories=row[9], total_protein_g=row[10],
            notes=row[11], created_at=row[12],
            image_url=row[13], category=row[14], price=row[15],
        )
