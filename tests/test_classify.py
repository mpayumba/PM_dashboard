"""Classification tests — word-boundary PM / PM-ME, validated on real titles."""
from __future__ import annotations

import pandas as pd

from src.classify import (
    STREAM_MAINTENANCE,
    STREAM_MECHATRONICS,
    STREAM_NON_PM,
    add_classification,
    origin_pm_mismatch,
)


def _classify(titles, cfg):
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


def test_origin_mismatch_surfaces_pm_origin_nonclassified(cfg):
    df = pd.DataFrame(
        {
            "title": ["Loader 1 Monthly", "Station A Weekly PM"],
            "origin": ["PM", "PM"],
        }
    )
    classified = add_classification(df, cfg)
    mismatch = origin_pm_mismatch(classified, cfg)
    assert len(mismatch) == 1
    assert mismatch.iloc[0]["title"] == "Loader 1 Monthly"


def test_origin_mismatch_empty_without_origin_column(cfg):
    df = pd.DataFrame({"title": ["Loader 1 Monthly"]})
    classified = add_classification(df, cfg)
    assert origin_pm_mismatch(classified, cfg).empty
