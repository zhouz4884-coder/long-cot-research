"""Execute decisions during generation, including detector and GPU costs."""
import argparse
import json
import math
from pathlib import Path
import pickle
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine,stable_seed,grade,public,append_jsonl


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--n',type=int,default=50);p.add_argument('--offset',type=int,default=0)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    p.add_argument('--methods',default='full,transition,learned_stop,eat,conformal_thinking,fixed0,fixed1024,random,value_outcome,value_frequency,value_cheap,matched_stop')
    p.add_argument('--out-name',default='qwen3_4b');args=p.parse_args()
    out=Path('results/online');out.mkdir(parents=True,exist_ok=True)
    calibration=json.loads(Path('results/analysis/policy_calibration.json').read_text(encoding="utf-8"))
    learners={}
    for name in ['linear','tree','readout_linear','readout_tree']:
        with Path(f'results/analysis/predictor_{name}.pkl').open('rb') as f:learners[name]=pickle.load(f)
    rows=[json.loads(x) for x in Path('data/test.jsonl').read_text(encoding="utf-8").splitlines()][args.offset:args.offset+args.n]
    path=out/f'{args.out_name}_{args.shard}.jsonl'
    done={(json.loads(x)['problem_id'],json.loads(x)['method']) for x in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    e=Engine(args.model)
    methods=args.methods.split(',')
    for row_index,row in enumerate(rows):
        if row_index%args.shards!=args.shard:continue
        # Rotate execution order without looking at outcomes.
        order=methods[row_index%len(methods):]+methods[:row_index%len(methods)]
        for method in order:
            if (row['problem_id'],method) in done:continue
            spec=calibration['selected_empirical'].get(method,{})
            effective=spec.get('method',method)
            predictor=learners[spec.get('predictor_type','linear')]
            learned_predictor=predictor
            prompt=e.prompt(row['question']);seed=stable_seed(20261008,row['problem_id'],0)
            log=[];selected_action=None;committed_full=False;ema_mean=ema_var=0.0;detector_ms=0.0
            seen=0;next_detection=0

            def hook(point,prefix,cache,logits):
                nonlocal selected_action,committed_full,ema_mean,ema_var,detector_ms,seen,next_detection
                if committed_full:return {'disable_capture':True}
                seen+=1;start=time.perf_counter();stop=False;action=None;detail={}
                if effective=='transition':
                    if point['kind']=='natural' and point['offset']<256:return False
                    if point['offset']<next_detection:return False
                    features=point['features'];readout=None
                    if 'readout_entropy' in predictor.features:
                        readout=e.entropy_probe(cache,logits);features={**features,'readout_entropy':readout['entropy']}
                    action,detail=predictor.choose(features,spec.get('cost_lambda',0.0001),spec.get('margin',0.0),mode=spec.get('prediction_mode','transition'))
                    if readout:detail.update(probe_input_tokens=readout['probe_input_tokens'],readout_probe=readout)
                    control=spec.get('control_mode','one_shot')
                    if control=='one_shot':
                        selected_action=action
                        if action=='FULL':committed_full=True
                        else:stop=True
                    else:
                        if action=='STOP':selected_action='STOP';stop=True
                        else:
                            selected_action=None
                            next_detection=point['offset']+(512 if control=='sequential_adaptive' and action=='FULL' else 128)
                elif effective=='learned_stop':
                    if point['kind']=='natural' and point['offset']<256:return False
                    features=point['features'];readout=None
                    if 'readout_entropy' in learned_predictor.features:
                        readout=e.entropy_probe(cache,logits);features={**features,'readout_entropy':readout['entropy']}
                    pred,_=learned_predictor.fast_one(features);detail=pred
                    if readout:detail.update(probe_input_tokens=readout['probe_input_tokens'],readout_probe=readout)
                    stop=pred['stop_correct']>=spec['correctness_threshold'];selected_action='STOP' if stop else None
                    action='STOP' if stop else 'CONTINUE'
                elif effective in ['eat','conformal_thinking']:
                    probe=e.entropy_probe(cache,logits);detail=probe;entropy=probe['entropy']
                    if effective=='eat':
                        ema_mean=0.8*ema_mean+0.2*entropy;ema_var=0.8*ema_var+0.2*(entropy-ema_mean)**2
                        variance=ema_var/(1-0.8**seen);detail['variance']=variance
                        stop=seen>=spec.get('minimum_steps',20) and variance<spec.get('variance_threshold',0.01)
                    else:
                        score=math.exp(-entropy);slope=spec.get('lower_slope',0.0)
                        lower=1/(1+math.exp(-max(-700,min(700,slope*(point['offset']-4096))))) if slope else -1
                        stop=score>=spec.get('upper',1.001) or score<lower;detail.update(score=score,lower=lower)
                    action='STOP' if stop else 'CONTINUE';selected_action='STOP' if stop else None
                elif effective=='fixed1024':
                    stop=point['offset']>=1024;action='STOP' if stop else 'CONTINUE';selected_action='STOP' if stop else None
                elif effective=='random':
                    from reason_transition.core import uniform
                    stop=point['offset']>=256 and uniform(seed,'random_stop',seen)<0.2
                    action='STOP' if stop else 'CONTINUE';selected_action='STOP' if stop else None
                detector_ms+=1000*(time.perf_counter()-start)
                log.append({'offset':point['offset'],'kind':point['kind'],'action':action,'detail':detail})
                return {'stop':stop,'disable_capture':committed_full}

            e.torch.cuda.synchronize();start=time.perf_counter()
            if effective=='fixed0':
                answer=e.answer(prompt,seed);e.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-start)
                scoring=grade(answer['text'],row['gold'])
                record={'problem_id':row['problem_id'],'method':method,'effective_method':effective,'seed':seed,
                    'model_path':args.model,'dtype':'float16','correct':scoring['correct'],'grade':scoring,
                    'think_tokens':0,'answer_tokens':answer['tokens'],'total_tokens':answer['tokens'],'wall_ms':wall_ms,
                    'detector_ms':0.0,'feature_gpu_ms':0.0,'decisions':[],'trace':None,'step':None,'answer':public(answer),
                    'length_censored':False,'step_overflow':False,'policy_spec':{},'quality_labels_available_during_decisions':False}
                append_jsonl(path,record);print(json.dumps({'online':row_index,'method':method,'id':row['problem_id'],'correct':scoring['correct'],'tokens':answer['tokens'],'ms':wall_ms}),flush=True)
                del answer;continue
            trace=e.decode(prompt,8192,seed,capture=effective in ['transition','learned_stop'],checkpoint_hook=hook if effective!='full' else None)
            total_think=trace['tokens'];state=(trace['cache'],trace['logits']);prefix=prompt+trace['ids'];step=None
            natural=trace['stop_reason']=='natural_end'
            if selected_action=='STEP':
                step=e.decode(prefix,214,seed,offset=total_think,until='step',initial=state)
                prefix+=step['ids'];total_think+=step['tokens'];state=(step['cache'],step['logits']);natural=step['stop_reason']=='natural_end'
            answer=e.answer(prefix,seed,natural_closed=natural,initial=state)
            e.torch.cuda.synchronize();wall_ms=1000*(time.perf_counter()-start)
            # Gold is read for scoring only after all generation decisions finish.
            scoring=grade(answer['text'],row['gold'])
            record={'problem_id':row['problem_id'],'method':method,'effective_method':effective,'seed':seed,
                'model_path':args.model,'dtype':'float16','correct':scoring['correct'],'grade':scoring,
                'think_tokens':total_think,'answer_tokens':answer['tokens'],'total_tokens':total_think+answer['tokens'],
                'wall_ms':wall_ms,'detector_ms':detector_ms,'feature_gpu_ms':trace['feature_gpu_ms'],
                'decisions':log,'trace':public(trace),'step':public(step) if step else None,'answer':public(answer),
                'length_censored':trace['length_censored'],'step_overflow':step['length_censored'] if step else False,
                'policy_spec':spec,'quality_labels_available_during_decisions':False}
            record['probe_input_tokens']=sum(r['detail'].get('probe_input_tokens',0) for r in log)
            append_jsonl(path,record)
            print(json.dumps({'online':row_index,'method':method,'id':row['problem_id'],'correct':scoring['correct'],
                'tokens':record['total_tokens'],'ms':wall_ms,'decisions':len(log)}),flush=True)
            del trace,answer,step


if __name__=='__main__':main()
