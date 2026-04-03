"""Sync Status Tracker — records sync state per data source.

Singleton in-memory tracker. Each sync function reports its status here.
Health check reads from here to diagnose root causes.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    REPAIRING = "repairing"


@dataclass
class SyncRecord:
    table: str
    status: SyncStatus = SyncStatus.IDLE
    last_attempt: float = 0
    last_success: float = 0
    last_error: str = ""
    last_error_type: str = ""
    rows_synced: int = 0
    attempts: int = 0
    trade_date: str = ""

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "table": self.table,
            "status": self.status.value,
            "last_attempt_ago_sec": round(now - self.last_attempt) if self.last_attempt else None,
            "last_success_ago_sec": round(now - self.last_success) if self.last_success else None,
            "last_error": self.last_error,
            "last_error_type": self.last_error_type,
            "rows_synced": self.rows_synced,
            "attempts": self.attempts,
            "trade_date": self.trade_date,
        }


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into error_type and human-readable message."""
    msg = str(exc)
    etype = type(exc).__name__

    if "UndefinedColumn" in msg or "UndefinedColumn" in etype:
        col = ""
        if "column" in msg and "does not exist" in msg:
            parts = msg.split('"')
            if len(parts) >= 2:
                col = parts[1]
        return "schema_mismatch", f"数据库缺少字段 {col}" if col else "数据库表结构与API返回不匹配"

    if "StringDataRightTruncation" in msg or "太长" in msg:
        return "schema_mismatch", "字段长度不够，需要ALTER TABLE扩容"

    if "UniqueViolation" in msg or "重复键" in msg:
        return "duplicate", "数据已存在(重复键)，跳过"

    if "CheckViolation" in msg or "没有为行找到" in msg:
        return "partition_missing", "分区表缺少对应月份分区"

    if "ConnectionRefused" in msg or "connection" in msg.lower():
        return "connection_error", "数据库连接失败"

    if "rate" in msg.lower() or "频次" in msg:
        return "rate_limit", "Tushare API频次超限，需等待"

    if "timeout" in msg.lower() or "Timeout" in etype:
        return "timeout", "请求超时"

    return "unknown", msg[:200]


class SyncTracker:
    """Thread-safe singleton tracking sync status for all data sources."""

    def __init__(self):
        self._records: dict[str, SyncRecord] = {}
        self._lock = threading.Lock()
        self._repair_running = False

    def begin(self, table: str, trade_date: str = ""):
        with self._lock:
            rec = self._records.setdefault(table, SyncRecord(table=table))
            rec.status = SyncStatus.SYNCING
            rec.last_attempt = time.time()
            rec.trade_date = trade_date
            rec.attempts += 1

    def success(self, table: str, rows: int = 0):
        with self._lock:
            rec = self._records.setdefault(table, SyncRecord(table=table))
            rec.status = SyncStatus.SUCCESS
            rec.last_success = time.time()
            rec.rows_synced = rows
            rec.last_error = ""
            rec.last_error_type = ""

    def fail(self, table: str, exc: Exception):
        with self._lock:
            rec = self._records.setdefault(table, SyncRecord(table=table))
            rec.status = SyncStatus.FAILED
            etype, msg = _classify_error(exc)
            rec.last_error = msg
            rec.last_error_type = etype
            logger.warning("sync_tracker: %s failed (%s): %s", table, etype, msg)

    def begin_repair(self, table: str):
        with self._lock:
            rec = self._records.setdefault(table, SyncRecord(table=table))
            rec.status = SyncStatus.REPAIRING

    def get(self, table: str) -> SyncRecord | None:
        with self._lock:
            return self._records.get(table)

    def get_all(self) -> dict[str, dict]:
        with self._lock:
            return {k: v.to_dict() for k, v in self._records.items()}

    def is_any_syncing(self) -> bool:
        with self._lock:
            return any(r.status in (SyncStatus.SYNCING, SyncStatus.REPAIRING) for r in self._records.values())

    @property
    def repair_running(self) -> bool:
        return self._repair_running

    @repair_running.setter
    def repair_running(self, val: bool):
        self._repair_running = val

    def recently_repaired(self, table: str, cooldown_sec: float = 300) -> bool:
        """Check if this table was attempted within cooldown period."""
        with self._lock:
            rec = self._records.get(table)
            if not rec or rec.last_attempt == 0:
                return False
            return (time.time() - rec.last_attempt) < cooldown_sec


sync_tracker = SyncTracker()
