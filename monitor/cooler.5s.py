#!/opt/homebrew/bin/python3
# <xbar.title>Cooler</xbar.title>
# <xbar.version>1.3</xbar.version>
# <xbar.desc>Temperatures, fan speeds, curves, and cooling profiles.</xbar.desc>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
# <swiftbar.runInBash>false</swiftbar.runInBash>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>

import datetime as dt
import argparse
import fcntl
from html import escape
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

INSTALLED = Path('/Library/Application Support/Cooler')
SOURCE = Path(os.environ.get("COOLER_HOME", str(INSTALLED)))
LAUNCHCTL = os.environ.get('COOLER_LAUNCHCTL', '/bin/launchctl')
CACHE = Path(os.environ.get("SWIFTBAR_PLUGIN_CACHE_PATH",
                            str(Path.home() / "Library/Caches/CoolerMonitor")))
ACTION_STATE = Path.home() / 'Library/Caches/CoolerMonitor'
USER_DATA = Path.home() / 'Library/Application Support/Cooler'
EDITABLE = {'baselineRPM', 'curve', 'palmCurve'}
# SwiftBar grays out rows without an action; an explicit light/dark color keeps readings legible.
INK = 'color=#1d1d1f,#ececec'
MUTED = 'color=#6e6e73,#98989d'
RESUMING = {'Waiting for three healthy samples', 'Resuming after a gap; collecting fresh samples'}
NOTES = {'Waiting for administrator approval': 'Waiting for administrator approval…',
         'Checking the new setting': 'Checking the new setting…',
         'Change cancelled': 'Change cancelled',
         'Setting saved': 'Saved; waiting for Cooler to confirm'}

# Fractions use each fan's available range above the profile's baseline.
PROFILES = {
    'quiet': (1200, [(50,0),(60,.05),(70,.2),(80,.5),(90,1)], [(32,0),(35,.1),(38,.35),(40,1)]),
    'balanced': (1500, [(45,0),(55,.05),(65,.2),(75,.5),(85,.8),(90,1)], [(31,0),(34,.15),(37,.4),(40,1)]),
    'cooler': (1800, [(45,0),(55,.1),(65,.3),(75,.65),(85,1)], [(30,0),(33,.2),(36,.5),(40,1)]),
    'max': (1800, [(10,1),(90,1)], [(10,1),(90,1)]),
}


def profile_config(name, config):
    baseline, chip, palm = PROFILES[name]
    return {**config, 'baselineRPM':baseline,
            'curve':[{'temperature':t,'fraction':f} for t,f in chip],
            'palmCurve':[{'temperature':t,'fraction':f} for t,f in palm]}


def profile_name(config):
    return next(('Max cooling' if name=='max' else name.title()
                 for name in PROFILES if profile_config(name,config)==config), 'Custom')


def custom_config(edited, config):
    # Only the comfort controls are editable. Sensors and recovery stay installed.
    if not isinstance(edited,dict) or set(edited)!=EDITABLE:
        raise ValueError('A custom curve must contain only the baseline and the two curves.')
    if not number(edited['baselineRPM']) or not 1200 <= edited['baselineRPM'] <= 2500:
        raise ValueError('Baseline must be between 1,200 and 2,500 RPM.')
    for key in ['curve','palmCurve']:
        points=edited[key]
        if not isinstance(points,list) or not 2 <= len(points) <= 20:
            raise ValueError('Each curve needs 2 to 20 points.')
        if not all(isinstance(p,dict) and set(p)=={'temperature','fraction'} and
                   number(p['temperature']) and 10 <= p['temperature'] <= 90 and
                   number(p['fraction']) and 0 <= p['fraction'] <= 1 for p in points):
            raise ValueError('Curve points need temperatures from 10 to 90°C and demand from 0 to 100%.')
        if points[-1]['fraction']!=1 or any(a['temperature']>=b['temperature'] or a['fraction']>b['fraction']
                                          for a,b in zip(points,points[1:])):
            raise ValueError('Temperatures must increase, demand cannot decrease, and the last point must reach 100%.')
    return {**config,**edited}


def editor_data():
    config=read_json(SOURCE/'config.json')
    result=subprocess.run([str(SOURCE/'cooler'),'probe'],capture_output=True,text=True,check=True,timeout=3)
    values=json.loads(result.stdout)['values']
    limits=[{'minimum':values[f'F{i}Mn'],'maximum':values[f'F{i}Mx']} for i in range(2)]
    if not all(number(f['minimum']) and number(f['maximum']) and 1000 <= f['minimum'] < f['maximum'] <= 10000 for f in limits):
        raise ValueError('Fan limits are unavailable. Reopen the editor when readings return.')
    saved=read_json(USER_DATA/'custom.json')
    if saved:
        saved=custom_config(saved,config)
    return {'current':config,'saved':saved or None,'limits':limits,
            'presets':{name:profile_config(name,config) for name in ['quiet','balanced','cooler']}}


