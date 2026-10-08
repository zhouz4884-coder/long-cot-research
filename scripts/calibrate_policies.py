"""Engineering-set-only policy selection. No held-out test labels are read."""
from collections import defaultdict
import json
import math
from pathlib import Path
import pickle
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np

out=Path('results/analysis');out.mkdir(exist_ok=True)
branches=[];probes=[];traces=[]
for kind,container in [('branches',branches),('probes',probes),('traces',traces)]:
    for f in sorted(Path('results/bank').glob(f'engineering_{kind}_*.jsonl')):
        if '_orphan_' in f.name:continue
        container.extend(json.loads(x) for x in f.read_text().splitlines())
assert len({r['problem_id'] for r in traces})==50,'Use the full frozen engineering set'
with (out/'predictor.pkl').open('rb') as f:predictor=pickle.load(f)
by_problem=defaultdict(list)
for r in probes:by_problem[r['problem_id']].append(r)
branch_by_id={r['checkpoint_id']:r for r in branches}
for group in by_problem.values():group.sort(key=lambda r:r['offset'])
baseline_accuracy=float(np.mean([r['grade']['correct'] for r in traces]))
baseline_tokens=float(np.mean([r['trace']['tokens']+r['answer']['tokens'] for r in traces]))
records=[]


def finish(spec,outcomes):
    accuracy=float(np.mean([r['correct'] for r in outcomes]));tokens=float(np.mean([r['tokens'] for r in outcomes]))
    harm=sum(r['full_correct'] and not r['correct'] for r in outcomes)/len(outcomes)
    records.append({**spec,'accuracy':accuracy,'mean_tokens':tokens,'paired_harm_rate':harm,
        'estimated_compute_units':float(np.mean([r['tokens']+r.get('probe_calls',0)*r.get('probe_prefix_tokens',8) for r in outcomes])),
        'delta_accuracy':accuracy-baseline_accuracy,'token_saving':1-tokens/baseline_tokens,'n':len(outcomes)})


def fallback(row):
    return {'correct':row['grade']['correct'],'tokens':row['trace']['tokens']+row['answer']['tokens'],
        'full_correct':row['grade']['correct'],'fp':0.,'fn':0.}


for mode in ['transition','outcome']:
  for cost in [0.0,0.00002,0.00005,0.0001,0.0002,0.0005]:
    for margin in [-0.1,-0.05,0.0,0.02,0.05]:
        outcomes=[]
        for row in traces:
            candidates=[r for r in branches if r['problem_id']==row['problem_id']]
            if not candidates:outcomes.append(fallback(row));continue
            point=min(candidates,key=lambda r:r['prefix_tokens'])
            action,_=predictor.choose(point['features'],cost,margin,mode=mode)
            key={'STOP':'stop','STEP':'step','FULL':'end'}[action]
            outcomes.append({'correct':point[key+'_correct'],'tokens':point['prefix_tokens']+point[key+'_tokens'],'full_correct':point['end_correct']})
        finish({'method':'transition','cost_lambda':cost,'margin':margin,'prediction_mode':mode},outcomes)

# Paper-formula EAT reimplementation, with engineering-only threshold tuning.
for minimum in [4,8,20]:
    for threshold in [0.0001,0.001,0.01,0.05,0.1,0.5]:
        outcomes=[]
        for row in traces:
            mean=variance=0.0;chosen=None
            for index,point in enumerate(by_problem[row['problem_id']],1):
                mean=0.8*mean+0.2*point['eat_entropy']
                variance=0.8*variance+0.2*(point['eat_entropy']-mean)**2
                if index>=minimum and variance/(1-0.8**index)<threshold:
                    chosen=point;break
            outcome={'correct':chosen['correct'],'tokens':chosen['offset']+chosen['answer_tokens'],
                'full_correct':row['grade']['correct']} if chosen else fallback(row)
            outcome['probe_calls']=index if chosen else len(by_problem[row['problem_id']])
            outcome['probe_prefix_tokens']=chosen['answer'].get('control_prefix_input_tokens',8) if chosen else 8
            outcomes.append(outcome)
        finish({'method':'eat','minimum_steps':minimum,'variance_threshold':threshold},outcomes)

# Conformal Thinking (2026) upper/lower threshold mechanisms on the same finite
# decision grid. The calibrated finite-sample UCB and empirical choices are both
# retained; no statistical guarantee is claimed for the empirical choice.
conformal=[]
for upper in [0.2,0.4,0.6,0.8,0.9,0.95,0.99,1.001]:
    for slope in [0.0,0.0001,0.0005,0.001,0.005]:
        outcomes=[]
        for row in traces:
            points=by_problem[row['problem_id']];chosen=None;reason=None;index=0
            for index,point in enumerate(points):
                score=math.exp(-point['eat_entropy'])
                lower=1/(1+math.exp(-max(-700,min(700,slope*(point['offset']-4096))))) if slope else -1
                if score>=upper:chosen=point;reason='upper';break
                if score<lower:chosen=point;reason='lower';break
            if chosen is None:
                outcome=fallback(row);outcome['probe_calls']=len(points);outcomes.append(outcome);continue
            future=[r['correct'] for r in points[index:]]+[row['grade']['correct']]
            outcomes.append({'correct':chosen['correct'],'tokens':chosen['offset']+chosen['answer_tokens'],
                'probe_calls':index+1,'probe_prefix_tokens':chosen['answer'].get('control_prefix_input_tokens',8),
                'full_correct':row['grade']['correct'],'fp':float(reason=='upper' and not chosen['correct']),
                'fn':float(np.mean(future)) if reason=='lower' else 0.})
        finish({'method':'conformal_thinking','upper':upper,'lower_slope':slope,'signal':'exp(-EAT)'},outcomes)
        candidate=records[-1];candidate['fp_risk']=float(np.mean([r.get('fp',0) for r in outcomes]));candidate['fn_risk']=float(np.mean([r.get('fn',0) for r in outcomes]))
        conformal.append(candidate)

selected={}
for method in ['transition','eat','conformal_thinking']:
    candidates=[r for r in records if r['method']==method and r['delta_accuracy']>=-0.01]
    selected[method]=min(candidates,key=lambda r:r['estimated_compute_units']) if candidates else {'method':'full','reason':'no empirical engineering point meets quality tolerance'}
K=len(conformal);bound=math.sqrt(math.log(2*K/0.05)/(2*len(traces)))
certified={}
for epsilon in [0.01,0.05,0.1,0.2,0.3,0.5]:
    feasible=[r for r in conformal if r['fp_risk']+bound<=epsilon and r['fn_risk']+bound<=epsilon]
    certified[str(epsilon)]=min(feasible,key=lambda r:r['estimated_compute_units']) if feasible else {'method':'full','reason':'finite-sample correction admits no early exit','bound':bound}
payload={'engineering_n':len(traces),'baseline_accuracy':baseline_accuracy,'baseline_tokens':baseline_tokens,
    'selected_empirical':selected,'conformal_ucb':certified,'finite_grid_bound':bound,
    'source':'https://arxiv.org/html/2602.03814v1','scope':'independent reimplementation on frozen paragraph decision grid; empirical selections have no risk guarantee',
    'candidates':records}
(out/'policy_calibration.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in payload.items() if k!='candidates'},indent=2))
