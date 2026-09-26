#!/usr/bin/env python3
"""Exercise the shipping CLI with deterministic input; writes an inspectable report."""
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
check('gentle baseline on both fans', p.returncode == 0 and r[0]['targets'] == [1800,1800])
p, r = run([frame(40,85)])
check('GPU alone requests full cooling', r[0]['targets'] == [5779,6241])
p, r = run([frame(85,40)])
check('CPU alone requests full cooling', r[0]['targets'] == [5779,6241])
p, r = run([frame(85), frame(40)])
check('fall rate limits rapid fan changes', r[1]['targets'] == [5699,6161])
p, r = run([frame(), frame(85)])
check('heat increase is immediate', r[1]['targets'] == [5779,6241])
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
p, r = run([frame(65, maxRPM=[1000,6241])])
check('invalid hardware fan limits refuse control', r[0]['mode'] == 'automatic')
bad = {**config, 'baselineRPM': 20000}
p, _ = run([frame()], bad)
check('malformed curve configuration rejected', p.returncode != 0)
p, r = run([frame(palm=40)])
check('warm palm rest alone requests full cooling', r[0]['targets'] == [5779,6241])
p, r = run([frame(65), frame(palm=None)])
check('missing palm sensor restores automatic control', r[1]['mode'] == 'automatic')
p, r = run([frame(65), frame(cpu=None), frame(), frame(), frame()])
check('three healthy samples resume cooling after sensor recovery', r[-1]['mode'] == 'custom' and r[-2]['mode'] == 'automatic')
report = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': checks, 'scope': 'Compiled CLI replay; no hardware writes. Live verification is separate.'}
(root/'artifacts/e2e-report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
