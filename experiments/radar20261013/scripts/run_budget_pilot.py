"""Real strict-budget request controls on a preregistered pilot subset."""
import argparse,hashlib,json,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl
from stem_quality import stem_issues,numeric_gold_issues


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True)
    p.add_argument('--shard',type=int,required=True);p.add_argument('--shards',type=int,default=2)
    args=p.parse_args()
    assert (ROOT/'results/pilot.complete.json').exists()
    spec=json.loads((ROOT/'provenance/budget_pilot_protocol.json').read_text())
    rows=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:spec['n']]
    invalid=[{'problem_id':q['problem_id'],'issues':stem_issues(q['question'],q['subject'])+numeric_gold_issues(q['gold'])} for q in rows if stem_issues(q['question'],q['subject']) or numeric_gold_issues(q['gold'])]
    rows=[q for q in rows if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])]
    (ROOT/'provenance/budget_pilot_input_exclusions.json').write_text(json.dumps(invalid,indent=2)+'\n')
    out=ROOT/f'results/budget_pilot_{args.shard}.jsonl'
    done={(r['problem_id'],r['budget']) for r in (json.loads(s) for s in out.read_text(encoding='utf-8').splitlines())} if out.exists() else set()
    e=Engine(args.model)
    for index,q in enumerate(rows):
        if index%args.shards!=args.shard:continue
        budgets=spec['budgets'];order=budgets[index%len(budgets):]+budgets[:index%len(budgets)]
        for budget in order:
            if (q['problem_id'],budget) in done:continue
            seed=stable_seed(spec['seed'],q['problem_id'],0)
            prompt=e.prompt(q['question'])
            e.torch.cuda.synchronize();start=time.perf_counter()
            trace=e.decode(prompt,budget,seed,capture=False)
            answer=e.answer(prompt+trace['ids'],seed,natural_closed=trace['stop_reason']=='natural_end',
                            initial=(trace['cache'],trace['logits']))
            e.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-start)
            score=grade(answer['text'],q['gold'])
            row={'problem_id':q['problem_id'],'budget':budget,'seed':seed,'model_path':args.model,
                 'method':'strict_fixed_budget','trace':public(trace),'answer':public(answer),
                 'correct':score['correct'],'grade':score,'wall_ms':wall_ms,
                 'total_tokens':trace['tokens']+answer['tokens'],
                 'length_censored':trace['length_censored'],'gold_available_during_generation':False,
                 'protocol_sha256':hashlib.sha256((ROOT/'provenance/budget_pilot_protocol.json').read_bytes()).hexdigest()}
            append_jsonl(out,row)
            print(json.dumps({'budget_pilot':index,'budget':budget,'correct':row['correct'],'wall_s':wall_ms/1000}),flush=True)
            del trace,answer
    assert len(out.read_text(encoding='utf-8').splitlines())==sum(i%args.shards==args.shard for i in range(len(rows)))*len(spec['budgets'])
    (ROOT/f'results/budget_pilot_{args.shard}.complete.json').write_text(json.dumps({'unix':time.time()}))
    print('BUDGET_PILOT_SHARD_COMPLETE',args.shard,flush=True)


if __name__=='__main__':main()
