"""运动方案模板 + 运动热量规则 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional, List

from ...records import WorkoutStore, ExercisePlanStore, ExercisePlanItem

router = APIRouter(prefix="/workout", tags=["运动方案模板"])


# ─── 请求模型 ───

class CreateTemplateRequest(BaseModel):
    """创建运动方案模板。"""
    template_name: str = Field(..., description="模板名称")
    description: str = Field("", description="模板描述")
    items: List[dict] = Field(..., description="运动项列表: [{exercise_name, exercise_type, duration_min}]")


class ApplyTemplateRequest(BaseModel):
    """应用模板到当天。"""
    template_id: int = Field(..., description="模板ID")
    plan_date: Optional[str] = Field(None, description="计划日期，不传默认今天")


# ─── 运动热量规则接口 ───

@router.get("/exercises", summary="获取运动热量规则列表")
async def list_exercises(exercise_type: str = None):
    """获取所有运动及其热量消耗规则，可按类型过滤。"""
    store = WorkoutStore()
    exercises = store.list_exercises(exercise_type)
    # 按类型分组
    groups = {"cardio": [], "strength": [], "anaerobic": []}
    for ex in exercises:
        key = ex.exercise_type
        if key not in groups:
            groups[key] = []
        groups[key].append(ex.to_dict())
    return groups


@router.get("/exercises/search", summary="搜索运动")
async def search_exercises(keyword: str = ""):
    """按关键词搜索运动。"""
    store = WorkoutStore()
    all_ex = store.list_exercises()
    if not keyword:
        return [ex.to_dict() for ex in all_ex]
    return [ex.to_dict() for ex in all_ex if keyword in ex.exercise_name]


# ─── 运动方案模板接口 ───

@router.post("/templates", summary="创建运动方案模板")
async def create_template(request: CreateTemplateRequest, req: Request):
    """创建自定义运动方案模板。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WorkoutStore()
    template_id = store.create_template(
        user_id=user_id,
        template_name=request.template_name,
        description=request.description,
        items=request.items,
    )
    return {
        "success": template_id is not None,
        "template_id": template_id,
    }


@router.get("/templates", summary="获取运动方案模板列表")
async def list_templates(req: Request, user_id: str = "anonymous"):
    """获取用户的所有运动方案模板。"""
    store = WorkoutStore()
    templates = store.list_templates(user_id)
    return {
        "templates": [t.to_dict() for t in templates],
        "count": len(templates),
    }


@router.get("/templates/{template_id}", summary="获取模板详情")
async def get_template(template_id: int):
    """获取单个模板详情。"""
    store = WorkoutStore()
    template = store.get_template(template_id)
    if not template:
        return {"success": False, "message": "模板不存在"}
    return template.to_dict()


@router.delete("/templates/{template_id}", summary="删除模板")
async def delete_template(template_id: int):
    """删除运动方案模板。"""
    store = WorkoutStore()
    deleted = store.delete_template(template_id)
    return {"success": deleted}


@router.post("/templates/apply", summary="应用模板到当天计划")
async def apply_template(request: ApplyTemplateRequest, req: Request):
    """将模板中的运动项添加到当天运动计划。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WorkoutStore()
    plan_store = ExercisePlanStore()

    template = store.get_template(request.template_id)
    if not template:
        return {"success": False, "message": "模板不存在"}

    from datetime import datetime
    plan_date = request.plan_date or datetime.now().strftime("%Y-%m-%d")

    added_count = 0
    total_calories = 0
    for item in template.items:
        exercise = store.get_exercise_by_name(item.get("exercise_name", ""))
        met = exercise.met_value if exercise else 5.0
        duration = item.get("duration_min", 30)
        calories = plan_store.calc_calories(item["exercise_name"], duration)

        plan_item = ExercisePlanItem(
            user_id=user_id,
            plan_date=plan_date,
            exercise_type=item.get("exercise_type", "cardio"),
            exercise_name=item.get("exercise_name", ""),
            duration_min=duration,
            calories_burned=calories,
        )
        item_id = plan_store.add_item(plan_item)
        if item_id:
            added_count += 1
            total_calories += calories

    return {
        "success": added_count > 0,
        "added_count": added_count,
        "total_calories": round(total_calories, 1),
        "template_name": template.template_name,
    }
