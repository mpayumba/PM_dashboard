"""End-to-end pipeline: raw export -> active, classified work orders.

Ties ingest -> parse -> classify into one call so the Streamlit app (and tests)
stay thin. Returns the cleaned frame plus a provenance/report bundle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from . import classify, ingest, parse
from .config import Config, load_config


@dataclass
class Dataset:
    df: pd.DataFrame                 # active, classified work orders
    mismatch: pd.DataFrame          # PM-origin rows whose title didn't classify
    source_path: str | None
    source_name: str | None
    source_modified: datetime | None
    report: dict                     # parse/coercion diagnostics
    config: Config


def build_dataset(config: Config | None = None) -> Dataset | None:
    """Load the latest raw export and run it through the full pipeline.

    Returns None when no CSV is present in data/raw/ (empty-state handling).
    """
    config = config or load_config()
    raw = ingest.load_latest(config=config)
    if raw is None:
        return None

    active, report = parse.process(raw.df, config)
    classified = classify.add_classification(active, config)
    mismatch = classify.origin_pm_mismatch(classified, config)

    return Dataset(
        df=classified,
        mismatch=mismatch,
        source_path=raw.path,
        source_name=raw.filename,
        source_modified=raw.modified,
        report=report,
        config=config,
    )
