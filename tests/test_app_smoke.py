"""Headless smoke test: run app.py end-to-end via Streamlit's AppTest.

Skipped automatically when streamlit isn't installed (e.g. a bare test env), so
the rest of the suite still runs. Requires a CSV in data/raw/ to exercise the
populated path; otherwise it asserts the empty-state renders without error.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ingest import find_latest_csv  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_runs_without_exception():
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"


@pytest.mark.skipif(find_latest_csv() is None, reason="no CSV in data/raw/")
def test_app_renders_kpis_with_data():
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    # KPI row + secondary row = at least 9 st.metric widgets.
    assert len(at.metric) >= 9
    labels = {m.label for m in at.metric}
    assert {"Active PMs", "Maintenance", "Mechatronics", "Overdue"} <= labels
    # The detail table renders at least one dataframe.
    assert len(at.dataframe) >= 1
