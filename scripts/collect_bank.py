"""Serial counterfactual branches from cloned *actual* KV states, two workers."""
import argparse
import copy
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,public,grade,append_jsonl,digest_ids


def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['development','engineering'],required=True)
    p.add_argument('--model',required=True);p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    p.add_argument('--n',type=int,default=0);p.add_argument('--max-think',type=int,default=8192)
    p.add_argument('--dense-stop',action='store_true');args=p.parse_args()
    admission=json.loads(Path('results/protocol/checks.json').read_text())
    assert admission.get('admitted'),'No training data collection before protocol admission'
    out=Path('results/bank');out.mkdir(parents=True,exist_ok=True)
    trace_path=out/f'{args.split}_traces_{args.shard}.jsonl';branch_path=out/f'{args.split}_branches_{args.shard}.jsonl'
    probe_path=out/f'{args.split}_probes_{args.shard}.jsonl'
    done={json.loads(x)['problem_id'] for x in trace_path.read_text().splitlines()} if trace_path.exists() else set()
    for child_path in [branch_path,probe_path]:
        if not child_path.exists():continue
        existing=[json.loads(x) for x in child_path.read_text().splitlines() if x.strip()]
        orphan=[r for r in existing if r['problem_id'] not in done]
        if orphan:
            archive=child_path.with_name(child_path.stem+f'_orphan_{int(time.time())}.jsonl')
            archive.write_text(''.join(json.dumps(r)+'\n' for r in orphan))
            keep=[r for r in existing if r['problem_id'] in done]
            temporary=child_path.with_suffix('.pending')
            temporary.write_text(''.join(json.dumps(r)+'\n' for r in keep));temporary.replace(child_path)
    rows=[json.loads(x) for x in Path(f'data/{args.split}.jsonl').read_text().splitlines()]
    if args.n:rows=rows[:args.n]
    code_hash=hashlib.sha256(Path('reason_transition/core.py').read_bytes()).hexdigest()
    e=Engine(args.model)
    for row_index,row in enumerate(rows):
        if row_index%args.shards!=args.shard or row['problem_id'] in done:continue
        seed=stable_seed(20261008,row['problem_id'],0);prompt=e.prompt(row['question'])
        zero=e.answer(prompt,seed)
        zero_public=public(zero);zero_grade=grade(zero['text'],row['gold']);del zero
        branches=[];probes=[];used=set();reflect_count=0

        def hook(point,prefix,cache,logits):
            nonlocal reflect_count
            n=point['offset'];selected=False
            if point['kind']=='natural':
                for target in [256,1024]:
                    if n>=target and target not in used:
                        used.add(target);selected=True;break
            elif reflect_count<2:
                reflect_count+=1;selected=True
            if not selected and not args.dense_stop:return {'offline_branching':True}
            e.torch.cuda.synchronize();start=time.perf_counter()
            stop_cache=copy.deepcopy(cache)
            e.torch.cuda.synchronize();clone_ms=1000*(time.perf_counter()-start)
            stop=e.answer(prefix,seed,initial=(stop_cache,logits))
            stop_record=public(stop);stop_grade=grade(stop['text'],row['gold'])
            del stop,stop_cache
            item={'problem_id':row['problem_id'],'offset':n,'kind':point['kind'],'prefix_hash':digest_ids(prefix),
                'eat_entropy':stop_record['eat_entropy'],'correct':stop_grade['correct'],'grade':stop_grade,
                'answer_tokens':stop_record['tokens'],'answer_ms':stop_record['ms'],'answer':stop_record,
                'features':point['features'],'cache_clone_ms':clone_ms,'selected_transition':selected}
            probes.append(item)
            if selected:
                step_cache=copy.deepcopy(cache)
                step=e.decode(prefix,214,seed,phase='think',offset=n,until='step',initial=(step_cache,logits))
                step_answer=e.answer(prefix+step['ids'],seed,natural_closed=step['stop_reason']=='natural_end',initial=(step['cache'],step['logits']))
                step_grade=grade(step_answer['text'],row['gold'])
                key=f"{row['problem_id']}:0:{n}:r0"
                record={'problem_id':row['problem_id'],'trace_id':0,'checkpoint_id':key,'checkpoint_kind':point['kind'],
                    'prefix_hash':point['prefix_hash'],'prefix_tokens':n,'prefix_ids':prefix,'decode_seed':seed,
                    'model_revision':'1cfa9a7208912126459214e8b04321603b3df60c','features':point['features'],
                    'subject':row['subject'],'level':row['level'],'stop_correct':stop_grade['correct'],'step_correct':step_grade['correct'],
                    'stop_tokens':stop_record['tokens'],'step_tokens':step['tokens']+step_answer['tokens'],
                    'stop_ms':stop_record['ms'],'step_ms':step['ms']+step_answer['ms'],
                    'stop':stop_record,'step':public(step),'step_answer':public(step_answer),
                    'stop_grade':stop_grade,'step_grade':step_grade,'step_overflow':step['length_censored'],
                    'step_soft_exceeded':step['tokens']>150,'repeat':0,'clone_ms':clone_ms,'parent_elapsed_ms':point['elapsed_ms'],
                    'cache_source':'deep copy of actual parent generation KV; no replay approximation',
                    'code_sha256':code_hash}
                branches.append(record)
                del step,step_answer,step_cache
                print(json.dumps({'branch':key,'stop':stop_grade['correct'],'step':step_grade['correct']}),flush=True)
            return {'offline_branching':True}

        trace=e.decode(prompt,args.max_think,seed,capture=True,checkpoint_hook=hook)
        answer=e.answer(prompt+trace['ids'],seed,natural_closed=trace['stop_reason']=='natural_end',initial=(trace['cache'],trace['logits']))
        full_grade=grade(answer['text'],row['gold'])
        record={**row,'trace_id':0,'seed':seed,'prompt_ids':prompt,'trace':public(trace),'answer':public(answer),'grade':full_grade,
            'model_revision':'1cfa9a7208912126459214e8b04321603b3df60c','dtype':'float16','code_sha256':code_hash,
            'max_think':args.max_think}
        record.update(zero_answer=zero_public,zero_grade=zero_grade)
        for branch in branches:
            branch.update(end_correct=full_grade['correct'],end_grade=full_grade,
                end_tokens=trace['tokens']-branch['prefix_tokens']+answer['tokens'],
                end_remaining_observed_ms=max(0,trace['ms']-branch['parent_elapsed_ms'])+answer['ms'],
                length_censored=trace['length_censored'],parse_status={'stop':branch['stop_grade']['parse_status'],
                    'step':branch['step_grade']['parse_status'],'end':full_grade['parse_status']},
                full_source='actual unmodified parent continuation; same KV and counter RNG; branching overhead subtracted')
            append_jsonl(branch_path,branch)
        for probe in probes:
            probe.update(end_correct=full_grade['correct'],full_think_tokens=trace['tokens'],full_answer_tokens=answer['tokens'],length_censored=trace['length_censored'])
            append_jsonl(probe_path,probe)
        # Trace record is a completion marker; all its child records precede it.
        append_jsonl(trace_path,record)
        print(json.dumps({'completed':row_index,'split':args.split,'problem_id':row['problem_id'],'tokens':trace['tokens'],
            'correct':full_grade['correct'],'natural_end':trace['stop_reason']=='natural_end','branches':len(branches),
            'probes':len(probes),'generation_ms':trace['ms'],'offline_branching_ms':trace['offline_branching_ms']}),flush=True)
        del trace,answer;gc.collect()


if __name__=='__main__':main()
