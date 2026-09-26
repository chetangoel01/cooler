#!/usr/bin/env python3
"""Process-level profile checks; run with python3 tests/profiles.py.

Failure inventory, before implementation: unauthorized refresh changes fans;
unknown action reaches authorization; invalid profile replaces working settings;
overlapping changes; cancellation is shown as success; failed stop leaves two
controllers; failed startup leaves a manual target; old status marks a new process
healthy; automatic mode loses live readings; selected preset disagrees with disk.

Runs the plugin's exported action scripts with simulated launchd/SMC operations.
Config validation and profile response use the real compiled Cooler CLI read-only.
No administrator prompt, launchd mutation, or hardware fan write is performed.
"""
import json
import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'monitor/cooler.5s.py'
LIVE_BASE = '/Library/Application Support/Cooler'
checks = []

with tempfile.TemporaryDirectory(prefix='cooler-profiles-') as directory:
    work = Path(directory)
    base = work / 'installed'
    base.mkdir()
    original = (ROOT / 'config.json').read_text()
    (base / 'config.json').write_text(original)
    (work / 'state.json').write_text(json.dumps({'loaded': True, 'enabled': True, 'automatic': False}))
    backend = work / 'backend.py'
    backend.write_text('''#!/opt/homebrew/bin/python3
import json, os, pathlib, subprocess, sys
p=pathlib.Path(__file__).resolve().parent
state=json.loads((p/'state.json').read_text())
command=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with (p/'events.jsonl').open('a') as f: f.write(json.dumps([command,args])+"\\n")
fail=(p/'fail').read_text() if (p/'fail').exists() else ''
code=0
if command=='pgrep': sys.exit(1)
if command=='chown': sys.exit(0)
if command=='launchctl':
    if args[0]=='print': sys.exit(0 if state['loaded'] else 113)
    if args[0]==fail: sys.exit(42)
    if args[0]=='disable': state['enabled']=False
    if args[0]=='enable': state['enabled']=True
    if args[0]=='bootout': state['loaded']=False
    if args[0]=='bootstrap':
        assert state['enabled'] and not state['loaded']
        state['loaded']=True; state['automatic']=False
elif command=='cooler':
    if args[0]==fail: sys.exit(42)
    if args[0]=='auto':
        if state['loaded']: sys.exit(43)
        state['automatic']=True
    elif args[0]=='check':
        code=subprocess.run([os.environ['COOLER_REAL_CLI'],'check',args[1]],stdout=subprocess.DEVNULL).returncode
    else: sys.exit(44)
(p/'state.json').write_text(json.dumps(state))
sys.exit(code)
''')
    backend.chmod(0o755)
    for name in ['launchctl', 'pgrep', 'chown']:
        (work/name).symlink_to(backend)
    (base/'cooler').symlink_to(backend)

    def preview(name):
        result = subprocess.run([str(PLUGIN), '--preview-profile', name], capture_output=True,
                                text=True, env={**os.environ, 'COOLER_HOME':str(base)})
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def execute(name, failure=None):
        (base/'config.json').write_text(original)
        (work/'state.json').write_text(json.dumps({'loaded':True,'enabled':True,'automatic':False}))
        (work/'events.jsonl').write_text('')
        (work/'fail').write_text(failure or '')
        proposal = preview(name)
        script = proposal['script'].replace(shlex.quote(LIVE_BASE), shlex.quote(str(base)))
        for tool, path in [('launchctl','/bin/launchctl'),('pgrep','/usr/bin/pgrep'),('chown','/usr/sbin/chown')]:
            script = script.replace(path, shlex.quote(str(work/tool)))
        subprocess.run(['/bin/sh','-n'], input=script, text=True, check=True)
        result = subprocess.run(['/bin/sh'], input=script, text=True, capture_output=True,
                                env={**os.environ,'COOLER_REAL_CLI':str(ROOT/'build/cooler')},timeout=15)
        return result, json.loads((work/'state.json').read_text()), proposal

    configs = {}
    for name in ['quiet','balanced','cooler']:
        result, state, proposal = execute(name)
        assert result.returncode == 0, result.stderr
        installed = json.loads((base/'config.json').read_text())
        assert installed == proposal['config'] and state['enabled'] and state['loaded']
        assert (base/'config.json').stat().st_mode & 0o777 == 0o644
        configs[name] = installed
    assert configs['cooler'] == json.loads(original), 'Cooler must preserve the original profile exactly'
    checks.append('All three presets validate, install, restart, and keep protected file modes')

    frame = work/'frames.json'
    for name, config in configs.items():
        path=work/(name+'.json'); path.write_text(json.dumps(config))
    temperatures = [(t,25) for t in range(45,96,5)] + [(25,t) for t in [30,33,35,36,38,39,40,45]]
    for temperature,palm in temperatures:
        frame.write_text(json.dumps([{'cpu':temperature,'gpu':temperature,'palm':palm,'elapsed':2}]))
        targets=[]
        for name in ['quiet','balanced','cooler']:
            result=subprocess.run([str(ROOT/'build/cooler'),'replay',str(work/(name+'.json')),str(frame)],
                                  capture_output=True,text=True,check=True)
            targets.append(json.loads(result.stdout)['targets'])
        assert all(targets[0][i] <= targets[1][i] <= targets[2][i] for i in range(2)), (temperature,targets)
        if temperature >= 90 or palm >= 40: assert targets[0] == targets[1] == targets[2] == [5779,6241]
    checks.append('Quiet ≤ Balanced ≤ Cooler across CPU/GPU and palm ranges; full speed by 90°C chip or 40°C palm')

    result,state,_=execute('automatic')
    assert result.returncode == 0 and not state['enabled'] and not state['loaded'] and state['automatic']
    assert (base/'config.json').read_text() == original
    checks.append('Apple automatic stops and disables Cooler while preserving the profile')

    for failure in ['check','bootout','bootstrap']:
        result,state,_=execute('balanced',failure)
        assert result.returncode != 0
        assert (base/'config.json').read_text() == original
        if failure=='check': assert state['loaded'] and state['enabled']
        if failure=='bootstrap': assert not state['loaded'] and not state['enabled'] and state['automatic']
    checks.append('Validation/stop/start failures preserve configuration; failed startup leaves Apple automatic')

    result=subprocess.run([str(PLUGIN),'--preview-profile','unexpected'],capture_output=True,text=True)
    assert result.returncode != 0
    checks.append('Unknown actions are rejected before authorization')

    # Exercise the complete action process with only the OS authorization endpoint substituted.
    auth=work/'authorize'
    auth.write_text('#!/bin/sh\necho "execution error: User canceled. (-128)" >&2\nexit 1\n')
    auth.chmod(0o755)
    actions=work/'actions'
    copy=work/'plugin.py'
    code=PLUGIN.read_text().replace("'/usr/bin/osascript'",repr(str(auth))).replace(
        "ACTION_STATE = Path.home() / 'Library/Caches/CoolerMonitor'",f'ACTION_STATE = Path({str(actions)!r})')
    copy.write_text(code); copy.chmod(0o755)
    before=Path(LIVE_BASE+'/config.json').read_bytes()
    result=subprocess.run([str(copy),'--apply-profile','balanced'],capture_output=True,text=True,timeout=5)
    assert result.returncode==0, result.stderr
    assert 'cancelled' in json.loads((actions/'action.json').read_text())['message']
    assert Path(LIVE_BASE+'/config.json').read_bytes()==before
    checks.append('Cancelled authorization keeps the installed configuration unchanged')
    (actions/'action.json').write_text(json.dumps({'message':'Original action in progress'}))
    with (actions/'action.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=subprocess.run([str(copy),'--apply-profile','quiet'],capture_output=True,text=True,timeout=5)
        assert result.returncode==0
        assert json.loads((actions/'action.json').read_text())['message']=='Original action in progress'
    checks.append('Overlapping actions are serialized before authorization')

report={'checks':checks,'passed':len(checks),'hardware_writes':False,'native_authorization_tested':False}
(ROOT/'artifacts/profiles-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
