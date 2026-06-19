"""Metrics tests — counts, overdue logic, aging buckets, breakdowns."""
from __future__ import annotations

import pandas as pd

from src import config as C
from src import metrics
from src.classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS, STREAM_NON_PM


def _frame():
    """Classified active frame with due dates relative to 2026-06-19."""
    rows = [
        # (title-derived) stream, is_pm, due_date, asset
        (STREAM_MAINTENANCE, True, "2026-06-15", "Station A"),   # overdue (-4)
        (STREAM_MAINTENANCE, True, "2026-06-19", "Station A"),   # due today (0)
        (STREAM_MECHATRONICS, True, "2026-06-22", "Unit 1"),    # 0-7 (+3)
        (STREAM_MECHATRONICS, True, "2026-07-09", "Unit 1"),    # 8-30 (+20)
        (STREAM_MAINTENANCE, True, "2026-07-29", "Press 1"),    # 31+ (+40)
        (STREAM_MECHATRONICS, True, None, "Lift 1"),            # no due date
        (STREAM_NON_PM, False, "2026-06-10", ""),               # non-PM, ignored
    ]
    df = pd.DataFrame(rows, columns=["pm_stream", "is_pm", C.DUE_DATE, C.ASSET])
    df[C.DUE_DATE] = pd.to_datetime(df[C.DUE_DATE])
    df[C.CREATED_DATE] = pd.to_datetime("2026-06-01")
    return df


def test_kpi_summary(reference_today):
    k = metrics.kpi_summary(_frame(), reference_today)
    assert k["total_active"] == 7
    assert k["total_pm"] == 6
    assert k["maintenance"] == 3
    assert k["mechatronics"] == 3
    assert k["non_pm"] == 1
    assert k["overdue"] == 1               # only the 2026-06-15 PM row
    assert k["overdue_pct"] == round(100 / 6, 1)
    assert k["due_today"] == 1
    assert k["due_this_week"] == 2          # today(0) + (+3); +20/+40 excluded
    assert k["due_this_month"] == 3         # 0, +3, +20


def test_overdue_ignores_non_pm(reference_today):
    # The non-PM row is overdue (2026-06-10) but must not count.
    k = metrics.kpi_summary(_frame(), reference_today)
    assert k["overdue"] == 1


def test_due_window_counts(reference_today):
    w = metrics.due_window_counts(_frame(), reference_today)
    assert w == {"overdue": 1, "due_today": 1, "due_this_week": 2, "due_this_month": 3, "no_due_date": 1}


def test_stream_counts(reference_today):
    sc = metrics.stream_counts(_frame())
    counts = dict(zip(sc["pm_stream"], sc["count"]))
    assert counts == {STREAM_MAINTENANCE: 3, STREAM_MECHATRONICS: 3}


def test_aging_buckets_partition(reference_today):
    ab = metrics.aging_buckets(_frame(), reference_today)
    total = ab["count"].sum()
    assert total == 6  # all PM rows accounted for, none dropped
    by_bucket = ab.groupby("bucket", observed=True)["count"].sum().to_dict()
    assert by_bucket[metrics.AGING_OVERDUE] == 1
    assert by_bucket[metrics.AGING_0_7] == 2     # due today + +3
    assert by_bucket[metrics.AGING_8_30] == 1
    assert by_bucket[metrics.AGING_30_PLUS] == 1
    assert by_bucket[metrics.AGING_NO_DATE] == 1


def test_count_by_asset_drops_blanks(reference_today):
    by_asset = metrics.count_by(_frame(), C.ASSET)
    assets = dict(zip(by_asset[C.ASSET], by_asset["count"]))
    assert assets["Station A"] == 2
    assert assets["Unit 1"] == 2
    assert "" not in assets  # blank asset (the non-PM row) excluded


def test_trend_by_week(reference_today):
    trend = metrics.trend_by_week(_frame(), reference_today)
    assert trend["count"].sum() == 6  # all PM rows have a created_date
    assert "week" in trend.columns


def test_empty_frame_is_safe(reference_today):
    empty = _frame().iloc[0:0]
    assert metrics.kpi_summary(empty, reference_today)["total_pm"] == 0
    assert metrics.stream_counts(empty).empty
    assert metrics.aging_buckets(empty, reference_today).empty
