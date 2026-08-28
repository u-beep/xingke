"""数据库连接管理中枢。

管理 PostgreSQL、Redis、Milvus、MySQL 四个数据库的连接池。
所有 Store 类通过此模块获取连接。

架构:
  PostgreSQL — 主数据库，存储会话/记忆/用量/安全日志
  Redis      — 短期记忆/Session 缓存/热数据
  Milvus     — 向量检索/知识库 Embedding
  MySQL      — 同步副本，只读分析/报表
"""

import logging
import threading
from contextlib import contextmanager
from typing import Optional

from .config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD,
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
    MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION,
    MYSQL_HOST, MYSQL_PORT, MYSQL_DB, MYSQL_USER, MYSQL_PASSWORD,
)

logger = logging.getLogger(__name__)

# ─── PostgreSQL 连接池 ───

_psycopg2_pool = None  # psycopg2.pool.ThreadedConnectionPool 实例
_pg_lock = threading.Lock()


def _get_pg_dsn() -> str:
    """构建 PostgreSQL 连接字符串。"""
    return (
        f"host={POSTGRES_HOST} port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} user={POSTGRES_USER} password={POSTGRES_PASSWORD}"
    )


def get_pg_pool():
    """获取 PostgreSQL 连接池（惰性初始化，线程安全）。"""
    global _psycopg2_pool
    if _psycopg2_pool is not None:
        return _psycopg2_pool
    with _pg_lock:
        if _psycopg2_pool is not None:
            return _psycopg2_pool
        try:
            from psycopg2 import pool as pg_pool
            _psycopg2_pool = pg_pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                dsn=_get_pg_dsn(),
            )
            logger.info("PostgreSQL 连接池已创建: %s:%d/%s", POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
        except Exception as exc:
            logger.error("PostgreSQL 连接池创建失败: %s", exc)
            raise
    return _psycopg2_pool


@contextmanager
def pg_cursor(commit: bool = True):
    """PostgreSQL 游标上下文管理器。

    自动从连接池获取连接、提交/回滚、归还连接。

    Args:
        commit: 是否在成功时自动提交事务
    Yields:
        psycopg2 cursor
    """
    pool = get_pg_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        pool.putconn(conn)


# ─── Redis 连接 ───

_redis_client = None
_redis_lock = threading.Lock()


def get_redis():
    """获取 Redis 客户端（惰性初始化，线程安全）。"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            import redis
            _redis_client = redis.ConnectionPool(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD or None,
                decode_responses=True,
                max_connections=20,
                protocol=2,  # 强制使用 RESP2，避免旧版 Redis 不支持 HELLO 命令
            )
            # 测试连接
            r = redis.Redis(connection_pool=_redis_client)
            r.ping()
            logger.info("Redis 连接已建立: %s:%d/%d", REDIS_HOST, REDIS_PORT, REDIS_DB)
        except Exception as exc:
            logger.error("Redis 连接失败: %s", exc)
            raise
    return _redis_client


def redis_client():
    """返回一个 Redis 客户端实例。"""
    import redis
    return redis.Redis(connection_pool=get_redis())


# ─── Milvus 连接 ───

_milvus_client = None
_milvus_lock = threading.Lock()


def get_milvus():
    """获取 Milvus 客户端（惰性初始化，线程安全）。"""
    global _milvus_client
    if _milvus_client is not None:
        return _milvus_client
    with _milvus_lock:
        if _milvus_client is not None:
            return _milvus_client
        try:
            from pymilvus import connections, utility
            alias = "default"
            connections.connect(
                alias=alias,
                host=MILVUS_HOST,
                port=str(MILVUS_PORT),
            )
            _milvus_client = alias
            logger.info("Milvus 连接已建立: %s:%d", MILVUS_HOST, MILVUS_PORT)
        except Exception as exc:
            logger.error("Milvus 连接失败: %s", exc)
            raise
    return _milvus_client


# ─── MySQL 连接 ───

_mysql_pool = None
_mysql_lock = threading.Lock()


def get_mysql_pool():
    """获取 MySQL 连接池（惰性初始化，线程安全）。"""
    global _mysql_pool
    if _mysql_pool is not None:
        return _mysql_pool
    with _mysql_lock:
        if _mysql_pool is not None:
            return _mysql_pool
        try:
            import pymysql
            from dbutils.pooled_db import PooledDB
            _mysql_pool = PooledDB(
                pymysql,
                maxconnections=10,
                mincached=2,
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                database=MYSQL_DB,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                charset="utf8mb4",
            )
            logger.info("MySQL 连接池已创建: %s:%d/%s", MYSQL_HOST, MYSQL_PORT, MYSQL_DB)
        except Exception as exc:
            logger.error("MySQL 连接池创建失败: %s", exc)
            raise
    return _mysql_pool


@contextmanager
def mysql_cursor(commit: bool = True):
    """MySQL 游标上下文管理器。"""
    pool = get_mysql_pool()
    conn = pool.connection()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


# ─── 健康检查 ───

def health_check() -> dict:
    """检查所有数据库连接状态。"""
    status = {"postgres": "unknown", "redis": "unknown", "milvus": "unknown", "mysql": "unknown"}

    # PostgreSQL
    try:
        with pg_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {e}"

    # Redis
    try:
        r = redis_client()
        r.ping()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {e}"

    # Milvus
    try:
        get_milvus()
        from pymilvus import utility
        collections = utility.list_collections()
        status["milvus"] = f"ok (collections: {len(collections)})"
    except Exception as e:
        status["milvus"] = f"error: {e}"

    # MySQL
    try:
        with mysql_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
        status["mysql"] = "ok"
    except Exception as e:
        status["mysql"] = f"error: {e}"

    return status
