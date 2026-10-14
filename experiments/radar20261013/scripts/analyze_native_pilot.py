"""Complete native sensitivity results; censoring and reader scope separated."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stem_quality import stem_issues,numeric_gold_issues
spec=json.loads((ROOT/'provenance/native_pilot_protocol.json').read_text())
qs=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:spec['n']]
ids={q['problem_id'] for q in qs if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])}
rows=[]
for g in [0,1]:
    assert (ROOT/f'results/native_pilot_{g}.complete.json').exists()
    rows += [json.loads(s) for s in (ROOT/f'results/native_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines()]
expected={(pid,b) for pid in ids for b in spec['nominal_thought_budgets']}
assert {(r['problem_id'],r['nominal_budget']) for r in rows}==expected and len(rows)==len(expected)
statistics={}
for b in spec['nominal_thought_budgets']:
    group=[r for r in rows if r['nominal_budget']==b];finished=[r for r in group if r['eos_completed']]
    statistics[str(b)]={'n':len(group),'correct':sum(r['correct'] for r in group),
        'thinking_closed':sum(r['thinking_closed'] for r in group),'length_censored':sum(r['length_censored'] for r in group),
        'eos_completed':len(finished),'correct_among_eos_completed':sum(r['correct'] for r in finished),
        'censored_complete_answer_correct':sum(r['correct'] and r['length_censored'] for r in group),
        'parse_non_success':sum(r['grade']['parse_status']!='ok' for r in group),
        'mean_wall_s':float(np.mean([r['wall_ms']/1000 for r in group])),
        'mean_tokens':float(np.mean([r['total_tokens'] for r in group])),
        'thinking_prefix_control_failures':sum(not r['same_thinking_prefix_control'] for r in group)}
report={'scope':'Pilot readout sensitivity, distinct total-budget native protocol; no blind-test or learned-policy performance.',
        'no_injected_answer_cue':True,'statistics':statistics,'source_problem_ids':sorted(ids)}
(ROOT/'results/native_pilot_analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='source_problem_ids'},indent=2))
