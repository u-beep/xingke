"""知识拉取器 — 定时通过官方 API 拉取营养学知识到 Milvus。

不使用爬虫，仅调用官方提供的公开 API：

1. USDA FoodData Central API
   - 美国农业部食物营养数据库
   - 官网: https://fdc.nal.usda.gov/
   - API 文档: https://fdc.nal.usda.gov/api-guide.html
   - 免费 API Key (默认使用 DEMO_KEY, 限 30 次/小时)
   - 提供: 食物成分、营养素、热量数据

2. Open Food Facts API
   - 全球开源食品数据库
   - 官网: https://world.openfoodfacts.org/
   - 完全免费, 无需 API Key
   - 提供: 食品营养标签、配料、营养评分

3. 中国居民膳食指南 (内置结构化数据)
   - 《中国食物成分表》标准版第6版 — 杨月欣主编
   - 《中国居民膳食指南(2022)》— 中国营养学会编著
   - 官网: https://www.cnsoc.org/ (无公开API, 结构化录入)
   - 覆盖70+条常见食材: 水果/肉类/坚果/主食/蔬菜/奶豆
   - 每条食材含: 热量/蛋白质/脂肪/碳水/膳食纤维/维C/钙/铁

工作流程:
  1. 调用官方 API 获取 JSON 数据
  2. 将数据转换为知识文档格式 (title, content, source, category)
  3. 去重（基于内容 SHA-256 hash）
  4. 通过 KnowledgeBase 写入 Milvus
  5. 同时持久化元数据到 PostgreSQL knowledge_documents 表

使用:
  命令行:  python -m shapeai.knowledge_fetcher [--once]
  代码内:  from .knowledge_fetcher import KnowledgeFetcher, FetchScheduler
           fetcher = KnowledgeFetcher()
           result = fetcher.fetch_all()       # 立即拉取一次
           scheduler = FetchScheduler(fetcher, interval=3600)
           scheduler.start()                    # 后台定时拉取
"""

import hashlib
import json as _json
import logging
import os
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

from .config import CRAWLER_TIMEOUT, CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)

# ─── 官方 API 配置 ───

# USDA FoodData Central API
USDA_API_KEY = os.environ.get("USDA_API_KEY", "DEMO_KEY")  # 用户可申请自己的 key
USDA_BASE_URL = "https://fdc.nal.usda.gov/api/v1"
USDA_PAGE_SIZE = 20  # 每次拉取条数 (DEMO_KEY 限 30 次/小时)

# Open Food Facts API (无需 key)
OFF_BASE_URL = "https://world.openfoodfacts.org/api/v2"
OFF_PAGE_SIZE = 20


# ─── HTTP 工具 ───


def _http_get_json(url: str, timeout: int = None) -> dict:
    """发起 HTTP GET 请求，解析 JSON 返回。"""
    timeout = timeout or CRAWLER_TIMEOUT
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": CRAWLER_USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode("utf-8"))


# ─── USDA FoodData Central 数据获取 ───


def fetch_usda_foods(page_size: int = USDA_PAGE_SIZE) -> list[dict]:
    """通过 USDA FoodData Central API 拉取食物营养数据。

    API 文档: https://fdc.nal.usda.gov/api-guide.html

    将每条食物记录转换为一个知识文档:
      title: 食物名称
      content: 营养素详情(蛋白质/脂肪/碳水/热量等)
      source: USDA FoodData Central
      category: food_nutrition
    """
    # USDA API v1: /foods/list 需要 POST, /foods/search 可用 GET
    url = f"{USDA_BASE_URL}/foods/search?api_key={USDA_API_KEY}&pageSize={page_size}&dataType=SR%20Legacy,Foundation"
    logger.info("USDA API 请求: %s", url)

    data = _http_get_json(url)
    foods = data.get("foods", [])
    if not isinstance(foods, list):
        return []

    documents = []
    for food in foods:
        # 提取食物名称
        desc = food.get("description", "")
        fdc_id = food.get("fdcId", "")
        if not desc:
            continue

        # 提取营养素
        nutrients = food.get("foodNutrients", [])
        nutrient_lines = []
        for n in nutrients:
            name = n.get("nutrientName", n.get("name", ""))
            amount = n.get("amount", n.get("value", ""))
            unit = n.get("unitName", n.get("unit", ""))
            if name and amount:
                nutrient_lines.append(f"  {name}: {amount}{unit}")

        # 构建知识文档
        title = f"USDA食物: {desc} (FDC ID: {fdc_id})"
        content_parts = [f"食物名称: {desc}"]
        if nutrient_lines:
            content_parts.append("营养素含量(每100g):")
            content_parts.extend(nutrient_lines)
        else:
            content_parts.append("营养素数据暂无")
        content_parts.append(f"数据来源: USDA FoodData Central (FDC ID: {fdc_id})")
        content_parts.append(f"官网: https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients")

        documents.append({
            "title": title,
            "content": "\n".join(content_parts),
            "source": "USDA FoodData Central",
            "category": "food_nutrition",
        })

    logger.info("USDA 拉取 %d 条食物数据", len(documents))
    return documents


# ─── Open Food Facts 数据获取 ───


