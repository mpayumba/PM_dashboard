"""Locate and load the latest raw CSV export from data/raw/.

Mode A (manual export) is the authoritative ingestion path: a human drops a CSV
exported from Asset Essentials (More -> Export) into data/raw/, and this module
picks up the most recent one by modification time.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .config import Config, load_config

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")


@dataclass(frozen=True)
class RawExport:
    """A loaded raw export plus provenance for display in the UI."""

    df: pd.DataFrame
    path: str
    modified: datetime

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)


def find_latest_csv(raw_dir: str = RAW_DIR) -> str | None:
    """Return the path to the most recently modified CSV in raw_dir, or None."""
    candidates = glob.glob(os.path.join(raw_dir, "*.csv"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def load_latest(raw_dir: str = RAW_DIR, config: Config | None = None) -> RawExport | None:
    """Load the latest raw CSV as strings (no type inference yet).

    Returns None when no CSV is present so callers can render an empty state.
    Everything is read as str with keep_default_na=False so that downstream
    parsing controls type coercion explicitly and empty cells stay as "".
    """
    config = config or load_config()
    path = find_latest_csv(raw_dir)
    if path is None:
        return None
    df = pd.read_csv(path, encoding=config.encoding, dtype=str, keep_default_na=False)
    modified = datetime.fromtimestamp(os.path.getmtime(path))
    return RawExport(df=df, path=path, modified=modified)
