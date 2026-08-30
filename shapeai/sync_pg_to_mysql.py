"""PostgreSQL -> MySQL 数据同步模块。

将 PostgreSQL 中的业务数据同步到 MySQL，
用于只读分析、报表查询、数据备份。

同步策略:
  1. 增量同步 -- 按 created_at 时间戳增量拉取
  2. 全量同步 -- 重新同步全表
  3. 定时同步 -- SyncScheduler 后台线程周期执行增量同步

使用:
  命令行:  python -m shapeai.sync_pg_to_mysql [--full]
  代码内:  from .sync_pg_to_mysql import SyncScheduler
           scheduler = SyncScheduler(interval=60)
           scheduler.start()   # 启动后台线程
           scheduler.stop()    # 停止
"""

import logging
import threading
import time
from datetime import datetime, timezone

from .database import pg_cursor, mysql_cursor
from .config import SYNC_ENABLED, SYNC_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

# 同步表配置: (pg_table, mysql_table, columns, has_created_at)
SYNC_TABLES = [
    {
        "pg_table": "users",
        "mysql_table": "users",
        "columns": ["id", "username", "password_hash", "nickname", "created_at", "updated_at", "last_login_at"],
        "pk": "id",
        "has_created_at": True,
    },
    {
        "pg_table": "sessions",
        "mysql_table": "sessions",
        "columns": ["id", "user_id", "created_at", "memory", "user_profile"],
        "pk": "id",
        "has_created_at": True,
    },
    {
        "pg_table": "messages",
        "mysql_table": "messages",
        "columns": ["id", "session_id", "role", "name", "args", "content", "is_retry", "created_at"],
        "pk": "id",
        "has_created_at": True,
    },
    {
        "pg_table": "usage_records",
        "mysql_table": "usage_records",
        "columns": ["id", "user_id", "endpoint", "scene", "model", "input_tokens", "output_tokens", "total_tokens", "created_at"],
        "pk": "id",
        "has_created_at": True,
    },
    {
        "pg_table": "interception_logs",
        "mysql_table": "interception_logs",
        "columns": ["id", "side", "type", "reason", "text_preview", "created_at"],
        "pk": "id",
        "has_created_at": True,
    },
]


def _convert_row(row: tuple) -> tuple:
    """将 PostgreSQL 行中的 JSONB/datetime 转换为 MySQL 可序列化的值。"""
    import json as _json
    converted = []
    for val in row:
        if val is None:
            converted.append(None)
        elif hasattr(val, "isoformat"):
            converted.append(val.isoformat())
        elif isinstance(val, (dict, list)):
            converted.append(_json.dumps(val, ensure_ascii=False))
        else:
            converted.append(val)
    return tuple(converted)


def sync_table_full(table_config: dict) -> int:
    """全量同步一张表。

    从 PostgreSQL 读取全部行，REPLACE INTO 到 MySQL。
    """
    pg_table = table_config["pg_table"]
    mysql_table = table_config["mysql_table"]
    columns = table_config["columns"]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    mysql_sql = f"REPLACE INTO {mysql_table} ({col_list}) VALUES ({placeholders})"

    pg_sql = f"SELECT {col_list} FROM {pg_table} ORDER BY created_at ASC" if table_config.get("has_created_at") \
        else f"SELECT {col_list} FROM {pg_table}"

    with pg_cursor(commit=False) as pg_cur:
        pg_cur.execute(pg_sql)
        rows = pg_cur.fetchall()

    if not rows:
        logger.info("%s: 无数据", pg_table)
        return 0

    converted = [_convert_row(row) for row in rows]

    with mysql_cursor() as mysql_cur:
        mysql_cur.executemany(mysql_sql, converted)

    logger.info("%s -> %s: 同步 %d 行", pg_table, mysql_table, len(converted))
    return len(converted)


def sync_table_incremental(table_config: dict, since: str = None) -> int:
    """增量同步一张表。

    只同步 created_at > since 的行。
    """
    if not table_config.get("has_created_at"):
        return sync_table_full(table_config)

    pg_table = table_config["pg_table"]
    mysql_table = table_config["mysql_table"]
    columns = table_config["columns"]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    mysql_sql = f"REPLACE INTO {mysql_table} ({col_list}) VALUES ({placeholders})"

    # 查找 MySQL 中最新的 created_at
    if since is None:
        with mysql_cursor(commit=False) as mysql_cur:
            try:
                mysql_cur.execute(f"SELECT MAX(created_at) FROM {mysql_table}")
                result = mysql_cur.fetchone()
                since = result[0] if result and result[0] else "1970-01-01"
            except Exception:
                since = "1970-01-01"

    pg_sql = f"SELECT {col_list} FROM {pg_table} WHERE created_at > %s ORDER BY created_at ASC"

    with pg_cursor(commit=False) as pg_cur:
        pg_cur.execute(pg_sql, (since,))
        rows = pg_cur.fetchall()

    if not rows:
        logger.debug("%s: 增量同步无新数据 (since=%s)", pg_table, since)
        return 0

    converted = [_convert_row(row) for row in rows]

    with mysql_cursor() as mysql_cur:
        mysql_cur.executemany(mysql_sql, converted)

    logger.info("%s -> %s: 增量同步 %d 行 (since=%s)", pg_table, mysql_table, len(converted), since)
    return len(converted)