def service_state():
    try:
        result = subprocess.run([LAUNCHCTL,'print','system/com.chetangoel.cooler'],capture_output=True,text=True,timeout=2)
        pid = re.search(r'\bpid = (\d+)',result.stdout) if result.returncode==0 else None
        disabled = subprocess.run([LAUNCHCTL,'print-disabled','system'],capture_output=True,text=True,timeout=2,check=True)
        setting = re.search(r'"com\.chetangoel\.cooler"\s*=>\s*(disabled|enabled|true|false)',disabled.stdout)
        return (int(pid[1]) if pid else None, setting[1] in ['disabled','true'] if setting else None)
    except (OSError,subprocess.SubprocessError):
        return None, None


def action_script(name, config, edited=None):
    """Fixed system operations; configuration is shell-quoted data, never code."""
    proposal = (None if name=='automatic' else custom_config(edited,config) if name=='custom'
                else profile_config(name,config))
    script = '''set -eu
umask 077
base='/Library/Application Support/Cooler'
job=system/com.chetangoel.cooler
plist=/Library/LaunchDaemons/com.chetangoel.cooler.plist
[ -x "$base/cooler" ] && [ -f "$plist" ] || { echo 'Cooler is not installed.' >&2; exit 1; }
if /usr/bin/pgrep -x 'Macs Fan Control|Stats|TG Pro|smcFanControl|macfan' >/dev/null; then
  echo 'Quit the other fan controller before switching.' >&2; exit 1
else
  result=$?
  [ "$result" = 1 ] || { echo 'Cannot check for competing controllers.' >&2; exit 1; }
fi
stage=$(/usr/bin/mktemp -d "$base/.profile.XXXXXX")
changing=0
cleanup() {
  result=$?
  trap - EXIT
  if [ "$result" != 0 ] && [ "$changing" = 1 ]; then
    /bin/launchctl disable "$job" || true
    if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job" || true; fi
    "$base/cooler" auto || true
    if [ -f "$stage/previous.json" ]; then /bin/mv -f "$stage/previous.json" "$base/config.json"; fi
    echo 'Change failed. Previous profile restored; Apple automatic recovery was attempted. Check the menu status.' >&2
  fi
  /bin/rm -rf "$stage"
  exit "$result"
}
trap cleanup EXIT
'''
    if proposal is not None:
        payload = shlex.quote(json.dumps(proposal, separators=(',',':'),allow_nan=False))
        script += f'''/usr/bin/printf '%s\\n' {payload} > "$stage/next.json"
"$base/cooler" check "$stage/next.json" >/dev/null
/bin/cp -p "$base/config.json" "$stage/previous.json"
/usr/sbin/chown root:wheel "$stage/next.json"
/bin/chmod 644 "$stage/next.json"
'''
    script += '''changing=1
/bin/launchctl disable "$job"
if /bin/launchctl print "$job" >/dev/null 2>&1; then /bin/launchctl bootout "$job"; fi
"$base/cooler" auto
'''
    if proposal is not None:
        script += '''/bin/mv -f "$stage/next.json" "$base/config.json"
/bin/launchctl enable "$job"
/bin/launchctl bootstrap system "$plist"
'''
    return {'config':proposal,'script':script}


def save_action(message):
    temporary = ACTION_STATE/'action.tmp'
    temporary.write_text(json.dumps({'message':message,'time':time.time()}))
    temporary.replace(ACTION_STATE/'action.json')


