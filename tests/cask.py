#!/usr/bin/env python3
"""Process checks for the scripts the Homebrew cask runs. Run: python3 tests/cask.py.

Failure inventory, written before the scripts: an upgrade resets the selected
profile (Homebrew runs the uninstall step on every upgrade, then installs again);
an upgrade turns Cooler back on after Apple Automatic was chosen; a fresh install
starts without a configuration; the full-speed hardware check runs on every
upgrade instead of only the first install; uninstall leaves the daemon loaded,
the fans in manual mode, or its plist behind; uninstall deletes the profile the
next install should keep; an install proceeds while another fan controller runs;
an install on another Mac model starts a controller that cannot work there.
Found in the first Homebrew install: files copied out of the downloaded app keep
its quarantine flag, and launchd refuses to load a quarantined daemon plist.

Runs packaging/install-daemon.sh and uninstall.sh with simulated launchd, sysctl,
pgrep, install and SMC operations in a temporary root. No root, launchd, or fan
access.
"""
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LIVE_BASE = "/Library/Application Support/Cooler"
LIVE_PLIST = "/Library/LaunchDaemons/com.chetangoel.cooler.plist"
TOOLS = {"launchctl": "/bin/launchctl", "pgrep": "/usr/bin/pgrep", "sysctl": "/usr/sbin/sysctl",
         "id": "/usr/bin/id", "install": "/usr/bin/install"}
BACKEND = r'''#!/opt/homebrew/bin/python3
import json, pathlib, subprocess, sys
p = pathlib.Path(WORK)  # also valid for the copy installed as the controller
state = json.loads((p / "state.json").read_text())
command, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with (p / "events.jsonl").open("a") as f: f.write(json.dumps([command, args]) + "\n")
code = 0
if command == "id": print(0)
elif command == "sysctl": print(state["model"])
elif command == "pgrep": code = 0 if state["competitor"] else 1
elif command == "install":
    # The real install, minus root ownership, so extended attributes carry over as they do on a Mac.
    kept, i = [], 0
    while i < len(args):
        if args[i] in ("-o", "-g"): i += 2; continue
        kept.append(args[i]); i += 1
    code = subprocess.run(["/usr/bin/install", *kept]).returncode
elif command == "launchctl":
    verb = args[0]
    if verb == "print-disabled":
        print('"com.chetangoel.cooler" => ' + ("disabled" if state["disabled"] else "enabled"))
    elif verb == "print": code = 0 if state["loaded"] else 113
    elif verb == "bootout": state["loaded"] = False
    elif verb == "enable": state["disabled"] = False
    elif verb == "bootstrap":
        assert not state["disabled"] and pathlib.Path(args[2]).exists()
        quarantined = subprocess.run(["/usr/bin/xattr", "-p", "com.apple.quarantine", args[2]],
                                     capture_output=True).returncode == 0
        if quarantined:
            print("Bootstrap failed: 5: Input/output error", file=sys.stderr); code = 5
        else: state["loaded"] = True
elif command == "cooler":
    if args[0] == "auto" and state["loaded"]: code = 43
(p / "state.json").write_text(json.dumps(state))
sys.exit(code)
'''
checks = []

