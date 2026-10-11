import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed

e=Engine('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B')
rows=[json.loads(x) for x in Path('data/math500_smoke.jsonl').read_text(encoding='utf-8').splitlines()][:3]
checks=[]
for row in rows:
    seed=stable_seed(row['problem_id'],'crop_test');prompt=e.prompt(row['question'])
    prefix_run=e.decode(prompt,256,seed,until='eos');prefix=prompt+prefix_run['ids']
    cache=prefix_run['cache'];logits=prefix_run['logits'];original_length=cache.get_seq_length()
    preserved=copy.deepcopy(cache)
    child=copy.deepcopy(cache);_,reference_logits=e.forward(e.suffix,child)
    lp=reference_logits.float().log_softmax(-1);reference=float(-(lp.exp()*lp).sum().item())
    observed=e.entropy_probe(cache,logits)
    same_keys=all(e.torch.equal(a.keys,b.keys) and e.torch.equal(a.values,b.values) for a,b in zip(cache.layers,preserved.layers))
    a=e.decode(prefix,16,seed,offset=256,until='eos',initial=(cache,logits))
    b=e.decode(prefix,16,seed,offset=256,until='eos',initial=(preserved,logits))
    check={'problem_id':row['problem_id'],'original_length':original_length,'same_kv':same_keys,
        'entropy_error':abs(reference-observed['entropy']),'same_sampled_continuation':a['ids']==b['ids'],'probe_ms':observed['ms']}
    checks.append(check);print(json.dumps(check),flush=True)
    assert same_keys and check['entropy_error']<1e-8 and a['ids']==b['ids']
Path('results/protocol/entropy_probe_crop.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
