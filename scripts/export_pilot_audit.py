import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import digest_ids

traces={};branches=[]
for p in Path('results/bank').glob('engineering_traces_*.jsonl'):
    traces.update({r['problem_id']:r for r in (json.loads(x) for x in p.read_text(encoding='utf-8').splitlines())})
for p in Path('results/bank').glob('engineering_branches_*.jsonl'):
    if '_orphan_' not in p.name:branches.extend(json.loads(x) for x in p.read_text(encoding='utf-8').splitlines())
assert len(traces)==24
assert all(digest_ids(r['prefix_ids'])==r['prefix_hash'] for r in branches)
pool=[]
for r in sorted(branches,key=lambda r:(r['problem_id'],r['prefix_tokens'])):
    for action,key in [('STOP','stop'),('STEP','step_answer')]:
        scored=r[action.lower()+'_grade']
        pool.append({'problem_id':r['problem_id'],'checkpoint_id':r['checkpoint_id'],'action':action,
            'gold':traces[r['problem_id']]['gold'],'text':r[key]['text'],'grade':scored,'kind':r['checkpoint_kind'],
            'step_overflow':r['step_overflow'],'prefix_hash':r['prefix_hash']})
selected=[]
for problem_id in sorted(traces):
    group=[r for r in pool if r['problem_id']==problem_id]
    if group:selected.extend(group[:2])
    else:
        r=traces[problem_id]
        selected.extend([{'problem_id':problem_id,'action':'FULL','gold':r['gold'],'text':r['answer']['text'],'grade':r['grade']},
            {'problem_id':problem_id,'action':'ZERO','gold':r['gold'],'text':r['zero_answer']['text'],'grade':r['zero_grade']}])
for candidate in pool:
    if len(selected)>=50:break
    if candidate not in selected:selected.append(candidate)
assert len(selected)==50
out=Path('results/analysis');out.mkdir(exist_ok=True)
(out/'pilot_audit_50.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
for i,row in enumerate(selected):
    print(json.dumps({'i':i+1,'id':row['problem_id'],'action':row['action'],'gold':row['gold'],
        'boxed':row['grade'].get('boxed'),'correct':row['grade']['correct'],'parse':row['grade']['parse_status']},ensure_ascii=False))
