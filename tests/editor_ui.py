#!/usr/bin/env python3
"""End-to-end checks of the installed Cooler Curves editor, driven through macOS
accessibility. Run: python3 tests/editor_ui.py  (the runner needs Accessibility and
Automation access to System Events; from Terminal, grant them in System Settings).

Failure inventory, written before the fix: removing a point crashes the editor (a
row outlives the shorter curve and reads past its end); switching between curves
with different point counts crashes; a demand edit in progress lands in the other
sensor curve after switching tabs; the test changes the installed or saved curve;
the test discards a draft the user has open; a crash dialog or editor window is
left on screen. Layout pass, written before its code: a point is hidden below the
list with no visible way to reach it.

It never presses Save & apply. It refuses to start while the editor is open. It
uses only accessibility actions on the editor's own controls, never keystrokes or
clicks at screen positions: macOS does not bring the editor to the front for an
automation client, so typed or positional input could reach another app. The
tab-switch edit case is therefore covered by code review, not by this test.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
APP = Path.home() / "Library/Application Support/Cooler/Cooler Curves.app"
PLUGIN = Path.home() / "Library/Application Support/SwiftBar/Plugins/cooler.5s.py"
REPORTS = Path.home() / "Library/Logs/DiagnosticReports"
WATCHED = [Path("/Library/Application Support/Cooler/config.json"),
           Path.home() / "Library/Application Support/Cooler/custom.json"]
FIND = '''
on findElement(roleName, label)
    tell application "System Events" to tell process "CoolerCurves"
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
    return subprocess.run(["pgrep", "-x", "CoolerCurves"], capture_output=True).returncode == 0


def click(role, label):
    ax(f'tell application "System Events" to click (my findElement("{role}", "{label}"))')
    time.sleep(1.5)
    assert running(), f"The editor crashed after clicking {label}"


def value(label):
    return ax(f'tell application "System Events" to return value of (my findElement("AXTextField", "{label}"))')


def shown(fraction):
    # The editor shows demand with at most one decimal place.
    return f"{fraction * 100:.1f}".rstrip("0").rstrip(".")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


assert not running(), "Close Cooler Curves first; this test will not discard an open draft."
reports = {p.name for p in REPORTS.glob("CoolerCurves-*")}
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
            value("Point 1 temperature")
            break
        except RuntimeError:
            assert time.time() < deadline, "The editor did not load its curves"
            time.sleep(0.5)

    geometry = ax(f'''tell application "System Events" to tell process "CoolerCurves"
    set lastField to my findElement("AXTextField", "Point {len(cpu)} temperature")
    set {{fx, fy}} to position of lastField
    set {{fw, fh}} to size of lastField
    set listArea to missing value
    set allElements to entire contents of window 1
    repeat with i from 1 to count of allElements
        try
            if role of (item i of allElements) is "AXScrollArea" then set listArea to item i of allElements
        end try
    end repeat
    set {{sx, sy}} to position of listArea
    set {{sw, sh}} to size of listArea
    return ((round fy) as text) & "," & ((round fh) as text) & "," & ((round sy) as text) & "," & ((round sh) as text)
end tell''')
    fy, fh, sy, sh = map(int, geometry.split(","))
    details["last_point_bottom"], details["list_bottom"] = fy + fh, sy + sh
    assert sy - 1 <= fy and fy + fh <= sy + sh + 1, f"Point {len(cpu)} is hidden below the list: {details}"
    checks.append(f"All {len(cpu)} CPU & GPU points are visible without scrolling")

    click("AXRadioButton", "Palm rest")
    details["palm_point_2_demand"] = value("Point 2 demand percent")
    assert details["palm_point_2_demand"] == shown(palm[1]["fraction"]), details
    click("AXButton", "Remove point 1")
    try:
        value(f"Point {len(palm)} temperature")
        raise AssertionError("Remove point did not shorten the palm curve")
    except RuntimeError:
        pass
    checks.append("Removing a point keeps the editor running and shortens the curve")

    for tab in ["CPU & GPU", "Palm rest", "CPU & GPU"]:
        click("AXRadioButton", tab)
    click("AXButton", "Remove point 2")
    checks.append("Switching between curves with different point counts and removing again keeps it running")
finally:
    if running():
        subprocess.run(["osascript", "-e", 'tell application id "com.chetangoel.cooler-curves" to quit'],
                       capture_output=True, timeout=30)
        time.sleep(2)

assert not running(), "The editor is still open"
assert {p.name for p in REPORTS.glob("CoolerCurves-*")} == reports, "A new crash report was written"
assert subprocess.run(["pgrep", "-x", "Problem Reporter"], capture_output=True).returncode != 0
assert [digest(p) for p in WATCHED] == hashes, "The installed or saved curve changed"
checks.append("Closed without applying; no crash report, dialog, or change to the installed or saved curve")

report = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": checks, "passed": len(checks),
          "details": details, "applied_changes": False}
(ROOT / "artifacts/editor-ui-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
