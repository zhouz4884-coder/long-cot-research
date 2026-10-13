import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl

bank=Path('results/bank');out=Path('results/controls');out.mkdir(exist_ok=True)
branches=[];traces={}
for f in bank.glob('engineering_branches_*.jsonl'):
    if '_orphan_' not in f.name:branches.extend(json.loads(x) for x in f.read_text(encoding="utf-8").splitlines())
for f in bank.glob('engineering_traces_*.jsonl'):
    traces.update({r['problem_id']:r for r in (json.loads(x) for x in f.read_text(encoding="utf-8").splitlines())})
points=[];used=set()
events=[r for r in branches if r['stop_correct']!=r['step_correct']]
neutrals=[r for r in branches if r['stop_correct']==r['step_correct']]
for r in sorted(events,key=lambda r:(r['problem_id'],r['prefix_tokens']))+sorted(neutrals,key=lambda r:(r['prefix_tokens'],r['problem_id'])):
    if r['checkpoint_id'] not in used:
        used.add(r['checkpoint_id']);points.append(r)
    if len(points)==8:break
e=Engine('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B')
path=out/'repeat_branches.jsonl'
done={(r['checkpoint_id'],r['repeat']) for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines())} if path.exists() else set()
for point in points:
    if all((point['checkpoint_id'],repeat) in done for repeat in range(4)):continue
    row=traces[point['problem_id']];prompt=row['prompt_ids'];prefix=point['prefix_ids']
    cache,logits=e.forward(prompt)
    for token in prefix[len(prompt):]:cache,logits=e.forward([token],cache)
    for repeat in range(4):
        if (point['checkpoint_id'],repeat) in done:continue
        seed=stable_seed(row['seed'],'independent_repeat',repeat)
        stop=e.answer(prefix,seed,initial=(copy.deepcopy(cache),logits))
        step=e.decode(prefix,214,seed,offset=point['prefix_tokens'],until='step',initial=(copy.deepcopy(cache),logits))
        answer=e.answer(prefix+step['ids'],seed,natural_closed=step['stop_reason']=='natural_end',initial=(step['cache'],step['logits']))
        record={'problem_id':point['problem_id'],'checkpoint_id':point['checkpoint_id'],'repeat':repeat,'seed':seed,
            'prefix_hash':point['prefix_hash'],'stop_correct':grade(stop['text'],row['gold'])['correct'],
            'step_correct':grade(answer['text'],row['gold'])['correct'],'stop':public(stop),'step':public(step),
            'step_answer':public(answer),'cache_source':'same tokenwise replay route as parent; cloned for each action'}
        append_jsonl(path,record);print(json.dumps({k:v for k,v in record.items() if k not in ['stop','step','step_answer']}),flush=True)
        del stop,step,answer
