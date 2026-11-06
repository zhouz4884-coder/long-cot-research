"""Eight fixed native fixtures, complete execution first, no short study cutoff."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT=Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_phase5d_20261106')
PYTHON='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPUS=['GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a','GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28']
STATUS=ROOT/'schedule_launcher.json';assert not STATUS.exists() and not (ROOT/'schedule_control').exists()
report={'status':'RUNNING','pid':os.getpid(),'started_unix':time.time(),'workers':{},'scope':'All8checkpoint schedules; no new qualitygeneration'}
lock=threading.Lock()
def save():
    tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(report,indent=2)+'\n');os.replace(tmp,STATUS)
def run(index,gpu):
    begin=time.time();row={'status':'RUNNING','gpu':gpu,'started_unix':begin}
    with lock:report['workers'][str(index)]=row;save()
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        XDG_CACHE_HOME=str(ROOT/'cache'/str(index)))
    cmd=[PYTHON,'-u','-B',str(ROOT/'replay_schedule_control.py'),'--root',str(ROOT),'--model',MODEL,'--gpu',gpu,'--worker',str(index)]
    try:
        with (ROOT/'logs'/f'schedule_worker_{index}.log').open('xb') as log:
            result=subprocess.run(cmd,cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,check=False)
        row.update(status='FINISHED',exit_code=result.returncode)
    except BaseException as e:row.update(status='ERROR',error_type=type(e).__name__)
    finally:
        row['elapsed_seconds']=time.time()-begin
        with lock:save()
save();threads=[threading.Thread(target=run,args=(i,g)) for i,g in enumerate(GPUS)]
for t in threads:t.start()
for t in threads:t.join()
report.update(status='FINISHED',elapsed_seconds=time.time()-report['started_unix'],
    conservative_GPU_seconds=sum(v['elapsed_seconds'] for v in report['workers'].values()))
report['conservative_GPU_minutes']=report['conservative_GPU_seconds']/60
report['ending_compute_processes']=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True,timeout=5);save()
