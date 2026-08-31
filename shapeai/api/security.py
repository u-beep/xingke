"""请求安全助手 — 登录态解析与当前用户获取。

鉴权流程:
  1. app.py 中的 auth_middleware 解析 Authorization: Bearer <token>,
     校验通过后将 user_id / username 写入 request.state
  2. 各业务路由统一通过 get_auth_user_id() 取当前用户,
     保证每个用户只能读写属于自己的数据
  3. AUTH_ENABLED=true 时, /api/v1/* (除 /api/v1/auth/*) 未登录返回 401
"""

from typing import Optional

from fastapi import Request

from ..auth import resolve_token


def bearer_token_from_request(request: Request) -> Optional[str]:
    """从请求头提取 Bearer Token；<img> 等无法携带请求头的场景回退到 ?token= 查询参数。"""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip() or None
    return request.query_params.get("token") or None


async def auth_middleware(request: Request, call_next):
    """全局鉴权中间件。

    - 携带有效 Token: request.state.user_id / username 可用
    - AUTH_ENABLED 且访问受保护路径: 未登录返回 401
    """
    from ..config import AUTH_ENABLED

    token = bearer_token_from_request(request)
    payload = resolve_token(token)
    if payload:
        request.state.user_id = payload["user_id"]
        request.state.username = payload["username"]
        request.state.token = token

    path = request.url.path
    if (
        AUTH_ENABLED
        and path.startswith("/api/v1")
        and not path.startswith("/api/v1/auth/")
        and not path.startswith("/api/v1/health")
        # 公开图片: 品牌 logo 与内置食材图库均无用户数据, 免登录访问
        and not path.startswith("/api/v1/takeout/images/")
        and not path.startswith("/api/v1/fridge/catalog-images/")
        and getattr(request.state, "user_id", None) is None
    ):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "未登录或登录已过期"},
        )

    return await call_next(request)


def get_auth_user_id(request: Request, explicit: Optional[str] = None) -> str:
    """解析当前请求归属的用户 ID。

    优先级:
      1. Token 登录用户 (request.state.user_id) — 数据隔离的最终依据
      2. 显式传入的 user_id 参数 (旧接口兼容)
      3. X-User-Id 请求头 (旧前端兼容)
      4. "anonymous"
    """
    authed = getattr(request.state, "user_id", None)
    if authed:
        return authed
    if explicit and explicit != "anonymous":
        return explicit
    return request.headers.get("X-User-Id", "anonymous")