def fetch_off_products(page_size: int = OFF_PAGE_SIZE) -> list[dict]:
    """通过 Open Food Facts API 拉取食品营养数据。

    API 文档: https://wiki.openfoodfacts.org/API
    完全免费, 无需 API Key。

    将每条食品记录转换为一个知识文档。
    """
    url = f"{OFF_BASE_URL}/search?search_terms=&page_size={page_size}&page=1&fields=product_name,nutriments,categories,nutriscore_grade,quantity,brands"
    logger.info("Open Food Facts API 请求: %s", url)

    data = _http_get_json(url)
    products = data.get("products", [])
    if not isinstance(products, list):
        return []

    documents = []
    for product in products:
        name = product.get("product_name", "")
        if not name:
            continue

        nutriments = product.get("nutriments", {})
        nutri_lines = []
        # 常见营养素
        for key, label in [
            ("energy-kcal_100g", "热量"),
            ("proteins_100g", "蛋白质"),
            ("fat_100g", "脂肪"),
            ("carbohydrates_100g", "碳水化合物"),
            ("sugars_100g", "糖"),
            ("fiber_100g", "膳食纤维"),
            ("sodium_100g", "钠"),
            ("calcium_100g", "钙"),
            ("iron_100g", "铁"),
        ]:
            val = nutriments.get(key)
            if val is not None:
                nutri_lines.append(f"  {label}: {val}{'kcal' if 'energy' in key else 'g'}")

        grade = product.get("nutriscore_grade", "N/A")
        brand = product.get("brands", "未知品牌")
        categories = product.get("categories", "")

        title = f"OFF食品: {name}"
        content_parts = [f"食品名称: {name}"]
        content_parts.append(f"品牌: {brand}")
        content_parts.append(f"营养评分(Nutri-Score): {grade}")
        if categories:
            content_parts.append(f"分类: {categories}")
        if nutri_lines:
            content_parts.append("营养素含量(每100g):")
            content_parts.extend(nutri_lines)
        content_parts.append("数据来源: Open Food Facts")
        content_parts.append("官网: https://world.openfoodfacts.org/")

        documents.append({
            "title": title,
            "content": "\n".join(content_parts),
            "source": "Open Food Facts",
            "category": "food_nutrition",
        })

    logger.info("Open Food Facts 拉取 %d 条食品数据", len(documents))
    return documents


# ─── 本地结构化知识 (中国食物成分表 + 中国居民膳食指南) ───
#
# 数据来源:
#   1. 《中国食物成分表》标准版第6版 — 杨月欣主编, 北京大学医学出版社
#   2. 《中国居民膳食指南(2022)》— 中国营养学会编著
#   3. 中国营养学会官网 https://www.cnsoc.org/ (膳食指南发布机构)
#
# 中国膳食指南官网(dg.cnsoc.org)为静态网站, 无公开 API,
# 以下数据基于官方出版物结构化录入, 每条食材一个独立文档,
# 覆盖: 水果、肉类、坚果、主食(谷薯类)、蔬菜、奶类/豆类 6大品类。
#
# 营养价值数据均为每100g可食部的含量。

# ─── 食材营养数据原始表 ───
# 字段: name, cat(品类), e(能量kcal), p(蛋白质g), f(脂肪g), c(碳水g),
#        fb(膳食纤维g), v(维C mg), ca(钙 mg), fe(铁 mg), note(营养价值)

