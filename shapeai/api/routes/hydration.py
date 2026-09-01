"""饮水记录 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from ...records import HydrationStore, HydrationRecord
from ..security import get_auth_user_id

router = APIRouter(prefix="/hydration", tags=["饮水记录"])


class HydrationRecordRequest(BaseModel):
    """记录饮水请求。"""
    amount_ml: float = Field(..., gt=0, description="饮水量毫升")
    drink_type: Optional[str] = Field("water", description="饮料类型: water/tea/coffee/juice/milk/soup/other")
    notes: Optional[str] = Field(None, description="备注")


class HydrationManualTotalRequest(BaseModel):
    """手动设置今日饮水总量请求。"""
    total_ml: float = Field(..., ge=0, description="目标总量(毫升)，0 表示清空今日饮水")


@router.post("/record", summary="记录饮水")
async def record_hydration(request: HydrationRecordRequest, req: Request):
    """记录用户饮水。"""
    user_id = get_auth_user_id(req)
    store = HydrationStore()
    record = HydrationRecord(
        user_id=user_id,
        amount_ml=request.amount_ml,
        drink_type=request.drink_type or "water",
        notes=request.notes,
    )
    record_id = store.add_record(record)
    return {
        "success": record_id is not None,
        "record_id": record_id,
        "message": "饮水记录已保存" if record_id else "记录失败",
    }


@router.post("/manual-total", summary="手动设置今日饮水总量")
async def set_manual_total(request: HydrationManualTotalRequest, req: Request):
    """手动修正今日饮水总量。

    新值大于当前总量时补录差值；小于时清空今日记录后重建单条手动记录。
    """
    user_id = get_auth_user_id(req)
    store = HydrationStore()
    ok = store.set_today_total(user_id, request.total_ml)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="设置今日饮水总量失败")
    summary = store.get_today_summary(user_id)
    return {"success": True, "summary": summary}


@router.get("/today", summary="获取今日饮水")
async def get_today_hydration(req: Request):
    """获取用户今日饮水记录及统计。"""
    user_id = get_auth_user_id(req)
    store = HydrationStore()
    records = store.get_today_records(user_id)
    summary = store.get_today_summary(user_id)
    return {
        "records": [r.to_dict() for r in records],
        "summary": summary,
    }


@router.get("/summary", summary="按日期获取饮水统计")
async def get_hydration_summary(req: Request, user_id: str = "anonymous", date: str = None):
    """获取指定日期的饮水统计。

    Args:
        user_id: 用户ID（登录态优先，参数仅作未鉴权回退）
        date: 日期 YYYY-MM-DD，不传默认今天
    """
    user_id = get_auth_user_id(req, user_id)
    store = HydrationStore()
    if date:
        summary = store.get_summary_by_date(user_id, date)
    else:
        summary = store.get_today_summary(user_id)
    return summary


class HydrationConfirmRequest(BaseModel):
    """用户确认计入饮水的请求。"""
    user_id: Optional[str] = Field(None, description="用户ID，未传则回退到 X-User-Id 头")
    amount_ml: float = Field(..., gt=0, description="饮水量毫升")
    drink_type: Optional[str] = Field("water", description="饮料类型")
    notes: Optional[str] = Field(None, description="备注")


@router.post("/confirm", summary="确认计入今日饮水总量")
async def confirm_hydration(request: HydrationConfirmRequest, req: Request):
    """用户确认后，将提取的饮水量写入今日饮水记录。"""
    # 登录态优先（Token 用户），回退到 body/X-User-Id/anonymous
    user_id = get_auth_user_id(req, request.user_id)
    store = HydrationStore()
    record = HydrationRecord(
        user_id=user_id,
        amount_ml=request.amount_ml,
        drink_type=request.drink_type or "water",
        notes=request.notes,
    )
    record_id = store.add_record(record)
    # 取今日累计用于返回
    summary = store.get_today_summary(user_id)
    return {
        "success": record_id is not None,
        "record_id": record_id,
        "saved_ml": request.amount_ml if record_id else 0,
        "total_ml": summary.get("total_ml", 0),
        "percentage": summary.get("percentage", 0),
        "goal_ml": summary.get("goal_ml", 2000),
    }


@router.get("/history", summary="查询饮水历史")
async def get_hydration_history(
    req: Request,
    days: int = 30,
    limit: int = 200,
):
    """查询用户饮水历史。"""
    user_id = get_auth_user_id(req)
    store = HydrationStore()
    records = store.get_history(user_id, days=days, limit=limit)
    return {
        "records": [r.to_dict() for r in records],
        "count": len(records),
        "days": days,
    }
