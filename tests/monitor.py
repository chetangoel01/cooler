#!/usr/bin/env python3
"""Read-only process checks. Run: python3 tests/monitor.py.

Failure inventory (before implementation): stale/missing/corrupt status presented
as live; missing or stalled probe; actual RPM confused with targets; automatic
mode described as custom; curves drift from installed config; monitor writes fans.
Menu redesign, written before its code: readings drawn as disabled gray text; a
problem hidden behind the normal fan icon; an old success message read as live
control; dynamic text adding tab columns, actions, or lines; the curves page or
SwiftBar's own menu becoming unreachable; a trailing separator doubling SwiftBar's.
Fixtures run the complete plugin with a fake probe and a temporary home folder, so
they never read or write the real saved curve or action state. The last check
reads this Mac.
"""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "monitor/cooler.5s.py"
ARTIFACTS = ROOT / "artifacts"
checks = []


def active(menu):
    # Cooler's targets appear only while it is verified in control, and never beside a warning.
    # Action history can mention a prior success, so it is not a signal.
    return (any(row.startswith("Targets\t") and row.split(" | ")[0].endswith(" RPM") for row in menu.splitlines())
            and "exclamationmark.triangle" not in menu)


with tempfile.TemporaryDirectory(prefix="cooler-monitor-") as directory:
    source = Path(directory)
    cache = source / "cache"
    config = json.loads((ROOT / "config.json").read_text())
    (source / "config.json").write_text(json.dumps(config))
    probe = source / "cooler"
    probe.write_text('''#!/opt/homebrew/bin/python3
import json, pathlib, sys, time
p = pathlib.Path(__file__).parent
with (p / "calls").open("a") as f: f.write(" ".join(sys.argv[1:]) + "\\n")
if (p / "stall").exists(): time.sleep(10)
print((p / "probe.json").read_text())
''')
    probe.chmod(0o755)
    launchctl = source / 'launchctl'
    launchctl.write_text('''#!/opt/homebrew/bin/python3
import pathlib, sys
p=pathlib.Path(__file__).parent
disabled=(p/'disabled').exists()
if sys.argv[1]=='print-disabled': print('"com.chetangoel.cooler" => '+('disabled' if disabled else 'enabled'))
elif disabled: sys.exit(113)
else: print('pid = 123')
''')
    launchctl.chmod(0o755)
    values = {"F0Ac": 2010, "F1Ac": 2110, "F0Mx": 5779, "F1Mx": 6241,
              "F0Mn": 1200, "F1Mn": 1200, "F0Md": 1, "F1Md": 1}
    (source / "probe.json").write_text(json.dumps({"values": values}))
    status = {"pid":123, "cpu": 55, "gpu": 49, "palm": 29, "mode": "custom",
              "reason": "Cooling curve active", "targets": [2198, 2244],
              "time": dt.datetime.now(dt.timezone.utc).isoformat()}

    home = source / "home"
    saved = home / "Library/Application Support/Cooler"
    saved.mkdir(parents=True)
    (saved / "custom.json").write_text(json.dumps({"baselineRPM": 1900, "curve": config["curve"],
                                                   "palmCurve": config["palmCurve"]}))

    def run():
        result = subprocess.run([str(PLUGIN)], text=True, capture_output=True, timeout=6,
                                env={**os.environ, "HOME": str(home), "COOLER_HOME": str(source),
                                     "COOLER_LAUNCHCTL":str(launchctl),
                                     "SWIFTBAR_PLUGIN_CACHE_PATH": str(cache)})
        assert result.returncode == 0, result.stderr
        return result.stdout, (cache / "curves.html").read_text()

    (source / "status.json").write_text(json.dumps(status))
    menu, html = run()
    rows = menu.splitlines()
    assert rows[0].startswith("55° | sfimage=fan.fill ") and active(menu)
    assert "CPU\t55° | color=" in menu and "Fans\t2,010 · 2,110 RPM | color=" in menu
    assert "alternate=true" in next(row for row in rows if row.startswith("Targets\t2,198 · 2,244 RPM"))
    assert 'param2=quiet' in menu and 'param2=balanced' in menu and 'param2=cooler' in menu and 'param2=automatic' in menu
    assert "CPU &amp; GPU" in html and "Palm rest" in html and "<svg" in html
    checks.append("Legible live temperatures and fan speeds, targets under Option, and both curve graphs")
    assert rows[-2].startswith("Edit Custom Curve… | bash=") and rows[-1].startswith("View Current Curves… | href=file://")
    assert rows[-1].endswith("alternate=true") and 'tooltip="1,900 RPM minimum, full speed at 85°C"' in menu
    header = PLUGIN.read_text()
    assert "<swiftbar.hideLastUpdated>true" in header and "<swiftbar.hideDisablePlugin>true" in header
    assert "hideSwiftBar" not in header
    checks.append("Editor and curves page stay reachable; SwiftBar keeps its own menu and single separator")
    maximum = {"baselineRPM": 1800, "curve": [{"temperature": 10, "fraction": 1}, {"temperature": 90, "fraction": 1}],
               "palmCurve": [{"temperature": 10, "fraction": 1}, {"temperature": 90, "fraction": 1}]}
    (source / "config.json").write_text(json.dumps({**config, **maximum}))
    menu, _ = run()
    assert menu.startswith("55° | sfimage=wind ") and "checked=true" in next(r for r in menu.splitlines() if "param2=max" in r)
    (source / "config.json").write_text(json.dumps(config))
    checks.append("The menu-bar icon shows Max cooling while it is in control")

    status['pid']=122
    (source/'status.json').write_text(json.dumps(status))
    menu,_=run()
    assert not active(menu) and "No recent update from Cooler" in menu
    checks.append('Status from an old controller process cannot mark a new one healthy')
    status['pid']=123
    (source/'status.json').write_text(json.dumps(status))

    config["baselineRPM"] = 2000
    (source / "config.json").write_text(json.dumps(config))
    _, html = run()
    assert "2,000 RPM" in html
    checks.append("Curves use installed configuration")

    status.update(mode="automatic", reason="Another fan controller is running", targets=[])
    (source / "status.json").write_text(json.dumps(status))
    menu, _ = run()
    assert menu.startswith("55° | sfimage=exclamationmark.triangle.fill ") and "Paused while another fan app is open" in menu
    assert not active(menu) and "Targets\tNot set by Cooler" in menu
    checks.append("Yielding to another controller has no Cooler targets and flags the menu bar")
    values.update(F0Md=0, F1Md=0)
    (source / "probe.json").write_text(json.dumps({"values": values}))
    menu, _ = run()
    assert "Targets\tSet by macOS" in menu
    checks.append("Hardware automatic mode is identified")

    (source/'disabled').touch()
    values.update({key:42 for key in config['cpuKeys']})
    values.update({key:39 for key in config['gpuKeys']})
    values.update({key:27 for key in config['palmKeys']})
    (source/'probe.json').write_text(json.dumps({'values':values}))
    old_time=status['time']; status['time']='2000-01-01T00:00:00Z'
    (source/'status.json').write_text(json.dumps(status))
    menu,_=run()
    assert menu.startswith('42° | sfimage=fan.badge.automatic.fill ') and 'GPU\t39° |' in menu
    assert 'checked=true' in next(row for row in menu.splitlines() if 'param2=automatic' in row)
    assert 'exclamationmark.triangle' not in menu
    checks.append('Apple automatic keeps live temperatures after the daemon is stopped')
    (source/'disabled').unlink()
    values={k:v for k,v in values.items() if k.startswith('F')}
    (source/'probe.json').write_text(json.dumps({'values':values}))
    status['time']=old_time

    status.update(mode="custom", time="2000-01-01T00:00:00Z")
    (source / "status.json").write_text(json.dumps(status))
    menu, html = run()
    assert menu.startswith("? | sfimage=exclamationmark.triangle.fill ") and "No recent update from Cooler" in menu
    assert not active(menu) and "55°" not in menu
    checks.append("Stale status never appears live")

    state = home / "Library/Caches/CoolerMonitor"
    state.mkdir(parents=True)
    (state / "action.json").write_text(json.dumps({"message": "Cooler curve active. Saved for future restarts.",
                                                   "time": time.time()}))
    menu, _ = run()
    assert "Saved for future restarts" not in menu and not active(menu)
    (state / "action.json").write_text(json.dumps({"message": "Change failed: fixture error", "time": time.time()}))
    menu, _ = run()
    assert "Change failed: fixture error | sfimage=exclamationmark.triangle " in menu
    checks.append("A past success never reads as live control; a failed change stays visible")
    (state / "action.json").unlink()

    for content in [None, "{broken"]:
        if content is None:
            (source / "status.json").unlink()
        else:
            (source / "status.json").write_text(content)
        menu, _ = run()
        assert menu.startswith("? | sfimage=exclamationmark.triangle.fill ") and "Cooler status unavailable" in menu
    checks.append("Missing and corrupt status stay readable")

    status.update(time=dt.datetime.now(dt.timezone.utc).isoformat(), targets=[2198, 2244])
    (source / "status.json").write_text(json.dumps(status))
    (source / "stall").touch()
    menu, html = run()
    assert "Fans\tUnavailable" in menu and "Fan control not confirmed" in menu and not active(menu)
    assert "Curves unavailable" in html
    checks.append("Probe timeout is bounded and does not claim verified control")

    (source / "stall").unlink()
    status.update(mode="automatic", reason="Bad\treason | bash=/usr/bin/true\nsecond line")
    (source / "status.json").write_text(json.dumps(status))
    menu, _ = run()
    row = next(row for row in menu.splitlines() if row.startswith("Paused: Bad"))
    assert row.count("|") == 1 and "\t" not in row and "second line" in row
    checks.append("Dynamic text cannot add columns, actions, or menu lines")
    assert set((source / "calls").read_text().splitlines()) == {"probe"}
    checks.append("The only hardware command is read-only probe")

with tempfile.TemporaryDirectory(prefix="cooler-live-monitor-") as cache:
    result = subprocess.run([str(PLUGIN)], capture_output=True, text=True, timeout=6,
                            env={**os.environ, "SWIFTBAR_PLUGIN_CACHE_PATH": cache})
    assert result.returncode == 0, result.stderr
    assert "Fans\t" in result.stdout and "CPU\t" in result.stdout
    assert "Fans\tUnavailable" not in result.stdout
    assert "CPU\tUnavailable" not in result.stdout and "No recent update" not in result.stdout
    ARTIFACTS.mkdir(exist_ok=True)
    # Keep the saved menu's curve link usable after the temporary cache is removed.
    (ARTIFACTS / "monitor-menu.txt").write_text(result.stdout.replace(
        (Path(cache) / "curves.html").as_uri(), (ARTIFACTS / "monitor-curves.html").as_uri()))
    (ARTIFACTS / "monitor-curves.html").write_text((Path(cache) / "curves.html").read_text())
    checks.append("Installed controller read successfully without administrator access")

report = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": checks, "passed": len(checks)}
(ARTIFACTS / "monitor-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
