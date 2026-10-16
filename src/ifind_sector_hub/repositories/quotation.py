# -*- coding: utf-8 -*-
"""行情缓存仓储：不复权板块行情 + 覆盖台账 + 交易日历 + 后台补全任务表。

覆盖台账沿用 relation_snapshots 的"发布台账 + 零行元数据"模式：
quotation_coverage 以交易日为粒度记录已确认日期（complete=有数据，empty=负缓存：确认无数据），
缺失即无行——读路径据此对请求区间做减法，只向 iFinD 取缺失部分。
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

_DDL = """
CREATE TABLE IF NOT EXISTS quotation_daily (
    code          TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL, change_ratio REAL, pre_close REAL,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS quotation_minute (
    code       TEXT NOT NULL,
    bar_time   TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, change_ratio REAL,
    PRIMARY KEY (code, bar_time)
);

CREATE TABLE IF NOT EXISTS quotation_coverage (
    code        TEXT NOT NULL,
    freq        TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    state       TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (code, freq, trade_date)
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS fill_tasks (
    task_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL,
    freq       TEXT NOT NULL,
    d_start    TEXT NOT NULL,
    d_end      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fill_pending ON fill_tasks(status, code, freq);
"""

COVERAGE_COMPLETE = "complete"
COVERAGE_EMPTY = "empty"


class QuotationRepository:
    """行情域读写；与 SectorStore 共指同一 SQLite 库文件。"""

    def __init__(self, db_path: str, busy_timeout_ms: int = 5000):
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ========== 行情读写 ==========
    def upsert_daily_bars(self, bars: Iterable[Dict]) -> int:
        """幂等写入日频 bar（响应指标名由调用层给出，此处按位置映射存储列）。"""
        rows = [(b.get("code", ""), b["time"],
                 b.get("open"), b.get("high"), b.get("low"), b.get("close"),
                 b.get("volume"), b.get("amount"),
                 b.get("changeRatio"), b.get("preClose"))
                for b in bars]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO quotation_daily "
                "(code, trade_date, open, high, low, close, volume, amount, change_ratio, pre_close) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows)
        return len(rows)

    def upsert_minute_bars(self, bars: Iterable[Dict]) -> int:
        rows = [(b.get("code", ""), b["time"],
                 b.get("open"), b.get("high"), b.get("low"), b.get("close"),
                 b.get("volume"), b.get("changeRatio"))
                for b in bars]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO quotation_minute "
                "(code, bar_time, open, high, low, close, volume, change_ratio) "
                "VALUES (?,?,?,?,?,?,?,?)",
                rows)
        return len(rows)

    def read_daily_bars(self, code: str, start: str, end: str) -> List[Dict]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM quotation_daily WHERE code = ? AND trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date", (code, start, end))
            return [dict(r) for r in cursor.fetchall()]

    def read_minute_bars(self, code: str, start: str, end: str) -> List[Dict]:
        """start/end 为 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM'，按字典序即可正确区间。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM quotation_minute WHERE code = ? AND bar_time BETWEEN ? AND ? "
                "ORDER BY bar_time", (code, start, end))
            return [dict(r) for r in cursor.fetchall()]

    # ========== 覆盖台账 ==========
    def upsert_coverage(self, code: str, freq: str, dates: Iterable[str], state: str) -> int:
        assert state in (COVERAGE_COMPLETE, COVERAGE_EMPTY)
        now = datetime.now().isoformat(timespec="seconds")
        date_list = list(dates)
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO quotation_coverage (code, freq, trade_date, state, fetched_at) "
                "VALUES (?,?,?,?,?)",
                [(code, freq, d, state, now) for d in date_list])
        return len(date_list)

    def get_coverage(self, code: str, freq: str, start: str, end: str) -> Dict[str, str]:
        """已确认日期 → 状态（complete/empty 均算已确认；缺失即无行）。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT trade_date, state FROM quotation_coverage "
                "WHERE code = ? AND freq = ? AND trade_date BETWEEN ? AND ?",
                (code, freq, start, end))
            return {r["trade_date"]: r["state"] for r in cursor.fetchall()}

    # ========== 交易日历 ==========
    def seed_calendar(self, dates: Iterable[str]) -> int:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO trading_calendar (trade_date) VALUES (?)",
                [(d,) for d in dates])
            return conn.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0]

    def get_trading_dates(self, start: str, end: str) -> List[str]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT trade_date FROM trading_calendar WHERE trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date", (start, end))
            return [r["trade_date"] for r in cursor.fetchall()]

    def calendar_bounds(self) -> Tuple[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(trade_date), MAX(trade_date) FROM trading_calendar").fetchone()
        return (row[0] or "", row[1] or "")

    # ========== 后台补全任务 ==========
    def enqueue_fill(self, code: str, freq: str, d_start: str, d_end: str) -> Optional[int]:
        """投递补全任务；同 code+freq 存在 pending/running 任务则不重复投递，返回 None。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            dup = conn.execute(
                "SELECT 1 FROM fill_tasks WHERE code = ? AND freq = ? "
                "AND status IN ('pending','running') AND d_start <= ? AND d_end >= ? "
                "LIMIT 1", (code, freq, d_end, d_start)).fetchone()
            if dup:
                return None
            cur = conn.execute(
                "INSERT INTO fill_tasks (code, freq, d_start, d_end, status, created_at, updated_at) "
                "VALUES (?,?,?,?, 'pending', ?, ?)", (code, freq, d_start, d_end, now, now))
            return cur.lastrowid

    def claim_pending_tasks(self, limit: int = 10) -> List[Dict]:
        """取一批 pending 任务置为 running（任一进程/看板触发即恢复消费）。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fill_tasks WHERE status = 'pending' ORDER BY task_id LIMIT ?",
                (limit,)).fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE fill_tasks SET status='running', updated_at=? WHERE task_id=?",
                    (now, r["task_id"]))
        return [dict(r) for r in rows]

    def finish_task(self, task_id: int, status: str, error: str = None) -> None:
        assert status in ("done", "failed")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE fill_tasks SET status=?, attempts=attempts+1, last_error=?, updated_at=? "
                "WHERE task_id=?", (status, error, now, task_id))

    def list_tasks(self, status: str = None, limit: int = 100) -> List[Dict]:
        with self._connect() as conn:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM fill_tasks WHERE status = ? ORDER BY task_id DESC LIMIT ?",
                    (status, limit))
            else:
                cursor = conn.execute(
                    "SELECT * FROM fill_tasks ORDER BY task_id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
