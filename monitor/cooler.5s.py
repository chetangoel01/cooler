#!/opt/homebrew/bin/python3
# <xbar.title>Cooler</xbar.title>
# <xbar.version>1.0</xbar.version>
# <xbar.desc>Read-only temperatures, fan speeds, and installed cooling curves.</xbar.desc>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
# <swiftbar.runInBash>false</swiftbar.runInBash>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>

import datetime as dt
from html import escape
import json
import math
import os
from pathlib import Path
import subprocess

SOURCE = Path(os.environ.get("COOLER_HOME", "/Library/Application Support/Cooler"))
CACHE = Path(os.environ.get("SWIFTBAR_PLUGIN_CACHE_PATH",
                            str(Path.home() / "Library/Caches/CoolerMonitor")))


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def temperature(value):
    return f"{value:.1f}°C" if number(value) and 5 <= value <= 125 else "Unavailable"


def rpm(value):
    return f"{value:,.0f} RPM" if number(value) and 0 <= value <= 10000 else "Unavailable"


def line(value):
    # Dynamic status text cannot introduce SwiftBar actions or extra menu lines.
    return str(value).replace("|", "/").replace("\n", " ").replace("\r", " ")


def graph(title, points, bounds):
    low, high = points[0]["temperature"] - 5, points[-1]["temperature"] + 5
    width, height = 680, 270
    def x(value): return 64 + (value - low) / (high - low) * 584
    def y(value): return 222 - value / 7000 * 198
    pieces = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)} temperature to fan RPM curve">']
    for value in [2000, 4000, 6000]:
        pieces.append(f'<path class="grid" d="M64 {y(value):.1f}H648"/><text x="52" y="{y(value)+4:.1f}" text-anchor="end">{value:,}</text>')
    pieces.append('<text x="64" y="14">RPM</text>')
    for point in points:
        px = x(point["temperature"])
        pieces.append(f'<text x="{px:.1f}" y="250" text-anchor="middle">{point["temperature"]:g}°C</text>')
    expanded = [{"temperature": low, "fraction": points[0]["fraction"]}, *points,
                {"temperature": high, "fraction": points[-1]["fraction"]}]
    for i, (floor, maximum) in enumerate(bounds):
        path = " ".join(f'{x(p["temperature"]):.1f},{y(floor + (maximum-floor)*p["fraction"]):.1f}' for p in expanded)
        pieces.append(f'<polyline class="fan{i}" points="{path}"/>')
        for p in points:
            pieces.append(f'<circle class="dot{i}" cx="{x(p["temperature"]):.1f}" cy="{y(floor+(maximum-floor)*p["fraction"]):.1f}" r="3"/>')
    pieces.append('</svg><table><caption class="sr-only">Exact curve points</caption><thead><tr><th>Temperature</th><th>Left fan</th><th>Right fan</th></tr></thead><tbody>')
    for p in points:
        cells = ''.join(f'<td>{rpm(floor + (maximum-floor)*p["fraction"])}</td>' for floor, maximum in bounds)
        pieces.append(f'<tr><td>{p["temperature"]:g}°C</td>{cells}</tr>')
    pieces.append('</tbody></table>')
    return f'<section><h2>{escape(title)}</h2>{"".join(pieces)}</section>'


def curves(config, values):
    try:
        baseline = config["baselineRPM"]
        assert number(baseline) and 1200 <= baseline <= 2500
        bounds = [(max(baseline, values[f"F{i}Mn"]), values[f"F{i}Mx"]) for i in range(2)]
        assert all(number(a) and number(b) and 1000 <= a < b <= 10000 for a, b in bounds)
        for key in ["curve", "palmCurve"]:
            points = config[key]
            assert len(points) >= 2
            assert all(number(p["temperature"]) and 10 <= p["temperature"] <= 90 and
                       number(p["fraction"]) and 0 <= p["fraction"] <= 1 for p in points)
            assert all(a["temperature"] < b["temperature"] and a["fraction"] <= b["fraction"]
                       for a, b in zip(points, points[1:]))
        content = '<p class="legend"><span class="left">━ Left fan</span><span class="right">┄ Right fan</span></p>'
        content += graph("CPU & GPU", config["curve"], bounds)
        content += graph("Palm rest", config["palmCurve"], bounds)
        content += '<p class="note">The highest request from CPU, GPU, or palm rest sets both fans. Speeds rise immediately and fall gradually, so the current target can remain above these lines while the laptop cools. Palm readings represent two sensors, not the whole underside.</p>'
    except (KeyError, TypeError, ValueError, AssertionError):
        content = '<p>Curves unavailable. The installed profile and fan limits must both be readable.</p>'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cooler · Cooling curves</title><style>
