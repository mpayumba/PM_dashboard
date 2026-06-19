"""Snapshot history + shift-completion tracking (SQLite, stdlib only).

Every pull of the active work-order list is recorded as a timestamped snapshot.
Because the Asset Essentials export is filtered to ACTIVE work orders (status
040), a completed PM simply disappears from later pulls. So:

    completed during a shift = PM work orders observed in any snapshot within the
                               shift window that are NOT in the latest snapshot.

This "disappeared-from-active = completed" model is the agreed approach for an
active-only export. A work order can also leave the active list by being
cancelled/rescheduled, so the metric is labelled "closed" in the UI.

Storage: data/processed/pm_history.sqlite (gitignored). Timestamps are stored as
'YYYY-MM-DD HH:MM:SS' local strings, which sort chronologically as text.
"""
from __future__ import annotations

import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from . import config as C
from .classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS
from .shifts import Shift

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "pm_history.sqlite")
TS_FMT = "%Y-%m-%d %H:%M:%S"


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    # WAL + a generous busy timeout so the hourly launchd job and the in-app
    # "Pull"/"Re-read" buttons can touch the DB concurrently without "database
    # is locked" errors.
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
               snapshot_ts TEXT PRIMARY KEY,
               source_file TEXT,
               n_active    INTEGER,
               n_pm        INTEGER
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS items (
               snapshot_ts   TEXT,
               work_order_id TEXT,
               pm_stream     TEXT,
               is_pm         INTEGER,
               title         TEXT,
               due_date      TEXT,
               asset         TEXT
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_ts ON items(snapshot_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_wo ON items(work_order_id)")
    return conn


def record_snapshot(
    df: pd.DataFrame,
    source_file: str,
    ts: datetime | None = None,
    db_path: str = DB_PATH,
) -> bool:
    """Persist one snapshot of the active, classified work orders.

    Idempotent by source_file: re-recording the same export is a no-op, so the
    hourly job and the manual button can run freely without duplicating history.
    Returns True if a new snapshot was written, False if it was a duplicate.
    """
    ts = ts or datetime.now()
    ts_str = ts.strftime(TS_FMT)
    conn = _connect(db_path)
    try:
        if source_file:
            dup = conn.execute(
                "SELECT 1 FROM snapshots WHERE source_file = ? LIMIT 1", (source_file,)
            ).fetchone()
            if dup:
                return False

        # Guarantee a unique snapshot_ts: if a DIFFERENT source file already
        # occupies this wall-clock second, nudge forward rather than overwrite it
        # (snapshot_ts is the PRIMARY KEY at 1-second resolution).
        while conn.execute("SELECT 1 FROM snapshots WHERE snapshot_ts = ?", (ts_str,)).fetchone():
            ts = ts + timedelta(seconds=1)
            ts_str = ts.strftime(TS_FMT)

        def col(name):
            return df[name] if name in df.columns else pd.Series([None] * len(df), index=df.index)

        is_pm = df["is_pm"] if "is_pm" in df.columns else pd.Series(False, index=df.index)
        rows = []
        for wo, stream, pm, title, due, asset in zip(
            col(C.WORK_ORDER_ID).astype(str),
            df["pm_stream"].astype(str) if "pm_stream" in df.columns else ["" for _ in range(len(df))],
            is_pm.astype(bool),
            col(C.TITLE + "_raw" if (C.TITLE + "_raw") in df.columns else C.TITLE).astype(str),
            col(C.DUE_DATE).astype(str),
            col(C.ASSET).astype(str),
        ):
            rows.append((ts_str, wo, stream, int(pm), title, due, asset))

        conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?)",
            (ts_str, source_file, len(df), int(is_pm.sum())),
        )
        conn.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        return True
    finally:
        conn.close()


@dataclass
class ShiftCompletion:
    shift: Shift
    available: bool = False
    completed_total: int = 0
    completed_by_stream: dict = field(default_factory=dict)
    remaining_active: int = 0
    scheduled_at_start: int = 0
    n_snapshots: int = 0
    first_ts: str | None = None
    last_ts: str | None = None

    @property
    def completion_rate(self) -> float:
        denom = self.completed_total + self.remaining_active
        return round(100.0 * self.completed_total / denom, 1) if denom else 0.0


def shift_completion(
    shift: Shift, as_of: datetime | None = None, db_path: str = DB_PATH
) -> ShiftCompletion:
    """Compute PMs closed during `shift` from the snapshot history."""
    as_of = as_of or datetime.now()
    # Half-open window [shift.start, shift.end) capped at `as_of`, matching
    # Shift.contains. A snapshot at exactly shift.end belongs to the NEXT shift,
    # so it is never counted in both adjacent shifts.
    start_s = shift.start.strftime(TS_FMT)
    end_excl_s = shift.end.strftime(TS_FMT)
    now_s = as_of.strftime(TS_FMT)

    conn = _connect(db_path)
    try:
        ts_rows = conn.execute(
            "SELECT snapshot_ts FROM snapshots "
            "WHERE snapshot_ts >= ? AND snapshot_ts < ? AND snapshot_ts <= ? ORDER BY snapshot_ts",
            (start_s, end_excl_s, now_s),
        ).fetchall()
        ts_list = [r[0] for r in ts_rows]
        if not ts_list:
            return ShiftCompletion(shift=shift, available=False)

        baseline_ts, latest_ts = ts_list[0], ts_list[-1]

        scheduled = {
            r[0]
            for r in conn.execute(
                "SELECT work_order_id FROM items WHERE snapshot_ts = ? AND is_pm = 1",
                (baseline_ts,),
            )
        }
        active_now = {
            r[0]
            for r in conn.execute(
                "SELECT work_order_id FROM items WHERE snapshot_ts = ? AND is_pm = 1",
                (latest_ts,),
            )
        }
        # Every PM WO seen during the window, with its (last-seen) stream.
        observed: dict = {}
        for wo, stream in conn.execute(
            "SELECT work_order_id, pm_stream FROM items "
            "WHERE is_pm = 1 AND snapshot_ts >= ? AND snapshot_ts <= ? ORDER BY snapshot_ts",
            (baseline_ts, latest_ts),
        ):
            observed[wo] = stream

        completed_ids = set(observed) - active_now
        by_stream = Counter(observed[wo] for wo in completed_ids)
        return ShiftCompletion(
            shift=shift,
            available=True,
            completed_total=len(completed_ids),
            completed_by_stream={
                STREAM_MAINTENANCE: by_stream.get(STREAM_MAINTENANCE, 0),
                STREAM_MECHATRONICS: by_stream.get(STREAM_MECHATRONICS, 0),
            },
            remaining_active=len(active_now),
            scheduled_at_start=len(scheduled),
            n_snapshots=len(ts_list),
            first_ts=baseline_ts,
            last_ts=latest_ts,
        )
    finally:
        conn.close()


def recent_shift_completions(
    shifts: list[Shift], as_of: datetime | None = None, db_path: str = DB_PATH
) -> list[ShiftCompletion]:
    return [shift_completion(s, as_of=as_of, db_path=db_path) for s in shifts]


def latest_snapshot_meta(db_path: str = DB_PATH) -> tuple[str, str] | None:
    """(snapshot_ts, source_file) of the most recent snapshot, or None."""
    if not os.path.exists(db_path):
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT snapshot_ts, source_file FROM snapshots ORDER BY snapshot_ts DESC LIMIT 1"
        ).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()


def snapshot_count(db_path: str = DB_PATH) -> int:
    if not os.path.exists(db_path):
        return 0
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    finally:
        conn.close()