def sync_all(full: bool = False) -> dict:
    """同步所有表。

    Args:
        full: True=全量同步, False=增量同步
    Returns:
        {"total": int, "details": {table_name: row_count}}
    """
    mode_label = "全量" if full else "增量"
    logger.info("开始 %s 同步 PostgreSQL -> MySQL", mode_label)

    total = 0
    details = {}
    for table_config in SYNC_TABLES:
        table_name = table_config["pg_table"]
        try:
            if full:
                count = sync_table_full(table_config)
            else:
                count = sync_table_incremental(table_config)
            details[table_name] = count
            total += count
        except Exception as exc:
            logger.error("[%s] 同步失败: %s", table_name, exc)
            details[table_name] = -1

    logger.info("%s 同步完成, 共 %d 行", mode_label, total)
    return {"total": total, "details": details}


# ─── 定时同步调度器 ───


class SyncScheduler:
    """PostgreSQL -> MySQL 定时同步调度器。

    在后台线程中周期执行增量同步。
    线程安全，支持 start/stop。

    用法:
        scheduler = SyncScheduler(interval_seconds=60)
        scheduler.start()
        ...
        scheduler.stop()

    也可用作上下文管理器:
        with SyncScheduler(interval_seconds=60) as scheduler:
            # 应用运行期间自动同步
            ...
    """

    def __init__(
        self,
        interval_seconds: int | None = None,
        full_sync_on_start: bool = False,
    ):
        """
        Args:
            interval_seconds: 同步间隔(秒)，None 时读取配置 SYNC_INTERVAL_SECONDS
            full_sync_on_start: 首次启动时是否先做一次全量同步
        """
        self.interval = interval_seconds or SYNC_INTERVAL_SECONDS
        self._full_on_start = full_sync_on_start
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_sync: dict | None = None       # 最近一次同步结果
        self._last_sync_at: str | None = None     # 最近一次同步时间
        self._error_count = 0
        self._total_runs = 0

    # ─── 生命周期 ───

    def start(self):
        """启动后台同步线程。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("SyncScheduler 已在运行")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="pg-mysql-sync",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "SyncScheduler 已启动, 间隔=%ds, 全量首次=%s",
                self.interval, self._full_on_start,
            )

    def stop(self, timeout: float = 10.0):
        """停止后台同步线程。"""
        with self._lock:
            if self._thread is None:
                return
            self._stop_event.set()
            self._thread.join(timeout=timeout)
            self._thread = None
            logger.info("SyncScheduler 已停止 (总运行%d次, 错误%d次)", self._total_runs, self._error_count)

    # ─── 上下文管理器 ───

    def __enter__(self) -> "SyncScheduler":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    # ─── 状态查询 ───

    def get_status(self) -> dict:
        """获取调度器运行状态。"""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_seconds": self.interval,
            "total_runs": self._total_runs,
            "error_count": self._error_count,
            "last_sync_at": self._last_sync_at,
            "last_sync_result": self._last_sync,
        }

    # ─── 内部逻辑 ───

    def _run_loop(self):
        """后台线程主循环。"""
        # 首次启动时先做一次同步
        first_round = True
        while not self._stop_event.is_set():
            try:
                if first_round and self._full_on_start:
                    result = sync_all(full=True)
                else:
                    result = sync_all(full=False)

                self._last_sync = result
                self._last_sync_at = datetime.now(timezone.utc).isoformat()
                self._total_runs += 1
            except Exception as exc:
                self._error_count += 1
                self._total_runs += 1
                logger.error("定时同步异常: %s", exc)

            first_round = False

            # 等待 interval 或 stop 信号
            self._stop_event.wait(timeout=self.interval)


# ─── CLI ───


def _print_sync_result(result: dict, full: bool):
    """打印同步结果。"""
    mode = "全量" if full else "增量"
    print("=" * 60)
    print(f"  ShapeAI 数据同步 PostgreSQL -> MySQL ({mode})")
    print("=" * 60)
    for table, count in result["details"].items():
        if count < 0:
            print(f"  [FAIL] {table}: 同步失败")
        else:
            print(f"  [OK]   {table}: {count} 行")
    print(f"\n  同步完成! 共 {result['total']} 行")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    full_mode = "--full" in sys.argv
    result = sync_all(full=full_mode)
    _print_sync_result(result, full_mode)
