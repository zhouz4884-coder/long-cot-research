"""Fresh GPU invariants for the actual candidate that may later be delivered."""
import copy,hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed
from radar_engine import candidate
from candidate_schema import scalar_schema
from probe_engine import ProbeEngine

assert (ROOT/'results/pilot.complete.json').exists(), 'Do not contend with measured pilot workers'
model='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
e=ProbeEngine(model)
questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:3]
checks=[]
for q,length in zip(questions,[128,512,2048]):
    prompt=e.prompt(q['question']);seed=stable_seed('candidate_admission',q['problem_id'])
    trace=e.decode(prompt,length,seed,until='eos')
    prefix=prompt+trace['ids'];parent=copy.deepcopy(trace['cache'])
    read=candidate(e,prefix,trace['cache'],trace['logits'],seed)
    original=e.answer(prefix,seed,initial=(copy.deepcopy(parent),trace['logits']))
    same_kv=all(e.torch.equal(a.keys,b.keys) and e.torch.equal(a.values,b.values) for a,b in zip(parent.layers,trace['cache'].layers))
    check={'problem_id':q['problem_id'],'prefix_tokens':length,'same_ids_as_frozen_reader':read['ids']==original['ids'],
           'same_text_as_frozen_reader':read['text']==original['text'],'all_parent_kv_unchanged':same_kv,
           'identity_hash_present':bool(read['candidate_identity_sha256']),
           'projection_dimensions':[len(read['cue_projection']),len(read['answer_projection'])],
           'entropy_error':abs(read['eat_entropy']-original['eat_entropy']),
           'schema':scalar_schema(read['text'])}
    assert same_kv and check['same_ids_as_frozen_reader'] and check['same_text_as_frozen_reader']
    assert check['entropy_error']<1e-8
    checks.append(check);print(json.dumps(check),flush=True)
    del trace,parent,read,original
payload={'passed':True,'checks':checks,'scope':'Finite readout/copy/equality invariants, not proof of answer correctness or performance.',
         'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['radar_engine.py','candidate_schema.py','probe_engine.py','reason_transition/core.py']}}
(ROOT/'provenance/candidate_protocol_admission.json').write_text(json.dumps(payload,indent=2)+'\n')
print('CANDIDATE_PROTOCOL_ADMITTED',flush=True)