_CN_FOOD_RAW: list[dict] = [
    # ── 主食 / 谷薯类 ──
    {"name": "大米(粳米)", "cat": "主食-谷类", "e": 347, "p": 7.7, "f": 0.6, "c": 77.4, "fb": 0.6, "v": 0, "ca": 13, "fe": 2.3, "note": "精白米,升糖指数较高,建议搭配杂粮"},
    {"name": "糙米", "cat": "主食-谷类", "e": 348, "p": 8.0, "f": 2.0, "c": 74.0, "fb": 3.4, "v": 0, "ca": 16, "fe": 1.4, "note": "保留米糠层,富含B族维生素和膳食纤维"},
    {"name": "小麦粉(标准粉)", "cat": "主食-谷类", "e": 354, "p": 11.2, "f": 1.5, "c": 73.6, "fb": 2.1, "v": 0, "ca": 31, "fe": 3.5, "note": "标准粉比精白粉保留更多营养"},
    {"name": "玉米(黄,干)", "cat": "主食-谷类", "e": 335, "p": 8.7, "f": 3.8, "c": 73.0, "fb": 6.4, "v": 0, "ca": 14, "fe": 2.4, "note": "富含玉米黄质,有益眼睛健康"},
    {"name": "燕麦片", "cat": "主食-谷类", "e": 367, "p": 15.0, "f": 6.7, "c": 61.6, "fb": 5.3, "v": 0, "ca": 186, "fe": 7.0, "note": "富含β-葡聚糖,有助于降低胆固醇"},
    {"name": "小米", "cat": "主食-谷类", "e": 358, "p": 9.0, "f": 3.1, "c": 75.1, "fb": 1.6, "v": 0, "ca": 41, "fe": 5.1, "note": "富含B族维生素,养胃佳品"},
    {"name": "荞麦", "cat": "主食-谷类", "e": 324, "p": 9.3, "f": 2.3, "c": 73.0, "fb": 6.5, "v": 0, "ca": 47, "fe": 6.2, "note": "富含芦丁,有助于控制血糖"},
    {"name": "红薯", "cat": "主食-薯类", "e": 99, "p": 1.1, "f": 0.2, "c": 24.7, "fb": 1.6, "v": 26, "ca": 23, "fe": 0.5, "note": "富含β-胡萝卜素,可部分替代主食"},
    {"name": "紫薯", "cat": "主食-薯类", "e": 106, "p": 1.2, "f": 0.2, "c": 25.5, "fb": 1.8, "v": 12, "ca": 33, "fe": 0.6, "note": "富含花青素,抗氧化作用强"},
    {"name": "马铃薯(土豆)", "cat": "主食-薯类", "e": 77, "p": 2.0, "f": 0.2, "c": 17.2, "fb": 0.7, "v": 27, "ca": 8, "fe": 0.8, "note": "钾含量丰富,烹饪方式影响热量"},
    {"name": "山药", "cat": "主食-薯类", "e": 57, "p": 1.9, "f": 0.2, "c": 12.4, "fb": 0.8, "v": 5, "ca": 16, "fe": 0.3, "note": "低热量主食替代,含黏蛋白"},
    {"name": "全麦面包", "cat": "主食-谷类加工品", "e": 250, "p": 10.0, "f": 3.5, "c": 46.0, "fb": 6.0, "v": 0, "ca": 80, "fe": 2.5, "note": "选择全麦粉含量>50%的产品"},
    {"name": "挂面", "cat": "主食-谷类加工品", "e": 344, "p": 9.6, "f": 0.7, "c": 75.1, "fb": 0.7, "v": 0, "ca": 14, "fe": 1.8, "note": "精制碳水,升糖指数较高"},
    {"name": "糯米", "cat": "主食-谷类", "e": 350, "p": 7.3, "f": 1.0, "c": 78.3, "fb": 0.8, "v": 0, "ca": 26, "fe": 1.5, "note": "升糖指数高,血糖异常者慎用"},

    # ── 水果类 ──
    {"name": "苹果", "cat": "水果", "e": 54, "p": 0.3, "f": 0.2, "c": 14.0, "fb": 2.4, "v": 4, "ca": 6, "fe": 0.3, "note": "富含果胶,有助于降低胆固醇"},
    {"name": "香蕉", "cat": "水果", "e": 93, "p": 1.4, "f": 0.2, "c": 22.0, "fb": 1.2, "v": 8, "ca": 7, "fe": 0.4, "note": "钾含量丰富(256mg),运动后补钾佳品"},
    {"name": "橙子", "cat": "水果", "e": 48, "p": 0.8, "f": 0.2, "c": 11.1, "fb": 0.6, "v": 33, "ca": 20, "fe": 0.4, "note": "维生素C丰富,增强免疫力"},
    {"name": "葡萄", "cat": "水果", "e": 44, "p": 0.5, "f": 0.2, "c": 10.3, "fb": 0.9, "v": 3, "ca": 5, "fe": 0.4, "note": "富含多酚类抗氧化物,皮和籽中含量更高"},
    {"name": "猕猴桃", "cat": "水果", "e": 61, "p": 0.8, "f": 0.6, "c": 14.5, "fb": 2.6, "v": 62, "ca": 17, "fe": 0.3, "note": "维C之王,帮助铁吸收"},
    {"name": "草莓", "cat": "水果", "e": 32, "p": 1.0, "f": 0.2, "c": 7.1, "fb": 2.0, "v": 47, "ca": 16, "fe": 1.0, "note": "低热量高维C,富含花青素"},
    {"name": "西瓜", "cat": "水果", "e": 26, "p": 0.5, "f": 0.1, "c": 6.4, "fb": 0.2, "v": 4, "ca": 6, "fe": 0.2, "note": "热量最低的水果之一,但升糖指数较高"},
    {"name": "芒果", "cat": "水果", "e": 35, "p": 0.6, "f": 0.2, "c": 8.3, "fb": 1.3, "v": 23, "ca": 11, "fe": 0.2, "note": "富含β-胡萝卜素,维生素A前体"},
    {"name": "蓝莓", "cat": "水果", "e": 57, "p": 0.7, "f": 0.3, "c": 12.9, "fb": 2.4, "v": 9.7, "ca": 6, "fe": 0.3, "note": "花青素含量极高,抗氧化之王"},
    {"name": "梨", "cat": "水果", "e": 51, "p": 0.4, "f": 0.2, "c": 13.3, "fb": 3.1, "v": 4.4, "ca": 9, "fe": 0.2, "note": "水分高,润肺生津,膳食纤维丰富"},
    {"name": "桃", "cat": "水果", "e": 48, "p": 0.9, "f": 0.1, "c": 12.2, "fb": 1.3, "v": 5, "ca": 6, "fe": 0.8, "note": "低热量,含果胶和有机酸"},
    {"name": "柚子", "cat": "水果", "e": 42, "p": 0.8, "f": 0.2, "c": 9.5, "fb": 0.9, "v": 23, "ca": 4, "fe": 0.3, "note": "低GI水果,含柚皮苷,辅助降脂"},
    {"name": "荔枝", "cat": "水果", "e": 70, "p": 0.9, "f": 0.2, "c": 16.6, "fb": 1.1, "v": 41, "ca": 2, "fe": 0.4, "note": "糖分较高,不宜空腹大量食用"},
    {"name": "红枣(干)", "cat": "水果-干果", "e": 274, "p": 3.2, "f": 0.5, "c": 72.8, "fb": 6.2, "v": 14, "ca": 64, "fe": 2.3, "note": "补血佳品,富含环磷酸腺苷"},

    # ── 肉类 / 畜禽鱼肉类 ──
    {"name": "鸡胸肉", "cat": "肉类-禽肉", "e": 133, "p": 31.0, "f": 1.2, "c": 0, "fb": 0, "v": 0, "ca": 15, "fe": 0.9, "note": "高蛋白低脂肪,健身首选"},
    {"name": "猪肉(瘦)", "cat": "肉类-畜肉", "e": 143, "p": 20.3, "f": 6.2, "c": 0, "fb": 0, "v": 0, "ca": 6, "fe": 3.0, "note": "富含B族维生素,铁吸收率较高"},
    {"name": "牛肉(瘦)", "cat": "肉类-畜肉", "e": 125, "p": 20.2, "f": 4.2, "c": 0, "fb": 0, "v": 0, "ca": 9, "fe": 2.8, "note": "富含肌酸和锌,增肌优选"},
    {"name": "羊肉(瘦)", "cat": "肉类-畜肉", "e": 118, "p": 20.5, "f": 3.9, "c": 0, "fb": 0, "v": 0, "ca": 9, "fe": 3.9, "note": "温补食材,富含左旋肉碱"},
    {"name": "草鱼", "cat": "肉类-鱼虾", "e": 113, "p": 17.9, "f": 3.2, "c": 0, "fb": 0, "v": 0, "ca": 36, "fe": 0.4, "note": "淡水鱼,低脂高蛋白"},
    {"name": "三文鱼", "cat": "肉类-鱼虾", "e": 208, "p": 20.0, "f": 13.0, "c": 0, "fb": 0, "v": 0, "ca": 9, "fe": 0.6, "note": "富含Omega-3(EPA+DHA),抗炎护心"},
    {"name": "金枪鱼", "cat": "肉类-鱼虾", "e": 184, "p": 30.0, "f": 6.0, "c": 0, "fb": 0, "v": 0, "ca": 12, "fe": 1.0, "note": "高蛋白深海鱼,富含DHA"},
    {"name": "虾仁", "cat": "肉类-鱼虾", "e": 87, "p": 18.6, "f": 0.3, "c": 0, "fb": 0, "v": 0, "ca": 62, "fe": 1.5, "note": "极低脂肪,富含虾青素"},
    {"name": "鸡蛋", "cat": "肉类-蛋类", "e": 144, "p": 13.3, "f": 8.8, "c": 1.5, "fb": 0, "v": 0, "ca": 56, "fe": 1.2, "note": "全营养食品,卵磷脂丰富"},
    {"name": "鸭肉", "cat": "肉类-禽肉", "e": 240, "p": 15.5, "f": 19.7, "c": 0, "fb": 0, "v": 0, "ca": 6, "fe": 2.2, "note": "脂肪含量较高,去皮后热量降低"},
    {"name": "鸡腿肉(去皮)", "cat": "肉类-禽肉", "e": 181, "p": 20.2, "f": 10.2, "c": 0, "fb": 0, "v": 0, "ca": 15, "fe": 1.0, "note": "比鸡胸肉脂肪略高,口感更好"},
    {"name": "猪排骨", "cat": "肉类-畜肉", "e": 278, "p": 18.3, "f": 23.0, "c": 0, "fb": 0, "v": 0, "ca": 13, "fe": 1.4, "note": "脂肪含量高,减脂期应控制"},
    {"name": "牛腩", "cat": "肉类-畜肉", "e": 235, "p": 17.1, "f": 18.8, "c": 0, "fb": 0, "v": 0, "ca": 8, "fe": 2.7, "note": "富含胶原蛋白,但脂肪较高"},
    {"name": "带鱼", "cat": "肉类-鱼虾", "e": 127, "p": 17.7, "f": 4.9, "c": 0, "fb": 0, "v": 0, "ca": 28, "fe": 1.2, "note": "海鱼,富含卵磷脂"},
    {"name": "鲫鱼", "cat": "肉类-鱼虾", "e": 108, "p": 17.1, "f": 2.7, "c": 0, "fb": 0, "v": 0, "ca": 79, "fe": 1.3, "note": "低脂高钙淡水鱼,汤品佳选"},

    # ── 坚果类 ──
    {"name": "核桃", "cat": "坚果", "e": 646, "p": 14.9, "f": 58.8, "c": 19.1, "fb": 9.5, "v": 1, "ca": 56, "fe": 2.7, "note": "富含α-亚麻酸(植物Omega-3),健脑益智"},
    {"name": "花生(炒)", "cat": "坚果", "e": 583, "p": 24.0, "f": 48.0, "c": 21.6, "fb": 6.3, "v": 2, "ca": 36, "fe": 1.8, "note": "蛋白质含量在坚果中较高,性价比高"},
    {"name": "杏仁", "cat": "坚果", "e": 578, "p": 22.5, "f": 49.0, "c": 23.9, "fb": 10.8, "v": 26, "ca": 248, "fe": 4.3, "note": "维生素E和钙含量高,抗氧化"},
    {"name": "腰果", "cat": "坚果", "e": 559, "p": 17.3, "f": 36.7, "c": 41.6, "fb": 3.3, "v": 0, "ca": 26, "fe": 4.8, "note": "碳水含量在坚果中较高"},
    {"name": "巴旦木(扁桃仁)", "cat": "坚果", "e": 579, "p": 21.0, "f": 50.0, "c": 22.0, "fb": 11.8, "v": 0, "ca": 269, "fe": 3.7, "note": "富含膳食纤维和维生素E"},
    {"name": "开心果", "cat": "坚果", "e": 614, "p": 20.6, "f": 53.0, "c": 21.9, "fb": 9.9, "v": 0, "ca": 105, "fe": 4.0, "note": "富含叶黄素,热量在坚果中相对较低"},
    {"name": "松子", "cat": "坚果", "e": 698, "p": 13.4, "f": 70.6, "c": 11.0, "fb": 2.8, "v": 0, "ca": 14, "fe": 5.9, "note": "脂肪含量最高的坚果之一"},
    {"name": "榛子", "cat": "坚果", "e": 617, "p": 20.0, "f": 52.9, "c": 17.3, "fb": 9.7, "v": 0, "ca": 181, "fe": 3.2, "note": "富含叶酸和维生素E"},
    {"name": "葵花籽(炒)", "cat": "坚果", "e": 615, "p": 22.9, "f": 49.9, "c": 19.1, "fb": 11.8, "v": 0, "ca": 72, "fe": 5.7, "note": "维生素E含量极高,抗氧化"},
    {"name": "芝麻(黑)", "cat": "坚果", "e": 559, "p": 19.1, "f": 46.1, "c": 24.0, "fb": 14.0, "v": 0, "ca": 780, "fe": 22.7, "note": "高钙高铁,黑芝麻养发乌发"},
    {"name": "南瓜籽", "cat": "坚果", "e": 574, "p": 30.0, "f": 46.0, "c": 14.0, "fb": 6.0, "v": 0, "ca": 39, "fe": 8.0, "note": "富含锌和镁,有益前列腺健康"},
    {"name": "夏威夷果", "cat": "坚果", "e": 718, "p": 7.9, "f": 75.0, "c": 13.8, "fb": 8.6, "v": 0, "ca": 40, "fe": 2.7, "note": "热量和脂肪含量最高的坚果,需控量"},

    # ── 蔬菜类 ──
    {"name": "西兰花", "cat": "蔬菜", "e": 36, "p": 4.1, "f": 0.6, "c": 4.3, "fb": 1.6, "v": 56, "ca": 67, "fe": 1.0, "note": "维C和硫代葡萄糖苷丰富,抗癌蔬菜"},
    {"name": "菠菜", "cat": "蔬菜", "e": 28, "p": 2.6, "f": 0.3, "c": 4.5, "fb": 1.7, "v": 32, "ca": 66, "fe": 2.9, "note": "富含叶酸和铁,草酸高需焯水"},
    {"name": "胡萝卜", "cat": "蔬菜", "e": 41, "p": 1.0, "f": 0.2, "c": 10.2, "fb": 2.8, "v": 13, "ca": 19, "fe": 0.6, "note": "β-胡萝卜素丰富,用油烹饪吸收更好"},
    {"name": "西红柿", "cat": "蔬菜", "e": 20, "p": 0.9, "f": 0.2, "c": 4.0, "fb": 0.5, "v": 19, "ca": 10, "fe": 0.4, "note": "富含番茄红素,加热后吸收率提高"},
    {"name": "黄瓜", "cat": "蔬菜", "e": 16, "p": 0.8, "f": 0.2, "c": 2.9, "fb": 0.5, "v": 9, "ca": 15, "fe": 0.3, "note": "热量极低,水分含量96%以上"},
    {"name": "生菜", "cat": "蔬菜", "e": 16, "p": 1.3, "f": 0.2, "c": 2.2, "fb": 0.7, "v": 14, "ca": 34, "fe": 0.5, "note": "低热量,富含叶酸"},
    {"name": "白菜(大白菜)", "cat": "蔬菜", "e": 17, "p": 1.5, "f": 0.1, "c": 3.2, "fb": 0.8, "v": 28, "ca": 50, "fe": 0.5, "note": "低热量高维C,冬季当家菜"},
    {"name": "芹菜", "cat": "蔬菜", "e": 14, "p": 0.8, "f": 0.1, "c": 3.0, "fb": 1.2, "v": 8, "ca": 48, "fe": 0.4, "note": "低热量高纤维,富含钾(154mg)"},
    {"name": "芦笋", "cat": "蔬菜", "e": 22, "p": 2.6, "f": 0.2, "c": 3.2, "fb": 1.4, "v": 7, "ca": 10, "fe": 0.7, "note": "富含天冬酰胺和叶酸"},
    {"name": "茄子", "cat": "蔬菜", "e": 21, "p": 1.1, "f": 0.2, "c": 4.9, "fb": 1.3, "v": 5, "ca": 13, "fe": 0.4, "note": "富含花青素(皮中),烹饪吸油需注意"},
    {"name": "青椒(甜椒)", "cat": "蔬菜", "e": 22, "p": 1.0, "f": 0.2, "c": 5.4, "fb": 1.4, "v": 72, "ca": 14, "fe": 0.5, "note": "维C含量极高,红甜椒含量更高"},
    {"name": "蘑菇(鲜香菇)", "cat": "蔬菜", "e": 26, "p": 2.2, "f": 0.3, "c": 5.2, "fb": 3.3, "v": 1, "ca": 2, "fe": 0.3, "note": "富含多糖和维生素D前体(麦角甾醇)"},
    {"name": "木耳(水发)", "cat": "蔬菜", "e": 27, "p": 1.5, "f": 0.2, "c": 6.0, "fb": 2.6, "v": 0, "ca": 34, "fe": 4.1, "note": "富含多糖和铁,预防血栓"},
    {"name": "海带(水发)", "cat": "蔬菜", "e": 14, "p": 1.2, "f": 0.1, "c": 2.8, "fb": 0.5, "v": 0, "ca": 150, "fe": 2.2, "note": "富含碘(36mg)和褐藻糖胶"},
    {"name": "紫甘蓝", "cat": "蔬菜", "e": 25, "p": 1.4, "f": 0.3, "c": 5.5, "fb": 2.3, "v": 39, "ca": 38, "fe": 0.5, "note": "花青素含量高,抗氧化"},
    {"name": "豆角(四季豆)", "cat": "蔬菜", "e": 31, "p": 2.0, "f": 0.4, "c": 5.7, "fb": 1.5, "v": 9, "ca": 29, "fe": 1.0, "note": "富含植物凝集素,务必充分加热"},
    {"name": "洋葱", "cat": "蔬菜", "e": 40, "p": 1.1, "f": 0.2, "c": 9.0, "fb": 0.9, "v": 8, "ca": 24, "fe": 0.6, "note": "含槲皮素和前列腺素A,辅助降脂"},
    {"name": "南瓜", "cat": "蔬菜", "e": 23, "p": 0.7, "f": 0.1, "c": 5.3, "fb": 0.8, "v": 8, "ca": 16, "fe": 0.4, "note": "富含β-胡萝卜素,低热量代餐"},
    {"name": "冬瓜", "cat": "蔬菜", "e": 12, "p": 0.4, "f": 0.2, "c": 2.6, "fb": 0.7, "v": 18, "ca": 19, "fe": 0.2, "note": "热量最低的蔬菜之一,利水消肿"},
    {"name": "油菜", "cat": "蔬菜", "e": 25, "p": 2.6, "f": 0.4, "c": 3.6, "fb": 1.0, "v": 36, "ca": 108, "fe": 1.4, "note": "深色叶菜,钙含量较高"},
    {"name": "豆芽(黄豆芽)", "cat": "蔬菜", "e": 47, "p": 4.5, "f": 1.6, "c": 4.5, "fb": 1.5, "v": 6, "ca": 21, "fe": 0.6, "note": "富含维C和叶酸,黄豆发芽后营养提升"},

    # ── 奶类 / 豆类 ──
    {"name": "牛奶", "cat": "奶类", "e": 54, "p": 3.0, "f": 3.2, "c": 3.4, "fb": 0, "v": 0, "ca": 104, "fe": 0.3, "note": "最佳钙来源,优质蛋白,含乳糖"},
    {"name": "酸奶(无糖)", "cat": "奶类", "e": 72, "p": 2.5, "f": 2.7, "c": 9.3, "fb": 0, "v": 1, "ca": 118, "fe": 0.3, "note": "益生菌丰富,乳糖不耐受者可选"},
    {"name": "脱脂牛奶", "cat": "奶类", "e": 35, "p": 3.4, "f": 0.1, "c": 5.0, "fb": 0, "v": 0, "ca": 123, "fe": 0.3, "note": "减脂期首选奶制品,高钙低脂"},
    {"name": "奶酪(切达)", "cat": "奶类", "e": 328, "p": 25.7, "f": 23.5, "c": 3.5, "fb": 0, "v": 0, "ca": 470, "fe": 0.7, "note": "高钙高蛋白,但热量高需控量"},
    {"name": "豆腐(北/老豆腐)", "cat": "豆类", "e": 98, "p": 12.2, "f": 4.8, "c": 1.5, "fb": 0.4, "v": 0, "ca": 138, "fe": 2.5, "note": "高蛋白高钙,植物肉代表"},
    {"name": "豆腐(南/嫩豆腐)", "cat": "豆类", "e": 57, "p": 6.2, "f": 2.5, "c": 1.6, "fb": 0.3, "v": 0, "ca": 116, "fe": 1.5, "note": "口感嫩滑,热量比北豆腐低"},
    {"name": "黄豆(干)", "cat": "豆类", "e": 390, "p": 35.0, "f": 16.0, "c": 34.2, "fb": 15.5, "v": 0, "ca": 191, "fe": 8.2, "note": "植物蛋白之王,含大豆异黄酮"},
    {"name": "黑豆(干)", "cat": "豆类", "e": 401, "p": 36.0, "f": 15.9, "c": 33.6, "fb": 10.2, "v": 0, "ca": 224, "fe": 7.0, "note": "富含花青素和维生素E,补肾养血"},
    {"name": "绿豆(干)", "cat": "豆类", "e": 329, "p": 21.6, "f": 0.8, "c": 62.0, "fb": 6.4, "v": 0, "ca": 81, "fe": 6.5, "note": "清热解暑,低脂高碳水"},
    {"name": "红豆(干)", "cat": "豆类", "e": 324, "p": 20.2, "f": 0.6, "c": 63.4, "fb": 7.7, "v": 0, "ca": 74, "fe": 7.4, "note": "富含膳食纤维和皂苷,利水消肿"},
    {"name": "豆浆(无糖)", "cat": "豆类", "e": 31, "p": 3.0, "f": 1.6, "c": 1.2, "fb": 0.3, "v": 0, "ca": 5, "fe": 0.4, "note": "低热量,乳糖不耐受者替代品,钙含量低"},
    {"name": "腐竹(干)", "cat": "豆类", "e": 489, "p": 44.6, "f": 21.7, "c": 22.3, "fb": 1.0, "v": 0, "ca": 77, "fe": 16.5, "note": "豆制品中蛋白质最高,但热量高"},
    {"name": "纳豆", "cat": "豆类", "e": 212, "p": 17.7, "f": 11.0, "c": 12.0, "fb": 5.4, "v": 0, "ca": 217, "fe": 3.3, "note": "富含维生素K2和纳豆激酶"},
]


