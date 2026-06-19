"""Refresh orchestration: (optionally) pull a fresh CSV, ingest, record snapshot.

Used by both the hourly launchd job (scripts/refresh.py --fetch) and the in-app
"Update now" buttons. Fails loudly but never crashes the caller: a failed fetch
is reported in the result and the most recent CSV already on disk is still
ingested/recorded so the dashboard degrades gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import exporter, history
from .config import Config, load_config
from .pipeline import build_dataset


@dataclass
class RefreshResult:
    ok: bool
    message: str
    fetched: bool = False
    fetch_error: str | None = None
    source_file: str | None = None
    snapshot_recorded: bool = False
    rows: int = 0


def do_refresh(
    fetch: bool = False,
    now: datetime | None = None,
    config: Config | None = None,
    db_path: str = history.DB_PATH,
) -> RefreshResult:
    now = now or datetime.now()

    fetched = False
    fetch_error: str | None = None
    if fetch:
        try:
            exporter.fetch(headless=True)
            fetched = True
        except exporter.ExporterError as exc:
            fetch_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - never let the job crash
            fetch_error = f"unexpected fetch error: {type(exc).__name__}: {exc}"

    # Ingest + record. A corrupt CSV, a YAML error, or a locked DB must degrade
    # to a structured result, never an uncaught traceback (the "Never raises"
    # contract). The dashboard then stays on the last good snapshot.
    try:
        config = config or load_config()
        ds = build_dataset(config)
        if ds is None:
            return RefreshResult(
                ok=False,
                message="No CSV found in data/raw/. Drop an export there or run the login + fetch.",
                fetched=fetched,
                fetch_error=fetch_error,
            )
        recorded = history.record_snapshot(ds.df, source_file=ds.source_name, ts=now, db_path=db_path)
    except Exception as exc:  # noqa: BLE001
        return RefreshResult(
            ok=False,
            message=f"Ingest/record failed: {type(exc).__name__}: {exc}",
            fetched=fetched,
            fetch_error=fetch_error,
        )

    if fetch and fetch_error:
        msg = (
            f"Auto-fetch FAILED ({fetch_error}). "
            f"Ingested existing file '{ds.source_name}' instead "
            f"({'recorded new snapshot' if recorded else 'already recorded'})."
        )
        ok = False
    elif fetch:
        msg = f"Fetched and ingested '{ds.source_name}' ({'new snapshot' if recorded else 'duplicate, not re-recorded'})."
        ok = True
    else:
        msg = f"Ingested '{ds.source_name}' ({'new snapshot' if recorded else 'duplicate, not re-recorded'})."
        ok = True

    return RefreshResult(
        ok=ok,
        message=msg,
        fetched=fetched,
        fetch_error=fetch_error,
        source_file=ds.source_name,
        snapshot_recorded=recorded,
        rows=len(ds.df),
    )
