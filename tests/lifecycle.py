#!/usr/bin/env python3
"""Real process/pipe/signal E2E checks using dry-run mode; never writes fans."""
import datetime, json, os, pathlib, select, signal, subprocess, tempfile, time
root = pathlib.Path(__file__).resolve().parents[1]
checks = []
with tempfile.TemporaryDirectory() as d:
    for name, sig in [('normal exit',signal.SIGTERM),('crash',signal.SIGKILL),('stall',signal.SIGSTOP),('watchdog loss',None)]:
        log = pathlib.Path(d)/name
        with log.open('w') as err:
            p = subprocess.Popen([str(root/'build/cooler'),'dry-run',str(root/'config.json'),'300'],stdout=subprocess.PIPE,stderr=err,text=True)
            watcher = None
            try:
                ready,_,_ = select.select([p.stdout],[],[],8)
                assert ready, 'No initial status'
                first=json.loads(p.stdout.readline())
                assert first['pid'] == p.pid and first['mode'] == 'custom', first
                watcher = int(subprocess.check_output(['/usr/bin/pgrep','-P',str(p.pid),'-x','cooler'],text=True).strip())
                started=time.monotonic()
                if sig is None: os.kill(watcher,signal.SIGKILL)
                else: os.kill(p.pid,sig)
                result=p.wait(timeout=16)
                expected='Watchdog exited' if sig is None else 'Dry-run watchdog restored automatic control'
                deadline=time.monotonic()+4
                while expected not in log.read_text() and time.monotonic()<deadline: time.sleep(.1)
                text=log.read_text()
                assert expected in text, text
                if sig == signal.SIGSTOP: assert 'Controller heartbeat timed out' in text and result == -signal.SIGKILL, text
                if sig == signal.SIGTERM: assert result == 0, result
                if sig is None: assert result != 0, result
                checks.append({'name':name,'passed':True,'elapsed':round(time.monotonic()-started,2),'log':text})
                print(name+': PASS',flush=True)
            finally:
                if p.poll() is None: p.kill(); p.wait()
                if watcher:
                    try: os.kill(watcher,signal.SIGTERM)
                    except ProcessLookupError: pass
report={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'scope':'Compiled CLI; actual process signals and watchdog; read-only hardware, no fan writes.'}
(root/'artifacts/lifecycle-report.json').write_text(json.dumps(report,indent=2)+'\n')
