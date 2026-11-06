"""Bounded Phase5-B module pilot; reuses the frozen, reviewed natural-EOS loop."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):
    p=Path(p);tmp=p.with_name(p.name+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8");os.replace(tmp,p)
def module(p,name,expected=None):
    if expected and sha(p)!=expected:raise ValueError("Source mismatch: "+str(p))
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def render_jobs(tokenizer,jobs):
    result=[]
    for job in jobs:
        text=tokenizer.apply_chat_template(job["messages"],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        if not text.endswith("<think>\n\n</think>\n\n"):raise ValueError("Nonthinking template required")
        ids=tokenizer.encode(text,add_special_tokens=False)
        result.append({**job,"prompt_text":text,"prompt_token_ids":ids,"position_ids":list(range(len(ids))),"prompt_tokens":len(ids)})
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--base-path',type=Path,required=True)
    ap.add_argument('--quality-path',type=Path,required=True);ap.add_argument('--device',default='cuda:0')
    ap.add_argument('--standalone-gpu');ap.add_argument('--cpu-interface-check',action='store_true');ap.add_argument('--runtime-dir',type=Path)
    ap.add_argument('--max-seconds',type=float,default=270);ap.add_argument('--seed',type=int,default=20261106)
    args=ap.parse_args();started=time.monotonic();args.output.mkdir(parents=True,exist_ok=False)
    state={'stage':'admission','job_id':None};records=[];runner=None;done=threading.Event()
    def watchdog():
        if not done.wait(args.max_seconds):
            write(args.output/'deadline.json',{'status':'HARD_DEADLINE','elapsed_seconds':time.monotonic()-started,'progress':state})
            os._exit(124)
    threading.Thread(target=watchdog,daemon=True).start()
    try:
        base=module(args.base_path,'p5b_base','246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b')
        quality=module(args.quality_path,'p5b_quality','0eab8a3a62381db7f56c9cf9101647703cb8e1208d9f3c38e25eec59fafcd2f9')
        core=module(args.root/'boundary_core.py','p5b_core')
        if args.cpu_interface_check:
            if args.device!='cpu' or args.model!='tiny-random':raise ValueError('Explicit CPU fixture only')
        else:
            if not args.standalone_gpu or not args.standalone_gpu.startswith('GPU-'):raise ValueError('Full explicit UUID required')
            freeze=json.loads((args.root/'prelaunch_freeze.json').read_text())
            for row in freeze['remote_files']:
                if sha(args.root/row['path'])!=row['sha256']:raise ValueError('Prelaunch binding mismatch')
        binding=base.bind_device(args)
        if args.runtime_dir:sys.path.insert(0,str(args.runtime_dir.resolve(strict=True)))
        import torch
        import numpy as np
        import transformers
        if transformers.__version__!='4.55.2':raise ValueError('TF4.55.2 only')
        if not args.cpu_interface_check and torch.__version__.split('+')[0] not in ('2.8.0','2.4.1'):raise ValueError('Real Torch binding')
        torch.set_num_threads(4);torch.manual_seed(args.seed);base.torch=quality.torch=torch;base.np=quality.np=np
        device=torch.device(binding['device'])
        dataset=json.loads((args.root/'CONTROL_DATASET.json').read_text(encoding='utf-8'));jobs=json.loads((args.root/'PREPARED_JOBS.json').read_text(encoding='utf-8'))
        cpu=json.loads((args.root/'CPU_PRECHECK.json').read_text(encoding='utf-8'))
        if cpu['source_sha256']!=sha(args.root/'boundary_core.py') or cpu['dataset_sha256']!=sha(args.root/'CONTROL_DATASET.json') or cpu['jobs_sha256']!=sha(args.root/'PREPARED_JOBS.json'):raise ValueError('CPU admission mismatch')
        cases={c['case_id']:c for c in dataset['cases']};guard=8 if args.cpu_interface_check else 768
        manifest={'status':'ADMITTED','source_sha256':sha(__file__),'core_sha256':sha(args.root/'boundary_core.py'),
                  'dataset_sha256':sha(args.root/'CONTROL_DATASET.json'),'prepared_jobs_sha256':sha(args.root/'PREPARED_JOBS.json'),
                  'cpu_admission_sha256':sha(args.root/'CPU_PRECHECK.json'),'binding':binding,
                  'base_sha256':sha(args.base_path),'quality_sha256':sha(args.quality_path),
                  'versions':{'torch':torch.__version__,'transformers':transformers.__version__,'python':sys.version},
                  'interface_only':args.cpu_interface_check,'guard':guard,'max_seconds':args.max_seconds,
                  'normal_stop':'configured EOS only; no parser/newline stop','planned_outputs':len(jobs),
                  'scope':'One synthetic20-definition program, three related E/C/W states; exact scoped checker and known graph; one-shot readout, no per-new-node checker. Not natural end-to-end algorithm.'}
        write(args.output/'manifest.json',manifest);load=time.monotonic();state['stage']='hash_load'
        if args.cpu_interface_check:
            from transformers import Qwen3Config,Qwen3ForCausalLM
            tok=quality.FixtureTokenizer([j['messages'] for j in jobs]);cfg=Qwen3Config(vocab_size=tok.vocab_size,hidden_size=32,intermediate_size=64,
                num_hidden_layers=3,num_attention_heads=4,num_key_value_heads=2,head_dim=8,max_position_embeddings=8192,
                attention_dropout=0.0,eos_token_id=4,pad_token_id=0,bos_token_id=1,layer_types=['full_attention']*3)
            cfg._attn_implementation='eager';model=Qwen3ForCausalLM(cfg).eval().to(device)
            manifest['model_scope']='random tiny CPU interface only'
        else:
            from transformers import AutoTokenizer,AutoModelForCausalLM
            assets=base.model_file_manifest(args.model)
            if assets['manifest_sha256']!='37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511':raise ValueError('4B model snapshot mismatch')
            manifest['model_files']=assets
            tok=AutoTokenizer.from_pretrained(args.model,local_files_only=True,trust_remote_code=False)
            model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,trust_remote_code=False,
                torch_dtype=torch.float16,attn_implementation='eager',low_cpu_mem_usage=True).eval().to(device)
            if next(model.parameters()).dtype!=torch.float16:raise ValueError('FP16 only')
        if model.config.model_type!='qwen3' or model.config._attn_implementation!='eager':raise ValueError('Model/attention binding')
        if any(x!='full_attention' for x in model.config.layer_types):raise ValueError('Full attention only')
        eos=model.generation_config.eos_token_id or tok.eos_token_id;eos_ids=set(eos if isinstance(eos,(list,tuple)) else [eos])
        compiled=render_jobs(tok,jobs)
        if any(j['prompt_tokens']+guard>model.config.max_position_embeddings for j in compiled):raise ValueError('Context overflow')
        if not args.cpu_interface_check and compiled!=json.loads((args.root/'rendered_prelaunch.json').read_text()):raise ValueError('Tokenizer input mismatch')
        write(args.output/'rendered_jobs.json',compiled)
        manifest.update(load_and_hash_seconds=time.monotonic()-load,rendered_jobs_sha256=sha(args.output/'rendered_jobs.json'),
                        model_config=model.config.to_dict(),eos_ids=sorted(eos_ids),parameter_dtype=str(next(model.parameters()).dtype),
                        tokenizer_class=type(tok).__name__)
        write(args.output/'manifest.json',manifest)
        runner=quality.make_runner(base,model,tok,device,args.output,state)
        if args.cpu_interface_check:write(args.output/'strict_EOS_mock.json',quality.strict_eos_mock_control(base,args.output))
        with torch.inference_mode():
            for job in compiled:
                if args.max_seconds-(time.monotonic()-started)<20:break
                state.update(stage='request_start',job_id=job['job_id'],method=job['method'],case_id=job['case_id'])
                rec={'job_id':job['job_id'],'case_id':job['case_id'],'method':job['method'],'status':'IN_PROGRESS','complete':False,
                     'rendering':job,'source_sha256':manifest['source_sha256'],'core_sha256':manifest['core_sha256']}
                path=args.output/(job['job_id']+'.json');write(path,rec);begin=time.monotonic();ledger_start=len(runner.forward_ledger)
                gstart=time.monotonic();controlled=None
                visible=cases[job['case_id']]['visible'] if job['case_id'] else dataset['cases'][0]['visible']
                if job['method'] in ('SharedGFull','BoundaryProjection'):controlled=core.controller(visible)
                rec['G_cpu_seconds']=time.monotonic()-gstart;rec['G_and_bookkeeping']=controlled
                regenerated=core.render(visible,job['method'],controlled)
                if regenerated!=job['messages'] or (controlled is not None and core.digest(controlled)!=job['G_state_hash']):raise ValueError('Request G/input mismatch')
                ids=job['prompt_token_ids'];prefill,pt=runner.timed('prefill',lambda:runner.forward(ids,[1]*len(ids),0))
                rec['prefill_timing']=pt;write(path,rec)
                def partial(tokens,text):
                    if len(tokens)%32==0:
                        rec['partial_free']={'token_ids':list(tokens),'text':text,'new_tokens':len(tokens)};write(path,rec)
                free,gt=runner.timed('generation',lambda:runner.natural_greedy(ids,prefill.past_key_values,prefill.logits[0,-1].float().cpu(),eos_ids,guard,partial))
                rec.update(free=free,generation_timing=gt,request_seconds_including_G=time.monotonic()-begin)
                extracted=core.extract_integer(free['text']);gold=cases[job['case_id']]['evaluation_only']['gold'] if job['case_id'] else dataset['cases'][0]['evaluation_only']['gold']
                correct=extracted['value']==gold
                rec.update(grade={'extraction':extracted,'numeric_correct':correct,'eos_and_correct':correct and free['eos_reached']},
                           evaluation_only={'gold':gold,'group':cases[job['case_id']]['evaluation_only']['group'] if job['case_id'] else None},
                           status='COMPLETE',complete=True,forward_cost=quality.cost(runner.forward_ledger[ledger_start:]))
                rec.pop('partial_free',None);write(path,rec);records.append(rec)
                write(args.output/'progress.json',{'complete_outputs':len(records),'planned_outputs':len(jobs),'elapsed_seconds':time.monotonic()-started,'last_job':job['job_id']})
                write(args.output/'forward_ledger.json',runner.forward_ledger);write(args.output/'timings.json',runner.timing)
                del prefill
        summary={'status':'COMPLETE' if len(records)==len(jobs) else 'PARTIAL_TIME_BUDGET','complete_outputs':len(records),'planned_outputs':len(jobs),
                 'elapsed_seconds':time.monotonic()-started,'independent_programs':1,'groups':{},'forward_cost':quality.cost(runner.forward_ledger),
                 'complete_ids':[r['job_id'] for r in records],'not_started':[j['job_id'] for j in jobs if j['job_id'] not in {r['job_id'] for r in records}]}
        for case in dataset['cases']:
            rr=[r for r in records if r['case_id']==case['case_id']]
            summary['groups'][case['evaluation_only']['group']]={r['method']:{'correct':r['grade']['numeric_correct'],'eos':r['free']['eos_reached'],
                'cap':r['free']['hit_safety_cap'],'tokens':r['free']['new_tokens'],'parsed':r['grade']['extraction']['value']} for r in rr}
        write(args.output/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
    except BaseException as exc:
        write(args.output/'error.json',{'type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),'progress':state,'elapsed_seconds':time.monotonic()-started})
        raise
    finally:done.set()


if __name__=='__main__':main()
