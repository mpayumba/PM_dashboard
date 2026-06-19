"""PM vs PM-ME classification.

Rules (order-sensitive, case-insensitive, word-boundary regex), validated
against the real export titles in Phase 2:

    is_mechatronics_pm = title matches me_pattern   (\\bPM-ME\\b)
    is_maintenance_pm  = title matches pm_pattern (\\bPM\\b) AND NOT mechatronics
    is_pm              = is_mechatronics_pm OR is_maintenance_pm
    pm_stream          = {Mechatronics, Maintenance, Non-PM}

Word boundaries keep "EQUIPMENT", "PUMP", "RPM", "PPM", "PMP" out, and the
AND-NOT ordering guarantees a PM-ME row is never also counted as Maintenance.
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .config import Config

STREAM_MECHATRONICS = "Mechatronics"
STREAM_MAINTENANCE = "Maintenance"
STREAM_NON_PM = "Non-PM"
STREAM_ORDER = (STREAM_MAINTENANCE, STREAM_MECHATRONICS, STREAM_NON_PM)


def add_classification(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Add is_mechatronics_pm, is_maintenance_pm, is_pm and pm_stream columns."""
    out = df.copy()
    titles = out[C.TITLE].fillna("").astype(str) if C.TITLE in out.columns else pd.Series("", index=out.index)

    is_me = titles.str.contains(config.me_regex)
    is_pm_any = titles.str.contains(config.pm_regex)
    is_maint = is_pm_any & ~is_me

    out["is_mechatronics_pm"] = is_me
    out["is_maintenance_pm"] = is_maint
    out["is_pm"] = is_me | is_maint

    stream = pd.Series(STREAM_NON_PM, index=out.index, dtype="object")
    stream[is_maint] = STREAM_MAINTENANCE
    stream[is_me] = STREAM_MECHATRONICS
    out["pm_stream"] = pd.Categorical(stream, categories=list(STREAM_ORDER))

    return out


def origin_pm_mismatch(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Rows the CMMS marks as PM-origin but whose title did not classify as PM.

    These are surfaced (not dropped, not reclassified) as data-quality items —
    typically title typos like "MonthlyPM" or titles missing the PM token.
    Returns an empty frame when the check is disabled or origin is unavailable.
    """
    if not config.flag_origin_pm_mismatch or C.ORIGIN not in df.columns:
        return df.iloc[0:0]
    origin = df[C.ORIGIN].astype(str).str.strip().str.upper()
    is_pm_origin = origin == config.origin_pm_value.strip().upper()
    return df[is_pm_origin & ~df["is_pm"]].copy()
