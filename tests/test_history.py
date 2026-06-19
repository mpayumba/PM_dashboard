"""Tests for the snapshot store and shift-completion ('disappeared = completed')."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS
from src.history import (
    latest_snapshot_meta,
    record_snapshot,
    shift_completion,
    snapshot_count,
)
from src.shifts import Shift, current_shift

DAY_SHIFT = Shift("Day", datetime(2026, 6, 19, 5, 0), datetime(2026, 6, 19, 17, 0))


def _snap(items):
    """items: list of (work_order_id, pm_stream, is_pm)."""
    return pd.DataFrame(
        {
            "work_order_id": [i[0] for i in items],
            "pm_stream": [i[1] for i in items],
            "is_pm": [i[2] for i in items],
            "title": [f"{i[0]} title" for i in items],
            "due_date": ["" for _ in items],
            "asset": ["" for _ in items],
        }
    )


def _seed(db):
    M, E = STREAM_MAINTENANCE, STREAM_MECHATRONICS
    # 05:00 baseline: A,B,C,D scheduled
    record_snapshot(_snap([("A", M, True), ("B", E, True), ("C", M, True), ("D", E, True)]),
                    source_file="f0500.csv", ts=datetime(2026, 6, 19, 5, 0), db_path=db)
    # 11:00: B completed (gone); E appears mid-shift
    record_snapshot(_snap([("A", M, True), ("C", M, True), ("D", E, True), ("E", E, True)]),
                    source_file="f1100.csv", ts=datetime(2026, 6, 19, 11, 0), db_path=db)
    # 15:00: C and E completed (gone); A,D remain
    record_snapshot(_snap([("A", M, True), ("D", E, True)]),
                    source_file="f1500.csv", ts=datetime(2026, 6, 19, 15, 0), db_path=db)


def test_disappeared_equals_completed(tmp_path):
    db = str(tmp_path / "h.sqlite")
    _seed(db)
    sc = shift_completion(DAY_SHIFT, as_of=datetime(2026, 6, 19, 15, 30), db_path=db)
    assert sc.available
    assert sc.scheduled_at_start == 4          # A,B,C,D at 05:00
    assert sc.remaining_active == 2            # A,D at 15:00
    assert sc.completed_total == 3             # B, C, E left the active list
    assert sc.completed_by_stream == {STREAM_MAINTENANCE: 1, STREAM_MECHATRONICS: 2}
    assert sc.n_snapshots == 3
    assert sc.completion_rate == 60.0          # 3 / (3 + 2)


def test_no_snapshots_means_unavailable(tmp_path):
    db = str(tmp_path / "h.sqlite")
    sc = shift_completion(DAY_SHIFT, as_of=datetime(2026, 6, 19, 15, 30), db_path=db)
    assert not sc.available
    assert sc.completed_total == 0


def test_record_snapshot_is_idempotent_by_source_file(tmp_path):
    db = str(tmp_path / "h.sqlite")
    df = _snap([("A", STREAM_MAINTENANCE, True)])
    assert record_snapshot(df, source_file="same.csv", ts=datetime(2026, 6, 19, 6, 0), db_path=db) is True
    assert record_snapshot(df, source_file="same.csv", ts=datetime(2026, 6, 19, 7, 0), db_path=db) is False
    assert snapshot_count(db) == 1


def test_completion_window_caps_at_shift_end(tmp_path):
    db = str(tmp_path / "h.sqlite")
    _seed(db)
    # A snapshot in the NEXT (night) shift must not affect the day-shift count.
    record_snapshot(_snap([("A", STREAM_MAINTENANCE, True)]),
                    source_file="f1800.csv", ts=datetime(2026, 6, 19, 18, 0), db_path=db)
    sc = shift_completion(DAY_SHIFT, as_of=datetime(2026, 6, 19, 23, 0), db_path=db)
    assert sc.last_ts == "2026-06-19 15:00:00"   # capped at shift end, ignores 18:00
    assert sc.completed_total == 3


def test_shift_end_boundary_snapshot_excluded(tmp_path):
    db = str(tmp_path / "h.sqlite")
    _seed(db)
    # A snapshot at EXACTLY 17:00:00 (shift end) belongs to the next shift, not Day.
    record_snapshot(_snap([("A", STREAM_MAINTENANCE, True), ("D", STREAM_MECHATRONICS, True)]),
                    source_file="f1700.csv", ts=datetime(2026, 6, 19, 17, 0), db_path=db)
    sc = shift_completion(DAY_SHIFT, as_of=datetime(2026, 6, 19, 23, 0), db_path=db)
    assert sc.last_ts == "2026-06-19 15:00:00"   # 17:00:00 excluded (half-open window)
    assert sc.completed_total == 3


def test_same_second_distinct_files_do_not_collide(tmp_path):
    db = str(tmp_path / "h.sqlite")
    ts = datetime(2026, 6, 19, 6, 0, 0)
    assert record_snapshot(_snap([("A", STREAM_MAINTENANCE, True)]), source_file="a.csv", ts=ts, db_path=db) is True
    # Same wall-clock second, DIFFERENT file: must be recorded, not overwritten.
    assert record_snapshot(_snap([("B", STREAM_MECHATRONICS, True)]), source_file="b.csv", ts=ts, db_path=db) is True
    assert snapshot_count(db) == 2


def test_latest_snapshot_meta(tmp_path):
    db = str(tmp_path / "h.sqlite")
    _seed(db)
    ts, src = latest_snapshot_meta(db)
    assert ts == "2026-06-19 15:00:00"
    assert src == "f1500.csv"
