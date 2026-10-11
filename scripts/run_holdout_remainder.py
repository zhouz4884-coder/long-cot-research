"""Complete the frozen 300-problem primary comparison after diagnostic stages."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

TASK=Path(__file__).resolve().parents[1];os.chdir(TASK)
PY=str(TASK/'.venv/bin/python')
MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
METHODS='full,transition,learned_stop,eat'
marker=Path('results/heldout_300.complete.json')
if marker.exists():raise SystemExit(0)
while not Path('results/second_model_24.complete.json').exists():
 state=json.loads(Path('results/pipeline_state.json').read_text())
 if state.get('status')=='failed':
  raise RuntimeError('The preceding experiment failed; repair before resuming')
 time.sleep(15)
policy_hash=hashlib.sha256(Path('results/analysis/policy_calibration.json').read_bytes()).hexdigest()
state_path=Path('results/holdout_state.json')
state_path.write_text(json.dumps({'stage':'heldout_remaining_250','status':'running','methods':METHODS.split(','),'policy_sha256':policy_hash,'started_unix':time.time()},indent=2))
jobs=[]
for gpu in [0,1]:
 env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=str(gpu);env['PYTHONUNBUFFERED']='1'
 log=Path(f'logs/heldout_remaining_gpu{gpu}.log').open('a')
 args=[PY,'scripts/evaluate_online.py','--model',MODEL,'--n','250','--offset','50','--shard',str(gpu),'--shards','2','--methods',METHODS]
 jobs.append((subprocess.Popen(args,env=env,stdout=log,stderr=subprocess.STDOUT),log,gpu))
while any(p.poll() is None for p,_,_ in jobs):time.sleep(10)
codes={str(g):p.returncode for p,_,g in jobs}
for _,log,_ in jobs:log.close()
unchanged=hashlib.sha256(Path('results/analysis/policy_calibration.json').read_bytes()).hexdigest()==policy_hash
payload={'stage':'heldout_300','status':'complete' if not any(codes.values()) and unchanged else 'failed','return_codes':codes,'policy_unchanged':unchanged,'policy_sha256':policy_hash,'ended_unix':time.time()}
state_path.write_text(json.dumps(payload,indent=2))
if payload['status']=='failed':raise SystemExit(1)
marker.write_text(json.dumps(payload,indent=2))
print(json.dumps(payload),flush=True)
