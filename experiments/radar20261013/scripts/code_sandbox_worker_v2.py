"""Trusted Docker worker: stdio or callable inputs, no expected answers."""
import json,resource,subprocess,sys
from pathlib import Path


def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(3,3))
    resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))


job=json.load(sys.stdin)
assert job['style'] in ['stdio','functional']
code=job['code']
if job['style']=='functional':
    prelude=json.loads(Path('/prelude.json').read_text())
    code=prelude+'\n'+code
Path('/tmp/solution.py').write_text(code,encoding='utf-8')
runner=r'''
import contextlib,io,json,runpy,sys
arguments=[json.loads(line) for line in sys.stdin.read().strip().split('\n')]
with contextlib.redirect_stdout(io.StringIO()):
    namespace=runpy.run_path('/tmp/solution.py')
    owner=namespace['Solution']() if 'Solution' in namespace else namespace
    method=getattr(owner,sys.argv[1]) if not isinstance(owner,dict) else owner[sys.argv[1]]
    result=method(*arguments)
if isinstance(result,tuple):result=list(result)
def check(value):
    if isinstance(value,tuple):raise TypeError('Nested tuple is not a JSON list')
    if isinstance(value,list):
        for item in value:check(item)
    if isinstance(value,dict):
        for item in value.values():check(item)
check(result)
print('CALLABLE_RESULT_JSON='+json.dumps(result,allow_nan=False))
'''
outputs=[]
for test_input in job['inputs']:
    args=[sys.executable,'/tmp/solution.py'] if job['style']=='stdio' else [sys.executable,'-c',runner,job['func_name']]
    try:
        p=subprocess.run(args,input=test_input,text=True,capture_output=True,
                         timeout=job.get('timeout_seconds',5),preexec_fn=limits)
        outputs.append({'stdout':p.stdout[:1000000],'stderr':p.stderr[:2000],
                        'returncode':p.returncode,'timeout':False})
    except subprocess.TimeoutExpired:
        outputs.append({'stdout':'','stderr':'timeout','returncode':None,'timeout':True})
print('SANDBOX_RESULTS_JSON='+json.dumps(outputs),flush=True)
