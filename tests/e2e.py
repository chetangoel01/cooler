#!/usr/bin/env python3
"""Exercise the shipping CLI with deterministic input; writes an inspectable report.

Supporting every M-series chip, written before its code: the chip generation is
misread from the brand string ("Apple M1 Max", a bare "Apple M6", a future
"Apple M10"), so a Mac gets another generation's sensor keys; a listed key missing
on one variant is required anyway, so Cooler never runs there; a chip without a
sensor map (an M7, an Intel CPU) or a Mac without fans is controlled anyway; a one-fan
Mac is driven as if it had two; the manual-mode key is written under the wrong
spelling (F0Md on the M1 Max, F0md on the M5 Pro); a Mac without palm sensors is
refused; an installed profile from an older version, which still names a model
and sensors, stops loading.
"""
import json, pathlib, subprocess, tempfile, datetime
root = pathlib.Path(__file__).resolve().parents[1]
exe = root / 'build/cooler'
config = json.loads((root / 'config.json').read_text())
checks = []

def run(frames, cfg=config):
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d/'config.json').write_text(json.dumps(cfg))
        (d/'frames.json').write_text(json.dumps(frames))
        p = subprocess.run([str(exe), 'replay', str(d/'config.json'), str(d/'frames.json')], text=True, capture_output=True)
        return p, [json.loads(s) for s in p.stdout.splitlines() if s.strip()]

def frame(cpu=40, gpu=40, **extra):
    return {'cpu': cpu, 'gpu': gpu, 'palm': 29, **extra}

def check(name, condition):
    checks.append({'name': name, 'passed': bool(condition)})
    assert condition, name

p, r = run([frame()])
check('gentle baseline on both fans', p.returncode == 0 and r[0]['targets'] == [2000,2000])
p, r = run([frame(40,85)])
check('GPU alone requests full cooling', r[0]['targets'] == [8400,9072])
p, r = run([frame(85,40)])
check('CPU alone requests full cooling', r[0]['targets'] == [8400,9072])
p, r = run([frame(85), frame(40)])
check('fall rate limits rapid fan changes', r[1]['targets'] == [8320,8992])
p, r = run([frame(), frame(85)])
check('heat increase is immediate', r[1]['targets'] == [8400,9072])
p, r = run([frame(65), {'cpu': None, 'gpu': 50}, frame(65)])
check('missing sensor restores auto and needs healthy recovery samples', r[1]['mode'] == 'automatic' and r[2]['mode'] == 'automatic')
p, r = run([frame(65), frame(0)])
check('invalid temperature restores auto', r[1]['mode'] == 'automatic')
p, r = run([frame(65), frame(65, conflict=True), frame(65)])
check('another controller suspends ours', r[1]['mode'] == 'automatic' and r[2]['mode'] == 'automatic')
p, r = run([frame(65, failFan=1)])
check('partial write failure restores both fans', r[0]['mode'] == 'automatic' and r[0]['restoredFans'] == [0,1])
p, r = run([frame(85), frame(40, elapsed=120)])
check('wake gap discards previous control state', r[1]['mode'] == 'automatic')
p, r = run([frame(65, maxRPM=[1000,9072])])
check('invalid hardware fan limits refuse control', r[0]['mode'] == 'automatic')
bad = {**config, 'baselineRPM': 20000}
p, _ = run([frame()], bad)
check('malformed curve configuration rejected', p.returncode != 0)
p, r = run([frame(palm=40)])
check('warm palm rest alone requests full cooling', r[0]['targets'] == [8400,9072])
p, r = run([frame(palm=None)])
check('a Mac without palm sensors cools on CPU and GPU alone', r[0]['mode'] == 'custom' and r[0]['targets'] == [2000,2000])
p, r = run([frame(85, maxRPM=[6000], minRPM=[1200])])
check('a one-fan Mac gets one target', r[0]['mode'] == 'custom' and r[0]['targets'] == [6000])
p, r = run([frame(65, maxRPM=[6000], minRPM=[1200], failFan=0)])
check('a failed write on a one-fan Mac restores that fan', r[0]['mode'] == 'automatic' and r[0]['restoredFans'] == [0])
old = {**config, 'model': 'MacBookPro18,4', 'cpuKeys': ['Tp09'], 'gpuKeys': ['Tg05'], 'palmKeys': ['Ts0P']}
p, r = run([frame()], old)
check('a profile from an older version, naming a model and sensors, still loads', p.returncode == 0 and r[0]['mode'] == 'custom')
p, r = run([frame(65), frame(cpu=None), frame(), frame(), frame()])
check('three healthy samples resume cooling after sensor recovery', r[-1]['mode'] == 'custom' and r[-2]['mode'] == 'automatic')