with tempfile.TemporaryDirectory(prefix="cooler-cask-") as directory:
    work = Path(directory)
    base, plist, resources = work / "installed", work / "com.chetangoel.cooler.plist", work / "Resources"
    resources.mkdir()
    backend = work / "backend.py"
    backend.write_text(BACKEND.replace("WORK", repr(str(work)), 1))
    backend.chmod(0o755)
    for name in TOOLS:
        (work / name).symlink_to(backend)
    helper = work / "Helpers/cooler"
    helper.parent.mkdir()
    helper.symlink_to(backend)
    for name in ["config.json", "com.chetangoel.cooler.plist", "uninstall.sh"]:
        (resources / name).write_bytes((ROOT / name).read_bytes())
    QUARANTINE = ["com.apple.quarantine", "0083;00000000;Homebrew Cask;"]

    def script(path):
        text = path.read_text().replace(shlex.quote(LIVE_BASE), shlex.quote(str(base)))
        text = text.replace(LIVE_PLIST, shlex.quote(str(plist)))
        for name, live in TOOLS.items():
            text = text.replace(live, shlex.quote(str(work / name)))
        copy = work / path.name
        copy.write_text(text)
        return copy

    installer, uninstaller = script(ROOT / "packaging/install-daemon.sh"), script(ROOT / "uninstall.sh")
    # The installed uninstaller must be the rewritten copy too, as the real one points at live paths.
    (resources / "uninstall.sh").write_text(uninstaller.read_text())
    # Homebrew keeps the quarantine flag on the downloaded app, so everything installed from it has one.
    helper.unlink()
    helper.write_text(BACKEND.replace("WORK", repr(str(work)), 1))
    helper.chmod(0o755)
    for path in [helper, *resources.iterdir()]:
        subprocess.run(["/usr/bin/xattr", "-w", *QUARANTINE, str(path)], check=True)

    def run(target, **state):
        current = {"model": "MacBookPro18,4", "competitor": False, "loaded": False, "disabled": False}
        path = work / "state.json"
        if path.exists():
            current.update(json.loads(path.read_text()))
        current.update(state)
        path.write_text(json.dumps(current))
        (work / "events.jsonl").write_text("")
        args = [str(helper), str(resources)] if target == installer else []
        result = subprocess.run(["/bin/sh", str(target), *args], capture_output=True, text=True, timeout=30)
        events = [json.loads(line) for line in (work / "events.jsonl").read_text().splitlines()]
        return result, json.loads(path.read_text()), events

    def cooler_calls(events):
        return [args[0] for command, args in events if command == "cooler"]

    result, state, events = run(installer)
    assert result.returncode == 0, result.stderr
    assert (base / "config.json").read_bytes() == (ROOT / "config.json").read_bytes() and plist.exists()
    assert state["loaded"] and cooler_calls(events).count("hardware-check") == 1
    assert (base / "uninstall.sh").exists() and (base / "cooler").stat().st_mode & 0o777 == 0o755
    checks.append("A first install writes the default profile, checks the fans once, and starts Cooler")
    flagged = [p.name for p in [plist, base / "cooler", base / "uninstall.sh", base / "config.json"]
               if subprocess.run(["/usr/bin/xattr", "-p", QUARANTINE[0], str(p)], capture_output=True).returncode == 0]
    assert not flagged, f"Installed files kept the download's quarantine flag: {flagged}"
    checks.append("Installed files drop the downloaded app's quarantine flag, so launchd loads the daemon")

    maximum = json.loads((ROOT / "config.json").read_text())
    maximum.update(baselineRPM=1800, curve=[{"temperature": 10, "fraction": 1}, {"temperature": 90, "fraction": 1}])
    (base / "config.json").write_text(json.dumps(maximum))
    result, state, events = run(uninstaller)
    assert result.returncode == 0, result.stderr
    assert not state["loaded"] and cooler_calls(events) == ["auto"]
    assert not plist.exists() and not (base / "cooler").exists() and not (base / "uninstall.sh").exists()
    assert json.loads((base / "config.json").read_text()) == maximum
    checks.append("Uninstall stops Cooler, restores automatic control, removes it, and keeps the profile")

    result, state, events = run(installer)
    assert result.returncode == 0, result.stderr
    assert json.loads((base / "config.json").read_text()) == maximum and state["loaded"]
    assert "hardware-check" not in cooler_calls(events)
    checks.append("An upgrade keeps the selected profile and skips the full-speed check")

    run(uninstaller)
    result, state, events = run(installer, disabled=True)
    assert result.returncode == 0, result.stderr
    assert not state["loaded"] and state["disabled"] and "stays off" in result.stdout
    assert not any(command == "launchctl" and args[0] in ("enable", "bootstrap") for command, args in events)
    assert json.loads((base / "config.json").read_text()) == maximum and plist.exists()
    checks.append("An upgrade after Apple Automatic installs Cooler but leaves it off")

    for change, message in [({"competitor": True}, "other fan controllers"), ({"model": "Mac14,6"}, "MacBookPro18,4")]:
        run(uninstaller, disabled=False, competitor=False, model="MacBookPro18,4")
        result, state, events = run(installer, **change)
        assert message in result.stderr and not plist.exists() and not state["loaded"], result
        assert (result.returncode == 0) == ("model" in change)
    checks.append("No controller is installed while another fan app runs or on another Mac model")

report = {"checks": checks, "passed": len(checks), "hardware_writes": False}
(ROOT / "artifacts/cask-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
