"""Mode B (optional, BEST-EFFORT): Asset Essentials CSV export via Playwright.

Thin CLI over src/exporter.py. The MANUAL export (Mode A) remains authoritative.

    python scripts/export_asset_essentials.py login          # one-time: log in (and 2FA); saves the session
    python scripts/export_asset_essentials.py fetch          # headless pull into data/raw/ using saved session
    python scripts/export_asset_essentials.py fetch --headed # same, but show the browser (debugging)

Requires:  pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import exporter  # noqa: E402

FALLBACK = f"""
------------------------------------------------------------------
Automated export unavailable. Fall back to the MANUAL export (Mode A):
  1. Open {exporter.WORKORDER_URL}
  2. Sign in and apply your saved active-work-order view.
  3. Click  More -> Export  to download the CSV.
  4. Move the downloaded file into:  {exporter.RAW_DIR}
------------------------------------------------------------------
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="Open a headed browser to establish/refresh the saved session.")
    f = sub.add_parser("fetch", help="Download a fresh CSV using the saved session.")
    f.add_argument("--headed", action="store_true", help="Show the browser instead of running headless.")
    args = parser.parse_args()

    try:
        if args.cmd == "login":
            exporter.login()
            return 0
        dest = exporter.fetch(headless=not args.headed)
        print(f"Export saved to: {dest}")
        return 0
    except exporter.NotLoggedIn as exc:
        print(f"NOT LOGGED IN: {exc}")
        print("Run:  python scripts/export_asset_essentials.py login")
        print(FALLBACK)
        return 1
    except exporter.ExporterError as exc:
        print(f"EXPORT ERROR: {exc}")
        print(FALLBACK)
        return 1


if __name__ == "__main__":
    sys.exit(main())
