# Heliene PM Dashboard

A local Streamlit dashboard for **Preventive Maintenance (PM) work orders** at the
Heliene solar-panel facility. It reads CSV exports from **Asset Essentials
(Dude Solutions)**, classifies active PM work orders into two streams —
**Maintenance** and **Mechatronics (ME)** — and surfaces operational KPIs
(overdue, aging, by-asset, trend).

There is **no API**; data comes from CSVs exported out of the Asset Essentials UI.

---

## Classification rules

The only reliable signal distinguishing the two streams is the **work-order title**:

| Stream           | Rule (case-insensitive, word-boundary regex)                |
|------------------|-------------------------------------------------------------|
| **Mechatronics** | title matches `\bPM-ME\b`                                    |
| **Maintenance**  | title matches `\bPM\b` **and not** `\bPM-ME\b`              |
| **Non-PM**       | neither matches                                             |

Word boundaries are essential: the substring `PM` appears inside ordinary words
(`EQUIPMENT`, `PUMP`, `RPM`, `PPM`, `PMP`), so a naive `"PM" in title` check is
wrong. The regexes above were validated against the real export and produce **no
`EQUIPMENT`-style false positives** and **never double-count a `PM-ME` row as
Maintenance**. The patterns live in [`config/column_mapping.yaml`](config/column_mapping.yaml)
and can be edited without touching code.

**Active filter:** only work orders with status code **`040`** are kept (the CMMS
renders this as `040 SCHEDULED`). The match is on the *leading code*, so `040`,
`40`, and `040 SCHEDULED` all count — applied defensively even though the saved
Asset Essentials view already pre-filters.

**Data quality:** work orders the CMMS marks as PM-origin but whose title does not
contain a clean PM token (e.g. a typo like `MonthlyPM`, or a title that omits the
token) are **surfaced in a data-quality panel** — never silently dropped and never
auto-reclassified (their stream is unrecoverable from the title).

---

## Setup (conda)

```bash
cd PM_dashboard
conda env create -f environment.yml
conda activate pm_dashboard
# Only if you intend to use the optional Playwright export (Mode B):
python -m playwright install chromium
```

If the env already exists: `conda env update -f environment.yml --prune`.

---

## Getting data — Mode A: manual export (primary, required)

1. Open <https://assetessentials.dudesolutions.com/Heliene/WorkOrder/Management> and sign in.
2. Apply your saved active-work-order view.
3. Click **More → Export** to download the CSV.
4. Move the downloaded file into **`data/raw/`**.

The dashboard loads the **most recent** CSV in `data/raw/` (by modified time) and
shows the filename + timestamp in the header. No browser automation is required.

### Mode B: semi-automated export (optional, best-effort)

A **one-time** interactive login saves a browser session, after which unattended
headless pulls reuse it:

```bash
python -m playwright install chromium                      # once
python scripts/export_asset_essentials.py login           # one-time: log in + 2FA; saves playwright/.auth/
python scripts/export_asset_essentials.py fetch           # headless pull into data/raw/ using the saved session
```

This is **best-effort** — Asset Essentials' DOM, auth, and sessions can change/expire.
On any failure it prints fallback instructions and exits non-zero without writing a
partial file. **Mode A remains authoritative.** When the saved session expires, just
re-run `login`.

---

## Run the dashboard

```bash
conda activate pm_dashboard
streamlit run app.py
```

The app shows: KPI cards (active PMs, Maintenance, Mechatronics, overdue count/%,
due today/week/month), a **Late (overdue) PMs** list, a **shift-completions** section,
a Maintenance-vs-Mechatronics split, an aging-by-due-date chart, top assets, an
assigned-week trend, a data-quality panel, and a filterable, downloadable detail
table. With no CSV present it shows the Mode A instructions.

The **Late (overdue) PMs** panel lists every PM whose due date has passed — sorted
most-late-first with a "days late" column, split by stream, and downloadable as CSV.
It honours the sidebar stream/asset/priority filters but ignores the due-date-window
filter, so late work is always visible.

**Updating the data, from the app:**

- **⬇️ Pull new CSV** — fetches a fresh export via the saved Playwright session
  (Mode B) and updates the dashboard.
- **🔁 Re-read file** — re-reads the newest CSV already in `data/raw/` (use after
  dropping a file in manually).
- **Auto-refresh while open** (sidebar) — reloads automatically within ~60s when a
  new export lands in `data/raw/`.

**Columns this export lacks:** the current saved view exports no **Assigned To**
(technician) or **Location** column, so the by-technician panel shows an explanatory
note (and falls back to a by-planner breakdown), and there is no location breakdown.
To enable them, add those columns to the Asset Essentials view and set `assigned_to`
/ `location` in `config/column_mapping.yaml`.

---

## Automated updates & shift tracking

Heliene runs 24/7 in two 12-hour shifts: **Day 05:00–17:00** and **Night 17:00–05:00**.

A macOS **launchd** agent keeps the dashboard current even when it's closed. It runs
`scripts/refresh.py --fetch` (pull → ingest → record a snapshot) on this schedule:

