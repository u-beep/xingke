"""ShapeAI 配置中心。

所有配置项支持环境变量覆盖，优先级：
显式参数 > 环境变量 > .env 文件 > 代码默认值。
"""

import os
from pathlib import Path

# ─── 版本号 ───
__version__ = "0.1.0"

# ─── 自动加载 .env 文件 ───
# 不依赖 python-dotenv，手动解析 .env，保持零外部依赖。


def _load_dotenv():
    """从项目根目录的 .env 文件加载环境变量。

    已存在的环境变量不会被 .env 覆盖（环境变量优先级更高）。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# ─── 项目根目录 ───
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SESSIONS_DIR = PROJECT_ROOT / ".shapeai" / "sessions"
RUNS_DIR = PROJECT_ROOT / ".shapeai" / "runs"
MEMORY_DIR = PROJECT_ROOT / ".shapeai" / "memory"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"

# 确保目录存在
for _d in (DATA_DIR, SESSIONS_DIR, RUNS_DIR, MEMORY_DIR, KNOWLEDGE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─── 模型网关配置 ───
# 主模型（豆包/OpenAI兼容）
PRIMARY_MODEL = os.environ.get("SHAPEAI_PRIMARY_MODEL", "deepseek-v4-pro")
PRIMARY_BASE_URL = os.environ.get("SHAPEAI_PRIMARY_BASE_URL", "https://api.deepseek.com/anthropic")
PRIMARY_API_KEY = os.environ.get("SHAPEAI_PRIMARY_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))

# 备用模型（通义千问/OpenAI兼容）
FALLBACK_MODEL = os.environ.get("SHAPEAI_FALLBACK_MODEL", "qwen-plus")
FALLBACK_BASE_URL = os.environ.get("SHAPEAI_FALLBACK_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode")
FALLBACK_API_KEY = os.environ.get("SHAPEAI_FALLBACK_API_KEY", os.environ.get("DASHSCOPE_API_KEY", ""))

# 模型参数
MODEL_TIMEOUT = int(os.environ.get("SHAPEAI_MODEL_TIMEOUT", "300"))
MODEL_TEMPERATURE = float(os.environ.get("SHAPEAI_TEMPERATURE", "0.3"))
MODEL_MAX_TOKENS = int(os.environ.get("SHAPEAI_MAX_TOKENS", "2048"))

# 视觉模型 (DeepSeek 多模态, OpenAI 兼容 chat completions)
VISION_MODEL = os.environ.get("SHAPEAI_VISION_MODEL", "deepseek-v4-flash-vision-exp")
VISION_BASE_URL = os.environ.get("SHAPEAI_VISION_BASE_URL", "https://api.deepseek.com")
VISION_API_KEY = os.environ.get(
    "SHAPEAI_VISION_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", "")
    or os.environ.get("PICO_DEEPSEEK_API_KEY", "")
    or os.environ.get("SHAPEAI_PRIMARY_API_KEY", ""),
)

# ─── Agent 配置 ───
AGENT_MAX_STEPS = int(os.environ.get("SHAPEAI_MAX_STEPS", "8"))
CONTEXT_BUDGET = int(os.environ.get("SHAPEAI_CONTEXT_BUDGET", "12000"))

# ─── API 服务配置 ───
# 注: 8900 在 Windows 上常被 Hyper-V 保留端口占用,默认改用 28900
API_HOST = os.environ.get("SHAPEAI_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("SHAPEAI_PORT", "28900"))
API_KEY = os.environ.get("SHAPEAI_API_KEY", "shapeai-dev-key")

# ─── 安全配置 ───
# 医疗边界：禁止出现的关键词
MEDICAL_FORBIDDEN_KEYWORDS = [
    "诊断", "确诊", "处方", "开药", "用药建议", "治疗方案",
    "疾病", "病变", "病理", "手术", "药物相互作用",
    "diagnose", "prescription", "treatment plan",
]

# 极端行为检测关键词
EXTREME_BEHAVIOR_KEYWORDS = [
    "催吐", "断食", "绝食", "极低热量", "零碳水", "泻药",
    "减肥药", "利尿剂", "超量运动", "过度训练",
]

# 敏感词过滤
SENSITIVE_WORDS = [
    "自杀", "自残", "厌食症", "暴食症",
]

# ─── 食物营养数据库（MVP 内置） ───
# 数值均为每 100g 参考值。别名映射在 FOOD_ALIAS。
FOOD_DATABASE = {
    # 主食
    "米饭": {"calories": 116, "protein": 2.6, "carbs": 25.9, "fat": 0.3, "unit": "100g"},
    "面条": {"calories": 110, "protein": 3.6, "carbs": 22.2, "fat": 0.6, "unit": "100g"},
    "馒头": {"calories": 223, "protein": 7.0, "carbs": 47.0, "fat": 1.1, "unit": "100g"},
    "燕麦": {"calories": 389, "protein": 16.9, "carbs": 66.0, "fat": 6.9, "unit": "100g"},
    "红薯": {"calories": 86, "protein": 1.6, "carbs": 20.0, "fat": 0.1, "unit": "100g"},
    "玉米": {"calories": 86, "protein": 3.2, "carbs": 19.0, "fat": 1.2, "unit": "100g"},
    "土豆": {"calories": 77, "protein": 2.0, "carbs": 17.8, "fat": 0.1, "unit": "100g"},
    "面包": {"calories": 313, "protein": 8.3, "carbs": 58.6, "fat": 5.1, "unit": "100g"},
    # 肉蛋
    "鸡蛋": {"calories": 144, "protein": 13.3, "carbs": 1.5, "fat": 8.8, "unit": "100g"},
    "鸡胸肉": {"calories": 133, "protein": 31.0, "carbs": 0, "fat": 1.2, "unit": "100g"},
    "鸡肉": {"calories": 167, "protein": 19.3, "carbs": 1.5, "fat": 9.6, "unit": "100g"},
    "牛肉": {"calories": 125, "protein": 20.2, "carbs": 0, "fat": 4.2, "unit": "100g"},
    "猪肉": {"calories": 143, "protein": 20.3, "carbs": 0, "fat": 6.2, "unit": "100g"},
    "鱼肉": {"calories": 103, "protein": 17.9, "carbs": 0, "fat": 3.2, "unit": "100g"},
    "虾仁": {"calories": 48, "protein": 10.4, "carbs": 0.1, "fat": 0.7, "unit": "100g"},
    # 蔬菜
    "豆腐": {"calories": 81, "protein": 8.1, "carbs": 1.9, "fat": 3.7, "unit": "100g"},
    "西兰花": {"calories": 36, "protein": 4.1, "carbs": 4.3, "fat": 0.6, "unit": "100g"},
    "西红柿": {"calories": 19, "protein": 0.9, "carbs": 4.0, "fat": 0.2, "unit": "100g"},
    "黄瓜": {"calories": 16, "protein": 0.8, "carbs": 2.9, "fat": 0.2, "unit": "100g"},
    "生菜": {"calories": 13, "protein": 1.3, "carbs": 2.0, "fat": 0.1, "unit": "100g"},
    "胡萝卜": {"calories": 39, "protein": 1.0, "carbs": 8.8, "fat": 0.2, "unit": "100g"},
    "番茄": {"calories": 18, "protein": 0.9, "carbs": 3.9, "fat": 0.2, "unit": "100g"},
    "白菜": {"calories": 17, "protein": 1.5, "carbs": 3.2, "fat": 0.1, "unit": "100g"},
    "菠菜": {"calories": 24, "protein": 2.6, "carbs": 4.5, "fat": 0.3, "unit": "100g"},
    "茄子": {"calories": 23, "protein": 1.1, "carbs": 4.9, "fat": 0.2, "unit": "100g"},
    "青椒": {"calories": 22, "protein": 1.0, "carbs": 5.4, "fat": 0.2, "unit": "100g"},
    "洋葱": {"calories": 40, "protein": 1.1, "carbs": 9.3, "fat": 0.2, "unit": "100g"},
    "蘑菇": {"calories": 22, "protein": 3.1, "carbs": 3.3, "fat": 0.3, "unit": "100g"},
    "豆芽": {"calories": 16, "protein": 2.1, "carbs": 2.5, "fat": 0.1, "unit": "100g"},
    # 水果
    "苹果": {"calories": 52, "protein": 0.3, "carbs": 14.0, "fat": 0.2, "unit": "100g"},
    "香蕉": {"calories": 89, "protein": 1.1, "carbs": 23.0, "fat": 0.3, "unit": "100g"},
    "橙子": {"calories": 47, "protein": 0.9, "carbs": 11.8, "fat": 0.1, "unit": "100g"},
    "葡萄": {"calories": 43, "protein": 0.5, "carbs": 10.3, "fat": 0.2, "unit": "100g"},
    "芭乐": {"calories": 41, "protein": 2.6, "carbs": 14.3, "fat": 1.0, "unit": "100g"},
    "李子": {"calories": 36, "protein": 0.7, "carbs": 8.7, "fat": 0.3, "unit": "100g"},
    # 乳制品
    "牛奶": {"calories": 54, "protein": 3.0, "carbs": 3.4, "fat": 3.2, "unit": "100g"},
    "酸奶": {"calories": 72, "protein": 2.5, "carbs": 9.3, "fat": 2.7, "unit": "100g"},
    # 调味
    "生姜": {"calories": 41, "protein": 1.3, "carbs": 7.6, "fat": 0.6, "unit": "100g"},
    "大蒜": {"calories": 149, "protein": 6.4, "carbs": 33.1, "fat": 0.5, "unit": "100g"},
    "葱": {"calories": 27, "protein": 1.6, "carbs": 5.2, "fat": 0.3, "unit": "100g"},
}

# 食材别名 → 标准库 key(解决 LLM 返回别名时精确/模糊匹配都失败的问题)
FOOD_ALIAS = {
    "洋柿子": "西红柿", "小番茄": "番茄", "圣女果": "番茄",
    "马铃薯": "土豆", "洋芋": "土豆", "山药蛋": "土豆",
    "鸡柳": "鸡胸肉", "鸡脯肉": "鸡胸肉",
    "牛排": "牛肉", "牛腩": "牛肉",
    "大葱": "葱", "香葱": "葱", "小葱": "葱", "葱花": "葱",
    "青葱": "葱", "蒜苗": "葱",
    "蒜头": "大蒜", "蒜瓣": "大蒜",
    "灯笼椒": "青椒", "甜椒": "青椒", "柿子椒": "青椒",
    "黄豆芽": "豆芽", "绿豆芽": "豆芽",
    "平菇": "蘑菇", "香菇": "蘑菇", "金针菇": "蘑菇",
    "酸乳": "酸奶",
    "橙": "橙子", "柑橘": "橙子",
    "提子": "葡萄",
    "番石榴": "芭乐", "拔子": "芭乐",
    "李": "李子", "青李": "李子", "红李": "李子", "黑李": "李子",
}


# ─── 数据库配置 ───
# PostgreSQL (主数据库，存储会话/记忆/用量/安全日志)
POSTGRES_HOST = os.environ.get("SHAPEAI_PG_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("SHAPEAI_PG_PORT", "5433"))  # compose 映射 5433->5432
POSTGRES_DB = os.environ.get("SHAPEAI_PG_DB", "shapeai")
POSTGRES_USER = os.environ.get("SHAPEAI_PG_USER", "shapeai")
POSTGRES_PASSWORD = os.environ.get("SHAPEAI_PG_PASSWORD", "shapeai123")

# Redis (短期记忆/缓存/Session 热数据)
REDIS_HOST = os.environ.get("SHAPEAI_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("SHAPEAI_REDIS_PORT", "6380"))  # compose 映射 6380->6379
REDIS_DB = int(os.environ.get("SHAPEAI_REDIS_DB", "0"))
REDIS_PASSWORD = os.environ.get("SHAPEAI_REDIS_PASSWORD", "")

# Milvus (向量检索/知识库)
MILVUS_HOST = os.environ.get("SHAPEAI_MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.environ.get("SHAPEAI_MILVUS_PORT", "19530"))
MILVUS_COLLECTION = os.environ.get("SHAPEAI_MILVUS_COLLECTION", "shapeai_knowledge")

# MySQL (同步副本，只读分析)
MYSQL_HOST = os.environ.get("SHAPEAI_MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("SHAPEAI_MYSQL_PORT", "3307"))  # compose 映射 3307->3306
MYSQL_DB = os.environ.get("SHAPEAI_MYSQL_DB", "shapeai")
MYSQL_USER = os.environ.get("SHAPEAI_MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("SHAPEAI_MYSQL_PASSWORD", "123456")

# MinIO (对象存储,冰箱食材图片,复用 docker-compose minio 服务)
# 注: 宿主机 9000/9001 被 Windows Hyper-V 保留,compose 映射为 19000/19001
MINIO_ENDPOINT = os.environ.get("SHAPEAI_MINIO_ENDPOINT", "localhost:19000")  # 宿主机 API 端口
MINIO_ACCESS_KEY = os.environ.get("SHAPEAI_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("SHAPEAI_MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.environ.get("SHAPEAI_MINIO_SECURE", "false").lower() in ("true", "1", "yes")
MINIO_BUCKET = os.environ.get("SHAPEAI_MINIO_BUCKET", "fridge-images")

# PG -> MySQL 定时同步配置
SYNC_ENABLED = os.environ.get("SHAPEAI_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")
SYNC_INTERVAL_SECONDS = int(os.environ.get("SHAPEAI_SYNC_INTERVAL", "60"))

# 知识爬虫配置 (定时拉取营养学网站知识到 Milvus)
CRAWLER_ENABLED = os.environ.get("SHAPEAI_CRAWLER_ENABLED", "false").lower() in ("true", "1", "yes")
CRAWLER_INTERVAL_SECONDS = int(os.environ.get("SHAPEAI_CRAWLER_INTERVAL", "3600"))  # 默认 1 小时
CRAWLER_TIMEOUT = int(os.environ.get("SHAPEAI_CRAWLER_TIMEOUT", "30"))  # HTTP 请求超时(秒)
CRAWLER_USER_AGENT = os.environ.get("SHAPEAI_CRAWLER_USER_AGENT", "ShapeAI-Knowledge-Bot/1.0")


def get_config() -> dict:
    """获取完整配置快照。"""
    return {
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "vision_model": VISION_MODEL,
        "api_port": API_PORT,
        "max_steps": AGENT_MAX_STEPS,
        "context_budget": CONTEXT_BUDGET,
        "databases": {
            "postgres": {"host": POSTGRES_HOST, "port": POSTGRES_PORT, "db": POSTGRES_DB},
            "redis": {"host": REDIS_HOST, "port": REDIS_PORT, "db": REDIS_DB},
            "milvus": {"host": MILVUS_HOST, "port": MILVUS_PORT},
            "mysql": {"host": MYSQL_HOST, "port": MYSQL_PORT, "db": MYSQL_DB},
            "minio": {"endpoint": MINIO_ENDPOINT, "bucket": MINIO_BUCKET, "secure": MINIO_SECURE},
        },
        "sync": {
            "enabled": SYNC_ENABLED,
            "interval_seconds": SYNC_INTERVAL_SECONDS,
        },
        "crawler": {
            "enabled": CRAWLER_ENABLED,
            "interval_seconds": CRAWLER_INTERVAL_SECONDS,
        },
    }
