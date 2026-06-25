"""Type coercion, date parsing, cleaning, and active-status filtering.

Pipeline: raw export (all strings) -> canonical columns -> typed/cleaned ->
filtered to active (status 040). Pure functions so each step is unit-testable.
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .config import Config

# Known Asset Essentials timestamp format, e.g. "06/17/2026 4:05:00 AM".
# We try this first (fast, unambiguous) and fall back to dateutil for anything
# that doesn't match, so other export date formats still parse.
_KNOWN_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def to_canonical(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Build a frame keyed by canonical column names.

    Only canonical columns that are mapped AND present in the export appear in
    the result, so downstream code never touches raw headers. A canonical
    column mapped to a header that is missing from the file is skipped (and the
    caller can detect the gap via Config.has vs the result's columns).
    """
    out = pd.DataFrame(index=df.index)
    for canonical, header in config.columns.items():
        if header in df.columns:
            out[canonical] = df[header]
    return out


def _parse_dates(series: pd.Series) -> pd.Series:
    """Coerce a string series to datetime; unparseable values become NaT."""
    s = series.replace("", pd.NA)
    parsed = pd.to_datetime(s, format=_KNOWN_DATE_FORMAT, errors="coerce")
    # Retry the ones the strict format missed, using flexible parsing.
    missing = parsed.isna() & s.notna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(s[missing], errors="coerce")
    return parsed


def coerce_types(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Strip strings, parse date columns, and normalize the title.

    Returns the cleaned frame and a small report dict describing how many date
    values failed to parse per column (so callers can log/surface it).
    """
    out = df.copy()
    report: dict = {"date_parse_failures": {}}

    # Preserve the title EXACTLY as exported before any stripping.
    raw_title = out[C.TITLE].copy() if C.TITLE in out.columns else None

    # Strip whitespace on all string columns. Detect both the classic `object`
    # dtype (pandas <3.0) and the new default `str` dtype (pandas >=3.0); a bare
    # `dtype == object` check silently skips string columns on pandas 3.x. Only
    # strip non-missing cells so real NA/NaN is preserved (not turned into "nan").
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            mask = out[col].notna()
            out.loc[mask, col] = out.loc[mask, col].astype(str).str.strip()

    # Re-attach the untouched original alongside the normalized (stripped) title.
    if raw_title is not None:
        out[C.TITLE + "_raw"] = raw_title

    # Coerce date columns; record parse failures (missing-aware so pre-existing
    # NA/NaT/blank cells are treated as empty, not as parse failures).
    for col in C.DATE_COLUMNS:
        if col in out.columns:
            s = out[col].astype("string").str.strip()
            empty = s.isna() | (s == "") | s.str.lower().isin(["nan", "nat", "none", "<na>"])
            parsed = _parse_dates(out[col])
            report["date_parse_failures"][col] = int((parsed.isna() & ~empty).sum())
            out[col] = parsed

    return out, report


def filter_active(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Keep only rows whose status matches the active code (e.g. 040).

    Tolerant of representation: matches on the leading integer code so that
    "040", "40", "040 SCHEDULED", and "40 - Scheduled" all count as active.
    If the status column is absent, the frame is returned unchanged (the saved
    view is assumed to have pre-filtered).
    """
    if C.STATUS not in df.columns:
        return df
    target = config.active_status_code()
    leading = df[C.STATUS].astype(str).str.extract(r"\s*(\d+)", expand=False)
    code = pd.to_numeric(leading, errors="coerce")
    return df[code == target].copy()


def process(df: pd.DataFrame, config: Config) -> tuple[pd.DataFrame, dict]:
    """Full parse step: canonical -> typed -> active-filtered."""
    canonical = to_canonical(df, config)
    typed, report = coerce_types(canonical)
    before = len(typed)
    active = filter_active(typed, config)
    report["rows_total"] = before
    report["rows_active"] = len(active)
    report["rows_dropped_inactive"] = before - len(active)
    return active.reset_index(drop=True), report
