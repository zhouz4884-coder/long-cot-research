"""Independent dtype and repeat controls for the initial cache-gate failure."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed

rows=[json.loads(x) for x in Path('data/math500_smoke.jsonl').read_text(encoding="utf-8").splitlines()][:3]
report=[]
for dtype in ['float16']:
    e=Engine('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B',dtype=dtype)
    for row in rows:
        prefix=e.prompt(row['question'])
        generated=e.decode(prefix,128,stable_seed(row['problem_id'],'prefix'),until='eos')
        prefix+=generated['ids'];middle=len(prefix)//2
        _,full=e.forward(prefix);_,repeat=e.forward(prefix)
        cache,_=e.forward(prefix[:middle]);_,restored=e.forward(prefix[middle:],cache)
        top=e.torch.topk(full,20).indices
        pa=full.float().softmax(-1);pb=restored.float().softmax(-1)
        item={'dtype':dtype,'problem_id':row['problem_id'],'prefix_tokens':len(prefix),
            'same_route_max_abs':float((full-repeat).abs().max().item()),
            'cross_route_max_abs':float((full-restored).abs().max().item()),
            'top20_max_abs':float((full[top]-restored[top]).abs().max().item()),
            'total_variation':float((pa-pb).abs().sum().item()/2),
            'same_argmax':int(full.argmax())==int(restored.argmax()),
            'prompt_suffix':e.tok.decode(e.prompt(row['question'])[-12:],skip_special_tokens=False)}
        report.append(item);print(json.dumps(item),flush=True)
    del e.model;e.torch.cuda.empty_cache();del e
Path('results/protocol/cache_diagnosis_fp16.json').write_text(json.dumps(report,indent=2))
