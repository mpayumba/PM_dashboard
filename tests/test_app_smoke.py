"""Headless smoke test: run app.py end-to-end via Streamlit's AppTest.

Skipped automatically when streamlit isn't installed (e.g. a bare test env). The
populated-path test seeds a small SANITIZED synthetic export into data/raw/ so it
runs deterministically in a clean checkout / CI (not dependent on a gitignored
real export), then removes it.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ingest import RAW_DIR  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

# Real export headers, synthetic values, exercising the Origin-based logic:
#   WO1/WO3 = Mechatronics (PM-ME), WO2 = Maintenance (PM), WO4 = Origin=PM but no
#   title token (Maintenance + data-quality flag), WO5 = Origin=Non-PM (excluded),
#   WO6 = 041 IN PROGRESS Non-PM (active but excluded).
_SYNTHETIC_CSV = (
    "Work Order #,Title,WO Status,Priority,Origin,Source Asset,Source User,Assigned,Expected\n"
    "WO1,Station A Monthly PM-ME,040 SCHEDULED,4 - High Priority,PM,Station A,Planner One,06/17/2026 4:05:00 AM,06/22/2026 11:59:00 PM\n"
    "WO2,Station B Weekly PM,040 SCHEDULED,5 - Medium,PM,Station B,Planner One,06/16/2026 4:05:00 AM,06/19/2026 11:59:00 PM\n"
    "WO3,Unit 1 Weekly PM-ME,040 SCHEDULED,4 - High Priority,PM,Unit 1,Planner One,06/15/2026 4:05:00 AM,06/12/2026 11:59:00 PM\n"
    "WO4,Loader 1 Monthly,040 SCHEDULED,5 - Medium,PM,Loader 1,Planner One,06/14/2026 4:05:00 AM,06/30/2026 11:59:00 PM\n"
    "WO5,Conveyor 1 - adjust guard,040 SCHEDULED,6 - Medium to Low,Non-PM,Conveyor 1,Planner Two,06/14/2026 8:00:00 AM,\n"
    "WO6,HMI password project,041 IN PROGRESS,4 - High Priority,Non-PM,,Planner Two,06/13/2026 9:00:00 AM,\n"
)


@pytest.fixture
def seeded_raw():
    """Write a synthetic export as the newest CSV in data/raw/, then remove it."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, "_smoke_synthetic.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_SYNTHETIC_CSV)
    os.utime(path, None)  # ensure it is the newest file (find_latest_csv picks by mtime)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_app_runs_without_exception(seeded_raw):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"


def test_app_renders_three_tabs_with_data(seeded_raw):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    # AppTest executes all tab bodies, so metrics/tables from all three appear.
    labels = {m.label for m in at.metric}
    assert {"Total PMs", "Late (overdue)", "Maintenance", "Mechatronics"} <= labels
    # one due-date table per tab (3) — at least 3 dataframes.
    assert len(at.dataframe) >= 3
