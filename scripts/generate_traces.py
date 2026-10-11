import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl


def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['development','engineering'],required=True)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    p.add_argument('--model',required=True);p.add_argument('--n',type=int,default=0)
    args=p.parse_args();out=Path('results/bank');out.mkdir(parents=True,exist_ok=True)
    checks=json.loads(Path('results/protocol/checks.json').read_text(encoding="utf-8"))
    assert checks.get('admitted'), 'Protocol admission must pass before collecting training labels'
    rows=[json.loads(x) for x in Path(f'data/{args.split}.jsonl').read_text(encoding="utf-8").splitlines()]
    if args.n:rows=rows[:args.n]
    path=out/f'{args.split}_traces_{args.shard}.jsonl'
    finished={json.loads(x)['problem_id'] for x in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    e=Engine(args.model)
    for i,row in enumerate(rows):
        if i%args.shards!=args.shard or row['problem_id'] in finished:continue
        seed=stable_seed(20261008,row['problem_id'],0)
        prompt=e.prompt(row['question']);trace=e.decode(prompt,4096,seed,capture=True)
        answer=e.answer(prompt+trace['ids'],seed,natural_closed=trace['stop_reason']=='natural_end',initial=(trace['cache'],trace['logits']))
        record={**row,'trace_id':0,'seed':seed,'prompt_ids':prompt,'trace':public(trace),'answer':public(answer),'grade':grade(answer['text'],row['gold']),
            'model_revision':'1cfa9a7208912126459214e8b04321603b3df60c','dtype':'float16'}
        append_jsonl(path,record)
        print(json.dumps({'split':args.split,'row':i,'problem_id':row['problem_id'],'tokens':trace['tokens'],
            'correct':record['grade']['correct'],'length_censored':trace['length_censored'],'checkpoints':len(trace['checkpoints'])}),flush=True)


if __name__=='__main__':main()
