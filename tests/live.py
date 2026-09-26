#!/usr/bin/env python3
"""On-device lifecycle test. Root required. Temporarily stops/restarts only Cooler."""
import datetime, json, os, pathlib, re, signal, subprocess, sys, time
root = pathlib.Path(__file__).resolve().parents[1]
base = pathlib.Path('/Library/Application Support/Cooler')
exe = str(base/'cooler')
service = 'system/com.chetangoel.cooler'
plist = '/Library/LaunchDaemons/com.chetangoel.cooler.plist'
report = {'started': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': [], 'observations': [],
          'not_verified': ['physical sleep/wake', 'full reboot', 'long-term temperature/noise comfort']}

def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)

def pid():
    text = command('/bin/launchctl', 'print', service)
    m = re.search(r'^\s*pid = (\d+)', text, re.M)
    return int(m[1]) if m else None

def wait_active(old=None, timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        try:
            current = pid()
            status = json.loads((base/'status.json').read_text())
            fresh = datetime.datetime.now(datetime.timezone.utc).timestamp()-datetime.datetime.fromisoformat(status['time'].replace('Z','+00:00')).timestamp() < 5
            if current and current != old and status['mode'] == 'custom' and fresh:
                return current, status
        except (subprocess.CalledProcessError, ValueError, KeyError, OSError):
            pass
        time.sleep(1)
    raise RuntimeError('Cooler did not return to healthy custom control')

def check(name, ok, details=None):
    report['checks'].append({'name':name, 'passed':bool(ok), 'details':details})
    print(name+': '+('PASS' if ok else 'FAIL'), flush=True)
    if not ok: raise RuntimeError(name)

success = False
try:
    if os.geteuid() != 0: raise RuntimeError('Run with sudo')
    current, status = wait_active()
    time.sleep(8)
    sample = json.loads(command(exe,'probe'))
    report['observations'].append(sample)
    values = sample['values']
    check('Both fans accept manual mode and bounded targets', all(values[f'F{i}Md'] == 1 and values[f'F{i}Mn'] <= values[f'F{i}Tg'] <= values[f'F{i}Mx'] for i in (0,1)))
    check('Both fans are physically spinning', all(1000 < values[f'F{i}Ac'] <= values[f'F{i}Mx']*1.05 for i in (0,1)))
    for label, sig in [('Normal termination',signal.SIGTERM), ('Controller crash',signal.SIGKILL), ('Controller stall',signal.SIGSTOP)]:
        old = pid()
        os.kill(old,sig)
        time.sleep(2)
        current,status = wait_active(old)
        check(label+' recovers automatically', current != old, {'oldPID':old,'newPID':current})
    old = pid()
    child = int(command('/usr/bin/pgrep','-P',str(old),'-x','cooler').strip())
    os.kill(child,signal.SIGKILL)
    time.sleep(2)
    current,status = wait_active(old)
    check('Watchdog failure triggers controller recovery',current != old)
    log = pathlib.Path('/var/log/cooler.log').read_text()
    check('Watchdog recorded automatic restoration', 'Watchdog restored automatic fan control' in log)
    check('Stall detector fired', 'Controller heartbeat timed out' in log)
    command('/bin/launchctl','bootout',service)
    command(exe,'auto')
    restored = json.loads(command(exe,'probe'))
    report['observations'].append(restored)
    check('Stopping restores both fan modes to automatic', all(restored['values'][f'F{i}Md'] in (0,3) for i in (0,1)))
    command('/bin/launchctl','bootstrap','system',plist)
    current,status = wait_active()
    check('Service restart reapplies custom curve', status['mode'] == 'custom')
    check('Installed files are protected', all(p.stat().st_uid == 0 and p.stat().st_mode & 0o022 == 0 for p in [base,base/'cooler',base/'config.json',pathlib.Path(plist)]))
    report['final_status'] = status
    report['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    success = True
except Exception as e:
    report['error'] = str(e)
    print('FAILED: '+str(e), flush=True)
finally:
    if not success:
        subprocess.run(['/bin/launchctl','bootout',service],capture_output=True)
        recovery = subprocess.run([exe,'auto'],text=True,capture_output=True)
        report['failure_recovery']={'exit':recovery.returncode,'output':recovery.stdout+recovery.stderr}
    destination=root/'artifacts/live-report.json'
    destination.write_text(json.dumps(report,indent=2)+'\n')
    if os.environ.get('SUDO_UID'):
        os.chown(destination,int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID']))
    print('Report: '+str(destination), flush=True)
sys.exit(0 if success else 1)
