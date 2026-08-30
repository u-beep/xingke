"""运动记录 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

from ...records import ExerciseStore, ExerciseRecord
from ..security import get_auth_user_id

router = APIRouter(prefix="/exercise", tags=["运动记录"])


class ExerciseRecordRequest(BaseModel):
    """记录运动请求。"""
    exercise_name: str = Field(..., description="运动名称")
    exercise_type: Optional[str] = Field(None, description="运动类型: 有氧/力量/核心/柔韧/休息")
    duration_min: Optional[int] = Field(None, description="时长(分钟)")
    calories_burned: Optional[float] = Field(None, description="消耗热量(kcal)")
    completed: bool = Field(True, description="是否完成")
    scheduled_date: Optional[str] = Field(None, description="计划日期(YYYY-MM-DD)")
    notes: Optional[str] = Field(None, description="备注")


@router.post("/record", summary="记录运动")
async def record_exercise(request: ExerciseRecordRequest, req: Request):
    """记录用户运动。"""
    user_id = get_auth_user_id(req)
    store = ExerciseStore()
    scheduled = None
    if request.scheduled_date:
        scheduled = date.fromisoformat(request.scheduled_date)
    record = ExerciseRecord(
        user_id=user_id,
        exercise_name=request.exercise_name,
        exercise_type=request.exercise_type,
        duration_min=request.duration_min,
        calories_burned=request.calories_burned,
        completed=request.completed,
        scheduled_date=scheduled,
        notes=request.notes,
    )
    record_id = store.add_record(record)
    return {
        "success": record_id is not None,
        "record_id": record_id,
        "message": "运动记录已保存" if record_id else "记录失败",
    }


@router.get("/today", summary="获取今日运动")
async def get_today_exercise(req: Request):
    """获取用户今日运动记录。"""
    user_id = get_auth_user_id(req)
    store = ExerciseStore()
    records = store.get_today_records(user_id)
    return {
        "records": [r.to_dict() for r in records],
        "count": len(records),
    }


@router.get("/week", summary="获取本周运动")
async def get_week_exercise(req: Request):
    """获取用户本周运动记录及统计。"""
    user_id = get_auth_user_id(req)
    store = ExerciseStore()
    records = store.get_week_records(user_id)
    summary = store.get_week_summary(user_id)
    return {
        "records": [r.to_dict() for r in records],
        "summary": summary,
    }


@router.get("/history", summary="查询运动历史")
async def get_exercise_history(
    req: Request,
    days: int = 30,
    limit: int = 200,
):
    """查询用户运动历史。"""
    user_id = get_auth_user_id(req)
    store = ExerciseStore()
    records = store.get_history(user_id, days=days, limit=limit)
    return {
        "records": [r.to_dict() for r in records],
        "count": len(records),
        "days": days,
    }
