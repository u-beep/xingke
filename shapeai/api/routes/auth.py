"""认证路由 — 注册 / 登录 / 当前用户 / 退出。

所有接口位于 /api/v1/auth/*, 无需 Token 即可访问 (register/login),
/me 与 /logout 需携带 Bearer Token。
"""

import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ...auth import (
    UserStore,
    create_token,
    resolve_token,
    revoke_token,
    validate_username,
    verify_password,
)
from ..security import bearer_token_from_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class RegisterRequest(BaseModel):
    """注册请求。"""
    username: str = Field(..., min_length=3, max_length=32, description="用户名(3-32位,字母/数字/下划线/中文)")
    password: str = Field(..., min_length=6, max_length=64, description="密码(6-64位)")
    nickname: Optional[str] = Field(None, max_length=32, description="昵称, 默认同用户名")


class LoginRequest(BaseModel):
    """登录请求。"""
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=64)


def _user_payload(user: dict, token: str) -> dict:
    """统一返回结构。"""
    return {
        "token": token,
        "user": {
            "user_id": user["username"],  # 业务侧 user_id = username
            "username": user["username"],
            "nickname": user.get("nickname"),
        },
    }


@router.post("/register", summary="注册新用户")
async def register(request: RegisterRequest):
    """创建账号，成功后直接返回会话令牌（自动登录）。"""
    username = request.username.strip()
    if not validate_username(username):
        raise HTTPException(
            status_code=400,
            detail="用户名不合法：3-32位，仅支持字母/数字/下划线/中文",
        )

    if UserStore.get_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已被注册")

    try:
        user = UserStore.create(username, request.password, request.nickname)
    except Exception as exc:
        logger.error("注册失败: %s", exc)
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    UserStore.update_last_login(username)
    token = create_token(user["username"], user["username"])
    return _user_payload(user, token)


@router.post("/login", summary="登录")
async def login(request: LoginRequest):
    """校验账号密码，返回会话令牌。"""
    username = request.username.strip()
    user = UserStore.get_by_username(username)
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    UserStore.update_last_login(username)
    token = create_token(user["username"], user["username"])
    return _user_payload(user, token)


@router.get("/me", summary="获取当前登录用户")
async def me(req: Request):
    """根据 Bearer Token 返回当前用户信息。"""
    token = bearer_token_from_request(req)
    payload = resolve_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    user = UserStore.get_by_username(payload["username"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已被删除")

    return {
        "user": {
            "user_id": user["username"],
            "username": user["username"],
            "nickname": user.get("nickname"),
        },
        "created_at": str(user.get("created_at") or ""),
        "last_login_at": str(user.get("last_login_at") or ""),
    }


@router.post("/logout", summary="退出登录")
async def logout(req: Request):
    """吊销当前会话令牌。"""
    token = bearer_token_from_request(req)
    revoke_token(token)
    return {"success": True, "message": "已退出登录"}
