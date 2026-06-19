"""Install/uninstall the macOS launchd agent that keeps the dashboard fresh 24/7.

The agent runs scripts/refresh.py --fetch on this schedule (local time):
  * every hour at :00  -> hourly PM-completion update; the 05:00 and 17:00 runs
                          double as the shift-start completion baselines
  * 04:30 and 16:30    -> pre-shift PM-list pull (30 min before each shift)

    python scripts/setup_launchd.py install     # write plist + load the agent
    python scripts/setup_launchd.py uninstall   # unload + remove the plist
    python scripts/setup_launchd.py status       # show whether it's loaded
    python scripts/setup_launchd.py plist        # print the generated plist (dry run)

Run this with the pm_dashboard env's python so the agent uses the right interpreter:
    conda activate pm_dashboard && python scripts/setup_launchd.py install

NOTE: auto-fetch needs the one-time Playwright login first
(`python scripts/export_asset_essentials.py login`). Until then the agent still
runs hourly and logs a harmless "not logged in" warning.

The host must be an ALWAYS-ON Mac. launchd does not stack missed calendar runs:
if the machine sleeps through a scheduled time, only ONE catch-up run fires on
wake, so a sleeping laptop will have gaps in the shift history. RunAtLoad=true
means the agent also refreshes immediately on install/login/reboot.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

LABEL = "com.heliene.pm-dashboard"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
REFRESH_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "refresh.py")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "scheduler.log")


def _calendar_entries() -> str:
    # Minute=0 with no Hour => every hour at :00. Plus the two pre-shift pulls.
    blocks = [{"Minute": 0}, {"Hour": 4, "Minute": 30}, {"Hour": 16, "Minute": 30}]
    out = []
    for b in blocks:
        kv = "".join(f"<key>{k}</key><integer>{v}</integer>" for k, v in b.items())
        out.append(f"      <dict>{kv}</dict>")
    return "\n".join(out)


def build_plist(python: str | None = None) -> str:
    python = python or sys.executable
    path_env = f"{os.path.dirname(python)}:/usr/bin:/bin:/usr/sbin:/sbin"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python}</string>
      <string>{REFRESH_SCRIPT}</string>
      <string>--fetch</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>{path_env}</string></dict>
    <key>StartCalendarInterval</key>
    <array>
{_calendar_entries()}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_PATH}</string>
</dict>
</plist>
"""


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def install() -> int:
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(PLIST_PATH, "w", encoding="utf-8") as fh:
        fh.write(build_plist())
    lint = _run(["plutil", "-lint", PLIST_PATH])
    print(lint.stdout.strip() or lint.stderr.strip())
    if lint.returncode != 0:
        print("plist failed validation; aborting.")
        return 1
    # Reload cleanly: bootout if already loaded, then bootstrap.
    _run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    res = _run(["launchctl", "bootstrap", _domain(), PLIST_PATH])
    if res.returncode != 0:
        # Fall back to the legacy verb on older macOS.
        res = _run(["launchctl", "load", "-w", PLIST_PATH])
    if res.returncode == 0:
        print(f"Installed and loaded {LABEL}.")
        print(f"  plist: {PLIST_PATH}")
        print(f"  log:   {LOG_PATH}")
        return 0
    print(f"launchctl failed: {res.stderr.strip() or res.stdout.strip()}")
    print(f"The plist was written to {PLIST_PATH}; load it manually with:")
    print(f"  launchctl bootstrap {_domain()} {PLIST_PATH}")
    return 1


def uninstall() -> int:
    _run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    _run(["launchctl", "unload", PLIST_PATH])
    if os.path.exists(PLIST_PATH):
        os.remove(PLIST_PATH)
    print(f"Uninstalled {LABEL}.")
    return 0


def status() -> int:
    res = _run(["launchctl", "print", f"{_domain()}/{LABEL}"])
    if res.returncode == 0:
        print(f"{LABEL} is LOADED.")
        for line in res.stdout.splitlines():
            if any(k in line for k in ("state =", "runs =", "last exit", "program =")):
                print("  " + line.strip())
    else:
        print(f"{LABEL} is NOT loaded. Run: python scripts/setup_launchd.py install")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmd", choices=["install", "uninstall", "status", "plist"])
    args = parser.parse_args()
    if args.cmd == "install":
        return install()
    if args.cmd == "uninstall":
        return uninstall()
    if args.cmd == "status":
        return status()
    print(build_plist())
    return 0


if __name__ == "__main__":
    sys.exit(main())
