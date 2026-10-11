import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl,digest_ids


def select(points):
    result=[]
    natural=[p for p in points if p['kind']=='natural']
    for threshold in [256,1024]:
        eligible=next((p for p in natural if p['offset']>=threshold),None)
        if eligible is not None and eligible not in result:result.append(eligible)
    result.extend([p for p in points if p['kind']=='reflective'][:2])
    return sorted(result,key=lambda p:p['offset'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['development','engineering'],required=True)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1);p.add_argument('--model',required=True)
    p.add_argument('--repeat',type=int,default=1)
    args=p.parse_args();out=Path('results/bank');out.mkdir(parents=True,exist_ok=True)
    assert json.loads(Path('results/protocol/checks.json').read_text(encoding="utf-8")).get('admitted')
    traces=[]
    for f in sorted(out.glob(f'{args.split}_traces_*.jsonl')):
        traces.extend(json.loads(x) for x in f.read_text(encoding="utf-8").splitlines())
    traces=sorted(traces,key=lambda r:r['problem_id'])
    path=out/f'{args.split}_branches_{args.shard}.jsonl'
    done={json.loads(x)['checkpoint_id'] for x in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    e=Engine(args.model)
    for row_index,row in enumerate(traces):
        if row_index%args.shards!=args.shard:continue
        for point in select(row['trace']['checkpoints']):
            n=point['offset'];prefix=row['prompt_ids']+row['trace']['ids'][:n]
            assert digest_ids(prefix)==point['prefix_hash']
            for repeat in range(args.repeat):
                key=f"{row['problem_id']}:0:{n}:r{repeat}"
                if key in done:continue
                seed=row['seed'] if repeat==0 else stable_seed(row['seed'],'repeat',repeat)
                stop=e.answer(prefix,seed)
                step=e.decode(prefix,214,seed,phase='think',offset=n,until='step')
                step_answer=e.answer(prefix+step['ids'],seed,natural_closed=step['stop_reason']=='natural_end',initial=(step['cache'],step['logits']))
                stop_grade=grade(stop['text'],row['gold']);step_grade=grade(step_answer['text'],row['gold'])
                record={'problem_id':row['problem_id'],'trace_id':0,'checkpoint_id':key,'checkpoint_kind':point['kind'],
                    'prefix_hash':point['prefix_hash'],'prefix_tokens':n,'prefix_ids':prefix,'decode_seed':seed,
                    'model_revision':row['model_revision'],'features':point['features'],'subject':row['subject'],'level':row['level'],
                    'stop_correct':stop_grade['correct'],'step_correct':step_grade['correct'],'end_correct':row['grade']['correct'],
                    'stop_tokens':stop['tokens'],'step_tokens':step['tokens']+step_answer['tokens'],
                    'end_tokens':row['trace']['tokens']-n+row['answer']['tokens'],
                    'stop_ms':stop['ms'],'step_ms':step['ms']+step_answer['ms'],
                    'end_remaining_observed_ms':max(0,row['trace']['ms']-point['elapsed_ms'])+row['answer']['ms'],
                    'stop':public(stop),'step':public(step),'step_answer':public(step_answer),
                    'stop_grade':stop_grade,'step_grade':step_grade,'end_grade':row['grade'],
                    'parse_status':{'stop':stop_grade['parse_status'],'step':step_grade['parse_status'],'end':row['grade']['parse_status']},
                    'length_censored':row['trace']['length_censored'],'step_overflow':step['length_censored'],
                    'step_soft_exceeded':step['tokens']>150,'repeat':repeat,
                    'full_source':'actual unmodified continuation in parent trajectory; same prefix and counter RNG; not regenerated'}
                append_jsonl(path,record)
                print(json.dumps({'checkpoint':key,'kind':point['kind'],'stop':record['stop_correct'],'step':record['step_correct'],
                    'full':record['end_correct'],'step_tokens':step['tokens'],'step_overflow':step['length_censored']}),flush=True)


if __name__=='__main__':main()
