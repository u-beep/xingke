"""消息反馈存储模块。

使用 PostgreSQL 持久化存储用户对 AI 消息的反馈。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..database import pg_cursor

logger = logging.getLogger(__name__)


@dataclass
class MessageFeedback:
    """消息反馈数据类。"""
    id: Optional[int] = None
    user_id: str = ""
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    feedback_type: str = ""  # thumbs_up / thumbs_down / report
    reason: Optional[str] = None
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "feedback_type": self.feedback_type,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class FeedbackStore:
    """消息反馈存储器。"""

    def add_feedback(self, feedback: MessageFeedback) -> Optional[int]:
        """添加反馈记录。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO message_feedback
                    (user_id, session_id, message_id, feedback_type, reason, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    feedback.user_id, feedback.session_id, feedback.message_id,
                    feedback.feedback_type, feedback.reason,
                    feedback.created_at or datetime.now(),
                ))
                row = cur.fetchone()
                feedback_id = row[0] if row else None
                logger.info("反馈已记录: user=%s type=%s id=%s",
                            feedback.user_id, feedback.feedback_type, feedback_id)
                return feedback_id
        except Exception as exc:
            logger.error("记录反馈失败: %s", exc)
            return None
