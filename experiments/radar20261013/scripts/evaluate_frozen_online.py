"""Actual request measurements; bank/replay cost never substitutes for latency."""
import argparse,hashlib,json,os,pickle,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl,digest_ids
from radar_engine import candidate
from candidate_schema import scalar_schema
from probe_engine import ProbeEngine
from risk_policy import quality_decision,features_at,eat_update,deer_pro_confidence
from protocol_guard import validate_formal


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True)
    p.add_argument('--split',choices=['selection','calibration','test'],required=True)
    p.add_argument('--policy-file',required=True);p.add_argument('--shard',type=int,required=True)
    p.add_argument('--shards',type=int,default=2);p.add_argument('--n',type=int,default=None)
    p.add_argument('--out-tag',required=True)
    args=p.parse_args()
    assert 0<=args.shard<args.shards and (args.n is None or args.n>0)
    formal_path=ROOT/'provenance/formal_protocol.json'
    formal,formal_hash=validate_formal(ROOT,args.model)
    policy_path=Path(args.policy_file)
    policy=json.loads(policy_path.read_text(encoding='utf-8'))
    policy_hash=hashlib.sha256(policy_path.read_bytes()).hexdigest()
    if args.split=='calibration':
        assert (ROOT/'provenance/calibration_candidates.json').exists(),'Freeze candidates before any calibration request'
    if args.split=='test':
        freeze=json.loads((ROOT/'provenance/final_test_freeze.json').read_text(encoding='utf-8'))
        assert freeze['policy_sha256']==policy_hash
        assert freeze['actual_test_generation_records_at_freeze']==0
        assert freeze['data_freeze_sha256']==hashlib.sha256((ROOT/'provenance/data_freeze.json').read_bytes()).hexdigest()
        assert args.n is None,'Final test must cover the full frozen expected scope'
    data=ROOT/f'data/{args.split}.jsonl'
    df=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    assert hashlib.sha256(data.read_bytes()).hexdigest()==df['splits'][args.split]['sha256']
    rows=[json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()]
    if args.n is not None:rows=rows[:args.n]
    models={}
    for name,metadata in policy.get('models',{}).items():
        path=ROOT/metadata['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==metadata['sha256']
        with path.open('rb') as f:models[name]=pickle.load(f)
    need_hidden=any('latent' in s.get('predictor','') for s in policy['methods'].values())
    e=ProbeEngine(args.model) if need_hidden else Engine(args.model)
    for i in range(2):
        warm=e.decode(e.prompt('What is 2 plus 2?'),16,stable_seed('online-warmup',i));del warm
    out=ROOT/f'results/online_{args.out_tag}_{args.shard}.jsonl'
    previous=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    assert all(r['policy_file_sha256']==policy_hash and r['formal_protocol_sha256']==formal_hash and r['model_path']==args.model for r in previous),'Do not append incompatible run versions'
    done={(r['problem_id'],r['method']) for r in previous}
    methods=list(policy['methods'])
    expected={(q['problem_id'],m) for i,q in enumerate(rows) if i%args.shards==args.shard for m in methods}
    assert len(done)==len(previous) and done<=expected,'Duplicate, stale, or foreign online records'
    for index,q in enumerate(rows):
        if index%args.shards!=args.shard:continue
        assert validate_formal(ROOT,args.model)[1]==formal_hash,'Formal runtime changed during requests'
        assert hashlib.sha256(policy_path.read_bytes()).hexdigest()==policy_hash
        assert hashlib.sha256(formal_path.read_bytes()).hexdigest()==formal_hash
        order=methods[index%len(methods):]+methods[:index%len(methods)]
        for method in order:
            if (q['problem_id'],method) in done:continue
            spec=policy['methods'][method];kind=spec['kind'];seed=stable_seed(formal['seed'],q['problem_id'],0)
            log=[];reads=[];committed=None;fallback=False;probe_ms=0.;probe_tokens=0;detector_ms=0.
            ema_mean=ema_variance=0.;observations=0
            next_legacy_detection=0
            prompt=e.prompt(q['question'])

            def hook(point,prefix,cache,logits):
                nonlocal committed,fallback,probe_ms,probe_tokens,detector_ms,ema_mean,ema_variance,observations,next_legacy_detection
                if fallback:return {'disable_capture':True}
                started=time.perf_counter();detail={};action='DEFER';read=None
                if point['offset']<spec.get('minimum_offset',256):return False
                if kind=='legacy_transfer':
                    assert spec['control_mode']=='sequential','Preserve the selected original control mode'
                    if point['kind']=='natural' and point['offset']<256:return False
                    if point['offset']<next_legacy_detection:return False
                    learner=models[spec['predictor']];features=point['features']
                    if 'readout_entropy' in learner.features:
                        probe=e.entropy_probe(cache,logits);probe_ms+=probe['ms'];probe_tokens+=probe['probe_input_tokens']
                        features={**features,'readout_entropy':probe['entropy']}
                    old_action,detail=learner.choose(features,spec['cost_lambda'],spec['margin'],mode=spec['prediction_mode'])
                    detector_ms+=1000*(time.perf_counter()-started)
                    log.append({'offset':point['offset'],'kind':point['kind'],'action':old_action,'detail':detail})
                    if old_action=='STOP':return {'stop':True}
                    next_legacy_detection=point['offset']+128
                    return False
                elif kind=='eat':
                    probe=e.entropy_probe(cache,logits);probe_ms+=probe['ms'];probe_tokens+=probe['probe_input_tokens']
                    observations+=1
                    ema_mean,ema_variance,adjusted=eat_update(ema_mean,ema_variance,probe['entropy'],observations)
                    detail={'entropy':probe['entropy'],'adjusted_variance':adjusted,'observations':observations}
                    if observations>=spec['minimum_steps'] and adjusted<spec['variance_threshold']:
                        read=candidate(e,prefix,cache,logits,seed,observe_hidden=False);reads.append(read);action='COMMIT'
                elif kind in ['risk_gate','current_correctness']:
                    learner=models[spec['predictor']]
                    read=candidate(e,prefix,cache,logits,seed,observe_hidden='latent' in spec['predictor']);reads.append(read)
                    schema=scalar_schema(read['text']);read['schema']=schema
                    prediction=learner.predict_one(features_at(point,read));detail={'prediction':prediction,'schema':schema}
                    action=quality_decision(spec,prediction,schema['valid'])
                elif kind in ['deer','deer_pro']:
                    read=candidate(e,prefix,cache,logits,seed,observe_hidden=False);reads.append(read)
                    score=read['maxprob_geomean']
                    if kind=='deer_pro':
                        other=[candidate(e,prefix,cache,logits,seed,cue_override=cue,observe_hidden=False)
                               for cue in spec['inducer_cues']]
                        reads.extend(other);score=deer_pro_confidence([read,*other],spec['fluctuation_penalty'])
                    detail={'confidence':score,'actual_checked_candidate_identity':read['candidate_identity_sha256']}
                    if read['stop_reason']=='answer_box_complete' and score>=spec['confidence_threshold']:action='COMMIT'
                else:raise ValueError('Unsupported online adaptive method '+kind)
                detector_ms+=1000*(time.perf_counter()-started)
                log.append({'offset':point['offset'],'kind':point['kind'],'action':action,'detail':detail})
                if action=='COMMIT':
                    assert read is not None
                    committed=read
                    return {'stop':True}
                if action=='FALLBACK':fallback=True;return {'disable_capture':True}
                return False

            max_think=spec.get('budget',formal['max_think_tokens'])
            adaptive=kind not in ['full','fixed_budget']
            e.torch.cuda.reset_peak_memory_stats();e.torch.cuda.synchronize();start=time.perf_counter()
            trace=e.decode(prompt,max_think,seed,capture=kind in ['risk_gate','current_correctness','legacy_transfer'],
                           checkpoint_hook=hook if adaptive else None)
            if committed is not None:
                answer=committed;new_final_tokens=0
                assert hashlib.sha256(answer['text'].encode('utf-8')).hexdigest()==answer['candidate_text_sha256']
                assert answer['answer_prefix_hash']==digest_ids(prompt+trace['ids']+e.suffix),'Candidate belongs to a different stopping context'
            else:
                answer=e.answer(prompt+trace['ids'],seed,natural_closed=trace['stop_reason']=='natural_end',
                                initial=(trace['cache'],trace['logits']))
                new_final_tokens=answer['tokens']
            e.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-start)
            side_tokens=sum(r['tokens'] for r in reads)
            score=grade(answer['text'],q['gold'])
            record={'problem_id':q['problem_id'],'method':method,'policy':spec,'split':args.split,
                    'seed':seed,'model_path':args.model,'dtype':'float16','attention':'sdpa',
                    'quality_labels_available_during_decisions':False,'correct':score['correct'],'grade':score,
                    'trace':public(trace),'answer':public(answer),'decisions':log,
                    'side_readouts':reads,'think_tokens':trace['tokens'],'side_generated_tokens':side_tokens,
                    'new_final_answer_tokens':new_final_tokens,'compute_generated_tokens':trace['tokens']+side_tokens+new_final_tokens,
                    'delivered_tokens':trace['tokens']+answer['tokens'],'probe_input_tokens':probe_tokens,
                    'candidate_header_input_tokens':sum(r['control_prefix_input_tokens'] for r in reads),
                    'wall_ms':wall_ms,'detector_callback_ms':detector_ms,'entropy_probe_ms':probe_ms,
                    'peak_allocated_bytes':e.torch.cuda.max_memory_allocated(),'peak_reserved_bytes':e.torch.cuda.max_memory_reserved(),
                    'length_censored':trace['length_censored'],'committed_checked_candidate':committed is not None,
                    'policy_file_sha256':policy_hash,
                    'formal_protocol_sha256':formal_hash,
                    'visible_gpu':os.environ.get('CUDA_VISIBLE_DEVICES')}
            assert record['compute_generated_tokens']>=record['delivered_tokens']
            append_jsonl(out,record)
            print(json.dumps({'online':index,'method':method,'id':q['problem_id'],'correct':score['correct'],
                              'compute_tokens':record['compute_generated_tokens'],'wall_s':wall_ms/1000}),flush=True)
            del trace,answer,reads
    records=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()]
    assert {(r['problem_id'],r['method']) for r in records}==expected and len(records)==len(expected)
    (ROOT/f'results/online_{args.out_tag}_{args.shard}.complete.json').write_text(json.dumps({'n':len(records),'unix':time.time()}))
    print('FROZEN_ONLINE_SHARD_COMPLETE',args.out_tag,args.shard,len(records),flush=True)


if __name__=='__main__':main()
