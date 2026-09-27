#!/usr/bin/env python3
"""Read-only check of the installed controller under this Mac's real workload.
Run: python3 tests/cadence.py [--seconds 120] [--since UTC-ISO-TIME] [--output PATH]

Failure inventory (before implementation): heavy load starves the control loop
past the ten-second watchdog; a restarted controller is starved before its first
heartbeat; throttled I/O delays the status write; the Interactive process type is
not loaded or not inherited by the watchdog; a quiet sample is mistaken for proof
under load; the observer itself stalls and misses status writes. Loop gaps come
from the status file's kernel modification times, not from observer timing.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STATUS = Path("/Library/Application Support/Cooler/status.json")
LOG = Path("/var/log/cooler.log")
PLIST = Path("/Library/LaunchDaemons/com.chetangoel.cooler.plist")
parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=120)
parser.add_argument("--since", help="count log events from this UTC time (default: plist install time)")
parser.add_argument("--output", default=str(ROOT / "artifacts/cadence-report.json"))
args = parser.parse_args()
since = (dt.datetime.fromisoformat(args.since.replace("Z", "+00:00")) if args.since
         else dt.datetime.fromtimestamp(PLIST.stat().st_mtime, dt.timezone.utc))


def priority(pid):
    return int(subprocess.run(["ps", "-o", "pri=", "-p", str(pid)], capture_output=True, text=True).stdout)


def service():
    text = subprocess.run(["launchctl", "print", "system/com.chetangoel.cooler"],
                          capture_output=True, text=True, timeout=5).stdout
    found = re.search(r"^\tpid = (\d+)", text, re.M)
    if not found:
        raise SystemExit("Cooler is not running; select a Cooler profile first.")
    pid = int(found.group(1))
    watchdog = subprocess.run(["pgrep", "-P", str(pid), "-f", "cooler watch"],
                              capture_output=True, text=True).stdout.split()
    return {"pid": pid, "spawn_type": re.search(r"spawn type = (.+)", text).group(1).strip(),
            "controller_priority": priority(pid), "watchdog_pid": int(watchdog[0]) if watchdog else None,
            "watchdog_priority": priority(watchdog[0]) if watchdog else None}


before = service()
mtimes, statuses, loads = [], [], []
observer_gap, last_mtime, next_load = 0.0, None, 0.0
last_loop = time.monotonic()
end = last_loop + args.seconds
while (now := time.monotonic()) < end:
    observer_gap, last_loop = max(observer_gap, now - last_loop), now
    try:
        mtime = STATUS.stat().st_mtime_ns
        if mtime != last_mtime:
            last_mtime = mtime
            mtimes.append(mtime)
            statuses.append(json.loads(STATUS.read_text()))
    except (OSError, ValueError):
        pass
    if now >= next_load:
        loads.append(os.getloadavg()[0])
        next_load = now + 1
    time.sleep(0.05)
after = service()

gaps = sorted((b - a) / 1e9 for a, b in zip(mtimes, mtimes[1:]))
events = []
for line in LOG.read_text(errors="replace").splitlines():
    stamp, _, message = line.partition(" ")
    try:
        if dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= since:
            events.append((stamp, message))
    except ValueError:
        continue
timeouts = [stamp for stamp, message in events if message.startswith("Controller heartbeat timed out")]
peak_cpu = max((s.get("cpu") or 0 for s in statuses), default=0)
peak_load = max(loads, default=0)
checks = {
    "launchd runs Cooler as an interactive process": all("interactive" in s["spawn_type"] for s in (before, after)),
    "controller priority is at least 31": all(s["controller_priority"] >= 31 for s in (before, after)),
    "watchdog priority is at least 31": all((s["watchdog_priority"] or 0) >= 31 for s in (before, after)),
    "no watchdog timeouts in the log since --since": not timeouts,
    "status updates never paused for 8 seconds or more": bool(gaps) and gaps[-1] < 8,
}
passed = all(checks.values())
# Every logged stall had CPU at 99-107°C. Load average is reported, not used:
# on macOS it exceeded 70 while the CPU was half idle.
heavy = peak_cpu >= 95
report = {
    "time": dt.datetime.now(dt.timezone.utc).isoformat(), "since": since.isoformat(),
    "service_start": before, "service_end": after,
    "sample": {"seconds": args.seconds, "status_updates": len(mtimes),
               "median_gap_s": round(gaps[len(gaps) // 2], 2) if gaps else None,
               "max_gap_s": round(gaps[-1], 2) if gaps else None, "gaps_over_4s": sum(g > 4 for g in gaps),
               "controller_pids": sorted({s.get("pid") for s in statuses}),
               "peak_cpu_c": round(peak_cpu, 1), "peak_load_1m": round(peak_load, 1),
               "observer_max_loop_gap_s": round(observer_gap, 2)},
    "log_since": {"heartbeat_timeouts": timeouts,
                  "controller_starts": sum(message.startswith("{") for _, message in events)},
    "checks": checks, "passed": passed, "heavy_load_observed": heavy,
    "conclusion": ("Failed" if not passed else "Passed under heavy load" if heavy else
                   "Passed, but the sample saw no heavy load; rerun during heavy use"),
}
Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
raise SystemExit(0 if passed else 1)
