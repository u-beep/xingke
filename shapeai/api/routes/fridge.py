"""我的冰箱 API 路由。

提供冰箱食材的增删改查、拍照识别入库（视觉模型 + MinIO 持久化）、
基于现有食材的智能菜谱推荐、确认使用菜谱后自动扣减库存。
"""

import base64
import json
import logging
import re
import time
import uuid

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional

from ...records import FridgeStore, FridgeItem
from ...config import FOOD_ALIAS, FOOD_DATABASE
from ..security import get_auth_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fridge", tags=["我的冰箱"])

# 菜谱推荐缓存: (user_id, 食材指纹, 偏好) -> (时间戳, recipes)
# 食材指纹 = 名称+数量集合,冰箱不变时命中缓存秒回
_RECIPE_CACHE: dict[tuple, tuple[float, list]] = {}
_RECIPE_CACHE_TTL = 600  # 10 分钟
_RECIPE_CACHE_MAX = 64


def _fuzzy_match_food(name: str, db: dict) -> Optional[dict]:
    """食材名精确匹配失败时的模糊匹配:双向子串包含。

    例:LLM 返回"番茄"而库 key 是"西红柿"无法命中,
    但"小番茄"/"圣女果"等含"番茄"字串可命中"番茄"。
    长度≥2 才参与,避免单字误匹配。
    """
    if not name or len(name) < 2:
        return None
    # 1) LLM 名包含数据库名(如"小番茄"含"番茄")
    for key, val in db.items():
        if len(key) >= 2 and key in name:
            return val
    # 2) 数据库名包含 LLM 名(如 LLM"鸡"匹配"鸡蛋"——要求 LLM 名≥2)
    for key, val in db.items():
        if len(key) >= 2 and name in key:
            return val
    return None


# ─── 请求模型 ───

class FridgeItemRequest(BaseModel):
    """新增/更新食材请求。"""
    name: str = Field(..., description="食材名称")
    category: Optional[str] = Field("", description="分类(蔬菜/肉蛋/主食/水果/乳制品/熟食/调味/其他)")
    quantity_g: float = Field(0, description="库存量(克)")
    unit: Optional[str] = Field("g", description="单位(g/个/包/ml)")
    calories: Optional[float] = Field(None, description="每100g热量参考")
    protein_g: Optional[float] = Field(None, description="每100g蛋白参考")
    carbs_g: Optional[float] = Field(None, description="每100g碳水参考")
    fat_g: Optional[float] = Field(None, description="每100g脂肪参考")
    notes: Optional[str] = Field(None, description="备注")
    shelf_life_days: Optional[float] = Field(None, description="保质期天数(支持小数,0.5=12h);为空表示不设置")


# 按分类的默认保质期(天),识别结果未返回时使用
_DEFAULT_SHELF_LIFE: dict[str, float] = {
    "蔬菜": 3, "肉蛋": 2, "主食": 7, "水果": 5,
    "乳制品": 7, "熟食": 2, "调味": 30, "其他": 7,
}


class FridgePhotoRequest(BaseModel):
    """拍照识别入库请求。"""
    image_base64: str = Field(..., description="Base64编码的图片(可含data:前缀)")


class RecipeRecommendRequest(BaseModel):
    """菜谱推荐请求。"""
    preferences: Optional[str] = Field("", description="偏好(如高蛋白/快手菜/低卡)")


class RecipeConfirmRequest(BaseModel):
    """确认使用菜谱并扣减库存请求。"""
    recipe: dict = Field(..., description="用户选定的菜谱对象 {name,description,steps[],ingredients[{name,amount_g,unit}]}")


def _user_id(req: Request) -> str:
    return get_auth_user_id(req)


# ─── 食材 CRUD ───

