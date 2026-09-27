#!/usr/bin/env python3
"""End-to-end checks of the installed Cooler Curves editor, driven through macOS
accessibility. Run: python3 tests/editor_ui.py  (the runner needs Accessibility and
Automation access to System Events; from Terminal, grant them in System Settings).

Failure inventory, written before the fix: removing a point crashes the editor (a
row outlives the shorter curve and reads past its end); switching between curves
with different point counts crashes; a demand edit in progress lands in the other
sensor curve after switching tabs; the test changes the installed or saved curve;
the test discards a draft the user has open; a crash dialog or editor window is
left on screen. Graph-first redesign, written before its code:
the window is larger than it needs to be; a point can only be reached with a mouse
on the chart; the selected point points past the end after a removal, tab switch,
or preset; a drag crosses a neighbor or moves the last point off full speed; a
typed value produces an invalid curve; the "now" marker shows a stale reading as
current; a pending field edit lands on the wrong point after Presets or Apply.

It never presses Save & apply. It refuses to start while the editor is open. It
uses only accessibility actions on the editor's own controls, never keystrokes or
clicks at screen positions: macOS does not bring the editor to the front for an
automation client, so typed or positional input could reach another app. The
tab-switch edit case is therefore covered by code review, not by this test.
"""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get("COOLER_APP", "/Applications/Cooler.app"))
PLUGIN = Path.home() / "Library/Application Support/SwiftBar/Plugins/cooler.5s.py"
REPORTS = Path.home() / "Library/Logs/DiagnosticReports"
WATCHED = [Path("/Library/Application Support/Cooler/config.json"),
           Path.home() / "Library/Application Support/Cooler/custom.json"]
FIND = '''
on findElement(roleName, label)
    tell application "System Events" to tell process "Cooler"
        set allElements to entire contents of window 1
        repeat with i from 1 to count of allElements
            set e to item i of allElements
            try
                if role of e is roleName then
                    set h to ""
                    try
                        set h to (value of attribute "AXHelp" of e) as text
                    end try
                    if (description of e) is label or h is label then return item i of allElements
                end if
            end try
        end repeat
    end tell
    error "Missing " & label
end findElement
'''
checks, details = [], {}


def ax(body):
    result = subprocess.run(["osascript", "-e", FIND + body], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def running():
    return subprocess.run(["pgrep", "-x", "Cooler"], capture_output=True).returncode == 0


def click(role, label):
    ax(f'tell application "System Events" to click (my findElement("{role}", "{label}"))')
    time.sleep(1.5)
    assert running(), f"The editor crashed after clicking {label}"


def value(label):
    return ax(f'tell application "System Events" to return value of (my findElement("AXTextField", "{label}"))')


def degrees(temperature):
    # The editor shows temperatures with at most one decimal place.
    return f"{temperature:.1f}".rstrip("0").rstrip(".")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


assert not running(), "Close Cooler Curves first; this test will not discard an open draft."
reports = {p.name for p in REPORTS.glob("Cooler*")}
hashes = [digest(p) for p in WATCHED]
# The draft the editor opens with, chosen by the editor's own rule.
data = json.loads(subprocess.run(["/opt/homebrew/bin/python3", str(PLUGIN), "--editor-data"],
                                 capture_output=True, text=True, check=True).stdout)
draft = ((data["saved"] or data["presets"]["cooler"]) if all(p["fraction"] == 1 for p in data["current"]["curve"])
         else data["current"])
cpu, palm = draft["curve"], draft["palmCurve"]
assert len(cpu) >= 3 and len(palm) >= 3, "The test needs at least three points on each curve"
subprocess.run(["open", "-a", str(APP)], check=True)
try:
    deadline = time.time() + 20
    while True:
        try:
            value("Selected point temperature")
            break
        except RuntimeError:
            assert time.time() < deadline, "The editor did not load its curves"
            time.sleep(0.5)

    size = ax('''tell application "System Events" to tell process "Cooler" to set windowSize to size of window 1
return ((item 1 of windowSize) as text) & "," & ((item 2 of windowSize) as text)''')
    width, height = map(int, size.split(","))
    details["window"] = f"{width}x{height}"
    assert width <= 660 and height <= 420, f"The window is larger than it needs to be: {details}"
    checks.append(f"The editor opens at {width} x {height} points")

    # The first point starts selected, so + and − work without touching the graph.
    assert value("Selected point temperature") == degrees(cpu[0]["temperature"])
    click("AXButton", "Remove point")
    assert value("Selected point temperature") == degrees(cpu[1]["temperature"]), "Remove point did not remove the selected point"
    rest = cpu[1:]
    gap = max(range(len(rest) - 1), key=lambda i: rest[i + 1]["temperature"] - rest[i]["temperature"])
    click("AXButton", "Add point")
    added = math.floor((rest[gap]["temperature"] + rest[gap + 1]["temperature"]) / 2 + 0.5)
    assert value("Selected point temperature") == degrees(added), "Add point did not add and select a point in the widest gap"
    checks.append("The + and − buttons remove and add points without touching the graph")

    click("AXRadioButton", "Palm rest")
    assert value("Selected point temperature") == degrees(palm[0]["temperature"]), "Palm rest did not select its first point"
    click("AXButton", "Remove point")
    assert value("Selected point temperature") == degrees(palm[1]["temperature"])
    checks.append("Removing a point on the palm curve keeps the editor running")

    for tab in ["CPU & GPU", "Palm rest", "CPU & GPU"]:
        click("AXRadioButton", tab)
    click("AXButton", "Remove point")
    checks.append("Switching between curves with different point counts and removing again keeps it running")
finally:
    if running():
        subprocess.run(["osascript", "-e", 'tell application id "com.chetangoel.cooler" to quit'],
                       capture_output=True, timeout=30)
        time.sleep(2)

assert not running(), "The editor is still open"
assert {p.name for p in REPORTS.glob("Cooler*")} == reports, "A new crash report was written"
assert subprocess.run(["pgrep", "-x", "Problem Reporter"], capture_output=True).returncode != 0
assert [digest(p) for p in WATCHED] == hashes, "The installed or saved curve changed"
checks.append("Closed without applying; no crash report, dialog, or change to the installed or saved curve")

report = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": checks, "passed": len(checks),
          "details": details, "applied_changes": False}
(ROOT / "artifacts/editor-ui-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
