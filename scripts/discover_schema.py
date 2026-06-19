"""Schema-discovery helper (Phase 2 GATE).

Loads the latest raw CSV export from data/raw/ and prints everything needed to
fill in config/column_mapping.yaml: column headers, dtypes, row count, distinct
status values, distinct origin values, and representative Title values (including
those containing PM and PM-ME).

Run:  python scripts/discover_schema.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")


def latest_csv(raw_dir: str) -> str:
    candidates = glob.glob(os.path.join(raw_dir, "*.csv"))
    if not candidates:
        sys.exit(f"No CSV found in {raw_dir}")
    return max(candidates, key=os.path.getmtime)


def main() -> None:
    path = latest_csv(RAW_DIR)
    print(f"=== FILE ===\n{path}\n")

    # utf-8-sig strips the BOM we observed on the header (﻿ before 'Work Order #').
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)

    print(f"=== SHAPE ===\nrows={len(df)}  cols={df.shape[1]}\n")

    print("=== COLUMNS (repr to expose hidden whitespace/BOM) ===")
    for i, c in enumerate(df.columns):
        print(f"  [{i}] {c!r}")
    print()

    print("=== DTYPES (raw, all read as str) ===")
    print(df.dtypes.to_string())
    print()

    # Distinct values for low-cardinality columns; samples for high-cardinality.
    for col in df.columns:
        n_unique = df[col].nunique(dropna=False)
        print(f"--- {col!r}  (n_unique={n_unique}) ---")
        if n_unique <= 25:
            vc = df[col].value_counts(dropna=False)
            for val, cnt in vc.items():
                print(f"    {cnt:>4}  {val!r}")
        else:
            print("    (high cardinality) sample of 12:")
            for val in df[col].head(12).tolist():
                print(f"        {val!r}")
        print()

    # Title-specific analysis for classification design.
    title_col = "Title" if "Title" in df.columns else df.columns[1]
    print(f"=== TITLE ANALYSIS (column={title_col!r}) ===")
    titles = df[title_col].astype(str)
    pm_me = titles[titles.str.contains(r"\bPM-ME\b", case=False, regex=True)]
    pm_word = titles[titles.str.contains(r"\bPM\b", case=False, regex=True)]
    pm_substr = titles[titles.str.contains("PM", case=False, regex=False)]
    print(f"titles containing 'PM' substring (naive):      {len(pm_substr)}")
    print(f"titles matching word-boundary  r'\\bPM\\b':       {len(pm_word)}")
    print(f"titles matching word-boundary  r'\\bPM-ME\\b':    {len(pm_me)}")
    print()
    print("  -- sample PM-ME titles --")
    for t in pm_me.head(10).tolist():
        print(f"     {t!r}")
    print("  -- sample PM (word) titles --")
    for t in pm_word.head(15).tolist():
        print(f"     {t!r}")
    print("  -- substring-PM but NOT word-boundary-PM (potential false positives a naive check would catch) --")
    fp = pm_substr[~pm_substr.index.isin(pm_word.index)]
    for t in fp.head(15).tolist():
        print(f"     {t!r}")
    print()

    # Date column parse check.
    for col in df.columns:
        sample = df[col].head(20)
        looks_datey = sample.str.contains(r"\d{1,2}/\d{1,2}/\d{2,4}", regex=True, na=False).mean()
        if looks_datey > 0.3:
            parsed = pd.to_datetime(df[col], errors="coerce")
            print(f"=== DATE-LIKE COLUMN {col!r}: parsed_ok={parsed.notna().sum()}/{len(df)} ===")
            print(f"    min={parsed.min()}  max={parsed.max()}")
            print()


if __name__ == "__main__":
    main()
