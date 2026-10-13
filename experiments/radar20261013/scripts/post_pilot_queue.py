"""Persistent dependency queue: real pilot -> interface admission -> reviewed pilot.

The scoring review is performed by the agent from raw materials, not inferred
from marker existence or file hashes. No formal/test experiment is auto-admitted.
"""
import json,os,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT)
PY=str(ROOT/'.venv/bin/python')
MODEL='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
statefile=ROOT/'results/post_pilot_state.json'


def state(stage,status,**kwargs):
    p={'stage':stage,'status':status,'unix':time.time(),**kwargs}
    statefile.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(p),flush=True)


def run(stage,jobargs):
    processes=[]
    for gpu,args in jobargs:
        env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=str(gpu);env['PYTHONUNBUFFERED']='1'
        handle=(ROOT/f'logs/{stage}_gpu{gpu}.log').open('a')
        proc=subprocess.Popen([PY,'-u',*args],env=env,stdout=handle,stderr=subprocess.STDOUT)
        processes.append((proc,handle,gpu))
    state(stage,'running',pids={str(g):p.pid for p,_,g in processes})
    while any(p.poll() is None for p,_,_ in processes):time.sleep(5)
    codes={str(g):p.returncode for p,_,g in processes}
    for _,handle,_ in processes:handle.close()
    if any(codes.values()):state(stage,'failed',exit_codes=codes);raise SystemExit(1)
    state(stage,'complete',exit_codes=codes)


state('pilot','waiting_for_real_complete_outputs')
while not (ROOT/'results/pilot.complete.json').exists():time.sleep(5)
questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()]
rows=[]
for file in (ROOT/'results').glob('pilot_full_*.jsonl'):
    rows += [json.loads(s) for s in file.read_text(encoding='utf-8').splitlines()]
assert len(rows)==len(questions)==100
assert {r['problem_id'] for r in rows}=={r['problem_id'] for r in questions}
summary={'n':100,'correct':sum(r['correct'] for r in rows),'censored':sum(r['length_censored'] for r in rows),
         'parse_non_success':sum(r['grade']['parse_status']!='ok' for r in rows),
         'mean_wall_s':sum(r['wall_ms'] for r in rows)/100000,
         'mean_tokens':sum(r['total_tokens'] for r in rows)/100,
         'scope':'Complete pilot; not final performance or scoring review admission.'}
(ROOT/'results/pilot_statistics.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary),flush=True)
run('candidate_admission',[(0,['scripts/validate_candidate_protocol.py'])])
state('pilot_review','waiting_for_agent_review_of_raw_answers_and_types')
while True:
    path=ROOT/'provenance/pilot_review.json'
    if path.exists() and json.loads(path.read_text()).get('admitted'):break
    time.sleep(5)
if summary['censored']/100>=.2:
    run('budget_pilot',[(g,['scripts/run_budget_pilot.py','--model',MODEL,'--shard',str(g)]) for g in [0,1]])
run('noise_bank',[(g,['scripts/collect_noise_bank.py','--model',MODEL,'--shard',str(g)]) for g in [0,1]])
run('noise_analysis',[(0,['scripts/analyze_noise_bank.py'])])
state('formal_reference','waiting_for_agent_interpretation_and_frozen_formal_protocol')