| Time (local)        | Purpose                                                            |
|---------------------|-------------------------------------------------------------------|
| every hour at `:00` | hourly PM-completion update; the 05:00 & 17:00 runs are the shift-start completion baselines |
| `04:30` and `16:30` | pre-shift PM-list pull, 30 min before each shift starts            |

**Activate it (after the one-time Playwright `login` above):**

```bash
conda activate pm_dashboard
python scripts/setup_launchd.py install      # write plist + load the agent
python scripts/setup_launchd.py status        # check it's loaded
python scripts/setup_launchd.py uninstall     # remove it
```

The agent logs to `data/processed/scheduler.log`. Until the one-time `login` is done
it still runs hourly and logs a harmless "not logged in" warning.

### How "completed this shift" is measured

The export is filtered to **active** work orders (status 040), so a completed PM
simply **disappears** from later pulls. Each pull is saved as a timestamped snapshot
in `data/processed/pm_history.sqlite` (gitignored). For a shift:

> **completed = PM work orders seen in any snapshot during the shift that are no
> longer in the latest snapshot**, split by Maintenance / Mechatronics.

A work order can also leave the active list by being cancelled/rescheduled, so the
figure is labelled "closed/completed". More snapshots during a shift → more accurate
counts, which is why the hourly pull matters.

**Limitations / assumptions for shift tracking:**

- **Always-on host.** launchd does not stack missed runs — if the Mac sleeps through
  a scheduled time, only one catch-up run fires on wake, leaving gaps. Run the agent
  on a machine that stays awake (or adjust `pmset`).
- **Snapshot granularity.** A PM completed *and* a replacement created between two
  pulls can be missed; if the shift-start (05:00/17:00) pull fails, the completion
  baseline falls back to the next successful pull (the app flags a late baseline).
- **Local time / DST.** All shift math uses local machine time. On the two DST
  transition days a shift is 11 or 13 hours of wall-clock; completion counts are
  unaffected (they're set-based), but interpret those two days' boundaries loosely.

---

## Run the tests

```bash
pytest -q
```

---

## Project structure

```
PM_dashboard/
├── app.py                      # Streamlit entry point (KPIs, shift section, charts, update buttons)
├── environment.yml             # conda environment spec
├── README.md
├── .gitignore                  # excludes ALL data (raw/processed/sample, *.csv/parquet/sqlite/log)
├── config/
│   └── column_mapping.yaml     # canonical-name -> export-header map + regexes (filled from real export)
├── src/
│   ├── config.py               # loads column_mapping.yaml
│   ├── ingest.py               # find & load latest raw CSV
│   ├── parse.py                # canonical rename, date coercion, 040 filter, parquet snapshot
│   ├── classify.py             # PM vs PM-ME classification
│   ├── metrics.py              # KPI / breakdown computations (pure, testable)
│   ├── pipeline.py             # ingest -> parse -> classify orchestration
│   ├── shifts.py               # 12-hour Day/Night shift model
│   ├── history.py              # SQLite snapshot store + shift-completion tracking
│   ├── exporter.py             # Playwright login + headless fetch (best-effort)
│   └── refresh.py              # pull -> ingest -> record-snapshot orchestration
├── scripts/
│   ├── discover_schema.py      # prints headers/dtypes/statuses/titles for any new export
│   ├── export_asset_essentials.py  # CLI: login / fetch (Playwright, best-effort)
│   ├── refresh.py              # CLI refresh entry point (used by launchd + the app button)
│   └── setup_launchd.py        # install/uninstall the 24/7 launchd update agent
├── data/
│   ├── raw/                    # exported CSVs                     (gitignored)
│   ├── processed/              # parquet + pm_history.sqlite + log (gitignored)
│   └── sample/                 # optional sanitized               (gitignored)
└── tests/
    ├── conftest.py             # fixtures (sanitized title cases, fixed reference date)
    ├── test_classify.py
    ├── test_parse.py
    ├── test_metrics.py
    ├── test_shifts.py
    ├── test_history.py
    └── test_app_smoke.py       # headless AppTest (skipped if streamlit absent)
```

---

## Data privacy

Work-order exports contain internal information (employee names, asset details).
`.gitignore` excludes everything under `data/raw/`, `data/processed/`, `data/sample/`
(keeping only `.gitkeep`), plus all `*.csv`, `*.parquet`, `*.sqlite`, and `*.log`
files, and the `playwright/.auth/` saved session. **Never commit raw or processed
work-order data** — including the snapshot history DB. Test fixtures use sanitized,
synthetic equipment/personnel names, not values copied from a real export.

---

## Adapting to a new export schema

If Asset Essentials changes the export columns, run:

```bash
python scripts/discover_schema.py
```

It prints the headers, dtypes, distinct statuses, and representative titles. Update
the `columns:` / `filters:` values in `config/column_mapping.yaml` to match (set a
value to `null` for any canonical column the export doesn't contain).