@router.get("/items", summary="获取冰箱食材列表")
async def list_items(req: Request, category: str = None):
    """获取用户冰箱食材列表，可按分类过滤。"""
    user_id = _user_id(req)
    store = FridgeStore()
    items = store.list_items(user_id, category=category)
    categories = store.list_categories(user_id)
    return {
        "items": [it.to_dict() for it in items],
        "count": len(items),
        "categories": categories,
    }


@router.post("/items", summary="新增食材")
async def add_item(request: FridgeItemRequest, req: Request):
    """手动新增食材。"""
    user_id = _user_id(req)
    store = FridgeStore()
    item = FridgeItem(
        user_id=user_id,
        name=request.name,
        category=request.category or "",
        quantity_g=request.quantity_g,
        unit=request.unit or "g",
        calories=request.calories,
        protein_g=request.protein_g,
        carbs_g=request.carbs_g,
        fat_g=request.fat_g,
        notes=request.notes,
        shelf_life_days=request.shelf_life_days,
    )
    item_id = store.add_item(item)
    if not item_id:
        raise HTTPException(status_code=500, detail="新增食材失败")
    created = store.get_item(user_id, item_id)
    return {"success": True, "item_id": item_id, "item": created.to_dict() if created else None}


@router.put("/items/{item_id}", summary="更新食材")
async def update_item(item_id: int, request: FridgeItemRequest, req: Request):
    """更新食材信息。"""
    user_id = _user_id(req)
    store = FridgeStore()
    updated = store.update_item(user_id, item_id, request.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="食材不存在或无更新字段")
    return {"success": True, "item": updated.to_dict()}


@router.delete("/items/{item_id}", summary="删除食材")
async def delete_item(item_id: int, req: Request):
    """删除冰箱食材。"""
    user_id = _user_id(req)
    store = FridgeStore()
    ok = store.delete_item(user_id, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="食材不存在")
    return {"success": True, "message": "已删除"}


@router.get("/catalog-images/{item_id}", summary="获取公共食材图库图片")
async def get_catalog_image(item_id: int):
    """从 MinIO 返回内置公共食材图库图片（免登录）。

    查询时严格限制 ``fridge/catalog/`` 对象前缀，绝不暴露用户拍照上传的私有图片。
    """
    store = FridgeStore()
    image_key = store.get_catalog_image_key(item_id)
    if not image_key:
        raise HTTPException(status_code=404, detail="公共食材图片不存在")
    try:
        from ...storage import get_object_bytes
        data, ctype = get_object_bytes(image_key)
        return Response(
            content=data,
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=604800, immutable"},
        )
    except Exception as exc:
        logger.error("读取公共食材图片失败: %s", exc)
        raise HTTPException(status_code=404, detail="公共食材图片对象不存在")


@router.get("/items/{item_id}/image", summary="获取食材原始图片")
async def get_item_image(item_id: int, req: Request):
    """从 MinIO 流式返回食材原始图片。"""
    user_id = _user_id(req)
    store = FridgeStore()
    item = store.get_item(user_id, item_id)
    if not item or not item.image_object_key:
        raise HTTPException(status_code=404, detail="图片不存在")
    try:
        from ...storage import get_object_bytes
        data, ctype = get_object_bytes(item.image_object_key)
        return Response(content=data, media_type=ctype)
    except Exception as exc:
        # MinIO NoSuchKey 等异常 -> 404, 其他视为服务异常
        msg = str(exc)
        logger.error("读取食材图片失败: %s", msg)
        if "NoSuchKey" in msg or "NoSuchKey" in msg.__class__.__name__ or "404" in msg:
            raise HTTPException(status_code=404, detail="原始图片对象不存在")
        raise HTTPException(status_code=500, detail="读取图片失败")


# ─── 拍照识别入库 ───

