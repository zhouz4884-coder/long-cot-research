"""Label-informed token upper bound, explicitly not an online method."""
from collections import defaultdict
import json
from pathlib import Path
import numpy as np

traces=[];probes=defaultdict(list)
for p in Path('results/bank').glob('engineering_traces_*.jsonl'):
    traces.extend(json.loads(x) for x in p.read_text(encoding='utf-8').splitlines())
for p in Path('results/bank').glob('engineering_probes_*.jsonl'):
    if '_orphan_' not in p.name:
        for s in p.read_text(encoding='utf-8').splitlines():
            r=json.loads(s);probes[r['problem_id']].append(r)
rows=[]
for trace in traces:
    points=sorted(probes[trace['problem_id']],key=lambda r:r['offset'])
    correct=[p for p in points if p['correct']]
    chosen=correct[0] if correct else (points[0] if not trace['grade']['correct'] and points else None)
    full_tokens=trace['trace']['tokens']+trace['answer']['tokens']
    rows.append({'problem_id':trace['problem_id'],'full_correct':trace['grade']['correct'],
        'oracle_correct':chosen['correct'] if chosen else trace['grade']['correct'],
        'full_tokens':full_tokens,'oracle_tokens':chosen['offset']+chosen['answer_tokens'] if chosen else full_tokens,
        'natural_end':trace['trace']['stop_reason']=='natural_end','observed_checkpoints':len(points)})
report={'n':len(rows),'full_accuracy':float(np.mean([r['full_correct'] for r in rows])),
    'oracle_accuracy':float(np.mean([r['oracle_correct'] for r in rows])),
    'mean_full_tokens':float(np.mean([r['full_tokens'] for r in rows])),
    'mean_oracle_tokens':float(np.mean([r['oracle_tokens'] for r in rows])),
    'token_saving_upper_bound':1-sum(r['oracle_tokens'] for r in rows)/sum(r['full_tokens'] for r in rows),
    'censored_n':sum(not r['natural_end'] for r in rows),
    'scope':'infeasible label-informed oracle on engineering checkpoints; not measured online speedup','rows':rows}
Path('results/analysis/pilot_oracle.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='rows'}))
