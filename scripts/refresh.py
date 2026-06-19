"""CLI refresh entry point — used by the launchd agent and the in-app button.

    python scripts/refresh.py            # ingest the latest CSV in data/raw + record snapshot
    python scripts/refresh.py --fetch    # also pull a fresh CSV via the saved Playwright session

Prints a single timestamped log line and exits 0 on success, 1 on any problem
(so launchd logs surface failures). Never raises.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.refresh import do_refresh  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the PM dashboard data.")
    parser.add_argument("--fetch", action="store_true", help="Pull a fresh CSV via Playwright first.")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        res = do_refresh(fetch=args.fetch)
    except Exception as exc:  # noqa: BLE001 - last line of defense; honor "Never raises"
        print(f"[{stamp}] WARN | refresh crashed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"[{stamp}] {'OK ' if res.ok else 'WARN'} | {res.message}", flush=True)
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
