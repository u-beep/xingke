"""图像识别路由。"""

from fastapi import APIRouter, Request

from ..models import FoodRecognitionRequest
from ..security import get_auth_user_id

router = APIRouter(prefix="/vision", tags=["图像识别"])


@router.post("/food-recognition", summary="食物识别")
async def recognize_food(request: FoodRecognitionRequest, req: Request):
    """识别食物并返回营养信息。

    支持通过图片Base64或文字描述进行识别。
    """
    service = req.app.state.food_recognition
    result = service.recognize(
        image_base64=request.image_base64,
        description=request.description,
        user_id=get_auth_user_id(req, request.user_id),
    )
    return result


@router.get("/food-database", summary="获取食物营养数据库")
async def get_food_database(req: Request):
    """获取内置食物营养数据库。"""
    service = req.app.state.food_recognition
    return {"foods": service.get_food_database()}


@router.get("/low-confidence-log", summary="获取低置信度识别记录")
async def get_low_confidence_log(req: Request, limit: int = 50):
    """获取低置信度识别记录（供人工标注回流）。"""
    service = req.app.state.food_recognition
    return {"records": service.get_low_confidence_log(limit=limit)}
