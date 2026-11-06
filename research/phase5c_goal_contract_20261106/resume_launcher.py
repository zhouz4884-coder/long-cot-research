"""User-authorized completion wave, without altering any scientific settings."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT=Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_phase5c_20261106')
PYTHON='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPUS=['GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a','GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28']
STATUS=ROOT/'resume_launcher.json';STUDY=ROOT/'STUDY_STATUS.json'
assert not STATUS.exists(),'No overwrite'
report={'status':'WAITING_ORIGINAL_WAVE','pid':os.getpid(),'workers':{},'budget_amendment':'User requested complete32x7; old30GPUminlimit superseded.'}
lock=threading.Lock()
def save():
    temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n');os.replace(temp,STATUS)
save();STUDY.write_text(json.dumps({'status':'GENERATING','planned_outputs':224,'stage':'wait_original_then_fill_missing'})+'\n')
while json.loads((ROOT/'launcher.json').read_text())['status']!='FINISHED':time.sleep(5)
report.update(status='RUNNING',started_unix=time.time());save()
def run(index,gpu):
    begin=time.time();row={'status':'RUNNING','gpu':gpu,'started_unix':begin}
    with lock:report['workers'][str(index)]=row;save()
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',XDG_CACHE_HOME=str(ROOT/'cache'/f'resume{index}'))
    cmd=['timeout','--signal=TERM','--kill-after=5s','7500s',PYTHON,'-u','-B',str(ROOT/'resume_worker.py'),
        '--root',str(ROOT),'--model',MODEL,'--gpu',gpu,'--worker',str(index)]
    try:
        with (ROOT/'logs'/f'resume_worker_{index}.log').open('xb') as log:
            result=subprocess.run(cmd,cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,check=False,timeout=7510)
        row.update(status='FINISHED',exit_code=result.returncode)
    except BaseException as exc:row.update(status='ERROR',error_type=type(exc).__name__)
    finally:
        row['elapsed_seconds']=time.time()-begin
        with lock:save()
threads=[threading.Thread(target=run,args=(i,g)) for i,g in enumerate(GPUS)]
for t in threads:t.start()
for t in threads:t.join()
report.update(status='FINISHED',conservative_aggregate_GPU_seconds=sum(row['elapsed_seconds'] for row in report['workers'].values()))
report['conservative_GPU_minutes']=report['conservative_aggregate_GPU_seconds']/60
report['ending_compute_processes']=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True,timeout=5);save()
expected={j['job_id'] for j in json.loads((ROOT/'jobs.json').read_text())};seen=[]
for directory in (ROOT/'results').glob('*worker_*'):
    for path in directory.glob('*.json'):
        value=json.loads(path.read_text())
        if isinstance(value,dict) and 'job_id' in value and 'token_ids' in value:seen.append(value['job_id'])
complete=len(seen)==len(set(seen)) and set(seen)==expected and all(row.get('exit_code')==0 for row in report['workers'].values())
STUDY.write_text(json.dumps({'status':'FINISHED' if complete else 'INCOMPLETE','planned_outputs':224,'completed_unique':len(set(seen)),
    'duplicates':len(seen)-len(set(seen)),'missing_ids':sorted(expected-set(seen)),'original_GPU_minutes':json.loads((ROOT/'launcher.json').read_text()).get('conservative_GPU_minutes'),
    'resume_GPU_minutes':report['conservative_GPU_minutes'],'scope':'All original results retained; only missing job IDs continued under user time extension.'},indent=2)+'\n')
