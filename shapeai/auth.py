"""用户认证核心模块 — 密码哈希、用户表存储、Token 会话管理。

设计:
  密码存储  PBKDF2-SHA256 加盐哈希（Python 标准库实现, 零外部依赖）
            存储格式: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
  用户主键  users.id (BIGSERIAL)；业务侧 user_id 统一使用 username 字符串,
            与既有各业务表 (diet_records/weight_records/...) 的 user_id 字段对齐
  会话令牌  secrets.token_urlsafe 随机 Token, 存 Redis:
            key   shapeai:auth:token:<token>
            value <user_id>|<username>
            TTL   默认 7 天, 每次校验成功滚动续期
"""

import hashlib
import logging
import re
import secrets
from typing import Optional

from .config import AUTH_TOKEN_EXPIRE_DAYS
from .database import pg_cursor, redis_client

logger = logging.getLogger(__name__)

# ─── 密码哈希 (PBKDF2-SHA256) ───

_PBKDF2_ITERATIONS = 120_000
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,32}$")


def validate_username(username: str) -> bool:
    """用户名: 3-32 位, 字母/数字/下划线/中文。"""
    return bool(username) and bool(_USERNAME_RE.match(username))


def hash_password(password: str) -> str:
    """生成加盐 PBKDF2 哈希。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否与存储的哈希匹配（恒定时间比较）。"""
    try:
        algo, iterations, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        ).hex()
        return secrets.compare_digest(calc, digest)
    except Exception:
        return False


# ─── 用户表存储 (PostgreSQL) ───

class UserStore:
    """users 表 CRUD。"""

    @staticmethod
    def create(username: str, password: str, nickname: Optional[str] = None) -> dict:
        """创建用户。用户名唯一冲突时抛 ValueError。"""
        password_hash = hash_password(password)
        with pg_cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, nickname)
                VALUES (%s, %s, %s)
                RETURNING id, username, nickname, created_at
                """,
                (username, password_hash, nickname or username),
            )
            row = cur.fetchone()
        user = {"id": row[0], "username": row[1], "nickname": row[2]}
        logger.info("新用户注册: %s (id=%s)", username, row[0])
        return user

    @staticmethod
    def get_by_username(username: str) -> Optional[dict]:
        """按用户名查询用户（含密码哈希, 仅供登录校验使用）。"""
        with pg_cursor(commit=False) as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, nickname, created_at, last_login_at
                FROM users WHERE username = %s
                """,
                (username,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "nickname": row[3],
            "created_at": row[4],
            "last_login_at": row[5],
        }

    @staticmethod
    def update_last_login(username: str) -> None:
        """更新最后登录时间。"""
        with pg_cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = now() WHERE username = %s",
                (username,),
            )


# ─── Token 会话 (Redis) ───

_TOKEN_PREFIX = "shapeai:auth:token:"


def _token_ttl() -> int:
    return max(1, AUTH_TOKEN_EXPIRE_DAYS) * 86400


def create_token(user_id: str, username: str) -> str:
    """创建会话令牌并写入 Redis。"""
    token = secrets.token_urlsafe(32)
    redis_client().set(f"{_TOKEN_PREFIX}{token}", f"{user_id}|{username}", ex=_token_ttl())
    return token


def resolve_token(token: Optional[str]) -> Optional[dict]:
    """校验令牌, 有效则返回 {user_id, username} 并滚动续期；无效返回 None。"""
    if not token:
        return None
    try:
        r = redis_client()
        key = f"{_TOKEN_PREFIX}{token}"
        val = r.get(key)
        if not val:
            return None
        user_id, _, username = val.partition("|")
        r.expire(key, _token_ttl())  # 滑动续期: 活跃用户不掉线
        return {"user_id": user_id, "username": username}
    except Exception as exc:
        logger.error("Token 校验失败(Redis 异常): %s", exc)
        return None


def revoke_token(token: Optional[str]) -> bool:
    """吊销令牌（退出登录）。"""
    if not token:
        return False
    try:
        return bool(redis_client().delete(f"{_TOKEN_PREFIX}{token}"))
    except Exception as exc:
        logger.error("Token 吊销失败(Redis 异常): %s", exc)
        return False
