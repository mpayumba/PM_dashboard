"""End-to-end pipeline: raw CSV -> active, classified work orders.

Ties parse -> classify into one call so the Streamlit app (and tests) stay thin.
Data comes from a CSV the user inputs: either uploaded in the app, or the newest
file in data/raw/. Returns the cleaned frame plus a provenance/report bundle.
"""
from __future__ import annotations

import io
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


def _assemble(raw_df, source_name, source_path, source_modified, config) -> Dataset:
    active, report = parse.process(raw_df, config)
    classified = classify.add_classification(active, config)
    mismatch = classify.origin_pm_mismatch(classified, config)
    return Dataset(
        df=classified,
        mismatch=mismatch,
        source_path=source_path,
        source_name=source_name,
        source_modified=source_modified,
        report=report,
        config=config,
    )


def build_dataset(config: Config | None = None) -> Dataset | None:
    """Run the newest CSV in data/raw/ through the pipeline (None if none present)."""
    config = config or load_config()
    raw = ingest.load_latest(config=config)
    if raw is None:
        return None
    return _assemble(raw.df, raw.filename, raw.path, raw.modified, config)


def build_from_csv_bytes(name: str, data: bytes, config: Config | None = None) -> Dataset:
    """Run an uploaded CSV (raw bytes) through the pipeline."""
    config = config or load_config()
    raw_df = pd.read_csv(
        io.BytesIO(data), encoding=config.encoding, dtype=str, keep_default_na=False
    )
    return _assemble(raw_df, name, None, None, config)
