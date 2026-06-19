"""KPI and breakdown computations.

Every function is pure: it takes a DataFrame (already classified, with a
`pm_stream` / `is_pm` column) plus an explicit reference date, and returns a
scalar dict or a tidy DataFrame ready to chart. The reference date is injected
(never read from the clock inside these functions) so results are deterministic
and unit-testable.

Date semantics (all comparisons are date-only, time-of-day ignored). A single set
of boundary constants (WEEK_DAYS=7, MONTH_DAYS=30) is shared by the KPI windows
AND the aging buckets so the headline cards and the aging chart can never drift:
    overdue        : due_date  <  today
    due_today      : due_date ==  today
    due_this_week  : today <= due_date <= today + 7 days   (matches "Due 0-7 days" bucket)
    due_this_month : today <= due_date <= today + 30 days  (matches "Due 0-7" + "Due 8-30")
The week/month windows are forward-looking and nested; overdue is separate.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS, STREAM_NON_PM

# Shared boundary constants — used by BOTH due_window_counts and the aging
# buckets so the KPI cards and the aging chart always agree on the same edges.
WEEK_DAYS = 7
MONTH_DAYS = 30

# Aging buckets — mutually exclusive, ordered for charting.
AGING_OVERDUE = "Overdue"
AGING_0_7 = "Due 0–7 days"        # 0 <= d <= WEEK_DAYS
AGING_8_30 = "Due 8–30 days"      # WEEK_DAYS < d <= MONTH_DAYS
AGING_30_PLUS = "Due 31+ days"    # d > MONTH_DAYS
AGING_NO_DATE = "No due date"
AGING_ORDER = (AGING_OVERDUE, AGING_0_7, AGING_8_30, AGING_30_PLUS, AGING_NO_DATE)


def days_until_due(df: pd.DataFrame, today: date) -> pd.Series:
    """Integer days from `today` to each row's due_date (NaN when no due date)."""
    if C.DUE_DATE not in df.columns:
        return pd.Series(np.nan, index=df.index)
    due = pd.to_datetime(df[C.DUE_DATE], errors="coerce").dt.normalize()
    delta = (due - pd.Timestamp(today)).dt.days
    return delta


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


def kpi_summary(df: pd.DataFrame, today: date) -> dict:
    """Headline KPIs computed from the full active+classified frame."""
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


def aging_buckets(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Tidy [bucket, pm_stream, count] over PM rows, for a stacked bar chart."""
    pm = _pm_only(df).copy()
    if pm.empty:
        return pd.DataFrame({"bucket": [], "pm_stream": [], "count": []})
    d = days_until_due(pm, today)

    def bucketize(x):
        if pd.isna(x):
            return AGING_NO_DATE
        if x < 0:
            return AGING_OVERDUE
        if x <= WEEK_DAYS:
            return AGING_0_7
        if x <= MONTH_DAYS:
            return AGING_8_30
        return AGING_30_PLUS

    pm["bucket"] = pd.Categorical(d.map(bucketize), categories=list(AGING_ORDER))
    pm["pm_stream"] = pm["pm_stream"].astype(str)
    grouped = (
        pm.groupby(["bucket", "pm_stream"], observed=False)
        .size()
        .reset_index(name="count")
    )
    # Drop buckets that are entirely empty (e.g. "No due date" when all have dates).
    nonzero_buckets = grouped.groupby("bucket", observed=True)["count"].transform("sum") > 0
    return grouped[nonzero_buckets].reset_index(drop=True)


def count_by(df: pd.DataFrame, column: str, top_n: int | None = None) -> pd.DataFrame:
    """Tidy [<column>, count] over PM rows, descending, blanks dropped."""
    pm = _pm_only(df)
    if column not in pm.columns or pm.empty:
        return pd.DataFrame({column: [], "count": []})
    series = pm[column].astype(str).str.strip()
    series = series[(series != "") & (series.str.lower() != "nan")]
    counts = series.value_counts()
    if top_n:
        counts = counts.head(top_n)
    return counts.rename_axis(column).reset_index(name="count")


def trend_by_week(df: pd.DataFrame, today: date, date_col: str = C.CREATED_DATE) -> pd.DataFrame:
    """Tidy [week, pm_stream, count] of active PMs by week of `date_col`."""
    pm = _pm_only(df)
    if date_col not in pm.columns or pm.empty:
        return pd.DataFrame({"week": [], "pm_stream": [], "count": []})
    work = pm[[date_col, "pm_stream"]].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    if work.empty:
        return pd.DataFrame({"week": [], "pm_stream": [], "count": []})
    work["week"] = work[date_col].dt.to_period("W").dt.start_time
    work["pm_stream"] = work["pm_stream"].astype(str)
    return (
        work.groupby(["week", "pm_stream"], observed=True)
        .size()
        .reset_index(name="count")
        .sort_values("week")
        .reset_index(drop=True)
    )
