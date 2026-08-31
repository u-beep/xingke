"""活动模块 API 路由。

提供:
  POST   /activities                     创建活动（自动建群+创建者入群）
  GET    /activities                     活动列表（城市/行政区/运动类型/关键词筛选）
  GET    /activities/sport-types         运动类型列表
  GET    /activities/cities              城市列表（有活动的城市）
  GET    /activities/districts           行政区列表（按城市）
  GET    /activities/mine                我加入/发起的活动
  GET    /activities/{id}                活动详情（含成员数/我的成员角色）
  PUT    /activities/{id}                修改活动（仅发起者）
  DELETE /activities/{id}                删除/解散活动（仅发起者）
  POST   /activities/{id}/join           加入活动（=加入群聊）
  POST   /activities/{id}/leave          退出活动
  GET    /activities/{id}/members        成员列表
  DELETE /activities/{id}/members/{uid}  移除成员（仅发起者）
  GET    /activities/{id}/group          群聊信息
  PUT    /activities/{id}/group          修改群信息（仅发起者）
  GET    /activities/{id}/messages       拉取群聊消息（支持 before_id 翻页）
  POST   /activities/{id}/messages       发送群聊消息（仅成员）
"""

import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...records import ActivityStore, ACTIVITY_SPORT_TYPES
from ...records.activity_store import ActivityError
from ..security import get_auth_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/activities", tags=["活动"])


def _error_response(exc: ActivityError):
    """业务异常 -> HTTP 响应。"""
    status_map = {
        "not_found": 404,
        "forbidden": 403,
        "conflict": 409,
        "full": 409,
        "bad_request": 422,
        "server_error": 500,
    }
    status = status_map.get(exc.code, 400)
    return JSONResponse(status_code=status, content={"detail": exc.message})


def _parse_datetime(value: str) -> datetime:
    """解析前端传来的活动时间(兼容 ISO 8601 带 Z 或 +08:00)。"""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise ActivityError("活动时间格式不正确，请使用 ISO 8601 格式") from exc


# ─── 请求模型 ───

class CreateActivityRequest(BaseModel):
    """创建活动请求。"""
    title: str = Field(..., min_length=1, max_length=128, description="活动名称")
    sport_type: str = Field(..., description="运动类型: 篮球/跑步/羽毛球/...")
    city: str = Field(..., min_length=1, max_length=64, description="城市")
    district: Optional[str] = Field("", max_length=64, description="行政区")
    location: Optional[str] = Field("", max_length=256, description="具体地点")
    start_time: str = Field(..., description="活动时间 ISO 8601")
    max_participants: int = Field(10, ge=1, le=500, description="人数上限")
    description: Optional[str] = Field("", max_length=2000, description="活动描述")


class UpdateActivityRequest(BaseModel):
    """修改活动请求（所有字段可选, 仅传需要修改的）。"""
    title: Optional[str] = Field(None, min_length=1, max_length=128)
    sport_type: Optional[str] = None
    city: Optional[str] = Field(None, min_length=1, max_length=64)
    district: Optional[str] = Field(None, max_length=64)
    location: Optional[str] = Field(None, max_length=256)
    start_time: Optional[str] = None
    max_participants: Optional[int] = Field(None, ge=1, le=500)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = None


class UpdateGroupRequest(BaseModel):
    """修改群信息请求。"""
    group_name: Optional[str] = Field(None, min_length=1, max_length=128)
    announcement: Optional[str] = Field(None, max_length=1000)


class SendMessageRequest(BaseModel):
    """发送群聊消息请求。"""
    content: str = Field(..., min_length=1, max_length=2000, description="消息内容")


# ─── 活动 CRUD ───

