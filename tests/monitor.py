#!/usr/bin/env python3
"""Read-only process checks. Run: python3 tests/monitor.py.

Failure inventory (before implementation): stale/missing/corrupt status presented
as live; missing or stalled probe; actual RPM confused with targets; automatic
mode described as custom; curves drift from installed config; monitor writes fans.
Fixtures run the complete plugin with a fake probe. The last check reads this Mac.
"""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "monitor/cooler.5s.py"
ARTIFACTS = ROOT / "artifacts"
checks = []


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
    values = {"F0Ac": 2010, "F1Ac": 2110, "F0Mx": 5779, "F1Mx": 6241,
              "F0Mn": 1200, "F1Mn": 1200, "F0Md": 1, "F1Md": 1}
    (source / "probe.json").write_text(json.dumps({"values": values}))
    status = {"cpu": 55, "gpu": 49, "palm": 29, "mode": "custom",
              "reason": "Cooling curve active", "targets": [2198, 2244],
              "time": dt.datetime.now(dt.timezone.utc).isoformat()}

    def run():
        result = subprocess.run([str(PLUGIN)], text=True, capture_output=True, timeout=6,
                                env={**os.environ, "COOLER_HOME": str(source),
                                     "SWIFTBAR_PLUGIN_CACHE_PATH": str(cache)})
        assert result.returncode == 0, result.stderr
        return result.stdout, (cache / "curves.html").read_text()

    (source / "status.json").write_text(json.dumps(status))
    menu, html = run()
    assert menu.startswith("55°C") and "Custom curve active" in menu
    assert "2,010 RPM" in menu and "2,198 RPM" in menu
    assert "CPU &amp; GPU" in html and "Palm rest" in html and "<svg" in html
    checks.append("Live temperatures, measured/target RPM, and both curve graphs")

    config["baselineRPM"] = 2000
    (source / "config.json").write_text(json.dumps(config))
    _, html = run()
    assert "2,000 RPM" in html
    checks.append("Curves use installed configuration")

    status.update(mode="automatic", reason="Another fan controller is running", targets=[])
    (source / "status.json").write_text(json.dumps(status))
    menu, _ = run()
    assert "Cooler paused" in menu and "Another fan controller" in menu
    assert "Custom curve active" not in menu and "Target  Managed outside Cooler" in menu
    checks.append("Yielding to another controller has no Cooler targets")
    values.update(F0Md=0, F1Md=0)
    (source / "probe.json").write_text(json.dumps({"values": values}))
    menu, _ = run()
    assert "Apple automatic" in menu
    checks.append("Hardware automatic mode is identified")

    status.update(mode="custom", time="2000-01-01T00:00:00Z")
    (source / "status.json").write_text(json.dumps(status))
    menu, html = run()
    assert menu.startswith("Cooler ?") and "Status is stale" in menu
    assert "Custom curve active" not in menu and "55.0°C" not in menu
    checks.append("Stale status never appears live")

    for content in [None, "{broken"]:
        if content is None:
            (source / "status.json").unlink()
        else:
            (source / "status.json").write_text(content)
        menu, _ = run()
        assert menu.startswith("Cooler ?") and "Status unavailable" in menu
    checks.append("Missing and corrupt status stay readable")

    status.update(time=dt.datetime.now(dt.timezone.utc).isoformat(), targets=[2198, 2244])
    (source / "status.json").write_text(json.dumps(status))
    (source / "stall").touch()
    menu, html = run()
    assert "Fan readings unavailable" in menu and "Custom curve active" not in menu
    assert "Curves unavailable" in html
    checks.append("Probe timeout is bounded and does not claim verified control")
    assert set((source / "calls").read_text().splitlines()) == {"probe"}
    checks.append("The only hardware command is read-only probe")

with tempfile.TemporaryDirectory(prefix="cooler-live-monitor-") as cache:
    result = subprocess.run([str(PLUGIN)], capture_output=True, text=True, timeout=6,
                            env={**os.environ, "SWIFTBAR_PLUGIN_CACHE_PATH": cache})
    assert result.returncode == 0, result.stderr
    assert "Actual" in result.stdout and "CPU" in result.stdout
    assert "Fan readings unavailable" not in result.stdout
    assert "CPU  Unavailable" not in result.stdout and "Status is stale" not in result.stdout
    ARTIFACTS.mkdir(exist_ok=True)
    # Keep the saved menu's curve link usable after the temporary cache is removed.
    (ARTIFACTS / "monitor-menu.txt").write_text(result.stdout.replace(
        (Path(cache) / "curves.html").as_uri(), (ARTIFACTS / "monitor-curves.html").as_uri()))
    (ARTIFACTS / "monitor-curves.html").write_text((Path(cache) / "curves.html").read_text())
    checks.append("Installed controller read successfully without administrator access")

report = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": checks, "passed": len(checks)}
(ARTIFACTS / "monitor-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
