"""Single explicitly bound 3090, fresh isolated output, cumulative <=300s ceiling."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_state_repair_p05_20261105')
PYTHON = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPU = 'GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a'
STATUS = ROOT / 'provenance/launcher_01.json'
OUTPUT = ROOT / 'results/p05_five_arm_01'
assert not STATUS.exists() and not OUTPUT.exists(), 'Preserve every previous attempt'
started = time.time()
report = {'pid': os.getpid(), 'started_unix': started, 'requested_gpus': 1,
          'gpu_uuid': GPU, 'status': 'ADMISSION', 'scope': 'Exploratory sixteen-state diagnostic',
          'prior_attempts_gpu_seconds': 0, 'aggregate_budget_seconds': 300}
try:
    frozen = json.loads((ROOT / 'provenance/prelaunch_freeze_01.json').read_text())
    for item in frozen['remote_files']:
        path = ROOT / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
    before = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
                                      '--format=csv,noheader,nounits'], universal_newlines=True, timeout=3)
    assert not any(row.split(',')[0].strip() == GPU for row in before.splitlines()), 'Selected GPU occupied'
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES=GPU, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               XDG_CACHE_HOME=str(ROOT / 'cache'), TRITON_CACHE_DIR=str(ROOT / 'cache/triton'))
    command = ['timeout', '--signal=TERM', '--kill-after=5s', '285s', PYTHON, '-u', '-B',
               str(ROOT / 'source/p05_five_arm.py'), '--model', MODEL,
               '--cases', str(ROOT / 'data/cases.json'), '--base-path', str(ROOT / 'source/p0_base_frozen.py'),
               '--extractor-path', str(ROOT / 'source/frozen_answer_extractor.py'),
               '--standalone-gpu', GPU, '--max-seconds', '270', '--output', str(OUTPUT)]
    report.update(status='RUNNING', command=command, protocol_freeze_sha256=hashlib.sha256(
                  (ROOT / 'provenance/prelaunch_freeze_01.json').read_bytes()).hexdigest())
    STATUS.write_text(json.dumps(report, indent=2) + '\n')
    with (ROOT / 'logs/p05_five_arm_01.log').open('xb') as log:
        result = subprocess.run(command, env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, timeout=294, check=False)
    report.update(status='FINISHED', exit_code=result.returncode)
except BaseException as error:
    report.update(status='LAUNCH_OR_EXECUTION_ERROR', exception_type=type(error).__name__)
    raise
finally:
    report['elapsed_seconds_including_hash_import_load'] = time.time() - started
    report['conservative_single_gpu_minutes'] = report['elapsed_seconds_including_hash_import_load'] / 60
    report['ending_compute_processes'] = subprocess.check_output(
        ['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory', '--format=csv,noheader,nounits'],
        universal_newlines=True, timeout=3)
    STATUS.write_text(json.dumps(report, indent=2) + '\n')