def _build_cn_food_doc(item: dict) -> dict:
    """将一条食材原始数据构建为知识文档。

    每条食材一个独立文档，内容包含：
    食材名称、品类、每100g营养含量、营养价值说明。
    """
    name = item["name"]
    cat = item["cat"]
    lines = [
        f"食材名称: {name}",
        f"品类: {cat}",
        f"每100g可食部营养含量:",
        f"  能量: {item['e']}kcal",
        f"  蛋白质: {item['p']}g",
        f"  脂肪: {item['f']}g",
        f"  碳水化合物: {item['c']}g",
        f"  膳食纤维: {item['fb']}g",
        f"  维生素C: {item['v']}mg",
        f"  钙: {item['ca']}mg",
        f"  铁: {item['fe']}mg",
        f"营养价值: {item['note']}",
        "",
        "数据来源: 《中国食物成分表》标准版第6版(杨月欣主编)",
        "指南来源: 《中国居民膳食指南(2022)》中国营养学会",
        "官网: https://www.cnsoc.org/",
    ]
    return {
        "title": f"中国膳食指南 - {name}({cat})",
        "content": "\n".join(lines),
        "source": "中国居民膳食指南",
        "category": "food_nutrition",
    }


# 中国居民膳食指南(2022) 每日推荐摄入量总结
_CN_DIETARY_GUIDELINES: list[dict] = [
    {
        "title": "中国居民膳食指南(2022) - 每日食物推荐量",
        "content": """中国居民膳食指南(2022) — 每日食物推荐摄入量(成人):

1. 谷薯类 200-300g(生重), 其中全谷物和杂豆50-150g, 薯类50-100g
2. 蔬菜类 300-500g, 深色蔬菜占一半以上
3. 水果类 200-350g, 果汁不能代替鲜果
4. 畜禽肉 40-75g, 水产品 40-75g, 蛋类 40-50g
5. 奶及奶制品 300-500g(以液态奶计)
6. 大豆及坚果 25-35g, 其中坚果 10g
7. 烹调油 25-30g, 食盐 <5g
8. 添加糖 <25g(最好<50g), 饮酒成年男性<25g酒精/女性<15g
9. 每日饮水 1500-1700ml(7-8杯)
10. 每日身体活动 6000步以上, 每周中等强度运动150分钟以上

能量参考需要量(轻体力活动):
  男性: 2250kcal/天
  女性: 1800kcal/天

数据来源: 《中国居民膳食指南(2022)》中国营养学会编著
官网: https://www.cnsoc.org/
膳食指南官网: http://dg.cnsoc.org/""",
        "source": "中国居民膳食指南",
        "category": "nutrition",
    },
    {
        "title": "中国居民膳食指南(2022) - 膳食宝塔与餐盘",
        "content": """中国居民膳食指南(2022) — 平衡膳食宝塔(从下到上):

第1层(谷薯类): 200-300g/天, 是能量基础
第2层(蔬果类): 蔬菜300-500g + 水果200-350g/天
第3层(动物性食物): 畜禽鱼蛋120-200g/天(鱼虾>畜禽肉)
第4层(奶豆坚果): 奶300-500g + 大豆坚果25-35g/天
第5层(油盐): 油25-30g + 盐<5g/天

膳食餐盘分配(一餐):
  蔬菜: 占餐盘1/2
  主食: 占餐盘1/4
  鱼禽蛋肉: 占餐盘1/8
  豆奶坚果: 占餐盘1/8

核心原则:
  1. 食物多样, 合理搭配(每日12种以上, 每周25种以上)
  2. 吃动平衡, 健康体重(BMI 18.5-23.9)
  3. 多吃蔬果、奶类、全谷、大豆
  4. 适量吃鱼、禽、蛋、瘦肉
  5. 少盐少油, 控糖限酒
  6. 规律进餐, 足量饮水
  7. 会烹会选, 会看标签
  8. 公筷分餐, 杜绝浪费

数据来源: 《中国居民膳食指南(2022)》中国营养学会编著
官网: https://www.cnsoc.org/""",
        "source": "中国居民膳食指南",
        "category": "nutrition",
    },
]

