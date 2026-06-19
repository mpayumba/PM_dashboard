"""Heliene PM dashboard — data pipeline package.

Modules:
    config   — load config/column_mapping.yaml into a typed Config object.
    ingest   — locate and load the latest raw CSV export from data/raw/.
    parse    — rename to canonical columns, coerce types, filter to active WOs.
    classify — PM vs PM-ME classification (word-boundary, case-insensitive).
    metrics  — pure KPI / breakdown functions returning tidy DataFrames.
"""
