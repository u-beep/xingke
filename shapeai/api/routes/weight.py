"""体重记录 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from ...records import WeightStore, WeightRecord

router = APIRouter(prefix="/weight", tags=["体重记录"])


class WeightRecordRequest(BaseModel):
    """记录体重请求。"""
    weight_kg: float = Field(..., description="体重(kg)")
    body_fat_pct: Optional[float] = Field(None, description="体脂率(%)")
    waist_cm: Optional[float] = Field(None, description="腰围(cm)")
    hip_cm: Optional[float] = Field(None, description="臀围(cm)")
    notes: Optional[str] = Field(None, description="备注")


@router.post("/record", summary="记录体重")
async def record_weight(request: WeightRecordRequest, req: Request):
    """记录用户体重及相关身体数据。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WeightStore()
    record = WeightRecord(
        user_id=user_id,
        weight_kg=request.weight_kg,
        body_fat_pct=request.body_fat_pct,
        waist_cm=request.waist_cm,
        hip_cm=request.hip_cm,
        notes=request.notes,
    )
    record_id = store.add_record(record)
    return {
        "success": record_id is not None,
        "record_id": record_id,
        "message": "体重记录已保存" if record_id else "记录失败",
    }


@router.get("/history", summary="查询体重历史")
async def get_weight_history(
    req: Request,
    days: int = 30,
    limit: int = 100,
):
    """查询用户体重历史记录。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WeightStore()
    records = store.get_history(user_id, days=days, limit=limit)
    return {
        "records": [r.to_dict() for r in records],
        "count": len(records),
        "days": days,
    }


@router.get("/latest", summary="获取最新体重")
async def get_latest_weight(req: Request):
    """获取用户最新体重记录。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WeightStore()
    record = store.get_latest(user_id)
    return {
        "record": record.to_dict() if record else None,
    }


@router.get("/stats", summary="体重统计")
async def get_weight_stats(
    req: Request,
    days: int = 7,
):
    """获取指定周期内的体重统计。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = WeightStore()
    stats = store.get_stats(user_id, days=days)
    return stats