:root{color-scheme:light dark;--bg:oklch(98% .006 230);--ink:oklch(24% .012 230);--muted:oklch(47% .014 230);--grid:oklch(86% .008 230);--accent:oklch(48% .12 240)}
@media(prefers-color-scheme:dark){:root{--bg:oklch(19% .009 230);--ink:oklch(92% .008 230);--muted:oklch(72% .012 230);--grid:oklch(34% .012 230);--accent:oklch(77% .10 240)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,sans-serif;font-variant-numeric:tabular-nums}main{max-width:744px;margin:48px auto;padding:0 28px 32px}h1{font-size:28px;letter-spacing:-.025em;margin:4px 0 8px}h2{font-size:19px;margin:0 0 18px}.eyebrow{color:var(--muted);font-size:13px}p{max-width:68ch;margin:8px 0 20px}section{margin:36px 0 48px}svg{width:100%;height:auto;overflow:visible}svg text{fill:var(--muted);font-size:12px}.grid{stroke:var(--grid);stroke-width:1}.fan0,.fan1{fill:none;stroke-width:2.5;stroke-linejoin:round}.fan0{stroke:var(--accent)}.fan1{stroke:var(--ink);stroke-dasharray:7 5}.dot0{fill:var(--accent)}.dot1{fill:var(--ink)}.left{color:var(--accent)}.legend{display:flex;gap:24px;font-size:13px}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:right;padding:9px 0;border-bottom:1px solid var(--grid)}td:first-child,th:first-child{text-align:left}th{font-weight:500;color:var(--muted)}.note{font-size:13px;color:var(--muted)}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}@media(max-width:480px){main{margin-top:24px;padding:0 18px 24px}}
</style><main><div class="eyebrow">COOLER / INSTALLED PROFILE</div><h1>Cooling curves</h1><p>Requested fan speed at each temperature. These are your configured curves, not a temperature history.</p>''' + content + '<footer class="note">Read-only view. Open again from the menu bar after changing the profile.</footer></main></html>'


def main():
    status = read_json(SOURCE / "status.json")
    try:
        sample_time = dt.datetime.fromisoformat(status["time"].replace("Z", "+00:00"))
        fresh = -2 <= (dt.datetime.now(dt.timezone.utc) - sample_time).total_seconds() <= 10
    except (KeyError, TypeError, ValueError, AttributeError):
        fresh = False
    values = {}
    try:
        result = subprocess.run([str(SOURCE / "cooler"), "probe"], capture_output=True,
                                text=True, timeout=2, check=True)
        values = json.loads(result.stdout)["values"]
        if not isinstance(values, dict): values = {}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    fan_readings = all(number(values.get(f"F{i}{key}")) for i in range(2) for key in ["Ac", "Md"])
    active = fresh and status.get("mode") == "custom" and fan_readings and all(values[f"F{i}Md"] == 1 for i in range(2))
    automatic = fresh and status.get("mode") == "automatic" and fan_readings and all(values[f"F{i}Md"] in [0, 3] for i in range(2))
    cpu = status.get("cpu") if fresh else None
    label = f"{cpu:.0f}°C" if temperature(cpu) != "Unavailable" else "Cooler ?"
    print(f'{label} | sfimage=fanblades dropdown=false tooltip="Cooler · CPU temperature"')
    print("---")
    if not fresh:
        state = "Status is stale" if status else "Status unavailable"
    elif active:
        state = "Custom curve active"
    elif automatic:
        state = "Apple automatic"
    elif status.get("mode") == "custom":
        state = "Custom curve requested; fan mode unverified"
    else:
        state = "Cooler paused"
    print(f"Cooler · {state}")
    if fresh and not active and status.get("reason"):
        print(f"{line(status['reason'])} | size=12")
    if not fresh:
        print("Waiting for a fresh controller update | size=12")
    print("---")
    for key, name in [("cpu", "CPU"), ("gpu", "GPU"), ("palm", "Palm rest")]:
        print(f"{name}  {temperature(status.get(key) if fresh else None)}")
    print("---")
    targets = status.get("targets", [])
    for i, side in enumerate(["Left", "Right"]):
        print(f"{side} fan · Actual  {rpm(values.get(f'F{i}Ac'))}")
        target = rpm(targets[i]) if active and isinstance(targets, list) and len(targets) == 2 else (
            "Apple automatic" if automatic else "Managed outside Cooler" if fresh and status.get("mode") == "automatic" else "Unavailable")
        print(f"Target  {target} | size=12")
    if not fan_readings:
        print("Fan readings unavailable | size=12")
    print("---")
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        page = CACHE / "curves.html"
        html = curves(read_json(SOURCE / "config.json"), values)
        if not page.exists() or page.read_text() != html:
            temporary = CACHE / "curves.tmp"
            temporary.write_text(html)
            temporary.replace(page)
        print(f"View cooling curves… | href={page.as_uri()}")
    except OSError:
        print("Curve view unavailable | size=12")
    print("Refresh now | refresh=true")


if __name__ == "__main__":
    main()
