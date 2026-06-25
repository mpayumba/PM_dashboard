"""Heliene PM dashboard — data pipeline package.

Modules:
    config   — load config/column_mapping.yaml into a typed Config object.
    ingest   — locate and load the latest raw CSV export from data/raw/.
    parse    — rename to canonical columns, coerce types, filter to active WOs.
    classify — PM vs Non-PM (Origin), then Maintenance vs Mechatronics (title PM-ME).
    metrics  — pure KPI / summary functions returning tidy DataFrames.
"""
