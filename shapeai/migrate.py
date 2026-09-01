"""数据库迁移脚本 — 建表、索引、扩展。

使用: python -m shapeai.migrate

在 PostgreSQL 中创建所有业务表，在 MySQL 中创建同步副本表，
在 Milvus 中创建知识库向量集合。
"""

import logging
from .database import pg_cursor, redis_client, get_milvus, mysql_cursor
from .config import MILVUS_COLLECTION
from .records.activity_store import ACTIVITY_SCHEMA_SQL

logger = logging.getLogger(__name__)

# ─── PostgreSQL 建表 SQL ───

PG_SCHEMA_SQL = """
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 用户账号表（注册/登录）
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    nickname      VARCHAR(64),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id          VARCHAR(64) PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL DEFAULT 'anonymous',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    memory      JSONB DEFAULT '{}'::jsonb,
    user_profile JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC);

-- 消息表（会话历史）
CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(32) NOT NULL,
    name        VARCHAR(64),
    args        JSONB DEFAULT '{}'::jsonb,
    content     TEXT,
    is_retry    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages (role);
-- GIN 索引：支持 args JSONB 内部字段查询
CREATE INDEX IF NOT EXISTS idx_messages_args_gin ON messages USING gin (args jsonb_path_ops);

-- 用户记忆表（中长期记忆独立于 session）
CREATE TABLE IF NOT EXISTS user_memories (
    user_id         VARCHAR(64) PRIMARY KEY,
    short_term      JSONB DEFAULT '[]'::jsonb,
    mid_term        JSONB DEFAULT '{}'::jsonb,
    long_term       JSONB DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Token 用量记录表
CREATE TABLE IF NOT EXISTS usage_records (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(128),
    scene           VARCHAR(64),
    model           VARCHAR(128),
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_records (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_records (model);

-- 安全拦截日志表
CREATE TABLE IF NOT EXISTS interception_logs (
    id              BIGSERIAL PRIMARY KEY,
    side            VARCHAR(16) NOT NULL,
    type            VARCHAR(64) NOT NULL,
    reason          TEXT,
    text_preview    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interception_type ON interception_logs (type);
CREATE INDEX IF NOT EXISTS idx_interception_time ON interception_logs (created_at DESC);

-- 知识文档表（元数据，向量存 Milvus）
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          BIGSERIAL PRIMARY KEY,
    title       VARCHAR(512),
    content     TEXT NOT NULL,
    source      VARCHAR(256),
    category    VARCHAR(64),
    milvus_id   BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_documents (category);
CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_documents (source);

-- 体重记录表
CREATE TABLE IF NOT EXISTS weight_records (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    weight_kg       FLOAT NOT NULL,
    body_fat_pct    FLOAT,
    waist_cm        FLOAT,
    hip_cm          FLOAT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_weight_records_user_time ON weight_records (user_id, recorded_at DESC);

-- 饮食记录表
CREATE TABLE IF NOT EXISTS diet_records (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    meal_type       VARCHAR(32) NOT NULL,
    food_name       VARCHAR(256) NOT NULL,
    amount_g        FLOAT,
    calories        FLOAT,
    protein_g       FLOAT,
    carbs_g         FLOAT,
    fat_g           FLOAT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    image_url       VARCHAR(512)
);
CREATE INDEX IF NOT EXISTS idx_diet_records_user_time ON diet_records (user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_diet_records_meal_type ON diet_records (meal_type);

-- 饮食记录扩展字段（来源与统计开关）
-- source: 'chat' 对话上报 / 'order' 外卖下单
-- order_id: 关联到 takeout_orders.id，可为 NULL
-- include_in_stats: 是否计入当日热量/蛋白质统计（用户可自主决定）
ALTER TABLE diet_records ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'chat';
ALTER TABLE diet_records ADD COLUMN IF NOT EXISTS order_id BIGINT;
ALTER TABLE diet_records ADD COLUMN IF NOT EXISTS include_in_stats BOOLEAN DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS idx_diet_records_source ON diet_records (source);
CREATE INDEX IF NOT EXISTS idx_diet_records_include_stats ON diet_records (include_in_stats);
CREATE INDEX IF NOT EXISTS idx_diet_records_order_id ON diet_records (order_id);

-- 外卖店家表（连锁快餐品牌维度）
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
);
CREATE INDEX IF NOT EXISTS idx_takeout_shops_category ON takeout_shops (category);

-- 外卖菜品表（属于某店家, 含店内分类）
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
);
CREATE INDEX IF NOT EXISTS idx_takeout_dishes_category ON takeout_dishes (category);
CREATE INDEX IF NOT EXISTS idx_takeout_dishes_available ON takeout_dishes (available);
CREATE INDEX IF NOT EXISTS idx_takeout_dishes_shop ON takeout_dishes (shop_name);

-- 外卖订单表（用户确认下单的外卖订单, shop_name 为下单时快照）
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
);
CREATE INDEX IF NOT EXISTS idx_takeout_orders_user_time ON takeout_orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_takeout_orders_status ON takeout_orders (order_status);

-- 订单碳水/脂肪总量（后续补充字段，历史订单默认 0）
ALTER TABLE takeout_orders ADD COLUMN IF NOT EXISTS total_carbs_g FLOAT DEFAULT 0;
ALTER TABLE takeout_orders ADD COLUMN IF NOT EXISTS total_fat_g FLOAT DEFAULT 0;

-- 运动记录表
CREATE TABLE IF NOT EXISTS exercise_records (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    exercise_name   VARCHAR(256) NOT NULL,
    exercise_type   VARCHAR(64),
    duration_min    INTEGER,
    calories_burned FLOAT,
    completed       BOOLEAN DEFAULT TRUE,
    scheduled_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_exercise_records_user_date ON exercise_records (user_id, scheduled_date DESC);

-- 用户目标表
CREATE TABLE IF NOT EXISTS user_goals (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    goal_type       VARCHAR(64) NOT NULL,
    target_value    FLOAT NOT NULL,
    current_value   FLOAT,
    unit            VARCHAR(32),
    start_value     FLOAT,
    deadline        DATE,
    status          VARCHAR(32) DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_goals_user ON user_goals (user_id, status);

-- 消息反馈表
CREATE TABLE IF NOT EXISTS message_feedback (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64),
    message_id      VARCHAR(64),
    feedback_type   VARCHAR(32) NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_message_feedback_user ON message_feedback (user_id, created_at DESC);

-- 饮水记录表
CREATE TABLE IF NOT EXISTS hydration_records (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    amount_ml       FLOAT NOT NULL,
    drink_type      VARCHAR(32) DEFAULT 'water',
    notes           TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hydration_user_time ON hydration_records (user_id, recorded_at DESC);

-- 用户资料表补充字段（daily_calorie_budget：每日热量预算，由营养素目标自动推算）
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS daily_calorie_budget INTEGER;
-- 三大营养素每日目标(g)：每天按体重/身高/BMI 自动生成默认值，用户可调整；调整后预算热量随之重算
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS protein_target_g REAL;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS carbs_target_g REAL;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS fat_target_g REAL;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS macro_targets_date VARCHAR(32);

-- 冰箱食材表（用户冰箱库存,图片存 MinIO 对象 key）
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
);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_time ON fridge_items (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_name ON fridge_items (user_id, name);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_cat  ON fridge_items (user_id, category);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_expires ON fridge_items (user_id, expires_at);
"""