def apply_profile(name, edited=None):
    # Fixture overrides are read-only. Authenticated operations always use real paths.
    if SOURCE != INSTALLED or LAUNCHCTL != '/bin/launchctl':
        raise ValueError('Profile changes cannot use fixture overrides.')
    ACTION_STATE.mkdir(parents=True,exist_ok=True)
    with (ACTION_STATE/'action.lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok':False,'message':'Another change is in progress. Try again when it finishes.'}
        proposal = action_script(name,read_json(INSTALLED/'config.json'),edited)
        # Stage the saved curve before authorization, but commit it only after installation succeeds.
        saved=None
        if name=='custom':
            USER_DATA.mkdir(parents=True,exist_ok=True)
            saved=USER_DATA/'custom.tmp'
            saved.write_text(json.dumps(edited,allow_nan=False,indent=2)+'\n')
        save_action('Waiting for administrator approval…')
        program = 'on run argv\nreturn do shell script (item 1 of argv) with administrator privileges\nend run'
        result = subprocess.run(['/usr/bin/osascript','-e',program,proposal['script']],capture_output=True,text=True)
        if result.returncode:
            if saved: saved.unlink(missing_ok=True)
            if '(-128)' in result.stderr:
                message='Change cancelled. Previous selection kept.'
            else:
                message='Change failed: '+result.stderr.strip()
            save_action(message)
            return {'ok':False,'message':message}
        if saved: saved.replace(USER_DATA/'custom.json')
        save_action('Checking the new setting…')
        for _ in range(15):
            pid, disabled = service_state()
            status = read_json(INSTALLED/'status.json')
            if name=='automatic' and disabled and pid is None:
                message='Apple automatic selected. Cooler will stay off after restart.'
                save_action(message)
                return {'ok':True,'message':message}
            if name!='automatic' and pid and status.get('pid')==pid and status.get('mode')=='custom':
                if read_json(INSTALLED/'config.json')==proposal['config']:
                    message=('Max cooling active until you switch modes.' if name=='max' else
                             name.title()+' curve active. Saved for future restarts.')
                    save_action(message)
                    return {'ok':True,'message':message}
            time.sleep(1)
        message='Setting saved; control is not yet confirmed. Check the SwiftBar status.'
        save_action(message)
        return {'ok':False,'message':message}


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def temperature(value):
    return f"{value:.0f}°" if number(value) and 5 <= value <= 125 else "Unavailable"


def rpm(value):
    return f"{value:,.0f} RPM" if number(value) and 0 <= value <= 10000 else "Unavailable"


def pair(values):
    # Left and right fans in one cell.
    if not isinstance(values, list) or len(values) != 2 or not all(number(v) and 0 <= v <= 10000 for v in values):
        return "Unavailable"
    return " · ".join(f"{v:,.0f}" for v in values) + " RPM"


def line(value):
    # Dynamic status text cannot introduce SwiftBar actions, extra menu lines, or tab columns.
    return str(value).replace("|", "/").replace("\n", " ").replace("\r", " ").replace("\t", " ")


