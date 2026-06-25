"""PM vs Non-PM classification, and the Maintenance / Mechatronics split.

PM vs Non-PM:
    classify_by == "origin"  ->  is_pm = (origin == origin_pm_value)   [authoritative]
    classify_by == "title"   ->  is_pm = title matches pm_pattern (\\bPM\\b)
The export tags every work order "PM" or "Non-PM" in its Origin column, so Origin
is the reliable signal. If origin mode is selected but the export has no Origin
column, the code falls back to the title rule automatically.

Maintenance vs Mechatronics (within PMs) — title only:
    is_mechatronics_pm = is_pm AND title matches me_pattern (\\bPM-ME\\b)
    is_maintenance_pm  = is_pm AND NOT mechatronics
    pm_stream          = {Mechatronics, Maintenance, Non-PM}

Word boundaries keep "EQUIPMENT", "PUMP", "RPM", "PPM", "PMP" out of the title
rule, and the AND-NOT ordering guarantees a PM-ME row is never also Maintenance.
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .config import Config

STREAM_MECHATRONICS = "Mechatronics"
STREAM_MAINTENANCE = "Maintenance"
STREAM_NON_PM = "Non-PM"
STREAM_ORDER = (STREAM_MAINTENANCE, STREAM_MECHATRONICS, STREAM_NON_PM)


def _is_pm_series(df: pd.DataFrame, titles: pd.Series, config: Config) -> pd.Series:
    """PM membership per row: Origin-based when available, else title-based."""
    if config.classify_by == "origin" and C.ORIGIN in df.columns:
        origin = df[C.ORIGIN].fillna("").astype(str).str.strip().str.upper()
        return origin == config.origin_pm_value.strip().upper()
    return titles.str.contains(config.pm_regex)


def add_classification(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Add is_mechatronics_pm, is_maintenance_pm, is_pm and pm_stream columns."""
    out = df.copy()
    titles = out[C.TITLE].fillna("").astype(str) if C.TITLE in out.columns else pd.Series("", index=out.index)

    is_pm = _is_pm_series(out, titles, config)
    is_me = is_pm & titles.str.contains(config.me_regex)
    is_maint = is_pm & ~is_me

    out["is_mechatronics_pm"] = is_me
    out["is_maintenance_pm"] = is_maint
    out["is_pm"] = is_pm

    stream = pd.Series(STREAM_NON_PM, index=out.index, dtype="object")
    stream[is_maint] = STREAM_MAINTENANCE
    stream[is_me] = STREAM_MECHATRONICS
    out["pm_stream"] = pd.Categorical(stream, categories=list(STREAM_ORDER))

    return out


def pm_without_title_token(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """PMs whose title contains no `PM`/`PM-ME` token (classified via Origin only).

    Purely informational: these are correctly counted as Maintenance PMs, but their
    titles could be improved to include the PM token. Empty when classification is
    title-based (in that mode every PM by definition has a PM token).
    """
    if "is_pm" not in df.columns or C.TITLE not in df.columns:
        return df.iloc[0:0]
    titles = df[C.TITLE].fillna("").astype(str)
    has_token = titles.str.contains(config.pm_regex) | titles.str.contains(config.me_regex)
    return df[df["is_pm"] & ~has_token].copy()