@router.post("/photo-recognize", summary="拍照识别食材并入库")
async def photo_recognize(request: FridgePhotoRequest, req: Request):
    """通过视觉模型识别图片中的食材，上传原始图片到 MinIO，
    并将识别得到的食材数据与图片一同持久化到冰箱数据表。

    同名同单位的食材自动合并库存；同一张照片识别出的多个食材共享同一图片 key。
    """
    user_id = _user_id(req)
    app_state = req.app.state

    # 1) 视觉模型识别
    service = app_state.food_recognition
    result = service.recognize(image_base64=request.image_base64, user_id=user_id)
    recognized = result.get("recognized", [])
    if not recognized or (len(recognized) == 1 and recognized[0].get("name") == "未知"):
        return {"success": False, "message": result.get("error", "未识别到食材"), "recognized": []}

    # 拍到的是完整菜品（如汉堡、三明治、卤味等成品/熟食）时，
    # 聚合为一条「熟食」整体入库，而不是把面包/肉/蔬菜拆成一堆食材
    dish = (result.get("dish") or "").strip()
    if dish:
        total_g = sum(float(it.get("quantity_g") or 0) for it in recognized)
        totals = {
            k: sum(float(it.get(k) or 0) for it in recognized)
            for k in ("calories", "protein", "carbs", "fat")
        }
        recognized = [{
            "name": dish,
            "category": "熟食",
            "quantity_g": round(total_g, 1),
            "unit": "g",
            "calories": round(totals["calories"], 1),
            "protein": round(totals["protein"], 1),
            "carbs": round(totals["carbs"], 1),
            "fat": round(totals["fat"], 1),
            "confidence": min(
                (float(it.get("confidence") or 0.8) for it in recognized),
                default=0.8,
            ),
        }]

    # 2) 上传原始图片到 MinIO
    raw_b64 = request.image_base64.split(",", 1)[-1] if "," in request.image_base64 else request.image_base64
    try:
        raw = base64.b64decode(raw_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片解码失败: {exc}")

    from ...storage import upload_bytes
    image_key = f"fridge/{user_id}/{uuid.uuid4().hex}.jpg"
    try:
        upload_bytes(image_key, raw, "image/jpeg")
    except Exception as exc:
        logger.error("上传食材图片到 MinIO 失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"图片存储失败: {exc}")

    # 3) 合并入库
    store = FridgeStore()
    merged_ids: list = []
    for item in recognized:
        name = item.get("name") or item.get("food_name")
        if not name or name == "未知":
            continue
        # 营养参考：识别返回值是"该分量的总营养",换算为"每100g"再存
        # (数据库 calories 字段语义=每100g热量参考)
        nutrition = {}
        qty = float(item.get("quantity_g") or 0)
        # 换算:总营养 * 100 / qty = 每100g营养(qty>0 时)
        if qty > 0:
            cal = item.get("calories")
            if cal and cal > 0:
                nutrition["calories"] = round(cal * 100 / qty, 1)
            prot = item.get("protein")
            if prot and prot > 0:
                nutrition["protein_g"] = round(prot * 100 / qty, 1)
            carb = item.get("carbs")
            if carb and carb > 0:
                nutrition["carbs_g"] = round(carb * 100 / qty, 1)
            ft = item.get("fat")
            if ft and ft > 0:
                nutrition["fat_g"] = round(ft * 100 / qty, 1)
        # 识别未给营养(或换算失败)→ 查内置库(别名→标准名→精确→模糊)
        if not nutrition:
            std_name = FOOD_ALIAS.get(name, name)
            db = (
                FOOD_DATABASE.get(std_name)
                or FOOD_DATABASE.get(name)
                or _fuzzy_match_food(name, FOOD_DATABASE)
            )
            if db:
                nutrition = {
                    "calories": db.get("calories"),
                    "protein_g": db.get("protein"),
                    "carbs_g": db.get("carbs"),
                    "fat_g": db.get("fat"),
                }

        item_id = store.merge_or_add(
            user_id=user_id,
            name=name,
            unit=item.get("unit") or "g",
            quantity_g=float(item.get("quantity_g") or 0),
            category=item.get("category") or "",
            nutrition=nutrition,
            image_object_key=image_key,
            shelf_life_days=item.get("shelf_life_days")
            or _DEFAULT_SHELF_LIFE.get(item.get("category") or "", 7),
        )
        if item_id:
            merged_ids.append(item_id)

    items = [store.get_item(user_id, iid).to_dict() for iid in merged_ids
             if store.get_item(user_id, iid)]

    return {
        "success": len(merged_ids) > 0,
        "recognized": recognized,
        "image_object_key": image_key,
        "items": items,
        "message": f"已识别 {len(recognized)} 项，入库 {len(merged_ids)} 项" if merged_ids else "入库失败",
    }


# ─── 菜谱推荐与扣减 ───

@router.post("/recipes/recommend", summary="基于冰箱现有食材推荐菜谱")
async def recommend_recipes(request: RecipeRecommendRequest, req: Request):
    """读取用户冰箱内现存食材，调用 LLM 基于现有食材做匹配生成菜谱方案。"""
    user_id = _user_id(req)
    app_state = req.app.state
    store = FridgeStore()

    items = store.list_items(user_id)
    if not items:
        return {"recipes": [], "fridge_snapshot": [], "message": "冰箱空空如也，先添加食材吧"}

    # 拼装食材清单
    ingredient_lines = []
    for it in items:
        qty = it.quantity_g or 0
        if qty <= 0:
            continue
        ingredient_lines.append(
            f"- {it.name} | {qty:.0f}{it.unit} | {it.category or '未分类'}"
        )
    if not ingredient_lines:
        return {"recipes": [], "fridge_snapshot": [it.to_dict() for it in items], "message": "所有食材库存为0"}

    ingredients_text = "\n".join(ingredient_lines[:25])  # 截断超长清单，控制输入 token
    # 无偏好("默认"/空输入)时不附加任何额外提示词，缩短 prompt 加快首 token
    prefs = request.preferences.strip() if request.preferences else ""

    # 1) 缓存命中: 冰箱未变+偏好相同 → 秒回
    fingerprint = tuple(sorted(
        (line.split(" | ")[0], line.split(" | ")[1]) for line in ingredient_lines
    ))
    cache_key = (user_id, fingerprint, prefs)
    cached = _RECIPE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _RECIPE_CACHE_TTL:
        logger.info("菜谱推荐命中缓存 user=%s (%d 条)", user_id, len(cached[1]))
        return {
            "recipes": cached[1],
            "fridge_snapshot": [it.to_dict() for it in items],
            "cached": True,
        }

    pref_section = f"【用户要求】{prefs}\n" if prefs else ""
    dish_rule = (
        "1. 只用现有食材+基础调味料；若【用户要求】是具体菜名，按该菜名生成，缺少的食材照常列入 ingredients；"
        if prefs
        else "1. 只用现有食材+基础调味料；"
    )
    prompt = f"""你是家常菜营养师。根据冰箱现有食材推荐最多 2 道菜谱。

【食材】
{ingredients_text}
{pref_section}
要求：
{dish_rule}
2. 步骤每步不超过 20 字；
3. 直接输出 JSON，不要思考、不要解释；格式中的字段值仅为占位示例，禁止照抄示例文字（如"菜名""一句话""名"）。

格式：{{"recipes":[{{"name":"菜名","description":"一句话","steps":["…"],"ingredients":[{{"name":"名","amount_g":100,"unit":"g"}}]}}]}}
"""
    # 2) 快路径: flash 模型(非推理,快数倍);失败/解析为空再回退主模型
    recipes = []
    raw = ""
    t0 = time.monotonic()
    fast_client = getattr(app_state.gateway, "vision", None)
    if fast_client is not None:
        try:
            raw = fast_client.complete(
                prompt, max_new_tokens=700,
            ) or ""
            recipes = _parse_recipes(raw)
            logger.info(
                "菜谱快路径(flash)成功: %d 条, 耗时 %.1fs",
                len(recipes), time.monotonic() - t0,
            )
        except Exception as exc:
            logger.warning("菜谱快路径失败,回退主模型: %s", exc)
            recipes = []
            raw = ""
    # 3) 回退: 主模型(pro, 推理模型,慢但稳)
    if not recipes:
        try:
            raw = app_state.gateway.complete(
                prompt, max_new_tokens=1500,
                user_id=user_id, scene="fridge_recipe", route="complex",
            ) or ""
            recipes = _parse_recipes(raw)
            logger.info(
                "菜谱主模型路径成功: %d 条, 耗时 %.1fs",
                len(recipes), time.monotonic() - t0,
            )
        except Exception as exc:
            logger.error("LLM 生成菜谱推荐失败: %s", exc)
            return {
                "recipes": [],
                "fridge_snapshot": [it.to_dict() for it in items],
                "raw": f"AI 推荐生成失败: {exc}",
            }
    # 按菜谱用量计算整餐热量和三大营养素；冰箱营养值缺失时回退内置营养库。
    fridge_nutrition_map = {
        it.name: {
            "calories": it.calories,
            "protein_g": it.protein_g,
            "carbs_g": it.carbs_g,
            "fat_g": it.fat_g,
        }
        for it in items
    }
    for rcp in recipes:
        rcp.update(_calc_recipe_nutrition(
            rcp.get("ingredients") or [], fridge_nutrition_map,
        ))

    # 4) 写入缓存(简单 LRU: 超容量淘汰最旧)
    if recipes:
        if len(_RECIPE_CACHE) >= _RECIPE_CACHE_MAX:
            oldest = min(_RECIPE_CACHE, key=lambda k: _RECIPE_CACHE[k][0])
            _RECIPE_CACHE.pop(oldest, None)
        _RECIPE_CACHE[cache_key] = (time.time(), recipes)

    return {
        "recipes": recipes,
        "fridge_snapshot": [it.to_dict() for it in items],
        "raw": raw if not recipes else None,
    }


def _calc_recipe_nutrition(
    ingredients: list[dict],
    fridge_nutrition_map: dict[str, dict],
) -> dict[str, float]:
    """按菜谱用量计算整餐热量及蛋白质、碳水、脂肪。

    冰箱中手动维护的每 100g 营养值优先；任一字段缺失时，按别名/精确/模糊
    匹配回退到 ``FOOD_DATABASE``。调味料等没有营养参考的用料会被跳过。
    """
    totals = {"total_calories": 0.0, "total_protein_g": 0.0, "total_carbs_g": 0.0, "total_fat_g": 0.0}
    db_key_map = {
        "total_calories": "calories",
        "total_protein_g": "protein",
        "total_carbs_g": "carbs",
        "total_fat_g": "fat",
    }
    fridge_key_map = {
        "total_calories": "calories",
        "total_protein_g": "protein_g",
        "total_carbs_g": "carbs_g",
        "total_fat_g": "fat_g",
    }

    for ing in ingredients:
        name = (ing.get("name") or "").strip()
        amount = float(ing.get("amount_g") or 0)
        if not name or amount <= 0:
            continue

        fridge_nutrition = fridge_nutrition_map.get(name)
        if not fridge_nutrition:
            fridge_nutrition = next(
                (nutrition for item_name, nutrition in fridge_nutrition_map.items()
                 if item_name and (name in item_name or item_name in name)),
                {},
            )
        std_name = FOOD_ALIAS.get(name, name)
        fallback = (
            FOOD_DATABASE.get(std_name)
            or FOOD_DATABASE.get(name)
            or _fuzzy_match_food(name, FOOD_DATABASE)
            or {}
        )
        for total_key, db_key in db_key_map.items():
            value = (fridge_nutrition or {}).get(fridge_key_map[total_key])
            if value is None:
                value = fallback.get(db_key)
            if value is not None:
                totals[total_key] += float(value) * amount / 100

    return {key: round(value, 1) for key, value in totals.items()}


@router.post("/recipes/confirm", summary="确认使用菜谱并扣减库存")
async def confirm_recipe(request: RecipeConfirmRequest, req: Request):
    """用户确认使用选定食谱后，按照食谱用料自动扣减冰箱内对应食材的库存数量。"""
    user_id = _user_id(req)
    store = FridgeStore()
    recipe = request.recipe or {}
    ingredients = recipe.get("ingredients") or []
    if not ingredients:
        raise HTTPException(status_code=400, detail="菜谱缺少用料信息")

    result = store.deduct_ingredients(user_id, ingredients)
    items = store.list_items(user_id)

    # 使用菜谱指定用量计算理论整餐营养；库存不足时仍保留用户确认烹饪的摄入记录。
    fridge_nutrition_map = {
        it.name: {
            "calories": it.calories,
            "protein_g": it.protein_g,
            "carbs_g": it.carbs_g,
            "fat_g": it.fat_g,
        }
        for it in items
    }
    nutrition = _calc_recipe_nutrition(ingredients, fridge_nutrition_map)

    # 用料摘要
    summary = "、".join(
        f"{ing.get('name','')} {ing.get('amount_g','')}{ing.get('unit','g')}"
        for ing in ingredients
    )
    # 记录今日餐次(用户确认菜谱即记录,即使库存不足/热量为0)
    meal_id = None
    if result.get("success"):
        meal_id = store.add_meal_log(
            user_id=user_id,
            recipe_name=recipe.get("name", ""),
            nutrition={
                "calories": nutrition["total_calories"],
                "protein_g": nutrition["total_protein_g"],
                "carbs_g": nutrition["total_carbs_g"],
                "fat_g": nutrition["total_fat_g"],
            },
            ingredients_summary=summary,
            recipe=recipe,
        )

    return {
        "success": result.get("success", False),
        "recipe_name": recipe.get("name", ""),
        "deducted": result.get("deducted", []),
        "insufficient": result.get("insufficient", []),
        "missing": result.get("missing", []),
        **nutrition,
        "meal_id": meal_id,
        "items": [it.to_dict() for it in items],
        "message": _build_deduction_message(result),
    }


@router.get("/meals", summary="按自然日查询今日餐次与热量")
async def list_meals(req: Request, date: Optional[str] = None):
    """查询指定日期(YYYY-MM-DD)的餐次日志,默认今天。"""
    user_id = _user_id(req)
    store = FridgeStore()
    target: Optional[datetime] = None
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="date 需为 YYYY-MM-DD 格式")
    meals = store.list_meal_logs(user_id, target)
    total = sum(float(m.get("total_calories") or 0) for m in meals)
    return {
        "date": (target or datetime.now()).strftime("%Y-%m-%d"),
        "meals": meals,
        "total_calories": round(total, 1),
        "count": len(meals),
    }


def _build_deduction_message(result: dict) -> str:
    """根据扣减结果生成面向用户的提示。"""
    if not result.get("success"):
        return "扣减失败：" + str(result.get("error", "未知错误"))
    insufficient = result.get("insufficient", [])
    missing = result.get("missing", [])
    if not insufficient and not missing:
        return "库存扣减完成，用料充足"
    parts = []
    if insufficient:
        parts.append("不足: " + "、".join(it["name"] for it in insufficient))
    if missing:
        parts.append("冰箱缺: " + "、".join(it["name"] for it in missing))
    return "部分扣减完成（" + "；".join(parts) + "）"


def _parse_recipes(text: str) -> list:
    """鲁棒解析 LLM 返回的菜谱 JSON。

    支持场景：
    - 纯 JSON 输出
    - markdown 围栏 ```json ... ```
    - 推理模型先输出思考过程再输出 JSON (从含 "recipes" 处用括号平衡提取)
    """
    if not text:
        return []
    raw = text.strip()
    # 去除 markdown 代码块围栏
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    # 尝试直接解析
    try:
        return _extract_recipes(json.loads(raw))
    except json.JSONDecodeError:
        pass
    # 去围栏后再试（捕获 ```json ... ```）
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        try:
            return _extract_recipes(json.loads(fenced.group(1)))
        except json.JSONDecodeError:
            pass
    # 推理模型:文本中含 "recipes" 字段,用括号平衡提取完整 JSON 对象
    recipes_json = _find_balanced_json_with_key(text, "recipes")
    if recipes_json:
        try:
            return _extract_recipes(json.loads(recipes_json))
        except json.JSONDecodeError:
            pass
    # 正则兜底提取最外层 { ... } 或 [ ... ]
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return _extract_recipes(json.loads(obj_match.group()))
        except json.JSONDecodeError:
            pass
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        try:
            return _extract_recipes(json.loads(arr_match.group()))
        except json.JSONDecodeError:
            pass
    return []


def _find_balanced_json_with_key(text: str, key: str) -> Optional[str]:
    """在 text 中查找包含指定 key 的完整 JSON 对象 (括号平衡).

    适用于 LLM 输出思考过程 + 末尾 JSON 的场景:从 "key" 出现位置往左
    找最近的 '{',再向右用栈匹配提取完整对象字符串。
    """
    search_from = 0
    while True:
        idx = text.find(f'"{key}"', search_from)
        if idx == -1:
            return None
        # 往左找最近的未配对 '{'
        brace_start = text.rfind("{", 0, idx)
        if brace_start == -1:
            search_from = idx + len(key) + 2
            continue
        # 从 brace_start 向右括号平衡扫描
        depth = 0
        i = brace_start
        in_str = False
        escape = False
        candidate = None
        while i < len(text):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[brace_start:i + 1]
                        break
            i += 1
        if candidate:
            return candidate
        search_from = idx + len(key) + 2


def _extract_recipes(data) -> list:
    """从解析后的 JSON 提取 recipes 列表并做最小校验。"""
    if isinstance(data, list):
        recipes = data
    elif isinstance(data, dict):
        recipes = data.get("recipes") or data.get("data") or []
    else:
        recipes = []
    result = []
    for r in recipes:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        if _is_placeholder_recipe(r):
            continue
        ingredients = []
        for ing in r.get("ingredients") or []:
            if isinstance(ing, dict) and ing.get("name"):
                ingredients.append({
                    "name": ing["name"],
                    "amount_g": float(ing.get("amount_g") or 0),
                    "unit": ing.get("unit") or "g",
                })
        result.append({
            "name": r.get("name", ""),
            "description": r.get("description", ""),
            "steps": r.get("steps") or [],
            "ingredients": ingredients,
        })
    return result


# prompt 格式示例中的占位字样，模型照抄示例时会出现这些"菜谱"
_PLACEHOLDER_WORDS = {"菜名", "菜谱名", "菜谱", "dish", "xxx", "…", "...", "example"}


def _is_placeholder_recipe(r: dict) -> bool:
    """识别模型照抄 prompt 格式示例产生的占位"菜谱"，避免污染展示与缓存。"""
    name = str(r.get("name") or "").strip().lower()
    if not name or name in _PLACEHOLDER_WORDS:
        return True
    desc = str(r.get("description") or "").strip()
    steps = r.get("steps") or []
    ingredients = r.get("ingredients") or []
    # 描述是占位语且无实际步骤/用料
    if desc in ("一句话", "一句话描述", "简短描述") and not steps and not ingredients:
        return True
    # 用料全是占位（如"名 100g"）
    if ingredients and all(
        str(i.get("name") or "").strip() in ("名", "食材", "…", "...")
        for i in ingredients
        if isinstance(i, dict)
    ):
        return True
    return False
