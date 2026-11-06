"""Finite old/new GPU identity control before resuming a frozen bank.

Selection uses shard and length only; no Gold or correctness is inspected.
This is a reproducibility check, not a new task benchmark.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def select_canary(rows,max_tokens=4096):
    eligible=[r for r in rows if r['points'] and len(r['full']['trace']['ids'])<=max_tokens]
    assert eligible,'No completed bounded-length row for a finite recovery canary'
    return min(eligible,key=lambda r:(len(r['full']['trace']['ids']),r['problem_id']))


def main():
    p=argparse.ArgumentParser();p.add_argument('--shard',type=int,required=True);p.add_argument('--output',required=True)
    args=p.parse_args();assert os.environ['CUDA_VISIBLE_DEVICES']==str(args.shard)
    output=Path(args.output);assert not output.exists(),'Keep prior canary evidence'
    from protocol_guard import validate_formal,sha256
    from probe_engine import ProbeEngine
    from radar_engine import candidate
    formal,fh=validate_formal(ROOT)
    path=ROOT/f'results/bank_development_{args.shard}.jsonl'
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
    old=select_canary(rows);point=old['points'][0]
    questions={r['problem_id']:r for r in (json.loads(s) for s in (ROOT/'data/development.jsonl').read_text(encoding='utf-8').splitlines())}
    engine=ProbeEngine(old['model_path']);prompt=engine.prompt(questions[old['problem_id']]['question'])
    observations=[]
    def hook(observed,prefix,cache,logits):
        if observed['offset']!=point['offset']:return {'offline_branching':True}
        parent=copy.deepcopy(cache)
        engine.entropy_probe(cache,logits)
        read=candidate(engine,prefix,cache,logits,old['seed'])
        kv_same=all(engine.torch.equal(a.keys,b.keys) and engine.torch.equal(a.values,b.values)
                    for a,b in zip(cache.layers,parent.layers))
        expected=point['readouts'][0]
        errors={}
        for key in ['cue_projection','answer_projection']:
            a,b=read.get(key),expected.get(key)
            errors[key]=max(abs(x-y) for x,y in zip(a,b)) if a is not None and b is not None and len(a)==len(b) else None
        observations.append({'offset':observed['offset'],'parent_kv_unchanged':kv_same,
            'prefix_hash_matches':observed['prefix_hash']==point['prefix_hash'],
            'candidate_ids_equal':read['ids']==expected['ids'],
            'candidate_identity_equal':read['candidate_identity_sha256']==expected['candidate_identity_sha256'],
            'projection_max_abs_errors':errors})
        return {'offline_branching':True}
    trace=engine.decode(prompt,formal['max_think_tokens'],old['seed'],capture=True,checkpoint_hook=hook)
    answer=engine.answer(prompt+trace['ids'],old['seed'],natural_closed=trace['stop_reason']=='natural_end',
                         initial=(trace['cache'],trace['logits']))
    passed=(len(observations)==1 and all(observations[0][k] for k in
            ['parent_kv_unchanged','prefix_hash_matches','candidate_ids_equal','candidate_identity_equal'])
            and trace['ids']==old['full']['trace']['ids'] and answer['ids']==old['full']['answer']['ids'])
    report={'passed':passed,'observed_at_unix':time.time(),'formal_protocol_sha256':fh,
        'problem_id':old['problem_id'],'shard':args.shard,'old_trace_tokens':len(old['full']['trace']['ids']),
        'new_trace_tokens':len(trace['ids']),'whole_thought_ids_equal':trace['ids']==old['full']['trace']['ids'],
        'final_answer_ids_equal':answer['ids']==old['full']['answer']['ids'],'checkpoint_checks':observations,
        'gold_or_correctness_used':False,'source_sha256':sha256(Path(__file__)),
        'old_record_sha256':hashlib.sha256(json.dumps(old,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'scope':'One length-selected completed input per GPU: whole thought/final IDs and first-checkpoint candidate/KV control. No universal numerical or new quality/time claim.'}
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    assert passed,'Old/new canary differs; preserve evidence and diagnose before mixing additional bank rows'


if __name__=='__main__':main()
