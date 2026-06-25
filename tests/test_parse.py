"""Parsing tests — canonical rename, date coercion, active-status filtering."""
from __future__ import annotations

import pandas as pd

from src import config as C
from src.parse import coerce_types, filter_active, process, to_canonical


def _raw():
    """A raw frame using the REAL export headers but SANITIZED values."""
    return pd.DataFrame(
        {
            "Work Order #": ["WO1", "WO2", "WO3"],
            "Title": [" Station A Weekly PM ", "Loader 1 Monthly", "Unit 1 PM-ME"],
            "WO Status": ["040 SCHEDULED", "010 NEW", "040 SCHEDULED"],
            "Priority": ["4 - High Priority", "5 - Medium", "4 - High Priority"],
            "Origin": ["PM", "PM", "PM"],
            "Source Asset": ["Station A", "Loader 1", ""],
            "Source User": ["Planner One", "Planner One", "Planner One"],
            "Assigned": ["06/17/2026 4:05:00 AM", "06/16/2026 1:04:00 AM", "06/17/2026 4:05:00 AM"],
            "Expected": ["06/22/2026 11:59:00 PM", "", "06/19/2026 11:59:00 PM"],
        }
    )


def test_to_canonical_renames_and_drops_unmapped(cfg):
    out = to_canonical(_raw(), cfg)
    # canonical names present
    for col in [C.WORK_ORDER_ID, C.TITLE, C.STATUS, C.PRIORITY, C.ASSET,
                C.DUE_DATE, C.CREATED_DATE, C.ORIGIN, C.REQUESTED_BY]:
        assert col in out.columns
    # null-mapped canonical columns absent
    assert C.ASSIGNED_TO not in out.columns
    assert C.LOCATION not in out.columns
    # raw headers gone
    assert "Work Order #" not in out.columns


def test_coerce_types_parses_dates_and_strips_title(cfg):
    canon = to_canonical(_raw(), cfg)
    out, report = coerce_types(canon)
    assert pd.api.types.is_datetime64_any_dtype(out[C.DUE_DATE])
    assert pd.api.types.is_datetime64_any_dtype(out[C.CREATED_DATE])
    # empty Expected -> NaT, others parsed
    assert out[C.DUE_DATE].isna().sum() == 1
    assert out[C.DUE_DATE].iloc[0] == pd.Timestamp("2026-06-22 23:59:00")
    # title stripped, raw kept
    assert out[C.TITLE].iloc[0] == "Station A Weekly PM"
    assert out[C.TITLE + "_raw"].iloc[0] == " Station A Weekly PM "
    # date parse failures reported and zero (empty != failure)
    assert report["date_parse_failures"][C.DUE_DATE] == 0


def test_filter_active_keeps_only_040(cfg):
    canon = to_canonical(_raw(), cfg)
    typed, _ = coerce_types(canon)
    active = filter_active(typed, cfg)
    assert len(active) == 2
    assert set(active[C.WORK_ORDER_ID]) == {"WO1", "WO3"}


def test_filter_active_tolerant_of_status_representations(cfg):
    df = pd.DataFrame({C.STATUS: ["040 SCHEDULED", "40 - Scheduled", "040", "050 COMPLETE", "10 NEW"]})
    active = filter_active(df, cfg)
    assert len(active) == 3  # first three are code 40


def test_filter_active_includes_041_in_progress(cfg):
    df = pd.DataFrame({C.STATUS: ["040 SCHEDULED", "041 IN PROGRESS", "050 COMPLETE"]})
    active = filter_active(df, cfg)
    assert len(active) == 2  # 040 + 041 are open; 050 (complete) dropped


def test_process_end_to_end(cfg):
    out, report = process(_raw(), cfg)
    assert report["rows_total"] == 3
    assert report["rows_active"] == 2
    assert report["rows_dropped_inactive"] == 1
    assert len(out) == 2
