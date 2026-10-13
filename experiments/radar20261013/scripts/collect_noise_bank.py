"""Nested reasoning-seed x answer-seed interventions on pilot-only states."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reason_transition.core import Engine, stable_seed, public, grade, append_jsonl
from radar_engine import candidate, decode_steps, candidate_features


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',required=True)
    p.add_argument('--shard',required=True,type=int)
    p.add_argument('--shards',default=2,type=int)
    args=p.parse_args()
    assert (ROOT/'results/pilot.complete.json').exists()
    protocol=json.loads((ROOT/'provenance/noise_protocol.json').read_text())
    questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text().splitlines()]
    raw={}
    for f in (ROOT/'results').glob('pilot_full_*.jsonl'):
        for s in f.read_text().splitlines():
            r=json.loads(s);assert r['problem_id'] not in raw;raw[r['problem_id']]=r
    assert set(raw)=={r['problem_id'] for r in questions}
    questions=questions[:protocol['problem_count']]
    e=Engine(args.model)
    out=ROOT/f'results/noise_bank_{args.shard}.jsonl'
    done={json.loads(s)['state_id'] for s in out.read_text().splitlines()} if out.exists() else set()
    statuses=[]
    for q_index,q in enumerate(questions):
        if q_index%args.shards!=args.shard:continue
        trace=raw[q['problem_id']]['trace']
        used=set()
        for target in protocol['checkpoint_minimum_offsets']:
            eligible=[c for c in trace['checkpoints'] if target<=c['offset']<len(trace['ids'])]
            if not eligible:
                statuses.append({'problem_id':q['problem_id'],'target_offset':target,'status':'no_eligible_state'})
                continue
            cp=eligible[0]
            if cp['offset'] in used:
                statuses.append({'problem_id':q['problem_id'],'target_offset':target,'status':'duplicate_selected_state'})
                continue
            used.add(cp['offset'])
            state_id=q['problem_id']+':'+str(cp['offset'])
            statuses.append({'state_id':state_id,'target_offset':target,'status':'eligible'})
            if state_id in done:continue
            start=time.perf_counter()
            prompt=e.prompt(q['question']);prefix=prompt+trace['ids'][:cp['offset']]
            cache,logits=e.forward(prefix)
            offset=cp['offset'];remaining=protocol['max_think_tokens']-offset
            answer_seeds=[stable_seed(protocol['seed'],state_id,'answer',i) for i in range(protocol['answer_repeats'])]
            # STOP has no reasoning random effect; answer seeds alone vary.
            stop=[candidate(e,prefix,cache,logits,s) for s in answer_seeds]
            branches=[]
            for r_index in range(protocol['reasoning_repeats']):
                r_seed=stable_seed(protocol['seed'],state_id,'reasoning',r_index)
                first=decode_steps(e,prefix,copy.deepcopy(cache),logits,r_seed,offset,1,min(remaining,protocol['defer_1_cap']))
                one_prefix=prefix+first['ids']
                one=[candidate(e,one_prefix,first['cache'],first['logits'],s,first['stop_reason']=='natural_end') for s in answer_seeds]
                branches.append({'action':'DEFER_1','reasoning_index':r_index,'reasoning_seed':r_seed,
                                 'trajectory':public(first),'readouts':one})
                left=min(remaining-first['tokens'],protocol['defer_4_cap']-first['tokens'])
                if first['stop_reason'] in ['natural_end','eos'] or left<=0:
                    fourth={**first,'steps_requested':4};four_prefix=one_prefix
                elif first['steps_completed']<1:
                    # A capped partial paragraph cannot reset its delimiter state.
                    # Decode the four-paragraph intervention from the same parent.
                    fourth=decode_steps(e,prefix,copy.deepcopy(cache),logits,r_seed,offset,4,
                                        min(remaining,protocol['defer_4_cap']))
                    four_prefix=prefix+fourth['ids']
                else:
                    extension=decode_steps(e,one_prefix,copy.deepcopy(first['cache']),first['logits'],r_seed,
                                           offset+first['tokens'],3,left)
                    fourth={**extension,'ids':first['ids']+extension['ids'],'text':first['text']+extension['text'],
                            'tokens':first['tokens']+extension['tokens'],
                            'steps_requested':4,'steps_completed':first['steps_completed']+extension['steps_completed'],
                            'ms':first['ms']+extension['ms'],'model_ms':first['model_ms']+extension['model_ms']}
                    four_prefix=prefix+fourth['ids']
                four=[candidate(e,four_prefix,fourth['cache'],fourth['logits'],s,fourth['stop_reason']=='natural_end') for s in answer_seeds]
                branches.append({'action':'DEFER_4','reasoning_index':r_index,'reasoning_seed':r_seed,
                                 'trajectory':public(fourth),'readouts':four})
                full=e.decode(prefix,remaining,r_seed,offset=offset,initial=(copy.deepcopy(cache),logits))
                full_prefix=prefix+full['ids']
                reads=[candidate(e,full_prefix,full['cache'],full['logits'],s,full['stop_reason']=='natural_end') for s in answer_seeds]
                assert first['ids']==full['ids'][:first['tokens']], 'Same-input prefix intervention control failed'
                assert fourth['ids']==full['ids'][:fourth['tokens']], 'DEFER4 prefix control failed'
                branches.append({'action':'FULL','reasoning_index':r_index,'reasoning_seed':r_seed,
                                 'trajectory':public(full),'readouts':reads})
                del first,fourth,full
            # No gold read or correctness feature before model work completes.
            for read in stop:
                read['grade']=grade(read['text'],q['gold']);read['correct']=read['grade']['correct']
            for branch in branches:
                for read in branch['readouts']:
                    read['grade']=grade(read['text'],q['gold']);read['correct']=read['grade']['correct']
            record={'state_id':state_id,'problem_id':q['problem_id'],'offset':offset,'features':cp['features'],
                    'subject':q['subject'],'difficulty':q['difficulty'],'gold':q['gold'],
                    'parent_prefix_hash':hashlib.sha256(json.dumps(prefix).encode()).hexdigest(),
                    'model_path':args.model,'protocol_sha256':hashlib.sha256((ROOT/'provenance/noise_protocol.json').read_bytes()).hexdigest(),
                    'stop_readouts':stop,'branches':branches,'candidate_features':candidate_features(stop[0]),
                    'same_input_continuation_controls_passed':True,'parent_seq_len_after':cache.get_seq_length(),
                    'collection_wall_s':time.perf_counter()-start,'gold_used_online':False}
            assert cache.get_seq_length()==len(prefix)
            append_jsonl(out,record)
            print(json.dumps({'noise_state':state_id,'stop_correct':[r['correct'] for r in stop],
                              'branch_readouts':len(branches)*len(answer_seeds),'wall_s':record['collection_wall_s']}),flush=True)
            del cache,logits,branches,stop
    status=ROOT/f'results/noise_status_{args.shard}.json'
    status.write_text(json.dumps(statuses,indent=2)+'\n')
    print('NOISE_SHARD_COMPLETE',args.shard,flush=True)


if __name__=='__main__':main()