# 活动模块建表 SQL（活动/群聊/成员/消息, 见 records/activity_store.py）
ACTIVITY_PG_SCHEMA_SQL = ACTIVITY_SCHEMA_SQL

# ─── MySQL 同步副本建表 SQL ───

MYSQL_SCHEMA_SQL = """
-- MySQL 同步副本（只读分析用，无外键约束，简化字段类型）

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    nickname      VARCHAR(64),
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME NULL
);
CREATE INDEX idx_users_username ON users (username);

CREATE TABLE IF NOT EXISTS sessions (
    id          VARCHAR(64) PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL DEFAULT 'anonymous',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    memory      JSON,
    user_profile JSON
);
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_created_at ON sessions (created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL,
    role        VARCHAR(32) NOT NULL,
    name        VARCHAR(64),
    args        JSON,
    content     TEXT,
    is_retry    TINYINT(1) DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_messages_session_id ON messages (session_id, created_at);
CREATE INDEX idx_messages_role ON messages (role);

CREATE TABLE IF NOT EXISTS usage_records (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(128),
    scene           VARCHAR(64),
    model           VARCHAR(128),
    input_tokens    INT DEFAULT 0,
    output_tokens   INT DEFAULT 0,
    total_tokens     INT DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_usage_user_time ON usage_records (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS interception_logs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    side            VARCHAR(16) NOT NULL,
    type            VARCHAR(64) NOT NULL,
    reason          TEXT,
    text_preview    TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interception_type ON interception_logs (type);
CREATE INDEX idx_interception_time ON interception_logs (created_at DESC);

CREATE TABLE IF NOT EXISTS hydration_records (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    amount_ml       FLOAT NOT NULL,
    drink_type      VARCHAR(32) DEFAULT 'water',
    notes           TEXT,
    recorded_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_hydration_user_time ON hydration_records (user_id, recorded_at DESC);
"""


