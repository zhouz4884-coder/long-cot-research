"""Uniform current scoring of retained independent-seed branch repetitions."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import grade

traces={}
for p in Path('results/bank').glob('engineering_traces_*.jsonl'):
 traces.update({r['problem_id']:r for r in (json.loads(line) for line in p.read_text(encoding='utf-8').splitlines())})
raw=[json.loads(line) for line in Path('results/controls/repeat_branches.jsonl').read_text(encoding='utf-8').splitlines()]
assert len({(r['checkpoint_id'],r['repeat']) for r in raw})==len(raw)
groups=defaultdict(list);derived=[]
for r in raw:
 gold=traces[r['problem_id']]['gold']
 stop=grade(r['stop']['text'],gold);step=grade(r['step_answer']['text'],gold)
 row={k:r[k] for k in ['problem_id','checkpoint_id','repeat','seed','prefix_hash']}
 row.update(stop_grade=stop,step_grade=step,stop_correct=stop['correct'],step_correct=step['correct'],
  original_stop_correct=r['stop_correct'],original_step_correct=r['step_correct'])
 groups[r['checkpoint_id']].append(row);derived.append(row)
summary=[]
for key,rows in groups.items():
 assert len(rows)==4,(key,len(rows))
 transitions=Counter(f"{r['stop_correct']}->{r['step_correct']}" for r in rows)
 summary.append({'checkpoint_id':key,'n':len(rows),'stop_correct':sum(r['stop_correct'] for r in rows),
  'step_correct':sum(r['step_correct'] for r in rows),'transition_counts':dict(transitions),
  'mean_step_minus_stop':sum(r['step_correct']-r['stop_correct'] for r in rows)/len(rows)})
out=Path('results/analysis');out.mkdir(exist_ok=True)
payload={'state_n':len(groups),'repeat_n':len(raw),'repeats_per_state':4,'states':summary,
 'sampling_scope':'Engineering event-conditioned states. Retains union of eight original states and post-scorer-repair selected states. Not representative event prevalence.',
 'warning':'Four repeats quantify observed stability but do not establish deterministic causal effect or population risk.'}
(out/'repeat_control_analysis.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
(out/'repeat_control_v3_grades.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in derived),encoding='utf-8')
print(json.dumps(payload,indent=2))
