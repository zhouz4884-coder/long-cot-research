"""Sequential finite interfaces after native completion; never releases formal.

Persistent lock and real child status allow observation across chat turns.
Existing GPU jobs are preserved. Each stage executes freshly, not by marker.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
MODEL = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
ENCODER = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/all-MiniLM-L6-v2'


def state(stage, status, **kwargs):
    payload = {'stage': stage, 'status': status, 'unix': time.time(), **kwargs}
    p = ROOT / 'results/finite_admission_state.json'
    temporary = p.with_suffix('.pending')
    temporary.write_text(json.dumps(payload, indent=2) + '\n')
    temporary.replace(p)
    print(json.dumps(payload), flush=True)


def wait_idle():
    while True:
        result = subprocess.run(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                                check=True, capture_output=True, text=True)
        active = [int(x.strip()) for x in result.stdout.splitlines() if x.strip().isdigit()]
        if not active:
            return
        state('resource_admission', 'waiting_for_live_gpu_processes', pids=active)
        time.sleep(10)


def main():
    lock = (ROOT / 'logs/finite_admission.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sys.path.insert(0, str(ROOT))
    from protocol_guard import sha256, source_snapshot
    audit = json.loads((ROOT / 'results/pilot_evidence_audit.json').read_text())
    assert audit['passed'] and audit['native_requests'] == 58 and audit['actual_test_generation_records'] == 0
    for name, digest in audit['raw_source_sha256'].items():
        assert sha256(ROOT / name) == digest
    binding = source_snapshot(ROOT)
    stages = [
        ('live_protocol', ['scripts/validate_new_protocol.py']),
        ('candidate_protocol', ['scripts/validate_candidate_protocol.py', '--lengths', '128', '8192', '16384',
                                '--prefix-source', 'saved_pilot', '--output', 'candidate_formal_admission.json']),
        ('dtsr_protocol', ['scripts/validate_dtsr_gpu.py', '--model', MODEL]),
        ('refrain_protocol', ['scripts/validate_refrain_gpu.py', '--model', MODEL, '--encoder', ENCODER,
                              '--encoder-manifest', 'provenance/refrain_encoder_manifest.json']),
        ('asag_protocol', ['scripts/validate_asag_gpu.py', '--model', MODEL]),
    ]
    for name, args in stages:
        assert source_snapshot(ROOT) == binding, 'Main runtime changed during interface validation'
        wait_idle()
        env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '0', 'PYTHONUNBUFFERED': '1'}
        with (ROOT / f'logs/finite_admission_{name}.log').open('a') as log:
            child = subprocess.Popen([sys.executable, '-u', *args], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            state(name, 'running', child_pid=child.pid, arguments=args)
            code = child.wait()
        state(name, 'exited', child_pid=child.pid, exit_code=code)
        if code:
            state(name, 'failed', child_pid=child.pid, exit_code=code)
            return code
    state('all_finite_interfaces', 'processes_exited_pending_evidence_review',
          scope='Not model-task efficacy; formal scientific review and actual per-report inspection remain required.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
