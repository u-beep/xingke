"""运动计划 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from ...records import ExercisePlanStore, ExercisePlanItem, EXERCISE_MET
from ..security import get_auth_user_id

router = APIRouter(prefix="/exercise-plan", tags=["运动计划"])


class PlanItemRequest(BaseModel):
    """添加运动计划项请求。"""
    exercise_type: str = Field(..., description="运动类型: cardio/strength/anaerobic")
    exercise_name: str = Field(..., description="运动名称")
    duration_min: int = Field(30, description="时长(分钟)")
    plan_date: Optional[str] = Field(None, description="计划日期 YYYY-MM-DD，不传默认今天")


@router.post("/add", summary="添加运动计划项")
async def add_plan_item(request: PlanItemRequest, req: Request):
    """添加一项运动到今日计划。"""
    user_id = get_auth_user_id(req)
    store = ExercisePlanStore()
    from datetime import datetime
    plan_date = request.plan_date or datetime.now().strftime("%Y-%m-%d")
    calories = store.calc_calories(request.exercise_name, request.duration_min)
    item = ExercisePlanItem(
        user_id=user_id,
        plan_date=plan_date,
        exercise_type=request.exercise_type,
        exercise_name=request.exercise_name,
        duration_min=request.duration_min,
        calories_burned=calories,
    )
    item_id = store.add_item(item)
    return {
        "success": item_id is not None,
        "item_id": item_id,
        "calories_burned": calories,
    }


@router.get("/today", summary="获取今日运动计划")
async def get_today_plan(req: Request, user_id: str = "anonymous"):
    """获取今日运动计划及统计。"""
    user_id = get_auth_user_id(req, user_id)
    store = ExercisePlanStore()
    summary = store.get_summary(user_id)
    return summary


@router.get("/by-date", summary="按日期获取运动计划")
async def get_plan_by_date(req: Request, user_id: str = "anonymous", date: str = None):
    """按日期获取运动计划。"""
    user_id = get_auth_user_id(req, user_id)
    store = ExercisePlanStore()
    summary = store.get_summary(user_id, date)
    return summary


@router.delete("/item/{item_id}", summary="删除运动计划项")
async def delete_plan_item(item_id: int, req: Request):
    """删除一项运动计划。"""
    store = ExercisePlanStore()
    deleted = store.delete_item(item_id)
    return {"success": deleted}


@router.delete("/clear-today", summary="清空今日运动计划")
async def clear_today_plan(req: Request, user_id: str = "anonymous"):
    """清空今日所有运动计划。"""
    user_id = get_auth_user_id(req, user_id)
    store = ExercisePlanStore()
    store.clear_today(user_id)
    return {"success": True}


@router.get("/exercises", summary="获取运动列表")
async def get_exercise_list():
    """获取所有可选运动及其 MET 值。"""
    from datetime import datetime
    # 按类型分组
    groups = {
        "cardio": [],
        "strength": [],
        "anaerobic": [],
    }
    # 有氧运动列表
    cardio_names = ["跑步", "快走", "游泳", "骑车", "跳绳", "椭圆机", "划船机",
                    "爬楼梯", "健身操", "跳舞", "羽毛球", "篮球", "足球",
                    "乒乓球", "网球"]
    strength_names = ["杠铃深蹲", "硬拉", "卧推", "哑铃训练", "器械训练",
                      "俯卧撑", "引体向上"]
    anaerobic_names = ["HIIT", "波比跳", "平板支撑", "卷腹", "俄罗斯转体"]

    for name in cardio_names:
        groups["cardio"].append({"name": name, "met": EXERCISE_MET.get(name, 5.0)})
    for name in strength_names:
        groups["strength"].append({"name": name, "met": EXERCISE_MET.get(name, 5.0)})
    for name in anaerobic_names:
        groups["anaerobic"].append({"name": name, "met": EXERCISE_MET.get(name, 5.0)})

    return groups
