"""Persistent, resumable dependency-ordered execution on two authorized GPUs."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import time

TASK=Path(__file__).resolve().parents[1];os.chdir(TASK)
PY=str(TASK/'.venv/bin/python');MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
LOG=TASK/'logs';LOG.mkdir(exist_ok=True)
STATE=TASK/'results/pipeline_state.json'


def state(stage,status,**extra):
    payload={'stage':stage,'status':status,'unix_time':time.time(),**extra}
    tmp=STATE.with_suffix('.pending');tmp.write_text(json.dumps(payload,indent=2));tmp.replace(STATE)
    print(json.dumps(payload),flush=True)


def read(path):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return {}


def run(stage,jobs):
    marker=TASK/f'results/{stage}.complete.json'
    if marker.exists():return
    state(stage,'running',jobs=[j[1] for j in jobs]);processes=[]
    for gpu,arguments in jobs:
        env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=str(gpu);env['PYTHONUNBUFFERED']='1'
        handle=(LOG/f'{stage}_gpu{gpu}.log').open('a')
        process=subprocess.Popen([PY,*arguments],env=env,stdout=handle,stderr=subprocess.STDOUT,cwd=TASK)
        processes.append((process,handle,gpu))
    while any(p.poll() is None for p,_,_ in processes):time.sleep(10)
    codes={str(gpu):p.returncode for p,_,gpu in processes}
    for _,handle,_ in processes:handle.close()
    if any(codes.values()):state(stage,'failed',return_codes=codes);raise SystemExit(1)
    marker.write_text(json.dumps({'completed_unix':time.time(),'return_codes':codes},indent=2));state(stage,'complete')


state('P0_admission','waiting_for_running_baseline_and_protocol')
while True:
    admitted=read('results/protocol/checks.json').get('admitted',False)
    clone_report=read('results/protocol/clone_check.json')
    clone=clone_report.get('passed',False) and clone_report.get('code_sha256')==hashlib.sha256(Path('reason_transition/core.py').read_bytes()).hexdigest()
    original_done='--- VERDICT ---' in Path('logs/original.log').read_text(encoding='utf-8',errors='replace')
    if admitted and clone and original_done:break
    time.sleep(15)
run('pilot_24',[(g,['scripts/collect_bank.py','--model',MODEL,'--split','engineering','--n','24','--shard',str(g),'--shards','2','--dense-stop']) for g in [0,1]])
run('pilot_analysis',[(0,['scripts/analyze_transitions.py','--pilot'])])
state('pilot_review','waiting_for_agent_audit_of_50_answers')
while not read('results/protocol/pilot_review.json').get('admitted'):time.sleep(15)
run('development_150',[(g,['scripts/collect_bank.py','--model',MODEL,'--split','development','--shard',str(g),'--shards','2']) for g in [0,1]])
run('engineering_50',[(g,['scripts/collect_bank.py','--model',MODEL,'--split','engineering','--n','50','--shard',str(g),'--shards','2','--dense-stop']) for g in [0,1]])
run('grouped_prediction',[(0,['scripts/analyze_transitions.py'])])
run('calibration',[(0,['scripts/calibrate_policies.py'])])
run('repeat_controls',[(0,['scripts/repeat_branch_controls.py'])])
state('test_freeze','waiting_for_complete_ablation_policy_freeze')
while not read('provenance/ABLATION_POLICY_FREEZE_20261012.json').get('admitted'):time.sleep(15)
run('online_50',[(g,['scripts/evaluate_online.py','--model',MODEL,'--n','50','--shard',str(g),'--shards','2']) for g in [0,1]])
if not read('provenance/qwen3_thinking_verified.json').get('all_match'):
    state('second_model','blocked_by_unverified_model_files');raise SystemExit(2)
model2='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B-Thinking-2507'
run('second_model_24',[(g,['scripts/evaluate_online.py','--model',model2,'--n','24','--offset','50','--shard',str(g),'--shards','2','--methods','full,transition','--out-name','qwen3_thinking_2507']) for g in [0,1]])
state('experiment_execution','complete_pending_statistical_analysis_and_agent_report')