def mapped(brand, probe):
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d)/'probe.json'
        path.write_text(json.dumps(probe))
        p = subprocess.run([str(exe), 'map', brand, str(path)], text=True, capture_output=True)
        return p, (json.loads(p.stdout) if p.returncode == 0 else None)

m1 = json.loads((root/'artifacts/baseline.json').read_text())
m5 = json.loads((root/'artifacts/m5-probe.json').read_text())
m1_cpu = ['Tp09','Tp0T','Tp01','Tp05','Tp0D','Tp0H','Tp0L','Tp0P','Tp0X','Tp0b']
p, m = mapped('Apple M1 Max', m1)
check('the saved M1 Max probe maps to the sensors verified on that Mac, two fans and F0Md',
      p.returncode == 0 and m['cpu'] == m1_cpu and m['gpu'] == ['Tg05','Tg0D','Tg0L','Tg0T']
      and m['palm'] == ['Ts0P','Ts1P'] and m['fans'] == 2 and m['modeKey'] == 'Md')
p, m = mapped('Apple M5 Pro', m5)
check('the saved M5 Pro probe maps to the measured sensors, two fans and F0md',
      p.returncode == 0 and len(m['cpu']) == 18 and m['gpu'] == sorted(k for k in m5['values'] if k.startswith('Tg'))
      and len(m['gpu']) == 42 and m['palm'] == ['Ts0P','Ts1P'] and m['fans'] == 2 and m['modeKey'] == 'md')
m6 = json.loads((root/'artifacts/m6-probe.json').read_text())
p, m = mapped('Apple M6', m6)
check('the saved M6 Mac mini probe maps to its load-tested sensors, one fan, no palm rest and F0md',
      p.returncode == 0 and m['cpu'] == sorted(k for k in m6['values'] if k.startswith('Tp0')) and len(m['cpu']) == 21
      and m['gpu'] == sorted(k for k in m6['values'] if k.startswith('Tg')) and len(m['gpu']) == 18
      and m['palm'] == [] and m['fans'] == 1 and m['modeKey'] == 'md')
partial = {**m1, 'values': {k: v for k, v in m1['values'].items() if k != 'Tp0b'}}
p, m = mapped('Apple M1 Max', partial)
check('a listed key missing on this variant is skipped, not required', p.returncode == 0 and m['cpu'] == m1_cpu[:-1])
desktop = {**m5, 'values': {k: v for k, v in m5['values'].items() if k not in ('Ts0P','Ts1P')}}
p, m = mapped('Apple M5 Pro', desktop)
check('a Mac without palm sensors maps with none', p.returncode == 0 and m['palm'] == [] and len(m['cpu']) == 18)
for brand in ['Apple M7 Pro', 'Apple M10', 'Intel(R) Core(TM) i9-9980HK CPU @ 2.40GHz', 'Apple A18 Pro']:
    p, _ = mapped(brand, m5)
    check(f'{brand} is refused', p.returncode != 0)
p, _ = mapped('Apple M5', {**m5, 'values': {**m5['values'], 'FNum': 0}})
check('a Mac without fans is refused', p.returncode != 0)
p, _ = mapped('Apple M3 Max', m5)
check('a Mac whose generation lists none of its keys is refused', p.returncode != 0)
report = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': checks, 'scope': 'Compiled CLI replay; no hardware writes. Live verification is separate.'}
(root/'artifacts/e2e-report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
