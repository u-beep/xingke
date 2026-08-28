"""用户目标 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

from ...records import GoalStore, UserGoal

router = APIRouter(prefix="/goals", tags=["目标管理"])


class CreateGoalRequest(BaseModel):
    """创建目标请求。"""
    goal_type: str = Field(..., description="目标类型: weight_loss/body_fat/muscle_gain/exercise_frequency")
    target_value: float = Field(..., description="目标值")
    current_value: Optional[float] = Field(None, description="当前值")
    unit: Optional[str] = Field(None, description="单位")
    start_value: Optional[float] = Field(None, description="起始值")
    deadline: Optional[str] = Field(None, description="截止日期(YYYY-MM-DD)")


class UpdateGoalRequest(BaseModel):
    """更新目标请求。"""
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    start_value: Optional[float] = None
    deadline: Optional[str] = None
    status: Optional[str] = None


@router.post("", summary="创建目标")
async def create_goal(request: CreateGoalRequest, req: Request):
    """创建新目标。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = GoalStore()
    deadline = None
    if request.deadline:
        deadline = date.fromisoformat(request.deadline)
    goal = UserGoal(
        user_id=user_id,
        goal_type=request.goal_type,
        target_value=request.target_value,
        current_value=request.current_value,
        unit=request.unit,
        start_value=request.start_value,
        deadline=deadline,
    )
    goal_id = store.create_goal(goal)
    return {
        "success": goal_id is not None,
        "goal_id": goal_id,
        "message": "目标已创建" if goal_id else "创建失败",
    }


@router.get("/progress", summary="获取目标进度")
async def get_goal_progress(req: Request):
    """获取用户所有活跃目标的进度。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = GoalStore()
    progress = store.get_progress_summary(user_id)
    return progress


@router.get("", summary="获取目标列表")
async def list_goals(
    req: Request,
    status: Optional[str] = None,
):
    """获取用户目标列表。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = GoalStore()
    goals = store.get_user_goals(user_id, status=status)
    return {
        "goals": [g.to_dict() for g in goals],
        "count": len(goals),
    }


@router.put("/{goal_id}", summary="更新目标")
async def update_goal(goal_id: int, request: UpdateGoalRequest, req: Request):
    """更新目标信息。"""
    store = GoalStore()
    updates = request.model_dump(exclude_unset=True)
    if "deadline" in updates and updates["deadline"]:
        updates["deadline"] = date.fromisoformat(updates["deadline"])
    success = store.update_goal(goal_id, updates)
    return {
        "success": success,
        "message": "目标已更新" if success else "更新失败",
    }
