"""Launch two bounded, disjoint single-model readout workers. No credentials."""
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
STATUS=ROOT/'launcher.json';assert not STATUS.exists() and not (ROOT/'results').exists()
started=time.time();report={'status':'RUNNING','pid':os.getpid(),'started_unix':started,'single_model':'Qwen3-4B',
    'physical_gpus':GPUS,'aggregate_GPU_seconds_cap':1800,'workers':{}}
lock=threading.Lock()
def save():
    tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(report,indent=2)+'\n');os.replace(tmp,STATUS)
def run(index,gpu):
    begin=time.time();env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES=gpu,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        XDG_CACHE_HOME=str(ROOT/'cache'/str(index)),TRITON_CACHE_DIR=str(ROOT/'cache'/str(index)/'triton'))
    command=['timeout','--signal=TERM','--kill-after=5s','880s',PYTHON,'-u','-B',str(ROOT/'paired_readout.py'),
        '--root',str(ROOT),'--model',MODEL,'--gpu',gpu,'--worker',str(index),'--max-seconds','850']
    row={'status':'RUNNING','gpu':gpu,'started_unix':begin,'command':command}
    with lock:report['workers'][str(index)]=row;save()
    try:
        with (ROOT/'logs'/f'worker_{index}.log').open('xb') as log:
            result=subprocess.run(command,cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,check=False,timeout=890)
        row.update(status='FINISHED',exit_code=result.returncode)
    except BaseException as exc:row.update(status='ERROR',error_type=type(exc).__name__)
    finally:
        row['elapsed_seconds']=time.time()-begin
        with lock:save()
save();threads=[threading.Thread(target=run,args=(i,g)) for i,g in enumerate(GPUS)]
for thread in threads:thread.start()
for thread in threads:thread.join()
report.update(status='FINISHED',elapsed_seconds=time.time()-started,
    conservative_aggregate_GPU_seconds=sum(row['elapsed_seconds'] for row in report['workers'].values()))
report['conservative_GPU_minutes']=report['conservative_aggregate_GPU_seconds']/60
report['ending_compute_processes']=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
    '--format=csv,noheader,nounits'],text=True,timeout=5);save()
