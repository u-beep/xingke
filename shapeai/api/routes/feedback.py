"""消息反馈 API 路由。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from ...records import FeedbackStore, MessageFeedback

router = APIRouter(prefix="/feedback", tags=["消息反馈"])


class MessageFeedbackRequest(BaseModel):
    """消息反馈请求。"""
    session_id: Optional[str] = Field(None, description="会话ID")
    message_id: Optional[str] = Field(None, description="消息ID")
    feedback_type: str = Field(..., description="反馈类型: thumbs_up/thumbs_down/report")
    reason: Optional[str] = Field(None, description="反馈原因")


@router.post("/message", summary="提交消息反馈")
async def submit_feedback(request: MessageFeedbackRequest, req: Request):
    """提交对 AI 消息的反馈。"""
    user_id = req.headers.get("X-User-Id", "anonymous")
    store = FeedbackStore()
    feedback = MessageFeedback(
        user_id=user_id,
        session_id=request.session_id,
        message_id=request.message_id,
        feedback_type=request.feedback_type,
        reason=request.reason,
    )
    feedback_id = store.add_feedback(feedback)
    return {
        "success": feedback_id is not None,
        "feedback_id": feedback_id,
        "message": "反馈已提交" if feedback_id else "提交失败",
    }
