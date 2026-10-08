import copy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,grade,public

e=Engine('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B')
rows=[json.loads(x) for x in Path('data/math500_smoke.jsonl').read_text().splitlines()]
row=rows[0];prompt=e.prompt(row['question']);seed=stable_seed(20261008,row['problem_id'],0)
initial=e.decode(prompt,128,seed,until='eos')
prefix=prompt+initial['ids'];cache=initial['cache'];logits=initial['logits']
parent_length=cache.get_seq_length();parent_snapshot=cache.layers[0].keys.clone()
child=copy.deepcopy(cache);stop=e.answer(prefix,seed,initial=(child,logits))
unchanged=(cache.get_seq_length()==parent_length and e.torch.equal(parent_snapshot,cache.layers[0].keys))
one=e.decode(prefix,16,seed,offset=128,until='eos',initial=(copy.deepcopy(cache),logits))
two=e.decode(prefix,16,seed,offset=128,until='eos',initial=(copy.deepcopy(cache),logits))
report={'parent_unchanged':unchanged,'same_continuation':one['ids']==two['ids'],
    'child_length':child.get_seq_length(),'parent_length':parent_length,'stop_answer':public(stop),'stop_grade':grade(stop['text'],row['gold'])}
p=Path('results/protocol/ending_initial_format_failure.jsonl')
if p.exists():
    old=json.loads(p.read_text().splitlines()[0]);fixed=e.answer(e.prompt(old['question'])+old['trace']['ids'],old['seed'],natural_closed=old['natural_closed'])
    report['same_prefix_format_repair']={'old':old['answer']['text'],'old_grade':old['grade'],'new':public(fixed),'new_grade':grade(fixed['text'],old['gold'])}
report['code_sha256']=hashlib.sha256(Path('reason_transition/core.py').read_bytes()).hexdigest()
report['short_answer_stops_on_complete_box']=stop['stop_reason']=='answer_box_complete'
report['passed']=unchanged and one['ids']==two['ids'] and report['short_answer_stops_on_complete_box']
Path('results/protocol/clone_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report),flush=True)
assert report['passed']
