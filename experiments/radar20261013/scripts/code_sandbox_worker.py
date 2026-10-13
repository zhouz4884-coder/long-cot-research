"""Trusted container worker. Receives inputs, never hidden expected outputs."""
import json,os,resource,subprocess,sys
from pathlib import Path


def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(3,3))
    resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))


job=json.load(sys.stdin)
assert job['style']=='stdio','Callable evaluation requires a separately frozen adapter'
Path('/tmp/solution.py').write_text(job['code'],encoding='utf-8')
outputs=[]
for test_input in job['inputs']:
    try:
        p=subprocess.run([sys.executable,'/tmp/solution.py'],input=test_input,text=True,
                         capture_output=True,timeout=job.get('timeout_seconds',5),preexec_fn=limits)
        outputs.append({'stdout':p.stdout[:1000000],'stderr':p.stderr[:2000],'returncode':p.returncode,'timeout':False})
    except subprocess.TimeoutExpired:
        outputs.append({'stdout':'','stderr':'timeout','returncode':None,'timeout':True})
print('SANDBOX_RESULTS_JSON='+json.dumps(outputs),flush=True)
