"""Complete matched strict-budget diagnostics, retaining censoring and failures."""
import json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stem_quality import stem_issues,numeric_gold_issues

spec=json.loads((ROOT/'provenance/budget_pilot_protocol.json').read_text())
questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:spec['n']]
ids={q['problem_id'] for q in questions if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])}
methods={b:{} for b in [8192,*spec['budgets']]}
for g in [0,1]:
    assert (ROOT/f'results/budget_pilot_{g}.complete.json').exists()
    for line in (ROOT/f'results/budget_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line);assert r['problem_id'] in ids
        assert r['problem_id'] not in methods[r['budget']]
        methods[r['budget']][r['problem_id']]=r
    for line in (ROOT/f'results/pilot_full_{g}.jsonl').read_text(encoding='utf-8').splitlines():
        r=json.loads(line)
        if r['problem_id'] in ids:methods[8192][r['problem_id']]=r
assert all(set(rows)==ids for rows in methods.values())
controls=[]
for pid in sorted(ids):
    reference=methods[8192][pid]
    for b,rows in methods.items():
        r=rows[pid]
        assert r['seed']==reference['seed'] and r['model_path']==reference['model_path']
        shared=min(len(r['trace']['ids']),len(reference['trace']['ids']))
        if r['trace']['ids'][:shared]!=reference['trace']['ids'][:shared]:controls.append({'problem_id':pid,'budget':b,'reason':'thinking_prefix_diverged'})
stats={}
rng=np.random.default_rng(20261013);order=sorted(ids)
ref=np.array([methods[8192][i]['correct'] for i in order])
for b,rows in methods.items():
    candidate=np.array([rows[i]['correct'] for i in order]);delta=candidate-ref
    draws=[delta[rng.integers(0,len(ids),len(ids))].mean() for _ in range(2000)]
    stats[str(b)]={'n':len(ids),'correct':int(candidate.sum()),'accuracy':float(candidate.mean()),
                   'accuracy_delta_vs8192':float(delta.mean()),'problem_bootstrap_95ci':np.quantile(draws,[.025,.975]).tolist(),
                   'mean_tokens':float(np.mean([r['total_tokens'] for r in rows.values()])),
                   'mean_wall_s':float(np.mean([r['wall_ms']/1000 for r in rows.values()])),
                   'censored':sum(r['trace']['length_censored'] for r in rows.values()),
                   'parse_non_success':sum(r['grade']['parse_status']!='ok' for r in rows.values()),
                   '8192_timing_has_pilot_feature_capture':b==8192}
report={'scope':'Pilot diagnostic; not blind test, final policy performance or independent certification.',
        'eligible_problem_ids':order,'statistics':stats,'thinking_prefix_control_failures':controls,
        'timing_warning':'8192 uses the previously measured feature-capture pilot; other budgets are actual independent uninstrumented requests. Formal comparison must use matched runtime settings.',
        'reference_selection_frozen':False}
(ROOT/'results/budget_pilot_analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='eligible_problem_ids'},indent=2))
