#!/usr/bin/env python3
"""Process checks for Max cooling and custom curves. No fan writes.

Failure inventory, written before implementation: max misses cold temperatures;
max bypasses sensor/conflict recovery; edited temperatures cross or demand falls;
last point never reaches full speed; NaN/booleans become numeric settings; edits
replace sensor/model/recovery settings; cancelled edits overwrite the saved curve;
switching presets loses the saved curve; preview or editor opening changes fans;
an unavailable fan limit is silently guessed; dragging disagrees with exact fields.

Run: python3 tests/curves.py. Native editor interactions are recorded separately
in artifacts/editor-live-check.json after installation, not simulated here.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'monitor/cooler.5s.py'
checks = []
original = json.loads((ROOT/'config.json').read_text())
installed = Path('/Library/Application Support/Cooler/config.json')
before = installed.read_bytes()

with tempfile.TemporaryDirectory(prefix='cooler-curves-') as directory:
    work = Path(directory)
    def run(*args):
        return subprocess.run([str(PLUGIN), *map(str,args)],capture_output=True,text=True,timeout=10)
    def preview(config):
        path=work/'edited.json'; path.write_text(json.dumps(config))
        return run('--preview-custom',path)
    editable = {key:copy.deepcopy(original[key]) for key in ['baselineRPM','curve','palmCurve']}
    editable['baselineRPM'] = 1900
    editable['palmCurve'][1]['fraction'] = .25
    result = preview(editable)
    assert result.returncode == 0, result.stderr
    proposal = json.loads(result.stdout)['config']
    assert all(proposal[k]==editable[k] for k in editable)
    assert all(proposal[k]==json.loads(before)[k] for k in original if k not in editable)
    path=work/'config.json'; path.write_text(json.dumps(proposal))
    subprocess.run([str(ROOT/'build/cooler'),'check',str(path)],check=True,capture_output=True)
    checks.append('Edited baseline and both curves produce a valid configuration without changing sensors or recovery')

    invalid=[]
    def bad(change):
        candidate=copy.deepcopy(editable); change(candidate); invalid.append(candidate)
    bad(lambda c:c.update(baselineRPM=1199))
    bad(lambda c:c.update(baselineRPM=True))
    bad(lambda c:c.update(baselineRPM=float('nan')))
    bad(lambda c:c.update(cpuKeys=['BAD!']))
    bad(lambda c:c['curve'][1].update(temperature=c['curve'][0]['temperature']))
    bad(lambda c:c['curve'][2].update(fraction=0))
    bad(lambda c:c['curve'][-1].update(fraction=.9))
    bad(lambda c:c['palmCurve'][-1].update(temperature=91))
    bad(lambda c:c['palmCurve'][0].update(fraction=-.1))
    bad(lambda c:c.update(curve=[]))
    for candidate in invalid:
        result=preview(candidate)
        assert result.returncode != 0, candidate
    checks.append('Out-of-range, malformed, nonmonotonic and nonfinite edits are rejected before authorization')

    result=run('--preview-profile','max')
    assert result.returncode==0, result.stderr
    maximum=json.loads(result.stdout)['config']
    path.write_text(json.dumps(maximum))
    frames=work/'frames.json'
    for temperature in [5,20,40,70,100,125]:
        frames.write_text(json.dumps([{'cpu':temperature,'gpu':temperature,'palm':temperature,'elapsed':2}]))
        result=subprocess.run([str(ROOT/'build/cooler'),'replay',str(path),str(frames)],capture_output=True,text=True,check=True)
        assert json.loads(result.stdout)['targets']==[5779,6241]
    for fault in [{'conflict':True},{'cpu':None},{'elapsed':11}]:
        frames.write_text(json.dumps([{'cpu':50,'gpu':40,'palm':30,'elapsed':2,**fault}]))
        result=subprocess.run([str(ROOT/'build/cooler'),'replay',str(path),str(frames)],capture_output=True,text=True,check=True)
        assert json.loads(result.stdout)['mode']=='automatic'
    checks.append('Max requests each hardware maximum across temperatures and retains automatic recovery')

    result=run('--editor-data')
    assert result.returncode==0, result.stderr
    data=json.loads(result.stdout)
    assert set(data['presets'])=={'quiet','balanced','cooler'}
    assert data['current']==json.loads(before)
    assert len(data['limits'])==2 and all(f['maximum']>f['minimum']>=1000 for f in data['limits'])
    assert installed.read_bytes()==before
    checks.append('Opening and previewing the editor reads actual limits and never changes installed settings')

report={'checks':checks,'passed':len(checks),'hardware_writes':False}
(ROOT/'artifacts/curves-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
