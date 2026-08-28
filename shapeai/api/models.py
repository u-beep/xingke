"""API 请求/响应数据模型。"""

from pydantic import BaseModel, Field
from typing import Optional, Any


# ─── 对话相关 ───

class ChatRequest(BaseModel):
    """对话请求。"""
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(None, description="会话ID，为空时新建会话")
    user_id: str = Field("anonymous", description="用户ID")
    user_profile: Optional[dict] = Field(None, description="用户画像（身高、体重、目标等）")


class ChatResponse(BaseModel):
    """对话响应。"""
    session_id: str
    response: str
    user_id: str


# ─── 工具相关 ───

class ToolCallRequest(BaseModel):
    """工具直接调用请求。"""
    tool_name: str = Field(..., description="工具名称")
    args: dict = Field(default_factory=dict, description="工具参数")
    user_id: str = Field("anonymous", description="用户ID")


class ToolCallResponse(BaseModel):
    """工具调用响应。"""
    tool_name: str
    content: str
    metadata: dict


# ─── 知识库相关 ───

class KnowledgeAddRequest(BaseModel):
    """添加知识文档请求。"""
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    source: str = Field("", description="来源")
    category: str = Field("user", description="分类")


class KnowledgeSearchRequest(BaseModel):
    """知识检索请求。"""
    query: str = Field(..., description="查询文本")
    top_k: int = Field(5, description="返回前K条")
    category: Optional[str] = Field(None, description="按分类过滤")


# ─── 图像识别 ───

class FoodRecognitionRequest(BaseModel):
    """食物识别请求。"""
    image_base64: Optional[str] = Field(None, description="Base64编码的图片")
    description: Optional[str] = Field(None, description="食物文字描述")
    user_id: str = Field("anonymous", description="用户ID")


# ─── 通用 ───

class SessionListResponse(BaseModel):
    """会话列表响应。"""
    sessions: list[dict]


class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str
    version: str
