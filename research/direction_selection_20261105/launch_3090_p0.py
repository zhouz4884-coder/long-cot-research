"""One explicitly selected authorized 3090; fresh output and a bounded subprocess."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/longcot_state_repair_20261105')
PYTHON = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python'
MODEL = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
GPU = 'GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a'
run_path = ROOT / 'results/p0_qwen3_4b_fp16_01'
status_path = ROOT / 'provenance/p0_launcher_01.json'
assert not status_path.exists() and not run_path.exists(), 'Preserve all existing attempts'
started = time.time()
report = {'pid': os.getpid(), 'started_unix': started, 'gpu_uuid': GPU,
          'requested_gpus': 1, 'scope': '16 injected short states, not natural long-CoT',
          'input_sha256': hashlib.sha256((ROOT / 'data/proposed_p0_cases.json').read_bytes()).hexdigest(),
          'source_sha256': hashlib.sha256((ROOT / 'source/real_model_p0.py').read_bytes()).hexdigest(),
          'status': 'ADMISSION'}
try:
    before = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
                                      '--format=csv,noheader,nounits'], universal_newlines=True)
    assert not any(line.split(',')[0].strip() == GPU for line in before.splitlines()), 'Selected GPU occupied'
    assert json.loads((ROOT / 'provenance/model_identity_01.json').read_text())['passed']
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES=GPU, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
               OPENBLAS_NUM_THREADS='4', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               XDG_CACHE_HOME=str(ROOT / 'cache'), TRITON_CACHE_DIR=str(ROOT / 'cache/triton'))
    report['status'] = 'RUNNING'
    status_path.write_text(json.dumps(report, indent=2) + '\n')
    command = ['timeout', '--signal=TERM', '--kill-after=15s', '1200s', PYTHON, '-u', '-B',
               str(ROOT / 'source/real_model_p0.py'), '--standalone-gpu', GPU,
               '--model', MODEL, '--cases', str(ROOT / 'data/proposed_p0_cases.json'),
               '--output', str(run_path), '--max-seconds', '1180', '--max-new-tokens', '32']
    report['command'] = command
    with (ROOT / 'logs/p0_qwen3_4b_fp16_01.log').open('xb') as log:
        result = subprocess.run(command, env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, timeout=1220, check=False)
    report.update(status='FINISHED', exit_code=result.returncode)
except BaseException as error:
    report.update(status='LAUNCH_OR_EXECUTION_ERROR', exception_type=type(error).__name__)
    raise
finally:
    report['elapsed_seconds_including_import_hash_load'] = time.time() - started
    report['conservative_single_gpu_minutes'] = report['elapsed_seconds_including_import_hash_load'] / 60
    report['ending_compute_processes'] = subprocess.check_output(
        ['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory', '--format=csv,noheader,nounits'],
        universal_newlines=True)
    status_path.write_text(json.dumps(report, indent=2) + '\n')