# 预构建的文档列表
LOCAL_CN_FOOD_DATA: list[dict] = [_build_cn_food_doc(item) for item in _CN_FOOD_RAW] + _CN_DIETARY_GUIDELINES


def fetch_cn_dietary_guide() -> list[dict]:
    """拉取中国居民膳食指南 + 中国食物成分表的结构化食材营养数据。

    数据来源:
      1. 《中国食物成分表》标准版第6版 — 杨月欣主编
      2. 《中国居民膳食指南(2022)》— 中国营养学会编著
      3. 中国营养学会官网 https://www.cnsoc.org/

    中国膳食指南官网为静态网站, 无公开 API,
    本函数返回结构化录入的食材营养数据(每条食材一个独立文档)。

    覆盖品类:
      - 主食(谷类/薯类/加工品): 大米、糙米、燕麦、红薯等14种
      - 水果: 苹果、香蕉、蓝莓、猕猴桃等14种
      - 肉类(禽肉/畜肉/鱼虾/蛋类): 鸡胸肉、牛肉、三文鱼、鸡蛋等15种
      - 坚果: 核桃、杏仁、腰果、芝麻等12种
      - 蔬菜: 西兰花、菠菜、番茄、海带等17种
      - 奶类/豆类: 牛奶、豆腐、黄豆、纳豆等13种

    Returns:
        list[dict]: 知识文档列表, 每个文档包含 title/content/source/category
    """
    logger.info("中国居民膳食指南: 准备 %d 条食材营养文档", len(LOCAL_CN_FOOD_DATA))
    return LOCAL_CN_FOOD_DATA


