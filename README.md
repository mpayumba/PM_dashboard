# Heliene PM Dashboard

A local Streamlit dashboard for **Preventive Maintenance (PM) work orders** at the
Heliene solar-panel facility. It reads a CSV you export from **Asset Essentials
(Dude Solutions)**, classifies active PMs into **Maintenance** and **Mechatronics
(ME)** streams, and presents them in three tabs.

There is **no API and no browser automation** — the dashboard works entirely from a
CSV you input (upload it in the app, or drop it into `data/raw/`).

---

## What it shows

Three tabs, each with summary statistics and a work-order list **ordered by due
date** (overdue first):

- **All PMs** — totals, Maintenance vs Mechatronics split, late count, overdue %,
  due ≤7 days, plus a data-quality note for any unclassifiable PM-origin rows.
- **Maintenance** — total PMs, late (overdue) count, overdue %, due ≤7 days, and the
  Maintenance work orders by due date.
- **Mechatronics** — the same, scoped to the Mechatronics (PM-ME) stream.

Each list is downloadable as CSV.

---

## Classification rules

The only reliable signal distinguishing the two streams is the **work-order title**:

| Stream           | Rule (case-insensitive, word-boundary regex)                |
|------------------|-------------------------------------------------------------|
| **Mechatronics** | title matches `\bPM-ME\b`                                    |
| **Maintenance**  | title matches `\bPM\b` **and not** `\bPM-ME\b`              |
| **Non-PM**       | neither matches                                             |

Word boundaries matter: the substring `PM` appears inside ordinary words
(`EQUIPMENT`, `PUMP`, `RPM`, `PPM`, `PMP`), so a naive `"PM" in title` check is
wrong. These regexes produce no such false positives and never double-count a
`PM-ME` row as Maintenance. They live in
[`config/column_mapping.yaml`](config/column_mapping.yaml) and can be edited without
touching code.

**Active filter:** only work orders with status code **`040`** are kept (the CMMS
renders this as `040 SCHEDULED`); the match is on the leading code, so `040`, `40`,
and `040 SCHEDULED` all count.

**Data quality:** PM-origin work orders whose title doesn't contain a clean PM token
(e.g. a typo like `MonthlyPM`) are surfaced in a panel on the All tab — never
silently dropped, never auto-reclassified.

---

## Setup (conda)

```bash
cd PM_dashboard
conda env create -f environment.yml
conda activate pm_dashboard
```

If the env already exists: `conda env update -f environment.yml --prune`.

---

## Getting data (manual export)

1. Open <https://assetessentials.dudesolutions.com/Heliene/WorkOrder/Management> and sign in.
2. Apply your saved active-work-order view.
3. Click **More → Export** to download the CSV.
4. **Input it into the dashboard** — either:
   - upload it in the sidebar (**recommended**), or
   - drop it into `data/raw/` (the app loads the newest file there).

---

## Run the dashboard

```bash
conda activate pm_dashboard
streamlit run app.py
```

Upload your CSV in the sidebar (or drop it in `data/raw/`) and use the three tabs.
The sidebar **as-of date** controls what counts as overdue (defaults to today). With
no CSV present the app shows upload instructions.

---

## Run the tests

```bash
pytest -q
```

---

## Project structure

```
PM_dashboard/
├── app.py                      # Streamlit entry point (3 tabs: All / Maintenance / Mechatronics)
├── environment.yml             # conda environment spec
├── README.md
├── LICENSE
├── .gitignore                  # excludes ALL data (raw/processed/sample, *.csv/parquet)
├── config/
│   └── column_mapping.yaml     # canonical-name -> export-header map + PM regexes
├── src/
│   ├── config.py               # loads column_mapping.yaml
│   ├── ingest.py               # find & load the latest raw CSV (data/raw fallback)
│   ├── parse.py                # canonical rename, date coercion, 040 filter
│   ├── classify.py             # PM vs PM-ME classification
│   ├── metrics.py              # summary stats + due-date ordering (pure, testable)
│   └── pipeline.py             # build a dataset from an uploaded CSV or data/raw
├── scripts/
│   └── discover_schema.py      # prints headers/dtypes/statuses/titles for any new export
├── data/
│   ├── raw/                    # input CSVs        (gitignored)
│   ├── processed/              # (gitignored)
│   └── sample/                 # (gitignored)
└── tests/
    ├── conftest.py             # fixtures (sanitized title cases, fixed reference date)
    ├── test_classify.py
    ├── test_parse.py
    ├── test_metrics.py
    └── test_app_smoke.py       # headless AppTest (skipped if streamlit absent)
```

---

## Data privacy

Work-order exports contain internal information (employee names, asset details).
`.gitignore` excludes everything under `data/raw/`, `data/processed/`, `data/sample/`
(keeping only `.gitkeep`) plus all `*.csv` / `*.parquet` files. **Never commit raw
work-order data.** Test fixtures use synthetic, sanitized names only.

---

## Adapting to a new export schema

If Asset Essentials changes the export columns, run:

```bash
python scripts/discover_schema.py
```

It prints the headers, dtypes, distinct statuses, and representative titles. Update
the `columns:` / `filters:` values in `config/column_mapping.yaml` to match (set a
value to `null` for any canonical column the export doesn't contain).
