"""Actual serial request runner for the declared DTSR controlled protocol."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl
from dtsr_adapter import decode_dtsr
from protocol_guard import validate_formal,sha256
from risk_policy import problem_shard

SOURCES=['dtsr_adapter.py','scripts/evaluate_dtsr_online.py','reason_transition/core.py',
         'reason_transition/text_decoder.py','risk_policy.py']


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True)
    p.add_argument('--split',choices=['selection','calibration','test'],required=True)
    p.add_argument('--protocol-file',required=True);p.add_argument('--out-tag',required=True)
    p.add_argument('--shard',type=int,required=True);p.add_argument('--shards',type=int,default=2)
    p.add_argument('--n',type=int,default=None);args=p.parse_args()
    assert 0<=args.shard<args.shards and os.environ.get('CUDA_VISIBLE_DEVICES')==str(args.shard)
    formal,formal_hash=validate_formal(ROOT,args.model)
    assert args.shards==formal['gpu_shards']
    path=Path(args.protocol_file);spec=json.loads(path.read_text());protocol_hash=sha256(path)
    assert spec['formal_protocol_sha256']==formal_hash
    assert set(spec['source_sha256'])==set(SOURCES)
    for name,digest in spec['source_sha256'].items():assert sha256(ROOT/name)==digest
    assert spec['method_scope']=='DTSR_controlled_token_level_serial_HF'
    admission_path=ROOT/spec['admission_file'];admission=json.loads(admission_path.read_text())
    assert admission['passed'] and admission['model_path']==args.model
    assert sha256(admission_path)==spec['admission_sha256']
    for name,digest in admission['source_sha256'].items():assert sha256(ROOT/name)==digest
    freeze=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    if args.split=='test':
        final=json.loads((ROOT/'provenance/dtsr_final_test_freeze.json').read_text())
        assert args.n is None and final['protocol_sha256']==protocol_hash
        assert final['actual_test_generation_records_at_freeze']==0
        assert final['data_freeze_sha256']==sha256(ROOT/'provenance/data_freeze.json')
    source=ROOT/f'data/{args.split}.jsonl';assert sha256(source)==freeze['splits'][args.split]['sha256']
    rows=[json.loads(s) for s in source.read_text(encoding='utf-8').splitlines()]
    if args.n is not None:assert args.n>0;rows=rows[:args.n]
    expected={q['problem_id'] for q in rows if problem_shard(q['problem_id'],args.shards)==args.shard}
    out=ROOT/f'results/online_{args.out_tag}_{args.shard}.jsonl'
    previous=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    assert all(r['protocol_sha256']==protocol_hash and r['formal_protocol_sha256']==formal_hash
               and r['model_path']==args.model and r['split']==args.split for r in previous)
    done={r['problem_id'] for r in previous};assert len(done)==len(previous) and done<=expected
    engine=Engine(args.model)
    for i in range(2):
        warm=engine.decode(engine.prompt('What is 2 plus 2?'),16,stable_seed('dtsr-warm',i));del warm
    for q in rows:
        if q['problem_id'] not in expected or q['problem_id'] in done:continue
        assert sha256(path)==protocol_hash and validate_formal(ROOT,args.model)[1]==formal_hash
        for name,digest in spec['source_sha256'].items():assert sha256(ROOT/name)==digest
        seed=stable_seed(formal['seed'],q['problem_id'],0)
        engine.torch.cuda.reset_peak_memory_stats();engine.torch.cuda.synchronize();started=time.perf_counter()
        prompt=engine.prompt(q['question']);tokenization_ms=1000*(time.perf_counter()-started)
        trace=decode_dtsr(engine,q['question'],prompt,formal['max_think_tokens'],seed,
                          spec['threshold'],spec['minimum_interval'],spec['rating_max_tokens'])
        answer=engine.answer(prompt+trace['ids'],seed,natural_closed=trace['stop_reason']=='natural_end',
                             initial=(trace['cache'],trace['logits']))
        engine.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-started)
        score=grade(answer['text'],q['gold'])
        record={'problem_id':q['problem_id'],'method':'dtsr_controlled','split':args.split,
                'seed':seed,'model_path':args.model,'formal_protocol_sha256':formal_hash,
                'protocol_sha256':protocol_hash,'policy':spec,'trace':public(trace),'answer':public(answer),
                'correct':score['correct'],'grade':score,'wall_ms':wall_ms,'prompt_tokenization_ms':tokenization_ms,
                'compute_generated_tokens':trace['tokens']+answer['tokens']+trace['rating_generated_tokens'],
                'delivered_tokens':trace['tokens']+answer['tokens'],'rating_input_tokens':trace['rating_input_tokens'],
                'assigned_shard':args.shard,'visible_gpu':os.environ['CUDA_VISIBLE_DEVICES'],
                'peak_allocated_bytes':engine.torch.cuda.max_memory_allocated(),
                'quality_labels_available_during_decisions':False,
                'scope':'Actual controlled serial backend request including every rating and prefill. Not author vLLM settings or serving latency.'}
        append_jsonl(out,record)
        print(json.dumps({'dtsr':q['problem_id'],'correct':score['correct'],'ratings':len(trace['decisions']),
                          'wall_s':wall_ms/1000}),flush=True)
        del trace,answer
    records=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()]
    assert len(records)==len(expected) and {r['problem_id'] for r in records}==expected
    (ROOT/f'results/online_{args.out_tag}_{args.shard}.complete.json').write_text(json.dumps({'n':len(records),'unix':time.time()}))


if __name__=='__main__':main()