# ─── 知识拉取器 ───


class KnowledgeFetcher:
    """知识拉取器 — 通过官方 API 获取营养学知识，写入 Milvus。

    数据源:
      1. USDA FoodData Central API (需 API Key, 默认 DEMO_KEY)
      2. Open Food Facts API (免费无限制)
      3. 中国居民膳食指南 (内置结构化数据, 70+条食材营养)
    """

    def __init__(self, knowledge_base=None):
        """
        Args:
            knowledge_base: KnowledgeBase 实例, None 时延迟创建
        """
        self._kb = knowledge_base
        self._seen_hashes: set[str] = set()
        self._last_fetch: dict | None = None
        self._total_fetched = 0
        self._total_errors = 0

    def _get_kb(self):
        """延迟获取 KnowledgeBase 实例。"""
        if self._kb is None:
            from .rag import KnowledgeBase
            self._kb = KnowledgeBase()
            self._kb.initialize()
        return self._kb

    # ─── 核心方法 ───

    def fetch_all(self) -> dict:
        """拉取所有数据源。

        Returns:
            {"total": int, "details": {source_name: doc_count}, "errors": [...]}
        """
        print("=" * 60)
        print("  ShapeAI 知识拉取器 — 官方 API 数据写入 Milvus")
        print("=" * 60)

        total = 0
        details = {}
        errors = []

        # 1. USDA FoodData Central API
        print("\n[USDA FoodData Central API] 拉取中...")
        try:
            docs = fetch_usda_foods()
            count = self._write_to_milvus(docs)
            details["USDA FoodData Central"] = count
            total += count
            print(f"  [OK] 新增 {count} 个文档块")
        except Exception as exc:
            self._total_errors += 1
            details["USDA FoodData Central"] = -1
            errors.append({"source": "USDA", "error": str(exc)})
            print(f"  [FAIL] {exc}")
            logger.error("USDA 拉取失败: %s", exc)

        # 2. Open Food Facts API
        print("\n[Open Food Facts API] 拉取中...")
        try:
            docs = fetch_off_products()
            count = self._write_to_milvus(docs)
            details["Open Food Facts"] = count
            total += count
            print(f"  [OK] 新增 {count} 个文档块")
        except Exception as exc:
            self._total_errors += 1
            details["Open Food Facts"] = -1
            errors.append({"source": "Open Food Facts", "error": str(exc)})
            print(f"  [FAIL] {exc}")
            logger.error("Open Food Facts 拉取失败: %s", exc)

        # 3. 中国居民膳食指南 + 中国食物成分表
        print("\n[中国居民膳食指南] 拉取常见食材营养数据...")
        try:
            docs = fetch_cn_dietary_guide()
            count = self._write_to_milvus(docs)
            details["中国居民膳食指南"] = count
            total += count
            print(f"  [OK] 新增 {count} 个文档块")
        except Exception as exc:
            self._total_errors += 1
            details["中国居民膳食指南"] = -1
            errors.append({"source": "中国居民膳食指南", "error": str(exc)})
            print(f"  [FAIL] {exc}")
            logger.error("中国居民膳食指南数据加载失败: %s", exc)

        self._total_fetched += total
        self._last_fetch = {
            "total": total,
            "details": details,
            "errors": errors,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        print(f"\n{'=' * 60}")
        print(f"  拉取完成! 新增 {total} 个文档块")
        print(f"  累计拉取: {self._total_fetched}, 错误: {self._total_errors}")
        print("=" * 60)

        return self._last_fetch

    def _write_to_milvus(self, documents: list[dict]) -> int:
        """将文档写入 Milvus (通过 KnowledgeBase) + 持久化元数据到 PG。"""
        if not documents:
            return 0

        # 去重
        new_docs = []
        for doc in documents:
            content = doc.get("content", "")
            if not content:
                continue
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content_hash in self._seen_hashes:
                continue
            self._seen_hashes.add(content_hash)
            new_docs.append(doc)

        if not new_docs:
            return 0

        # 写入 Milvus
        kb = self._get_kb()
        count = kb.add_documents_batch(new_docs)

        # 持久化元数据到 PostgreSQL
        self._persist_to_pg(new_docs)

        return count

    def _persist_to_pg(self, documents: list[dict]):
        """将文档元数据持久化到 PostgreSQL knowledge_documents 表。"""
        try:
            from .database import pg_cursor
            with pg_cursor() as cur:
                for doc in documents:
                    cur.execute("""
                        INSERT INTO knowledge_documents (title, content, source, category)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        doc.get("title", "")[:512],
                        doc.get("content", ""),
                        doc.get("source", "")[:256],
                        doc.get("category", "")[:64],
                    ))
        except Exception as exc:
            logger.warning("PG 持久化失败(不影响 Milvus): %s", exc)

    # ─── 状态查询 ───

    def get_status(self) -> dict:
        """获取拉取器状态。"""
        return {
            "total_fetched": self._total_fetched,
            "total_errors": self._total_errors,
            "seen_hashes": len(self._seen_hashes),
            "sources": [
                {
                    "name": "USDA FoodData Central",
                    "type": "official_api",
                    "url": "https://fdc.nal.usda.gov/api/v1",
                    "api_key_configured": USDA_API_KEY != "DEMO_KEY",
                },
                {
                    "name": "Open Food Facts",
                    "type": "official_api",
                    "url": "https://world.openfoodfacts.org/api/v2",
                    "api_key_configured": True,
                },
                {
                    "name": "中国居民膳食指南",
                    "type": "local_data",
                    "url": "https://www.cnsoc.org/",
                    "description": "《中国居民膳食指南(2022)》+《中国食物成分表》标准版第6版, 70+条食材营养数据",
                    "api_key_configured": True,
                },
            ],
            "last_fetch": self._last_fetch,
        }


# ─── 定时拉取调度器 ───


class FetchScheduler:
    """知识拉取定时调度器。

    在后台线程中周期拉取营养学知识并写入 Milvus。

    用法:
        scheduler = FetchScheduler(fetcher, interval_seconds=3600)
        scheduler.start()
        ...
        scheduler.stop()

    也可用作上下文管理器:
        with FetchScheduler(fetcher, interval=3600) as scheduler:
            ...
    """

    def __init__(
        self,
        fetcher: KnowledgeFetcher | None = None,
        interval_seconds: int | None = None,
    ):
        from .config import CRAWLER_INTERVAL_SECONDS
        self.fetcher = fetcher or KnowledgeFetcher()
        self.interval = interval_seconds or CRAWLER_INTERVAL_SECONDS
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        """启动后台拉取线程。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("FetchScheduler 已在运行")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="knowledge-fetcher",
                daemon=True,
            )
            self._thread.start()
            logger.info("FetchScheduler 已启动, 间隔=%ds", self.interval)

    def stop(self, timeout: float = 60.0):
        """停止后台拉取线程。"""
        with self._lock:
            if self._thread is None:
                return
            self._stop_event.set()
            self._thread.join(timeout=timeout)
            self._thread = None
            logger.info("FetchScheduler 已停止")

    def __enter__(self) -> "FetchScheduler":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def get_status(self) -> dict:
        """获取调度器状态。"""
        status = self.fetcher.get_status()
        status["running"] = self._thread is not None and self._thread.is_alive()
        status["interval_seconds"] = self.interval
        return status

    def _run_loop(self):
        """后台线程主循环。"""
        while not self._stop_event.is_set():
            try:
                self.fetcher.fetch_all()
            except Exception as exc:
                logger.error("定时拉取异常: %s", exc)
            # 等待 interval 或 stop 信号
            self._stop_event.wait(timeout=self.interval)


# ─── CLI ───


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if "--list" in sys.argv:
        fetcher = KnowledgeFetcher()
        print("数据源列表:")
        for s in fetcher.get_status()["sources"]:
            print(f"  [{s['type']}] {s['name']} - {s.get('url', '本地')}")
        sys.exit(0)

    fetcher = KnowledgeFetcher()
    result = fetcher.fetch_all()
    print(f"\n拉取结果: {result['total']} 个文档块")
