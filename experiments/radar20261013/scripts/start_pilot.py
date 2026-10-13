"""Admit current model/cache behavior, then run actual fresh baseline shards."""
import json
import os
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parents[1]
os.chdir(root)
py = str(root / '.venv/bin/python')
model = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
env = os.environ.copy();env['CUDA_VISIBLE_DEVICES']='0';env['PYTHONUNBUFFERED']='1'
with (root/'logs/live_admission.log').open('a') as f:
    result = subprocess.run([py,'scripts/validate_new_protocol.py'],env=env,stdout=f,stderr=subprocess.STDOUT)
if result.returncode:
    raise SystemExit(result.returncode)
assert json.loads((root/'provenance/live_protocol_admission.json').read_text())['passed']
jobs=[]
for gpu in [0,1]:
    env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=str(gpu);env['PYTHONUNBUFFERED']='1'
    f=(root/f'logs/pilot_gpu{gpu}.log').open('a')
    p=subprocess.Popen([py,'-u','scripts/run_pilot.py','--model',model,'--shard',str(gpu)],env=env,stdout=f,stderr=subprocess.STDOUT)
    jobs.append((p,f,gpu))
    print(json.dumps({'stage':'pilot','gpu':gpu,'pid':p.pid}),flush=True)
while any(p.poll() is None for p,_,_ in jobs):
    time.sleep(5)
codes={str(gpu):p.returncode for p,_,gpu in jobs}
for _,f,_ in jobs:f.close()
assert all(v==0 for v in codes.values()), codes
print('PILOT_ALL_COMPLETE',flush=True)
(root/'results/pilot.complete.json').write_text(json.dumps({'exit_codes':codes,'completed_unix':time.time()}))
