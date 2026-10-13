"""Problem-cluster analysis of crossed readout/continuation interventions."""
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from crossed_variance import crossed_components
protocol=json.loads((ROOT/'provenance/noise_protocol.json').read_text())
files=sorted((ROOT/'results').glob('noise_bank_*.jsonl'))
assert len(files)==2,'No partial noise-bank analysis presented as final'
states=[]
for file in files:
    states += [json.loads(s) for s in file.read_text(encoding='utf-8').splitlines()]
assert len({s['state_id'] for s in states})==len(states)
statuses=[]
for shard in [0,1]:
    statuses+=json.loads((ROOT/f'results/noise_status_{shard}.json').read_text())
expected={s['state_id'] for s in statuses if s['status']=='eligible'}
assert {s['state_id'] for s in states}==expected,'Unfinished state interventions'
assert states,'No eligible measured states'
per_problem=defaultdict(list)
details=[]
for s in states:
    stop=np.array([r['correct'] for r in s['stop_readouts']],dtype=float)
    assert len(stop)==protocol['answer_repeats']
    item={'state_id':s['state_id'],'problem_id':s['problem_id'],'offset':s['offset'],
          'stop_accuracy':float(stop.mean()),'stop_readout_variance':float(stop.var(ddof=1)),
          'stop_disagrees_in_correctness':len(set(stop))>1,'actions':{}}
    for action in ['DEFER_1','DEFER_4','FULL']:
        branches=sorted([b for b in s['branches'] if b['action']==action],key=lambda b:b['reasoning_index'])
        y=np.array([[r['correct'] for r in b['readouts']] for b in branches],dtype=float)
        assert y.shape==(protocol['reasoning_repeats'],protocol['answer_repeats'])
        components=crossed_components(y)
        within=components['within_readout']
        ms_interaction=components['interaction']
        observed_between=components['observed_reasoning_means']
        # The same answer seeds cross all reasoning seeds. Ordinary nested
        # correction (subtract within/m) is biased under this common randomness.
        # Two-way random-effect ANOVA subtracts interaction/m instead.
        adjusted_between=components['reasoning_unclipped']
        answer_seed_component=components['answer_seed_unclipped']
        # Keep negative estimates visible: only constrained descriptive display clips.
        item['actions'][action]={
            'accuracy':float(y.mean()),'accuracy_delta_vs_stop':float(y.mean()-stop.mean()),
            'within_readout_variance':within,'observed_variance_of_reasoning_means':observed_between,
            'crossed_seed_interaction_variance':ms_interaction,
            'answer_seed_main_variance_unclipped':answer_seed_component,
            'bias_corrected_between_reasoning_variance_unclipped':adjusted_between,
            'constrained_between_reasoning_variance':max(0.,adjusted_between),
            'paired_harm_rate':float(((stop[None,:]==1)&(y==0)).mean()),
            'paired_fix_rate':float(((stop[None,:]==0)&(y==1)).mean()),
            'mean_thought_ms':float(np.mean([b['trajectory']['ms'] for b in branches])),
            'mean_thought_tokens':float(np.mean([b['trajectory']['tokens'] for b in branches])),
            'capped_branch_count':sum(b['trajectory']['length_censored'] for b in branches),
            'insufficient_paragraph_count':sum(b['trajectory'].get('steps_completed',0)<int(action[-1])
                                               and b['trajectory']['stop_reason'] not in ['natural_end','eos']
                                               for b in branches) if action!='FULL' else None}
    details.append(item);per_problem[s['problem_id']].append(item)
ids=sorted(per_problem)
report={'scope':'Pilot-only operational interventions; not blind-test performance, latent reasoning causality or population flip prevalence.',
        'transition_orientation':'paired_fix = STOP wrong/action correct = harmful STOP relative to action; paired_harm is the opposite continuation regression.',
        'problems_with_states':len(ids),'eligible_states':len(states),
        'problem_ids':ids,'eligibility_status_counts':{k:sum(s['status']==k for s in statuses)
                                                     for k in sorted({s['status'] for s in statuses})},
        'actions':{},'states':details,'bootstrap_unit':'problem_id',
        'variance_estimator':'Crossed R x E two-way random-effects ANOVA. Reasoning variance = var(row means) - MS_interaction/E; within readout variance = answer-seed main effect + interaction in expectation.',
        'variance_warning':'Only three reasoning and three readout repeats; estimates are noisy. Negative corrected components retained. Bernoulli variance alone does not show semantic progress.'}
rng=np.random.default_rng(20261013)
for action in ['DEFER_1','DEFER_4','FULL']:
    metrics=['accuracy_delta_vs_stop','within_readout_variance','bias_corrected_between_reasoning_variance_unclipped',
             'paired_harm_rate','paired_fix_rate','mean_thought_ms','mean_thought_tokens']
    x=np.array([[np.mean([s['actions'][action][m] for s in per_problem[pid]]) for m in metrics] for pid in ids])
    samples=np.array([x[rng.integers(0,len(ids),len(ids))].mean(axis=0) for _ in range(2000)])
    ci=np.quantile(samples,[.025,.975],axis=0)
    report['actions'][action]={m:{'problem_equal_weight_mean':float(x[:,j].mean()),
                                  'problem_bootstrap_95ci':[float(ci[0,j]),float(ci[1,j])]} for j,m in enumerate(metrics)}
path=ROOT/'results/noise_analysis.json';path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['states','problem_ids']},indent=2))
