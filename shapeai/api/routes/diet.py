"""饮食记录 API 路由。"""

import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from ...records import DietStore, DietRecord
from ..security import get_auth_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diet", tags=["饮食记录"])


def _inject_real_budget(summary: dict, user_id: str) -> dict:
    """用 ProfileStore 的用户自定义预算覆盖 summary 里的硬编码 budget，重算 remaining/goal_achieved。"""
    try:
        from ...user_profile import ProfileStore
        profile = ProfileStore().get(user_id)
        budget = profile.daily_calorie_budget
        if budget is None:
            # 未自定义则用身体数据算的 TDEE 建议
            from .profile import _compute_suggested_tdee
            budget = _compute_suggested_tdee(profile)
        if budget:
            summary["budget"] = budget
            consumed = summary.get("total_calories", 0)
            summary["remaining"] = round(budget - consumed, 1)
            summary["goal_achieved"] = consumed >= budget
            summary["budget_source"] = "custom" if profile.daily_calorie_budget else "tdee_suggested"
        else:
            summary["budget_source"] = "default"
        return summary
    except Exception as exc:
        logger.warning("注入用户热量预算失败，用默认: %s", exc)
        summary["budget_source"] = "default"
        return summary


class DietRecordRequest(BaseModel):
    """记录饮食请求。"""
    meal_type: str = Field(..., description="餐次: breakfast/lunch/dinner/snack")
    food_name: str = Field(..., description="食物名称")
    amount_g: Optional[float] = Field(None, description="重量(g)")
    calories: Optional[float] = Field(None, description="热量(kcal)")
    protein_g: Optional[float] = Field(None, description="蛋白质(g)")
    carbs_g: Optional[float] = Field(None, description="碳水(g)")
    fat_g: Optional[float] = Field(None, description="脂肪(g)")
    image_url: Optional[str] = Field(None, description="图片URL")


@router.post("/record", summary="记录饮食")
async def record_diet(request: DietRecordRequest, req: Request):
    """记录用户饮食。"""
    user_id = get_auth_user_id(req)
    store = DietStore()
    record = DietRecord(
        user_id=user_id,
        meal_type=request.meal_type,
        food_name=request.food_name,
        amount_g=request.amount_g,
        calories=request.calories,
        protein_g=request.protein_g,
        carbs_g=request.carbs_g,
        fat_g=request.fat_g,
        image_url=request.image_url,
    )
    record_id = store.add_record(record)
    return {
        "success": record_id is not None,
        "record_id": record_id,
        "message": "饮食记录已保存" if record_id else "记录失败",
    }


@router.get("/today", summary="获取今日饮食")
async def get_today_diet(req: Request):
    """获取用户今日饮食记录及统计。"""
    user_id = get_auth_user_id(req)
    store = DietStore()
    records = store.get_today_records(user_id)
    summary = _inject_real_budget(store.get_today_summary(user_id), user_id)
    return {
        "records": [r.to_dict() for r in records],
        "summary": summary,
    }


@router.get("/summary", summary="按日期获取饮食统计")
async def get_diet_summary(req: Request, user_id: str = "anonymous", date: str = None):
    """获取指定日期的饮食统计。

    Args:
        user_id: 用户ID（登录态优先，参数仅作未鉴权回退）
        date: 日期 YYYY-MM-DD，不传默认今天
    """
    user_id = get_auth_user_id(req, user_id)
    store = DietStore()
    if date:
        summary = _inject_real_budget(store.get_summary_by_date(user_id, date), user_id)
    else:
        summary = _inject_real_budget(store.get_today_summary(user_id), user_id)
    return summary


class DietConfirmRequest(BaseModel):
    """用户确认计入热量的请求。"""
    user_id: Optional[str] = Field(None, description="用户ID，未传则回退到 X-User-Id 头")
    foods: list = Field(..., description="食物列表: [{food_name, meal_type, amount_g, calories, protein_g, carbs_g, fat_g}]")


@router.post("/confirm", summary="确认计入今日热量统计")
async def confirm_diet(request: DietConfirmRequest, req: Request):
    """用户确认后，将提取的食物数据写入今日饮食记录。"""
    # 登录态优先（Token 用户），回退到 body/X-User-Id/anonymous
    user_id = get_auth_user_id(req, request.user_id)
    store = DietStore()
    saved_count = 0
    total_calories = 0
    for food in request.foods:
        record = DietRecord(
            user_id=user_id,
            meal_type=food.get("meal_type", "snack"),
            food_name=food.get("food_name", ""),
            amount_g=food.get("amount_g"),
            calories=food.get("calories"),
            protein_g=food.get("protein_g"),
            carbs_g=food.get("carbs_g"),
            fat_g=food.get("fat_g"),
        )
        record_id = store.add_record(record)
        if record_id:
            saved_count += 1
            total_calories += food.get("calories", 0)
    return {
        "success": saved_count > 0,
        "saved_count": saved_count,
        "total_calories": round(total_calories, 1),
    }


