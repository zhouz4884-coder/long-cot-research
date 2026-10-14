"""Recoverable dependency queue; scientific admission is reviewed separately.

The old queue retains ownership of crossed-noise workers. This queue waits for
its real terminal state before using either GPU. It never fabricates review or
completion files and never starts final-test generation on its own.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MODEL = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'


def write_state(stage, status, **details):
    payload = {'stage': stage, 'status': status, 'unix': time.time(), **details}
    path = ROOT / 'results/continuation_state.json'
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(payload, indent=2) + '\n')
    temporary.replace(path)
    print(json.dumps(payload), flush=True)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def gpu_workers():
    result = subprocess.run(
        ['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
        capture_output=True, text=True, check=True)
    return sorted({int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()})


def wait_for_idle():
    last = None
    while True:
        workers = gpu_workers()
        if not workers:
            return
        if workers != last:
            write_state('resource_admission', 'waiting_for_existing_gpu_workers', pids=workers)
            last = workers
        time.sleep(15)


def wait_file(path, stage, predicate=lambda x: True):
    write_state(stage, 'waiting_for_reviewed_dependency', dependency=str(path.relative_to(ROOT)))
    while True:
        value = read_json(path)
        if value is not None and predicate(value):
            return value
        old = read_json(ROOT / 'results/post_pilot_state.json')
        if stage == 'crossed_noise' and old and old.get('status') == 'failed':
            raise RuntimeError('Existing pilot/noise queue failed: ' + json.dumps(old))
        time.sleep(15)


def run_jobs(stage, jobs, markers=(), gpu=True):
    if markers and all((ROOT / marker).exists() for marker in markers):
        write_state(stage, 'raw_completion_markers_exist_pending_analysis')
        return
    if gpu:
        wait_for_idle()
    running = []
    try:
        for device, arguments in jobs:
            environment = os.environ.copy()
            environment['PYTHONUNBUFFERED'] = '1'
            if device is not None:
                environment['CUDA_VISIBLE_DEVICES'] = str(device)
            log = (ROOT / f'logs/continuation_{stage}_{device}.log').open('a')
            process = subprocess.Popen(
                [sys.executable, '-u', *arguments], cwd=ROOT, env=environment,
                stdout=log, stderr=subprocess.STDOUT)
            running.append((process, log, device))
        write_state(stage, 'running', pids={str(device):p.pid for p, _, device in running})
        while any(p.poll() is None for p, _, _ in running):
            time.sleep(5)
        codes = {str(device):p.returncode for p, _, device in running}
        if any(codes.values()):
            raise RuntimeError(stage + ' workers failed: ' + json.dumps(codes))
        assert not markers or all((ROOT / marker).exists() for marker in markers), 'Worker exited without expected output marker'
        write_state(stage, 'processes_exited_pending_evidence_review', exit_codes=codes)
    finally:
        for process, log, device in running:
            if process.poll() is None:
                # Preserve live inference on supervisor interruption. A restarted
                # queue waits for these workers and invokes resumable collectors.
                print(json.dumps({'preserved_live_worker':process.pid,'device':device}), flush=True)
            log.close()


def cpu(stage, script, *arguments):
    run_jobs(stage, [(None, [script, *arguments])], gpu=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--through', choices=['pilot_review', 'm1_review'], default='m1_review')
    args = parser.parse_args()
    # Linux flock prevents two resumed supervisors from dispatching one stage.
    import fcntl
    lock = (ROOT / 'logs/continuation.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Another continuation supervisor owns this study', flush=True)
        return
    try:
        old = wait_file(ROOT / 'results/post_pilot_state.json', 'crossed_noise',
                        lambda x: x.get('stage') == 'formal_reference')
        assert old['status'] == 'waiting_for_agent_interpretation_and_frozen_formal_protocol'
        cpu('budget_analysis', 'scripts/analyze_budget_pilot.py')
        cpu('noise_analysis', 'scripts/analyze_noise_bank.py')
        run_jobs('native_pilot', [(g, ['scripts/run_native_pilot.py', '--model', MODEL, '--shard', str(g)]) for g in [0,1]],
                 [f'results/native_pilot_{g}.complete.json' for g in [0,1]])
        cpu('native_analysis', 'scripts/analyze_native_pilot.py')
        cpu('pilot_integrity', 'scripts/audit_pilot_evidence.py')
        write_state('formal_review', 'waiting_for_agent_interpretation',
                    evidence=['results/budget_pilot_analysis.json', 'results/noise_analysis.json',
                              'results/native_pilot_analysis.json', 'results/pilot_evidence_audit.json'])
        if args.through == 'pilot_review':
            return
        review = wait_file(ROOT / 'provenance/formal_review.json', 'formal_review',
                           lambda x: x.get('admitted_for_development') is True)
        sys.path.insert(0, str(ROOT))
        from protocol_guard import validate_formal, sha256
        formal, formal_hash = validate_formal(ROOT, MODEL)
        assert review['formal_protocol_sha256'] == formal_hash
        for name, digest in review['reviewed_evidence_sha256'].items():
            assert sha256(ROOT / name) == digest, 'Reviewed pilot evidence changed: ' + name
        for split in ['development', 'selection']:
            run_jobs('bank_' + split,
                     [(g, ['scripts/collect_policy_bank.py', '--model', MODEL, '--split', split, '--shard', str(g)]) for g in [0,1]],
                     [f'results/bank_{split}_{g}.complete.json' for g in [0,1]])
        training_path=ROOT/'results/risk_training/grouped_cv.json'
        if not training_path.exists():
            cpu('risk_training', 'scripts/train_risk_heads.py')
        training=read_json(training_path)
        assert training['formal_protocol_sha256']==formal_hash
        for name,digest in training['model_sha256'].items():
            assert sha256(ROOT/f'results/risk_training/{name}.pkl')==digest
        if not (ROOT/'provenance/calibration_candidates.json').exists():
            cpu('candidate_selection', 'scripts/select_calibrate_policies.py', '--phase', 'selection')
        family=read_json(ROOT/'provenance/calibration_candidates.json')
        assert family['model_sha256']==training['model_sha256']
        if not (ROOT/'provenance/m1_selection_online.json').exists():
            cpu('m1_online_plan', 'scripts/build_m1_online_plan.py')
        run_jobs('m1_selection_online',
                 [(g, ['scripts/evaluate_frozen_online.py', '--model', MODEL, '--split', 'selection',
                       '--policy-file', 'provenance/m1_selection_online.json', '--out-tag', 'm1_selection',
                       '--shard', str(g)]) for g in [0,1]],
                 [f'results/online_m1_selection_{g}.complete.json' for g in [0,1]])
        cpu('m1_analysis', 'scripts/analyze_m1_online.py')
        write_state('m1_review', 'waiting_for_agent_scientific_gate',
                    evidence=['results/m1_online_analysis.json'],
                    remaining='Independent calibration, strong baselines, conditional M2, frozen test and transfers, conditional serving and complete archive')
    except Exception as error:
        write_state('continuation', 'failed', error=type(error).__name__ + ': ' + str(error))
        raise


if __name__ == '__main__':
    main()