@router.post("", summary="创建活动（自动建群）")
async def create_activity(body: CreateActivityRequest, req: Request):
    """创建活动: 建活动 -> 自动建群 -> 创建者以管理员身份入群。"""
    user_id = get_auth_user_id(req)
    username = getattr(req.state, "username", None) or user_id
    store = ActivityStore()
    try:
        activity = store.create_activity(
            creator_id=user_id,
            creator_nickname=username,
            title=body.title,
            sport_type=body.sport_type,
            city=body.city,
            district=body.district or "",
            location=body.location or "",
            start_time=_parse_datetime(body.start_time),
            max_participants=body.max_participants,
            description=body.description or "",
        )
        if not activity:
            raise ActivityError("创建活动失败", "server_error")
        return {
            "success": True,
            "activity": activity.to_dict(),
            "group_id": activity.group_id,
            "message": "活动创建成功，群聊已自动创建",
        }
    except ActivityError as exc:
        return _error_response(exc)


@router.get("", summary="活动列表")
async def list_activities(
    req: Request,
    city: Optional[str] = None,
    district: Optional[str] = None,
    sport_type: Optional[str] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    only_mine: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """活动列表, 支持城市/行政区/运动类型/关键词/状态筛选与分页。"""
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    results = store.list_activities(
        city=city, district=district, sport_type=sport_type,
        keyword=keyword, status=status,
        only_mine=only_mine, user_id=user_id,
        limit=min(limit, 200), offset=max(offset, 0),
    )
    return {
        "activities": [r["activity"] for r in results if r["activity"]],
        "member_counts": [r["member_count"] for r in results if r["activity"]],
        "count": len(results),
    }


@router.get("/sport-types", summary="运动类型列表")
async def list_sport_types():
    """支持的运动类型枚举。"""
    return {"sport_types": ACTIVITY_SPORT_TYPES}


@router.get("/cities", summary="有活动的城市列表")
async def list_cities():
    store = ActivityStore()
    return {"cities": store.list_districts()}


@router.get("/districts", summary="行政区列表（按城市过滤）")
async def list_districts(city: Optional[str] = None):
    store = ActivityStore()
    return {"districts": store.list_districts(city)}


@router.get("/mine", summary="我加入/发起的活动")
async def list_my_activities(req: Request):
    """当前用户参与的所有活动（含角色 owner/member）。"""
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    results = store.list_my_activities(user_id)
    return {
        "activities": [r["activity"] for r in results if r["activity"]],
        "roles": [r["role"] for r in results if r["activity"]],
        "member_counts": [r["member_count"] for r in results if r["activity"]],
        "count": len(results),
    }


@router.get("/{activity_id}", summary="活动详情")
async def get_activity(activity_id: int, req: Request):
    """活动详情（含成员数与当前用户角色）。"""
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    activity = store.get_activity(activity_id)
    if not activity:
        return JSONResponse(status_code=404, content={"detail": "活动不存在"})
    member = store.get_member(activity_id, user_id)
    member_count = store.count_members(activity_id)
    return {
        "activity": activity.to_dict(),
        "member_count": member_count,
        "my_role": member.role if member else None,  # owner/member/null(未加入)
        "is_creator": activity.creator_id == user_id,
    }


@router.put("/{activity_id}", summary="修改活动（仅发起者）")
async def update_activity(activity_id: int, body: UpdateActivityRequest, req: Request):
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    try:
        fields = body.model_dump(exclude_none=True)
        if "start_time" in fields:
            fields["start_time"] = _parse_datetime(fields["start_time"])
        activity = store.update_activity(activity_id, user_id, **fields)
        return {"success": True, "activity": activity.to_dict()}
    except ActivityError as exc:
        return _error_response(exc)


@router.delete("/{activity_id}", summary="解散活动（仅发起者）")
async def delete_activity(activity_id: int, req: Request):
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    try:
        store.delete_activity(activity_id, user_id)
        return {"success": True, "message": "活动已解散，关联群聊已删除"}
    except ActivityError as exc:
        return _error_response(exc)


# ─── 加入/退出 ───

@router.post("/{activity_id}/join", summary="加入活动（自动加入群聊）")
async def join_activity(activity_id: int, req: Request):
    user_id = get_auth_user_id(req)
    username = getattr(req.state, "username", None) or user_id
    store = ActivityStore()
    try:
        result = store.join_activity(activity_id, user_id, nickname=username)
        return {**result, "message": "已加入活动并进入群聊"}
    except ActivityError as exc:
        return _error_response(exc)


@router.post("/{activity_id}/leave", summary="退出活动")
async def leave_activity(activity_id: int, req: Request):
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    try:
        result = store.leave_activity(activity_id, user_id)
        return {**result, "message": "已退出活动"}
    except ActivityError as exc:
        return _error_response(exc)


# ─── 成员 ───

@router.get("/{activity_id}/members", summary="成员列表")
async def list_members(activity_id: int, req: Request):
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    activity = store.get_activity(activity_id)
    if not activity:
        return JSONResponse(status_code=404, content={"detail": "活动不存在"})
    member = store.get_member(activity_id, user_id)
    if not member:
        return JSONResponse(status_code=403, content={"detail": "仅成员可查看成员列表"})
    members = store.list_members(activity_id)
    return {
        "members": [m.to_dict() for m in members],
        "count": len(members),
        "my_role": member.role,
    }


@router.delete("/{activity_id}/members/{target_user_id}", summary="移除成员（仅发起者）")
async def remove_member(activity_id: int, target_user_id: str, req: Request):
    operator_id = get_auth_user_id(req)
    store = ActivityStore()
    try:
        result = store.remove_member(activity_id, operator_id, target_user_id)
        return {**result, "message": f"已移除成员 {target_user_id}"}
    except ActivityError as exc:
        return _error_response(exc)


# ─── 群聊 ───

@router.get("/{activity_id}/group", summary="群聊信息")
async def get_group(activity_id: int, req: Request):
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    group = store.get_group_by_activity(activity_id)
    if not group:
        return JSONResponse(status_code=404, content={"detail": "群聊不存在"})
    member = store.get_member(activity_id, user_id)
    if not member:
        return JSONResponse(status_code=403, content={"detail": "仅成员可查看群聊"})
    return {
        "group": group.to_dict(),
        "my_role": member.role,
        "member_count": store.count_members(activity_id),
    }


@router.put("/{activity_id}/group", summary="修改群信息（仅发起者）")
async def update_group(activity_id: int, body: UpdateGroupRequest, req: Request):
    operator_id = get_auth_user_id(req)
    store = ActivityStore()
    try:
        group = store.update_group(
            activity_id, operator_id,
            group_name=body.group_name,
            announcement=body.announcement,
        )
        return {"success": True, "group": group.to_dict()}
    except ActivityError as exc:
        return _error_response(exc)


@router.get("/{activity_id}/messages", summary="拉取群聊消息")
async def list_messages(
    activity_id: int, req: Request,
    before_id: Optional[int] = None, limit: int = 50,
):
    """拉取群聊消息（时间正序; before_id 用于向前翻页）。"""
    user_id = get_auth_user_id(req)
    store = ActivityStore()
    activity = store.get_activity(activity_id)
    if not activity:
        return JSONResponse(status_code=404, content={"detail": "活动不存在"})
    group = store.get_group_by_activity(activity_id)
    if not group:
        return JSONResponse(status_code=404, content={"detail": "群聊不存在"})
    messages = store.list_messages(group.id, user_id, before_id=before_id, limit=min(limit, 200))
    return {
        "group_id": group.id,
        "messages": [m.to_dict() for m in messages],
        "count": len(messages),
    }


@router.post("/{activity_id}/messages", summary="发送群聊消息（仅成员）")
async def send_message(activity_id: int, body: SendMessageRequest, req: Request):
    user_id = get_auth_user_id(req)
    username = getattr(req.state, "username", None) or user_id
    store = ActivityStore()
    activity = store.get_activity(activity_id)
    if not activity:
        return JSONResponse(status_code=404, content={"detail": "活动不存在"})
    group = store.get_group_by_activity(activity_id)
    if not group:
        return JSONResponse(status_code=404, content={"detail": "群聊不存在"})
    try:
        message = store.send_message(group.id, user_id, body.content, sender_nickname=username)
        return {"success": True, "message": message.to_dict()}
    except ActivityError as exc:
        return _error_response(exc)