def hint(name, saved):
    if name == 'automatic': return 'macOS controls the fans and Cooler stays off'
    if name == 'max': return 'Both fans at full speed until you switch modes'
    try:
        baseline, chip = ((saved['baselineRPM'], [(p['temperature'], p['fraction']) for p in saved['curve']])
                          if name == 'custom' else PROFILES[name][:2])
        full = next(t for t, f in chip if f >= 1)
        return line(f"{baseline:,.0f} RPM minimum, full speed at {full:g}°C").replace('"', "'")
    except (KeyError, TypeError, ValueError, StopIteration):
        return 'Your saved curve'


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
</style><main><div class="eyebrow">COOLER / INSTALLED PROFILE</div><h1>Cooling curves</h1>''' + f'<p>{profile_name(config)} profile. Requested fan speed at each temperature. These are your configured curves, not a temperature history.</p>' + content + '<footer class="note">Read-only view. Open again from the menu bar after changing the profile.</footer></main></html>'


def main():
    config = read_json(SOURCE / 'config.json')
    pid, disabled = service_state()
    status = read_json(SOURCE / "status.json")
    try:
        sample_time = dt.datetime.fromisoformat(status["time"].replace("Z", "+00:00"))
        fresh = -2 <= (dt.datetime.now(dt.timezone.utc) - sample_time).total_seconds() <= 10
        fresh = fresh and pid is not None and status.get('pid')==pid
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
    automatic = fan_readings and all(values[f"F{i}Md"] in [0, 3] for i in range(2)) and (
        (fresh and status.get('mode')=='automatic') or (disabled is True and pid is None))
    temperatures = {}
    for group in ['cpu','gpu','palm']:
        keys = config.get(group+'Keys',[])
        readings = [values.get(key) for key in keys]
        valid = readings and all(number(v) and 5 <= v <= 125 for v in readings)
        temperatures[group] = max(readings) if valid else status.get(group) if fresh else None
    selected = 'automatic' if disabled is True else profile_name(config).lower() if pid else None
    if selected=='max cooling': selected='max'
    mode, reason = status.get('mode'), line(status.get('reason', ''))
    resuming = fresh and mode == 'automatic' and reason in RESUMING
    # A warning means the checked mode is not what the fans are doing right now.
    if disabled is True and pid is None:
        warning = None if automatic else 'Cooler is off; fan mode unconfirmed'
    elif not fresh:
        warning = 'No recent update from Cooler' if status else 'Cooler status unavailable'
    elif active or resuming:
        warning = None
    elif mode == 'automatic':
        warning = {'Another fan controller is running': 'Paused while another fan app is open',
                   'macOS reports critical thermal pressure': 'Paused: macOS reports critical heat'}.get(reason, 'Paused: '+reason)
    else:
        warning = 'Fan control not confirmed'
    cpu = temperatures['cpu']
    label = temperature(cpu) if temperature(cpu) != "Unavailable" else "?"
    # Solid glyphs match the menu bar; the icon itself tells the state at a glance.
    icon = ('exclamationmark.triangle.fill' if warning else 'wind' if active and selected == 'max' else
            'fan.badge.automatic.fill' if automatic and disabled is True else 'fan.fill')
    print(f'{label} | sfimage={icon} dropdown=false tooltip="CPU temperature"')
    print("---")
    action = read_json(ACTION_STATE/'action.json')
    message = line(action.get('message', ''))
    age = time.time()-action['time'] if number(action.get('time')) else math.inf
    # The checkmark shows a successful change; only failures and changes in progress get a row.
    note = next((text for prefix, text in NOTES.items() if message.startswith(prefix)), None)
    if message.startswith('Change failed') and 0 <= age < 1800:
        print(f"{message} | sfimage=exclamationmark.triangle {INK} length=48")
    elif note and 0 <= age < 120:
        print(f"{note} | {MUTED}")
    if warning:
        print(f"{warning} | sfimage=exclamationmark.triangle {INK} length=48")
    elif resuming:
        print(f"Resuming control… | {MUTED}")
    for key, name in [("cpu", "CPU"), ("gpu", "GPU"), ("palm", "Palm rest")]:
        print(f"{name}\t{temperature(temperatures[key])} | {INK}")
    print(f"Fans\t{pair([values.get(f'F{i}Ac') for i in range(2)])} | {INK}")
    # Holding Option swaps measured speeds for Cooler's targets, shown only while it is verified in control.
    target = (pair(status.get('targets')) if active else 'Set by macOS' if automatic else
              'Not set by Cooler' if fresh and mode == 'automatic' else 'Unavailable')
    print(f"Targets\t{target} | {INK} alternate=true")
    print('---')
    saved = read_json(USER_DATA/'custom.json')
    descriptions = {'automatic':'Apple Automatic','quiet':'Quiet','balanced':'Balanced','cooler':'Cooler',
                    'max':'Max Cooling'}
    if saved: descriptions['custom']='Custom Curve'
    script_path = json.dumps(str(Path(__file__).resolve()))
    for name,title in descriptions.items():
        checked = str(selected==name).lower()
        print(f'{title} | bash=/opt/homebrew/bin/python3 param0={script_path} param1=--apply-profile param2={name} terminal=false refresh=true checked={checked} tooltip="{hint(name, saved)}"')
    print('---')
    print(f'Edit Custom Curve… | bash=/opt/homebrew/bin/python3 param0={script_path} param1=--edit-curves terminal=false refresh=true')
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        page = CACHE / "curves.html"
        html = curves(config, values)
        if not page.exists() or page.read_text() != html:
            temporary = CACHE / "curves.tmp"
            temporary.write_text(html)
            temporary.replace(page)
        # Holding Option offers the read-only curves page in place of the editor.
        print(f"View Current Curves… | href={page.as_uri()} alternate=true")
    except OSError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Cooler menu and profile controls')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply-profile',choices=['automatic','custom',*PROFILES])
    actions.add_argument('--preview-profile',choices=['automatic',*PROFILES])
    actions.add_argument('--apply-custom',type=Path)
    actions.add_argument('--preview-custom',type=Path)
    actions.add_argument('--editor-data',action='store_true')
    actions.add_argument('--edit-curves',action='store_true')
    args = parser.parse_args()
    try:
        if args.preview_profile:
            print(json.dumps(action_script(args.preview_profile,read_json(SOURCE/'config.json'))))
        elif args.preview_custom:
            print(json.dumps(action_script('custom',read_json(SOURCE/'config.json'),read_json(args.preview_custom))))
        elif args.apply_custom:
            print(json.dumps(apply_profile('custom',read_json(args.apply_custom))))
        elif args.apply_profile:
            edited=read_json(USER_DATA/'custom.json') if args.apply_profile=='custom' else None
            print(json.dumps(apply_profile(args.apply_profile,edited)))
        elif args.editor_data:
            print(json.dumps(editor_data()))
        elif args.edit_curves:
            subprocess.run(['/usr/bin/open','-b','com.chetangoel.cooler'],check=True)
        else:
            main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        import sys
        print(json.dumps({'ok':False,'message':str(error)}))
        sys.exit(1)
