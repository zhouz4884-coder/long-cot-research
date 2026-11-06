"""One bounded quality-first prototype run; credentials are not part of this file."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_phase5_quality_20261106')
PYTHON = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPU = 'GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a'
OUTPUT = ROOT / 'results/quality_round_01'
STATUS = ROOT / 'provenance/launcher_01.json'
assert not STATUS.exists() and not OUTPUT.exists(), 'Preserve every previous run'
started = time.time()
report = {'pid': os.getpid(), 'started_unix': started, 'status': 'ADMISSION',
          'gpu_uuid': GPU, 'requested_gpus': 1, 'aggregate_budget_seconds': 300,
          'scope': 'Shared-root-G one-shot frame prototype; 6 main states and 6 basis outputs'}
try:
    freeze = json.loads((ROOT / 'provenance/prelaunch_freeze_01.json').read_text())
    for row in freeze['remote_files']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    occupancy = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
                                         '--format=csv,noheader,nounits'], universal_newlines=True, timeout=3)
    assert not any(line.split(',')[0].strip() == GPU for line in occupancy.splitlines()), 'Selected GPU occupied'
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES=GPU, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               XDG_CACHE_HOME=str(ROOT / 'cache'), TRITON_CACHE_DIR=str(ROOT / 'cache/triton'))
    command = ['timeout', '--signal=TERM', '--kill-after=5s', '285s', PYTHON, '-u', '-B',
        str(ROOT / 'source/phase5_quality_runner.py'), '--model', MODEL, '--output', str(OUTPUT),
        '--data', str(ROOT / 'data/topology_v2.json'), '--adapter-path', str(ROOT / 'source/prepare_cpu_input_adapter.py'),
        '--base-path', str(ROOT / 'source/p0_base_frozen.py'), '--parser-path', str(ROOT / 'source/frozen_answer_extractor.py'),
        '--standalone-gpu', GPU, '--max-seconds', '270', '--seed', '20261106']
    report.update(status='RUNNING', command=command, quality_guard_tokens=512,
                  freeze_sha256=hashlib.sha256((ROOT / 'provenance/prelaunch_freeze_01.json').read_bytes()).hexdigest())
    STATUS.write_text(json.dumps(report, indent=2) + '\n')
    with (ROOT / 'logs/quality_round_01.log').open('xb') as log:
        result = subprocess.run(command, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, timeout=294, check=False)
    report.update(status='FINISHED', exit_code=result.returncode)
except BaseException as error:
    report.update(status='LAUNCH_OR_EXECUTION_ERROR', exception_type=type(error).__name__)
    raise
finally:
    report['elapsed_seconds_including_imports_hash_load'] = time.time() - started
    report['conservative_single_gpu_minutes'] = report['elapsed_seconds_including_imports_hash_load'] / 60
    report['ending_compute_processes'] = subprocess.check_output(['nvidia-smi',
        '--query-compute-apps=gpu_uuid,pid,used_gpu_memory', '--format=csv,noheader,nounits'],
        universal_newlines=True, timeout=3)
    STATUS.write_text(json.dumps(report, indent=2) + '\n')
