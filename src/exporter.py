"""Playwright export of the Asset Essentials work-order list (best-effort).

Uses a PERSISTENT browser profile (playwright/.auth/, gitignored) so a human logs
in ONCE (interactively, completing 2FA) and the saved session is reused by the
unattended hourly job. This is best-effort: Asset Essentials' DOM, auth, and
export behavior can change, and sessions expire. On failure the caller falls back
to the manual export (Mode A). Nothing here is the authoritative data path.

Public API:
    login()                  -> open a headed browser to establish/refresh the session
    fetch(headless=True)     -> download a fresh CSV into data/raw/, returns its path
Exceptions:
    PlaywrightMissing        -> the playwright package/browser isn't installed
    NotLoggedIn              -> the saved session is absent/expired (run login())
    ExportFailed             -> the export flow broke (DOM change, timeout, etc.)
"""
from __future__ import annotations

import os
from datetime import datetime

WORKORDER_URL = "https://assetessentials.dudesolutions.com/Heliene/WorkOrder/Management"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
USER_DATA_DIR = os.path.join(PROJECT_ROOT, "playwright", ".auth")


class ExporterError(RuntimeError):
    """Base class for exporter failures."""


class PlaywrightMissing(ExporterError):
    pass


class NotLoggedIn(ExporterError):
    pass


class ExportFailed(ExporterError):
    pass


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PlaywrightMissing(
            "playwright is not installed. Run: pip install playwright && python -m playwright install chromium"
        ) from exc
    return sync_playwright


def _looks_logged_in(page, timeout_ms: int = 30_000) -> bool:
    """Heuristic: the work-order grid's 'More' control is present when authed."""
    try:
        page.get_by_role("button", name="More").first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def _login_page_detected(page) -> bool:
    """True only when a login form/URL is actually present (vs. a merely slow load)."""
    try:
        url = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        url = ""
    if any(k in url for k in ("login", "signin", "sign-in", "auth")):
        return True
    try:
        return page.locator("input[type='password']").count() > 0
    except Exception:  # noqa: BLE001
        return False


def login() -> None:
    """Open a headed browser so a human can log in; the session is then saved."""
    sync_playwright = _import_playwright()
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(WORKORDER_URL, wait_until="domcontentloaded", timeout=60_000)
        print("\nLog in (and complete 2FA) in the browser window.")
        input("Once the work-order list is visible, press Enter here to save the session… ")
        ok = _looks_logged_in(page)
        ctx.close()
    if ok:
        print(f"Session saved to {USER_DATA_DIR}. Unattended fetches can now reuse it.")
    else:
        print("WARNING: could not confirm the work-order list loaded; fetches may still require login.")


def fetch(headless: bool = True, timeout_ms: int = 90_000) -> str:
    """Download a fresh CSV into data/raw/ using the saved session.

    Raises NotLoggedIn if the session is missing/expired, ExportFailed on any
    other problem. Never writes a partial file.
    """
    sync_playwright = _import_playwright()
    if not os.path.isdir(USER_DATA_DIR) or not os.listdir(USER_DATA_DIR):
        raise NotLoggedIn("No saved session. Run the one-time login first.")
    os.makedirs(RAW_DIR, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=headless, accept_downloads=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(WORKORDER_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            if not _looks_logged_in(page):
                # Only call it a session problem if a login form is actually shown;
                # otherwise it's a transient slow-load, which is retryable.
                if _login_page_detected(page):
                    raise NotLoggedIn("Saved session expired (login page detected). Re-run the one-time login.")
                raise ExportFailed("Work-order grid did not load in time (slow network or DOM change?).")

            try:
                page.get_by_role("button", name="More").first.click()
                with page.expect_download(timeout=timeout_ms) as dl_info:
                    page.get_by_role("button", name="Export").first.click()
                download = dl_info.value
            except Exception as exc:  # noqa: BLE001
                raise ExportFailed(f"Export flow failed (DOM change/timeout?): {exc}") from exc

            # Write to a temp file and atomically rename, so data/raw/ never holds a
            # truncated work_orders_*.csv with a fresh mtime that ingest would load.
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(RAW_DIR, f"work_orders_{ts}.csv")
            tmp = dest + ".part"
            try:
                download.save_as(tmp)
                os.replace(tmp, dest)
            except Exception as exc:  # noqa: BLE001
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise ExportFailed(f"Saving the download failed: {exc}") from exc
            return dest
        finally:
            ctx.close()
