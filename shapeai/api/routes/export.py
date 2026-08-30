"""数据导出 API 路由。"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta
import io
import csv

from ...records import WeightStore
from ..security import get_auth_user_id

router = APIRouter(prefix="/export", tags=["数据导出"])


@router.get("/weight-history", summary="导出体重历史")
async def export_weight_history(
    req: Request,
    days: int = 30,
    format: str = "csv",
):
    """导出体重历史数据为 CSV 或 JSON。"""
    user_id = get_auth_user_id(req)
    store = WeightStore()
    records = store.get_history(user_id, days=days, limit=1000)

    if format == "json":
        import json
        data = json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(data.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=weight_history_{user_id}.json"},
        )

    # CSV 格式
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["记录ID", "用户ID", "体重(kg)", "体脂率(%)", "腰围(cm)", "臀围(cm)", "记录时间", "备注"])
    for r in records:
        writer.writerow([
            r.id, r.user_id, r.weight_kg, r.body_fat_pct or "",
            r.waist_cm or "", r.hip_cm or "",
            r.recorded_at.strftime("%Y-%m-%d %H:%M:%S") if r.recorded_at else "",
            r.notes or "",
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=weight_history_{user_id}.csv"},
    )
