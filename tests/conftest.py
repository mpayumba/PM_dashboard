"""Shared pytest fixtures and path setup."""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import pytest

# Make `src` importable when running `pytest` from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    """The real committed config (regexes + mapping)."""
    return load_config()


@pytest.fixture
def reference_today():
    """Fixed reference date so overdue/aging math is deterministic."""
    return date(2026, 6, 19)


# Titles modeled on the real export's PM-token PATTERNS (Phase 2 discovery) but
# SANITIZED — generic equipment names, no internal asset inventory or personnel.
# Each tricky pattern from the real data is preserved (PM-ME, glued "MonthlyPM",
# "Safety/PPM", cadence-only titles, calibrations) so the regex is still exercised.
REAL_TITLE_CASES = [
    ("Station A Monthly PM-ME", "Mechatronics"),
    ("Monthly Safety PM-ME for Zone 1", "Mechatronics"),
    ("Inspect Station 1 Weekly PM-ME", "Mechatronics"),
    ("Lift Unit 1 Annual PM-ME", "Mechatronics"),
    ("Tack & Adjust 1 Monthly PM", "Maintenance"),
    ("Buffer Unit 5 PM Quarterly", "Maintenance"),
    ("Press 1 (bottom) Weekly Vacuum PM", "Maintenance"),
    ("Grinder 1 Bi-Weekly PM", "Maintenance"),
    ("Conveyors PM Pre-Line Quarterly", "Maintenance"),
    # --- tricky negatives: substring 'PM' but NOT a PM token ---
    ("Safety/PPM Templates Annual Review", "Non-PM"),
    ("Backsheet Cutter 3 MonthlyPM", "Non-PM"),  # glued typo (missing space)
    ("Loader 1 Monthly", "Non-PM"),
    ("Analyzer 1 Annual Calibration", "Non-PM"),
    # --- synthetic negatives that must never match ---
    ("EQUIPMENT inspection", "Non-PM"),
    ("PUMP rebuild", "Non-PM"),
    ("RPM Sensor swap", "Non-PM"),
    ("PMP certification", "Non-PM"),
]


@pytest.fixture
def real_titles_df():
    titles = [t for t, _ in REAL_TITLE_CASES]
    expected = [s for _, s in REAL_TITLE_CASES]
    return pd.DataFrame({"title": titles, "_expected": expected})
