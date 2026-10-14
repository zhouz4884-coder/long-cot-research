"""Dense observed-answer bank for development/selection/independent calibration.

This collects real GPU actions; timing reconstructed from an instrumented
trajectory is marked as a proxy. Test must use actual frozen online policies.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine, stable_seed, public, grade, append_jsonl
from radar_engine import candidate, candidate_features
from candidate_schema import scalar_schema
from probe_engine import ProbeEngine
from protocol_guard import validate_formal,validate_resume
from risk_policy import problem_shard


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',required=True)
    p.add_argument('--split',required=True,choices=['development','selection','calibration'])
    p.add_argument('--shard',required=True,type=int)
    p.add_argument('--shards',default=2,type=int)
    args=p.parse_args()
    assert 0<=args.shard<args.shards
    assert os.environ.get('CUDA_VISIBLE_DEVICES')==str(args.shard),'Use the frozen physical GPU assignment'
    assert (ROOT/'provenance/formal_protocol.json').exists(), 'Formal reference budget not frozen yet'
    formal,formal_hash=validate_formal(ROOT,args.model)
    assert args.shards==formal['gpu_shards'] and formal['gpu_assignment']=='problem_id_sha256_independent_of_split_membership'
    family_hash=None
    if args.split=='calibration':
        family_path=ROOT/'provenance/calibration_candidates.json'
        assert family_path.exists(),'Freeze candidates before any calibration request'
        family_hash=hashlib.sha256(family_path.read_bytes()).hexdigest()
    data=ROOT/f'data/{args.split}.jsonl'
    freeze=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    assert hashlib.sha256(data.read_bytes()).hexdigest()==freeze['splits'][args.split]['sha256']
    rows=[json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()]
    out=ROOT/f'results/bank_{args.split}_{args.shard}.jsonl'
    previous=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    expected_ids={r['problem_id'] for r in rows if problem_shard(r['problem_id'],args.shards)==args.shard}
    done=validate_resume(previous,formal_hash,args.model,expected_ids)
    if family_hash is not None:
        assert all(r['candidate_family_sha256']==family_hash for r in previous),'Calibration rows belong to another frozen candidate family'
    e=ProbeEngine(args.model) if formal.get('capture_candidate_hidden',False) else Engine(args.model)
    for index,row in enumerate(rows):
        if problem_shard(row['problem_id'],args.shards)!=args.shard or row['problem_id'] in done:continue
        assert validate_formal(ROOT,args.model)[1]==formal_hash,'Formal protocol changed during collection'
        if family_hash is not None:
            assert hashlib.sha256(family_path.read_bytes()).hexdigest()==family_hash,'Candidate family changed during calibration'
        seed=stable_seed(formal['seed'],row['problem_id'],0)
        answer_seeds=[seed]+[stable_seed(formal['seed'],row['problem_id'],'readout',i) for i in [1,2]]
        points=[];seen_extra=set()
        prompt=e.prompt(row['question'])
        e.torch.cuda.synchronize();start=time.perf_counter()

        def hook(point,prefix,cache,logits):
            # Generate all potential terminal answers without choosing by labels.
            probe=e.entropy_probe(cache,logits)
            reads=[candidate(e,prefix,cache,logits,answer_seeds[0])]
            for read in reads:
                read['schema']=scalar_schema(read['text'])
            # Extra measurement is sparse and identified; no hidden imputation.
            crossed_extra=[t for t in formal['extra_readout_offsets'] if t<=point['offset'] and t not in seen_extra]
            selected_extra=bool(crossed_extra)
            seen_extra.update(crossed_extra)
            if selected_extra:
                reads += [candidate(e,prefix,cache,logits,s) for s in answer_seeds[1:]]
                for read in reads[1:]:read['schema']=scalar_schema(read['text'])
            points.append({**point,'probe':probe,'readouts':reads,
                           'candidate_features':candidate_features(reads[0]),
                           'schema_valid':reads[0]['schema']['valid'],
                           'extra_readout_observed':selected_extra,
                           'extra_readout_targets_crossed':crossed_extra,
                           'gold_used_for_collection':False})
            return {'offline_branching':True}

        trace=e.decode(prompt,formal['max_think_tokens'],seed,capture=True,checkpoint_hook=hook)
        final=e.answer(prompt+trace['ids'],answer_seeds[0],natural_closed=trace['stop_reason']=='natural_end',
                       initial=(trace['cache'],trace['logits']))
        e.torch.cuda.synchronize();collection_ms=1000*(time.perf_counter()-start)
        final['grade']=grade(final['text'],row['gold']);final['correct']=final['grade']['correct']
        for point in points:
            for read in point['readouts']:
                read['grade']=grade(read['text'],row['gold']);read['correct']=read['grade']['correct']
        record={'problem_id':row['problem_id'],'split':args.split,'model_path':args.model,'seed':seed,
                'formal_protocol_sha256':formal_hash,
                'assigned_shard':problem_shard(row['problem_id'],args.shards),'gpu_assignment':formal['gpu_assignment'],
                'visible_gpu':os.environ['CUDA_VISIBLE_DEVICES'],
                'candidate_family_sha256':family_hash,
                'full':{'trace':public(trace),'answer':public(final),'correct':final['correct'],
                        'instrumented_reference_ms':trace['ms']+final['ms'],
                        'reference_timing_is_uninstrumented_online_benchmark':False},
                'points':points,'collection_ms':collection_ms,
                'compute_generated_tokens':trace['tokens']+final['tokens']+sum(r['tokens'] for c in points for r in c['readouts']),
                'scorer_version':final['grade'].get('scorer_version'),
                'all_correctness_labels_computed_after_generation':True}
        append_jsonl(out,record)
        print(json.dumps({'bank':args.split,'index':index,'id':row['problem_id'],'full_correct':final['correct'],
                          'points':len(points),'wall_s':collection_ms/1000}),flush=True)
        del trace,final,points
    expected=len(expected_ids)
    assert len(out.read_text(encoding='utf-8').splitlines())==expected
    (ROOT/f'results/bank_{args.split}_{args.shard}.complete.json').write_text(json.dumps({'n':expected,'unix':time.time()}))
    print('POLICY_BANK_SHARD_COMPLETE',args.split,args.shard,expected,flush=True)


if __name__=='__main__':main()
