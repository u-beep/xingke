"""对象存储管理 (MinIO)。

冰箱食材原始图片通过 MinIO 持久化存储：
  - 上传：``upload_bytes(key, data, content_type)``
  - 读取：``get_object_bytes(key)`` 返回 (bytes, content_type)
  - 供路由 ``GET /api/v1/fridge/items/{id}/image`` 流式返回给前端

复用 docker-compose 中已有的 minio 服务 (默认 endpoint=localhost:9001，
凭据 minioadmin/minioadmin)，运行时惰性初始化并自动创建独立 bucket
``fridge-images``，与 Milvus 内部对同一 MinIO 实例的使用互不干扰。
"""

import io
import logging
import threading
from typing import Optional

from .config import (
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_SECURE, MINIO_BUCKET,
)

logger = logging.getLogger(__name__)

_minio_client = None
_minio_lock = threading.Lock()
_bucket_ensured = False


def get_minio_client():
    """获取 MinIO 客户端（惰性初始化，线程安全）。"""
    global _minio_client
    if _minio_client is not None:
        return _minio_client
    with _minio_lock:
        if _minio_client is not None:
            return _minio_client
        try:
            from minio import Minio
            _minio_client = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE,
            )
            logger.info("MinIO 客户端已创建: %s bucket=%s secure=%s",
                        MINIO_ENDPOINT, MINIO_BUCKET, MINIO_SECURE)
        except Exception as exc:
            logger.error("MinIO 客户端创建失败: %s", exc)
            raise
    return _minio_client


def ensure_bucket(bucket: str = MINIO_BUCKET) -> None:
    """确保 bucket 存在（幂等，仅首次执行 IO）。"""
    global _bucket_ensured
    if _bucket_ensured:
        return
    client = get_minio_client()
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("已创建 MinIO bucket: %s", bucket)
        _bucket_ensured = True
    except Exception as exc:
        logger.error("确保 MinIO bucket 失败: %s", exc)
        raise


def upload_bytes(
    key: str,
    data: bytes,
    content_type: str = "image/jpeg",
    bucket: str = MINIO_BUCKET,
) -> str:
    """上传字节数据到 MinIO，返回对象 key。

    Args:
        key: 对象 key，建议格式 ``fridge/{user_id}/{uuid}.jpg``
        data: 原始字节
        content_type: MIME 类型
    Returns:
        对象 key（供入库 image_object_key）
    """
    ensure_bucket(bucket)
    client = get_minio_client()
    try:
        client.put_object(
            bucket, key, io.BytesIO(data), length=len(data),
            content_type=content_type,
        )
        logger.info("已上传 MinIO 对象: %s/%s (%d bytes)", bucket, key, len(data))
        return key
    except Exception as exc:
        logger.error("上传 MinIO 对象失败: %s", exc)
        raise


def get_object_bytes(
    key: str,
    bucket: str = MINIO_BUCKET,
) -> tuple[bytes, str]:
    """读取 MinIO 对象，返回 (bytes, content_type)。"""
    client = get_minio_client()
    try:
        resp = client.get_object(bucket, key)
        try:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            return data, ctype
        finally:
            resp.close()
            resp.release_conn()
    except Exception as exc:
        logger.error("读取 MinIO 对象失败: %s/%s: %s", bucket, key, exc)
        raise


def object_exists(key: str, bucket: str = MINIO_BUCKET) -> bool:
    """判断对象是否存在。"""
    client = get_minio_client()
    try:
        return client.stat_object(bucket, key) is not None
    except Exception:
        return False


def health_check() -> dict:
    """检查 MinIO 连接状态。"""
    status = {"minio": "unknown"}
    try:
        ensure_bucket()
        status["minio"] = f"ok (bucket: {MINIO_BUCKET})"
    except Exception as e:
        status["minio"] = f"error: {e}"
    return status
