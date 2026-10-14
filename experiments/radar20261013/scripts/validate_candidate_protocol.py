"""Fresh GPU invariants for the actual candidate that may later be delivered."""
import argparse,copy,hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed
from radar_engine import candidate
from candidate_schema import scalar_schema
from probe_engine import ProbeEngine
from protocol_guard import package_snapshot

assert (ROOT/'results/pilot.complete.json').exists(), 'Do not contend with measured pilot workers'
parser=argparse.ArgumentParser()
parser.add_argument('--model',default='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B')
parser.add_argument('--output',default='candidate_protocol_admission.json')
parser.add_argument('--lengths',nargs=3,type=int,default=[128,512,2048])
parser.add_argument('--prefix-source',choices=['generated','saved_pilot'],default='generated')
args=parser.parse_args();model=args.model
assert Path(args.output).name==args.output,'Use a plain admission filename'
assert all(n>0 for n in args.lengths)
e=ProbeEngine(model)
questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()]
by_id={q['problem_id']:q for q in questions}
saved=[]
if args.prefix_source=='saved_pilot':
    for file in sorted((ROOT/'results').glob('budget_pilot_[01].jsonl')):
        saved += [json.loads(s) for s in file.read_text(encoding='utf-8').splitlines()]
    saved=[row for row in saved if row['model_path']==model and row['problem_id'] in by_id]
    assert saved,'No completed same-model saved pilot prefixes; do not substitute another model'
used=set()
checks=[]
for index,length in enumerate(args.lengths):
    if args.prefix_source=='saved_pilot':
        eligible=[row for row in saved if len(row['trace']['ids'])>=length
                  and not any(token==e.endthink or token in e.eos for token in row['trace']['ids'][:length])]
        assert eligible,'No valid saved prefix at the requested actual length'
        unused=[row for row in eligible if row['problem_id'] not in used]
        row=min(unused or eligible,key=lambda r:(r['problem_id'],r['budget']))
        q=by_id[row['problem_id']];used.add(q['problem_id'])
    else:q=questions[index]
    prompt=e.prompt(q['question']);seed=stable_seed('candidate_admission',q['problem_id'])
    e.torch.cuda.reset_peak_memory_stats()
    if args.prefix_source=='saved_pilot':
        ids=row['trace']['ids'][:length];cache,logits=e.forward(prompt+ids)
        trace={'ids':ids,'cache':cache,'logits':logits}
    else:trace=e.decode(prompt,length,seed,until='eos')
    prefix=prompt+trace['ids'];parent=copy.deepcopy(trace['cache'])
    read=candidate(e,prefix,trace['cache'],trace['logits'],seed)
    original=e.answer(prefix,seed,initial=(copy.deepcopy(parent),trace['logits']))
    same_kv=all(e.torch.equal(a.keys,b.keys) and e.torch.equal(a.values,b.values) for a,b in zip(parent.layers,trace['cache'].layers))
    check={'problem_id':q['problem_id'],'prefix_tokens':len(trace['ids']),'requested_max_tokens':length,'same_ids_as_frozen_reader':read['ids']==original['ids'],
           'same_text_as_frozen_reader':read['text']==original['text'],'all_parent_kv_unchanged':same_kv,
           'identity_hash_present':bool(read['candidate_identity_sha256']),
           'projection_dimensions':[len(read['cue_projection']),len(read['answer_projection'])],
           'entropy_error':abs(read['eat_entropy']-original['eat_entropy']),
           'prefix_source':args.prefix_source,'peak_allocated_bytes':e.torch.cuda.max_memory_allocated(),
           'schema':scalar_schema(read['text'])}
    assert same_kv and check['same_ids_as_frozen_reader'] and check['same_text_as_frozen_reader']
    assert check['entropy_error']<1e-8
    checks.append(check);print(json.dumps(check),flush=True)
    del trace,parent,read,original
    if args.prefix_source=='saved_pilot':del cache,logits
payload={'passed':True,'model_path':model,'checks':checks,'scope':'Finite readout/copy/equality invariants, not proof of answer correctness or performance.',
         'prefix_reconstruction_scope':'Saved pilot mode selects by length only and restores a real cache via full prefill; it is not the historical incremental KV state. Generated mode records actual termination length.',
         'package_versions':package_snapshot(),
         'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['radar_engine.py','candidate_schema.py','probe_engine.py','reason_transition/core.py','reason_transition/text_decoder.py','stem_quality.py','scripts/validate_candidate_protocol.py']}}
(ROOT/'provenance'/args.output).write_text(json.dumps(payload,indent=2)+'\n')
print('CANDIDATE_PROTOCOL_ADMITTED',flush=True)