def migrate_postgresql():
    """执行 PostgreSQL 建表迁移。"""
    logger.info("开始 PostgreSQL 迁移...")
    statements = [s.strip() for s in PG_SCHEMA_SQL.split(";") if s.strip()]
    statements += [s.strip() for s in ACTIVITY_PG_SCHEMA_SQL.split(";") if s.strip()]
    for stmt in statements:
        try:
            with pg_cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            logger.warning("PG 语句执行跳过(可能已存在): %s", str(exc)[:100])
    logger.info("PostgreSQL 迁移完成，共 %d 条语句", len(statements))


def migrate_mysql():
    """执行 MySQL 建表迁移。"""
    logger.info("开始 MySQL 迁移...")
    statements = [s.strip() for s in MYSQL_SCHEMA_SQL.split(";") if s.strip()]
    for stmt in statements:
        try:
            with mysql_cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            logger.warning("MySQL 语句执行跳过(可能已存在): %s", str(exc)[:100])
    logger.info("MySQL 迁移完成，共 %d 条语句", len(statements))


def migrate_milvus():
    """创建 Milvus 知识库向量集合。"""
    logger.info("开始 Milvus 迁移...")
    try:
        from pymilvus import (
            Collection, CollectionSchema, FieldSchema, DataType, utility
        )
        get_milvus()

        if utility.has_collection(MILVUS_COLLECTION):
            logger.info("Milvus 集合 '%s' 已存在", MILVUS_COLLECTION)
            return

        # 向量维度 1536 对应 text-embedding-3-small / text-embedding-ada-002
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536),
        ]
        schema = CollectionSchema(fields, description="ShapeAI 知识库向量集合")
        collection = Collection(MILVUS_COLLECTION, schema)

        # 创建 IVF_FLAT 索引
        collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": "IVF_FLAT",
                "metric_type": "COSINE",
                "params": {"nlist": 128},
            },
        )
        logger.info("Milvus 集合 '%s' 创建完成，维度=1536", MILVUS_COLLECTION)
    except Exception as exc:
        logger.error("Milvus 迁移失败: %s", exc)
        raise


def migrate_redis():
    """Redis 初始化（设置 key 前缀，无需建表）。"""
    logger.info("检查 Redis 连接...")
    r = redis_client()
    r.set("shapeai:migration:done", "1", ex=86400)
    logger.info("Redis 连接正常，前缀 shapeai:")


def migrate_all():
    """执行全部迁移。"""
    print("=" * 60)
    print("  ShapeAI 数据库迁移")
    print("=" * 60)

    # 1. PostgreSQL
    print("\n[1/4] PostgreSQL 迁移...")
    try:
        migrate_postgresql()
        print("  [OK] PostgreSQL 迁移完成")
    except Exception as e:
        print(f"  [FAIL] PostgreSQL 迁移失败: {e}")

    # 2. MySQL
    print("\n[2/4] MySQL 迁移...")
    try:
        migrate_mysql()
        print("  [OK] MySQL 迁移完成")
    except Exception as e:
        print(f"  [FAIL] MySQL 迁移失败: {e}")

    # 3. Milvus
    print("\n[3/4] Milvus 迁移...")
    try:
        migrate_milvus()
        print("  [OK] Milvus 迁移完成")
    except Exception as e:
        print(f"  [FAIL] Milvus 迁移失败: {e}")

    # 4. Redis
    print("\n[4/4] Redis 检查...")
    try:
        migrate_redis()
        print("  [OK] Redis 连接正常")
    except Exception as e:
        print(f"  [FAIL] Redis 连接失败: {e}")

    print("\n" + "=" * 60)
    print("  迁移完成!")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    migrate_all()
