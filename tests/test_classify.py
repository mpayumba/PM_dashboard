"""Classification tests — Origin-based PM/Non-PM + title PM-ME split.

The shared `cfg` fixture uses classify_by="origin", but frames WITHOUT an Origin
column fall back to the title rule (\\bPM\\b), so the title-based cases below still
exercise the fallback path.
"""
from __future__ import annotations

import pandas as pd

from src.classify import (
    STREAM_MAINTENANCE,
    STREAM_MECHATRONICS,
    STREAM_NON_PM,
    add_classification,
    pm_without_title_token,
)


def _classify(titles, cfg):
    # No 'origin' column -> falls back to the title rule.
    return add_classification(pd.DataFrame({"title": titles}), cfg)


def test_real_titles_map_to_expected_streams(real_titles_df, cfg):
    out = add_classification(real_titles_df, cfg)
    assert list(out["pm_stream"].astype(str)) == list(real_titles_df["_expected"])


def test_pm_me_is_mechatronics_not_maintenance(cfg):
    out = _classify(["Station A Monthly PM-ME"], cfg)
    assert bool(out["is_mechatronics_pm"].iloc[0]) is True
    assert bool(out["is_maintenance_pm"].iloc[0]) is False  # never double-counted
    assert bool(out["is_pm"].iloc[0]) is True
    assert out["pm_stream"].iloc[0] == STREAM_MECHATRONICS


def test_plain_pm_is_maintenance(cfg):
    out = _classify(["Station A Weekly PM"], cfg)
    assert bool(out["is_maintenance_pm"].iloc[0]) is True
    assert bool(out["is_mechatronics_pm"].iloc[0]) is False
    assert out["pm_stream"].iloc[0] == STREAM_MAINTENANCE


def test_equipment_and_acronyms_are_not_pm(cfg):
    # The classic trap: 'EQUIPMENT' contains the substring 'PM'.
    for title in ["EQUIPMENT inspection", "PUMP rebuild", "RPM Sensor swap", "PMP cert", "Safety/PPM Review"]:
        out = _classify([title], cfg)
        assert bool(out["is_pm"].iloc[0]) is False, title
        assert out["pm_stream"].iloc[0] == STREAM_NON_PM


def test_glued_typo_monthlypm_is_not_matched(cfg):
    # Documents a known limitation: a missing space defeats the \bPM\b boundary.
    out = _classify(["Backsheet Cutter 3 MonthlyPM"], cfg)
    assert bool(out["is_pm"].iloc[0]) is False


def test_case_insensitive(cfg):
    out = _classify(["station weekly pm", "weekly PM-me task"], cfg)
    assert out["pm_stream"].iloc[0] == STREAM_MAINTENANCE
    assert out["pm_stream"].iloc[1] == STREAM_MECHATRONICS


def test_no_pm_me_row_is_counted_as_maintenance(cfg):
    titles = [
        "Station A Monthly PM-ME",
        "Monthly Safety PM-ME for Zone 1",
        "Tack & Adjust 1 Monthly PM",
    ]
    out = add_classification(pd.DataFrame({"title": titles}), cfg)
    # Every mechatronics row must have is_maintenance_pm False.
    assert not (out["is_mechatronics_pm"] & out["is_maintenance_pm"]).any()


def test_counts_match_discovery(real_titles_df, cfg):
    out = add_classification(real_titles_df, cfg)
    vc = out["pm_stream"].astype(str).value_counts()
    assert vc.get(STREAM_MECHATRONICS, 0) == 4
    assert vc.get(STREAM_MAINTENANCE, 0) == 5
    assert vc.get(STREAM_NON_PM, 0) == 8


def test_origin_authoritative_includes_pm_without_title_token(cfg):
    # Origin == PM with no PM token in the title -> still a (Maintenance) PM.
    df = pd.DataFrame(
        {
            "title": ["Loader 1 Monthly", "Conveyor 1 - adjust guard"],
            "origin": ["PM", "Non-PM"],
        }
    )
    out = add_classification(df, cfg)
    assert bool(out["is_pm"].iloc[0]) is True
    assert out["pm_stream"].iloc[0] == STREAM_MAINTENANCE   # PM, no PM-ME -> Maintenance
    assert bool(out["is_pm"].iloc[1]) is False              # Origin Non-PM -> excluded
    assert out["pm_stream"].iloc[1] == STREAM_NON_PM


def test_origin_pm_me_title_is_mechatronics(cfg):
    df = pd.DataFrame({"title": ["Station A Monthly PM-ME"], "origin": ["PM"]})
    out = add_classification(df, cfg)
    assert out["pm_stream"].iloc[0] == STREAM_MECHATRONICS


def test_origin_non_pm_with_pm_token_title_is_excluded(cfg):
    # Even if a Non-PM row's title had a PM token, Origin wins in origin mode.
    df = pd.DataFrame({"title": ["Weekly PM cleanup task"], "origin": ["Non-PM"]})
    out = add_classification(df, cfg)
    assert bool(out["is_pm"].iloc[0]) is False
    assert out["pm_stream"].iloc[0] == STREAM_NON_PM


def test_pm_without_title_token_flags_origin_only_pms(cfg):
    df = pd.DataFrame(
        {
            "title": ["Loader 1 Monthly", "Station A Weekly PM", "Conveyor 1 - fix"],
            "origin": ["PM", "PM", "Non-PM"],
        }
    )
    classified = add_classification(df, cfg)
    q = pm_without_title_token(classified, cfg)
    assert len(q) == 1
    assert q.iloc[0]["title"] == "Loader 1 Monthly"
