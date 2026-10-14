"""Actual native math generation, with no injected delimiter or answer cue."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl
from stem_quality import stem_issues,numeric_gold_issues
from protocol_guard import sha256,package_snapshot


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True)
    parser.add_argument('--shard',required=True,type=int);parser.add_argument('--shards',default=2,type=int)
    args=parser.parse_args();assert 0<=args.shard<args.shards
    path=ROOT/'provenance/native_pilot_protocol.json';spec=json.loads(path.read_text())
    protocol_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    assert spec['package_versions']==package_snapshot()
    for name,digest in spec['source_sha256'].items():
        assert sha256(ROOT/name)==digest,'Native pilot runtime changed: '+name
    assert Path(args.model).name==spec['model_name']
    data=ROOT/'data/pilot.jsonl';data_hash=hashlib.sha256(data.read_bytes()).hexdigest()
    rows=[json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()][:spec['n']]
    rows=[q for q in rows if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])]
    out=ROOT/f'results/native_pilot_{args.shard}.jsonl'
    previous=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    assert all(r['protocol_sha256']==protocol_hash and r['data_sha256']==data_hash and r['model_path']==args.model for r in previous)
    done={(r['problem_id'],r['nominal_budget']) for r in previous};assert len(done)==len(previous)
    expected={(q['problem_id'],b) for i,q in enumerate(rows) if i%args.shards==args.shard for b in spec['nominal_thought_budgets']}
    assert done<=expected
    reference={}
    for f in (ROOT/'results').glob('pilot_full_[01].jsonl'):
        for s in f.read_text(encoding='utf-8').splitlines():
            r=json.loads(s);reference[r['problem_id']]=r
    e=Engine(args.model)
    for i in range(2):
        warm=e.decode(e.prompt('What is 2 plus 2?'),16,stable_seed('native-warmup',i),until='eos');del warm
    for index,q in enumerate(rows):
        if index%args.shards!=args.shard:continue
        budgets=spec['nominal_thought_budgets'];order=budgets[index%len(budgets):]+budgets[:index%len(budgets)]
        for budget in order:
            if (q['problem_id'],budget) in done:continue
            assert hashlib.sha256(path.read_bytes()).hexdigest()==protocol_hash
            for name,digest in spec['source_sha256'].items():
                assert sha256(ROOT/name)==digest,'Native pilot runtime changed: '+name
            seed=stable_seed(spec['seed'],q['problem_id'],0);prompt=e.prompt(q['question'])
            e.torch.cuda.reset_peak_memory_stats();e.torch.cuda.synchronize();started=time.perf_counter()
            trace=e.decode(prompt,budget+spec['extra_total_budget_tokens'],seed,until='eos',capture=False)
            e.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-started)
            close=trace['ids'].index(e.endthink) if e.endthink in trace['ids'] else None
            answer_ids=trace['ids'][close+1:] if close is not None else []
            answer_text=e.tok.decode(answer_ids,skip_special_tokens=False,clean_up_tokenization_spaces=False)
            thought_ids=trace['ids'][:close+1] if close is not None else trace['ids']
            original=reference[q['problem_id']];shared=min(len(original['trace']['ids']),len(thought_ids))
            control=thought_ids[:shared]==original['trace']['ids'][:shared] and seed==original['seed']
            score=grade(answer_text,q['gold'])
            row={'problem_id':q['problem_id'],'method':'native_uninterrupted','nominal_budget':budget,
                 'total_budget':budget+spec['extra_total_budget_tokens'],'seed':seed,'model_path':args.model,
                 'trace':public(trace),'native_answer_text':answer_text,'thinking_closed':close is not None,
                 'thinking_tokens':len(thought_ids),'native_answer_tokens':len(answer_ids),'correct':score['correct'],
                 'grade':score,'wall_ms':wall_ms,'total_tokens':trace['tokens'],'length_censored':trace['length_censored'],
                 'eos_completed':trace['stop_reason']=='eos','same_thinking_prefix_control':control,
                 'protocol_sha256':protocol_hash,'data_sha256':data_hash,'quality_labels_available_during_generation':False,
                 'peak_allocated_bytes':e.torch.cuda.max_memory_allocated(),'visible_gpu':os.environ.get('CUDA_VISIBLE_DEVICES')}
            append_jsonl(out,row)
            print(json.dumps({'native_pilot':index,'budget':budget,'correct':score['correct'],'closed':close is not None,
                              'eos_completed':row['eos_completed'],'wall_s':wall_ms/1000}),flush=True)
            del trace
    final=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()]
    assert {(r['problem_id'],r['nominal_budget']) for r in final}==expected and len(final)==len(expected)
    (ROOT/f'results/native_pilot_{args.shard}.complete.json').write_text(json.dumps({'n':len(final),'unix':time.time()}))


if __name__=='__main__':main()
