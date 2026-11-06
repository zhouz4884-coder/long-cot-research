"""Bound and record the exit of a resumed, CPU/IO-only ModelScope download."""
import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/data/home/zhoubin/longcot_state_repair_20261105')
out = root / 'provenance/modelscope_download_supervisor_04.json'
assert not out.exists()
started = time.time()
report = {'pid': os.getpid(), 'started_unix': started, 'attempt': '04',
          'scope': 'CPU/IO only; resume existing SDK partial files', 'status': 'RUNNING'}
out.write_text(json.dumps(report, indent=2))
env = dict(os.environ)
env.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
           CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1',
           MODELSCOPE_CACHE='/tmp/zhoubin/longcot_state_repair_20261105/modelscope-cache')
try:
    with (root / 'logs/modelscope_download_04.log').open('xb') as log:
        result = subprocess.run(['timeout', '--kill-after=15s', '1200s',
            str(root / 'env/longcot-v100/bin/python'), '-u', '-B',
            str(root / 'source/download_modelscope.py'), '--attempt', '04'],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
            cwd=str(root), timeout=1220)
    report.update(status='FINISHED', exit_code=result.returncode)
finally:
    report['elapsed_seconds'] = time.time() - started
    out.write_text(json.dumps(report, indent=2) + '\n')
