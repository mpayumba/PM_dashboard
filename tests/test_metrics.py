"""Metrics tests — counts, overdue logic, per-tab stats, due-date ordering."""
from __future__ import annotations

from datetime import date

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


def test_summary_stats_over_full_pm_set(reference_today):
    s = metrics.summary_stats(_frame(), reference_today)
    assert s["total"] == 6          # PM rows only (non-PM excluded)
    assert s["late"] == 1
    assert s["overdue_pct"] == round(100 / 6, 1)
    assert s["due_this_week"] == 2


def test_summary_stats_on_stream_subset(reference_today):
    df = _frame()
    maint = df[(df["is_pm"]) & (df["pm_stream"].astype(str) == STREAM_MAINTENANCE)]
    s = metrics.summary_stats(maint, reference_today)
    assert s["total"] == 3          # 3 maintenance PMs
    assert s["late"] == 1           # the 2026-06-15 maintenance row


def test_by_due_date_orders_overdue_first_nodate_last(reference_today):
    ordered = metrics.by_due_date(_frame(), reference_today)
    assert len(ordered) == 6        # PM rows only
    assert "days_until_due" in ordered.columns
    assert ordered.iloc[0]["days_until_due"] == -4   # most overdue first
    # the no-due-date row sorts last
    assert pd.isna(ordered.iloc[-1][C.DUE_DATE])


def test_by_due_date_without_due_date_column(reference_today):
    # An export missing the due_date column must degrade, not crash.
    df = pd.DataFrame({"pm_stream": [STREAM_MAINTENANCE, STREAM_MECHATRONICS], "is_pm": [True, True]})
    out = metrics.by_due_date(df, reference_today)
    assert len(out) == 2
    assert out["days_until_due"].isna().all()


def test_overdue_items(reference_today):
    late = metrics.overdue_items(_frame(), reference_today)
    assert len(late) == 1                       # only the 2026-06-15 PM row
    assert late.iloc[0]["days_overdue"] == 4
    assert late.iloc[0]["pm_stream"] == STREAM_MAINTENANCE
    assert "days_overdue" in late.columns
    # non-PM overdue row (2026-06-10) must be excluded
    assert (late["pm_stream"].astype(str) != STREAM_NON_PM).all()


def test_overdue_items_sorted_most_late_first():
    today = date(2026, 6, 19)
    rows = [
        (STREAM_MAINTENANCE, True, "2026-06-17", "A"),  # 2 days late
        (STREAM_MECHATRONICS, True, "2026-06-10", "B"),  # 9 days late
        (STREAM_MAINTENANCE, True, "2026-06-18", "C"),  # 1 day late
    ]
    df = pd.DataFrame(rows, columns=["pm_stream", "is_pm", C.DUE_DATE, C.ASSET])
    df[C.DUE_DATE] = pd.to_datetime(df[C.DUE_DATE])
    late = metrics.overdue_items(df, today)
    assert list(late["days_overdue"]) == [9, 2, 1]


def test_overdue_items_empty_when_none_late():
    late = metrics.overdue_items(_frame(), date(2026, 1, 1))  # everything due later
    assert late.empty
    assert "days_overdue" in late.columns


def test_empty_frame_is_safe(reference_today):
    empty = _frame().iloc[0:0]
    assert metrics.kpi_summary(empty, reference_today)["total_pm"] == 0
    assert metrics.summary_stats(empty, reference_today)["total"] == 0
    assert metrics.stream_counts(empty).empty
    assert metrics.by_due_date(empty, reference_today).empty