@router.get("/history", summary="查询饮食历史")
async def get_diet_history(
    req: Request,
    days: int = 30,
    limit: int = 200,
):
    """查询用户饮食历史。"""
    user_id = get_auth_user_id(req)
    store = DietStore()
    records = store.get_history(user_id, days=days, limit=limit)
    return {
        "records": [r.to_dict() for r in records],
        "count": len(records),
        "days": days,
    }


@router.get("/daily", summary="按日期查询饮食记录(外卖+冰箱菜谱,纯记录展示)")
async def get_daily_diet(req: Request, date: Optional[str] = None):
    """按自然日聚合饮食记录，供「饮食记录」Tab 展示。

    数据来源（合并，按时间倒序）：
    - diet_records(source='order'): 外卖购买产生的记录
    - diet_records(source='chat'): 对话/手动上报产生的记录
    - fridge_meal_log: 「我的冰箱」确认菜谱扣减产生的餐次

    统计口径：diet_records 仅汇总 include_in_stats=TRUE 的记录，
    冰箱餐次全部计入。
    """
    user_id = get_auth_user_id(req)
    from datetime import datetime as _dt

    # 日期参数校验（默认今天）
    if date:
        try:
            target = _dt.strptime(date, "%Y-%m-%d")
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="date 需为 YYYY-MM-DD 格式")
    else:
        target = _dt.now()
    date_str = target.strftime("%Y-%m-%d")

    store = DietStore()
    diet_records = store.get_records_by_date(user_id, date_str)

    # 冰箱菜谱餐次
    from ...records import FridgeStore
    fridge_meals = FridgeStore().list_meal_logs(user_id, target)

    # 统一记录格式并合并
    records: list[dict] = []
    for r in diet_records:
        d = r.to_dict()
        d["record_key"] = f"diet-{d['id']}"
        # 来源展示名
        d["source_label"] = "外卖" if d.get("source") == "order" else "手动记录"
        records.append(d)
    for m in fridge_meals:
        records.append({
            "record_key": f"meal-{m['id']}",
            "id": m["id"],
            "meal_type": "",
            "food_name": m["recipe_name"],
            "amount_g": None,
            "calories": m["total_calories"],
            "protein_g": None,
            "carbs_g": None,
            "fat_g": None,
            "recorded_at": m["consumed_at"],
            "image_url": None,
            "source": "fridge",
            "order_id": None,
            "include_in_stats": True,
            "source_label": "冰箱菜谱",
            "ingredients_summary": m.get("ingredients_summary"),
        })
    # 按时间倒序(无时间的排最后)
    records.sort(key=lambda x: x.get("recorded_at") or "", reverse=True)

    # 统计: diet 部分(仅 include_in_stats) + 冰箱餐次全计
    summary = _inject_real_budget(store.get_summary_by_date(user_id, date_str), user_id)
    fridge_cal = sum(float(m.get("total_calories") or 0) for m in fridge_meals)
    total_cal = round(float(summary.get("total_calories") or 0) + fridge_cal, 1)
    summary["total_calories"] = total_cal
    if summary.get("remaining") is not None:
        summary["remaining"] = round(summary["remaining"] - fridge_cal, 1)
    if summary.get("budget"):
        summary["goal_achieved"] = total_cal >= summary["budget"]
    summary["fridge_calories"] = round(fridge_cal, 1)
    # 来源分布补冰箱
    if "source_breakdown" in summary:
        summary["source_breakdown"]["fridge"] = {
            "calories": round(fridge_cal, 1), "protein_g": 0,
        }

    return {
        "date": date_str,
        "records": records,
        "count": len(records),
        "summary": summary,
    }


# ─────────────────────────────────────────────────────────────
#  Agent 智能饮食推荐
# ─────────────────────────────────────────────────────────────

