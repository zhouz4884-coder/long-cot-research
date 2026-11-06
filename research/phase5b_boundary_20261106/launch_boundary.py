"""One <=300 single-GPU-second study, using the existing authorized environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_phase5b_boundary_20261106')
PYTHON='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPU='GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a'
STATUS=ROOT/'launcher_01.json';OUT=ROOT/'results/round_01'
assert not STATUS.exists() and not OUT.exists(),'Never overwrite a previous run'
started=time.time();report={'status':'ADMISSION','pid':os.getpid(),'started_unix':started,'gpu_uuid':GPU,'aggregate_budget_seconds':300}
try:
    for row in json.loads((ROOT/'prelaunch_freeze.json').read_text())['remote_files']:
        assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
    occupied=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],universal_newlines=True,timeout=3)
    assert not any(line.split(',')[0].strip()==GPU for line in occupied.splitlines()),'GPU occupied'
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES=GPU,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        XDG_CACHE_HOME=str(ROOT/'cache'),TRITON_CACHE_DIR=str(ROOT/'cache/triton'))
    command=['timeout','--signal=TERM','--kill-after=5s','285s',PYTHON,'-u','-B',str(ROOT/'boundary_runner.py'),
        '--root',str(ROOT),'--model',MODEL,'--output',str(OUT),'--base-path',str(ROOT/'p0_base_frozen.py'),
        '--quality-path',str(ROOT/'phase5_quality_frozen.py'),'--standalone-gpu',GPU,'--max-seconds','270']
    report.update(status='RUNNING',command=command);STATUS.write_text(json.dumps(report,indent=2)+'\n')
    with (ROOT/'logs/worker_01.log').open('xb') as log:
        run=subprocess.run(command,cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,timeout=294,check=False)
    report.update(status='FINISHED',exit_code=run.returncode)
except BaseException as exc:
    report.update(status='LAUNCH_OR_EXECUTION_ERROR',error_type=type(exc).__name__)
    raise
finally:
    report['elapsed_seconds']=time.time()-started;report['conservative_single_GPU_minutes']=report['elapsed_seconds']/60
    report['ending_compute_processes']=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
        '--format=csv,noheader,nounits'],universal_newlines=True,timeout=3)
    STATUS.write_text(json.dumps(report,indent=2)+'\n')
