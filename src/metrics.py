"""KPI / summary computations for the dashboard.

Every function is pure: it takes a DataFrame (already classified, with a
`pm_stream` / `is_pm` column) plus an explicit reference date, and returns a
scalar dict or a tidy DataFrame. The reference date is injected (never read from
the clock inside these functions) so results are deterministic and testable.

Date semantics (date-only comparisons, time-of-day ignored):
    overdue (late) : due_date <  today
    due_today      : due_date == today
    due_this_week  : today <= due_date <= today + 7 days
    due_this_month : today <= due_date <= today + 30 days
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS, STREAM_NON_PM

WEEK_DAYS = 7
MONTH_DAYS = 30


def days_until_due(df: pd.DataFrame, today: date) -> pd.Series:
    """Integer days from `today` to each row's due_date (NaN when no due date)."""
    if C.DUE_DATE not in df.columns:
        return pd.Series(np.nan, index=df.index)
    due = pd.to_datetime(df[C.DUE_DATE], errors="coerce").dt.normalize()
    return (due - pd.Timestamp(today)).dt.days


def _pm_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["is_pm"]] if "is_pm" in df.columns else df


def due_window_counts(df: pd.DataFrame, today: date) -> dict:
    """Overdue / due-today / due-this-week / due-this-month counts over PM rows."""
    pm = _pm_only(df)
    d = days_until_due(pm, today)
    return {
        "overdue": int((d < 0).sum()),
        "due_today": int((d == 0).sum()),
        "due_this_week": int(((d >= 0) & (d <= WEEK_DAYS)).sum()),
        "due_this_month": int(((d >= 0) & (d <= MONTH_DAYS)).sum()),
        "no_due_date": int(d.isna().sum()),
    }


def summary_stats(df: pd.DataFrame, today: date) -> dict:
    """Per-tab statistics over the PM rows of `df` (works on any stream subset).

    Returns total PMs, late (overdue) count, overdue %, and the due windows.
    """
    pm = _pm_only(df)
    total = int(len(pm))
    windows = due_window_counts(df, today)
    late = windows["overdue"]
    return {
        "total": total,
        "late": late,
        "overdue_pct": round(100.0 * late / total, 1) if total else 0.0,
        "due_today": windows["due_today"],
        "due_this_week": windows["due_this_week"],
        "due_this_month": windows["due_this_month"],
        "no_due_date": windows["no_due_date"],
    }


def kpi_summary(df: pd.DataFrame, today: date) -> dict:
    """Headline KPIs for the All-PMs tab, computed from the full classified frame."""
    stream = df["pm_stream"].astype(str) if "pm_stream" in df.columns else pd.Series(dtype=str)
    total_pm = int(df["is_pm"].sum()) if "is_pm" in df.columns else 0
    windows = due_window_counts(df, today)
    overdue = windows["overdue"]
    return {
        "total_active": int(len(df)),
        "total_pm": total_pm,
        "maintenance": int((stream == STREAM_MAINTENANCE).sum()),
        "mechatronics": int((stream == STREAM_MECHATRONICS).sum()),
        "non_pm": int((stream == STREAM_NON_PM).sum()),
        "overdue": overdue,
        "overdue_pct": round(100.0 * overdue / total_pm, 1) if total_pm else 0.0,
        "due_today": windows["due_today"],
        "due_this_week": windows["due_this_week"],
        "due_this_month": windows["due_this_month"],
    }


def stream_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Tidy [pm_stream, count] for the Maintenance vs Mechatronics split (PM rows)."""
    pm = _pm_only(df)
    if "pm_stream" not in pm.columns or pm.empty:
        return pd.DataFrame({"pm_stream": [], "count": []})
    counts = pm["pm_stream"].astype(str).value_counts()
    order = [STREAM_MAINTENANCE, STREAM_MECHATRONICS]
    counts = counts.reindex(order).dropna()
    return counts.rename_axis("pm_stream").reset_index(name="count")


def overdue_items(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """The late (overdue) PM rows with a `days_overdue` column, most-late first.

    A PM is late when its due_date is strictly before `today`. Rows with no due
    date are not late. Returns an empty frame (with a days_overdue column) when
    nothing is overdue.
    """
    pm = _pm_only(df).copy()
    if pm.empty or C.DUE_DATE not in pm.columns:
        out = pm.iloc[0:0].copy()
        out["days_overdue"] = pd.Series(dtype="int64")
        return out
    d = days_until_due(pm, today)
    late = pm[d < 0].copy()
    late["days_overdue"] = (-d[d < 0]).astype(int)
    return late.sort_values("days_overdue", ascending=False).reset_index(drop=True)


def by_due_date(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """All PM rows ordered by due date (soonest/most-overdue first, no-date last).

    Adds a `days_until_due` column (negative = overdue).
    """
    pm = _pm_only(df).copy()
    if pm.empty:
        pm["days_until_due"] = pd.Series(dtype="float64")
        return pm
    pm["days_until_due"] = days_until_due(pm, today)
    # Sort by due date when present; otherwise fall back to the (all-NaN) days
    # column so an export missing the due_date column degrades instead of crashing.
    sort_col = C.DUE_DATE if C.DUE_DATE in pm.columns else "days_until_due"
    return pm.sort_values(sort_col, ascending=True, na_position="last").reset_index(drop=True)