@router.get("/recommendation", summary="Agent 智能饮食推荐")
async def get_diet_recommendation(req: Request, user_id: str = "anonymous"):
    """Agent 智能饮食推荐。

    调度链路：
    1. DietStore 读取今日已摄入 + 剩余热量（注入用户自定义预算）
    2. ProfileStore 读取用户饮食偏好/忌口
    3. TakeoutStore 读取外卖可选菜品列表
    4. KnowledgeBase（RAG）检索营养知识（高蛋白/饱腹/低卡搭配）
    5. ModelGateway 调 LLM，结合剩余热量约束 + 菜品 + 知识 + 偏好生成推荐
    """
    user_id = get_auth_user_id(req, user_id)
    app_state = req.app.state

    # ① 剩余热量
    store = DietStore()
    summary = _inject_real_budget(store.get_today_summary(user_id), user_id)
    budget = summary.get("budget", 1600)
    consumed = summary.get("total_calories", 0)
    remaining = max(0, summary.get("remaining", budget - consumed))

    # ② 用户偏好
    from ...user_profile import ProfileStore
    profile = ProfileStore().get(user_id)
    prefs = []
    if profile.disliked_foods:
        prefs.append(f"不喜欢的食物: {'、'.join(profile.disliked_foods)}")
    if profile.dietary_restrictions:
        prefs.append(f"饮食限制: {'、'.join(profile.dietary_restrictions)}")
    if profile.preferred_cuisines:
        prefs.append(f"偏好菜系: {'、'.join(profile.preferred_cuisines)}")
    if profile.health_goal:
        goal_map = {"lose_weight": "减脂", "maintain": "维持", "gain_muscle": "增肌"}
        prefs.append(f"健康目标: {goal_map.get(profile.health_goal, profile.health_goal)}")
    prefs_text = "\n".join(prefs) if prefs else "(无特殊偏好)"

    # ③ 外卖菜品列表
    from ...records import TakeoutStore
    takeout_store = TakeoutStore()
    dishes = takeout_store.list_dishes(category=None, only_available=True)
    # 精简菜品信息给 LLM（控制 prompt 长度）
    dish_lines = []
    for d in dishes[:24]:
        dish_lines.append(
            f"- {d.dish_name} | {d.category} | {d.calories}kcal | 蛋白{d.protein_g}g 碳水{d.carbs_g}g 脂肪{d.fat_g}g | ¥{d.price}"
        )
    dishes_text = "\n".join(dish_lines) if dish_lines else "(暂无外卖菜品)"

    # ④ RAG 检索营养知识
    knowledge = ""
    if getattr(app_state, "knowledge_base", None):
        try:
            results = app_state.knowledge_base.retrieve("减脂饮食 高蛋白饱腹感 低热量食物搭配 营养均衡", top_k=3)
            if results:
                knowledge = "\n".join(f"- {r.get('content', '')[:200]}" for r in results)
        except Exception as exc:
            logger.warning("RAG 检索失败: %s", exc)
    knowledge_text = knowledge if knowledge else "(无相关知识)"

    # ⑤ 构造 prompt 调 LLM 生成推荐
    prompt = f"""你是一位专业的营养师助手。请基于以下信息为用户推荐今日接下来的饮食方案。

【今日热量约束】
- 每日热量预算: {budget} kcal
- 已摄入: {consumed} kcal
- 剩余可吃: {remaining} kcal

【用户偏好】
{prefs_text}

【外卖可选菜品】
{dishes_text}

【营养知识库】
{knowledge_text}

请严格约束在「剩余可吃 {remaining} kcal」范围内，从上面的外卖菜品中挑选 1-3 道组合成推荐方案，并说明理由。输出格式如下（保持简洁，不要废话）：

推荐方案:
1. <菜品名> — <热量>kcal（理由：高蛋白/低卡/饱腹 等）
2. <菜品名> — <热量>kcal（理由）
（如需第3道）
合计: <总热量>kcal，剩余 <差额>kcal

营养建议:
<一句话结合知识库给出今日后续饮食的总体建议，例如控制碳水、补充蛋白等>
"""
    recommendation = ""
    try:
        recommendation = app_state.gateway.complete(
            prompt,
            user_id=user_id,
            scene="diet",
            route="default",
        ) or ""
    except Exception as exc:
        logger.error("LLM 生成饮食推荐失败: %s", exc)
        recommendation = f"AI 推荐生成失败: {exc}"

    return {
        "user_id": user_id,
        "remaining_calories": remaining,
        "consumed_calories": round(consumed, 1),
        "budget": budget,
        "recommendation": recommendation.strip(),
        "dishes_count": len(dishes),
        "budget_source": summary.get("budget_source", "default"),
    }
