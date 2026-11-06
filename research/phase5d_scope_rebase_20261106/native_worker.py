"""Eight new native-thinking interface fixtures; no repair or online Gold."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from native_engine import NativeEngine


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):
    p=Path(p);tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');os.replace(tmp,p)
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--model',required=True)
    ap.add_argument('--gpu',required=True);ap.add_argument('--worker',type=int,choices=[0,1],required=True)
    args=ap.parse_args();root=args.root;out=root/f'native_results/worker_{args.worker}';out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    freeze=json.loads((root/'native_prelaunch_freeze.json').read_text())
    for row in freeze['files']:assert sha(root/row['path'])==row['sha256'],row['path']
    assert os.environ.get('CUDA_VISIBLE_DEVICES')==args.gpu
    occupied=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True)
    assert not any(v.split(',')[0].strip()==args.gpu for v in occupied.splitlines()),'GPU occupied'
    import torch,transformers
    assert transformers.__version__=='4.55.2' and torch.__version__.split('+')[0]=='2.8.0'
    torch.set_num_threads(4);device=torch.device('cuda:0')
    helper=load(root/'p0_base_frozen.py','native_assets');assets=helper.model_file_manifest(args.model)
    assert assets['manifest_sha256']=='37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511'
    from transformers import AutoTokenizer,AutoModelForCausalLM
    tok=AutoTokenizer.from_pretrained(args.model,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,trust_remote_code=False,torch_dtype=torch.float16,
        attn_implementation='sdpa',low_cpu_mem_usage=True).eval().to(device)
    assert next(model.parameters()).dtype==torch.float16 and model.config._attn_implementation=='sdpa'
    cases=[json.loads(line) for line in (root/'native_visible.jsonl').read_text().splitlines() if line.strip()]
    prepared=json.loads((root/'native_rendered_prelaunch.json').read_text())
    assert len(cases)==len(prepared)==8
    assert len({v['case_id'] for v in cases})==len({v['case_id'] for v in prepared})==8
    for row,record in zip(cases,prepared):
        ids=tok.apply_chat_template([{'role':'user','content':row['question']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}],
            tokenize=True,add_generation_prompt=True,enable_thinking=True)
        assert ids==record['prompt_ids'] and row['case_id']==record['case_id']
    write(out/'manifest.json',{'worker':args.worker,'GPU':args.gpu,'source_sha256':sha(__file__),'engine_sha256':sha(root/'native_engine.py'),
        'model_files':assets,'model_config':model.config.to_dict(),'generation_config':model.generation_config.to_dict(),
        'torch':torch.__version__,'transformers':transformers.__version__,'backend':'sdpa','dtype':'FP16','batch':1,
        'hash_load_seconds':time.monotonic()-started,'thinking_template':True,'technical_context_capacity':model.config.max_position_embeddings,
        'scientific_new_token_cap':None,'scope':'Native Continue only;8enginefixtures,notalgorithmqualitygain.'})
    results=[]
    for index,case in enumerate(cases):
        if index%2!=args.worker:continue
        folder=out/case['case_id'];folder.mkdir(exist_ok=False)
        write(folder/'started.json',{'case_id':case['case_id'],'question_sha256':hashlib.sha256(case['question'].encode()).hexdigest(),'status':'IN_PROGRESS'})
        engine=NativeEngine(model,tok,device);torch.cuda.reset_peak_memory_stats(device)
        try:
            with torch.inference_mode():result=engine.run(case['question'],20261106+index,folder,write)
            result['case_id']=case['case_id'];result['peak_allocated_bytes']=torch.cuda.max_memory_allocated(device);write(folder/'result.json',result)
            results.append({'case_id':case['case_id'],'EOS':result['EOS'],'new_tokens':result['new_tokens'],'think_closed':result['think_closed'],
                'context_cap':result['hit_context_cap'],'checkpoint':result['checkpoint_observed'],'parity':result['checkpoint_criteria_pass']})
        except BaseException as e:
            write(folder/'error.json',{'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'ledger':engine.ledger})
            raise
        write(out/'progress.json',{'completed_cases':len(results),'planned_cases':4,'cases':results,'elapsed_seconds':time.monotonic()-started})
    write(out/'summary.json',{'status':'COMPLETE','completed_cases':len(results),'cases':results,'elapsed_seconds':time.monotonic()-started})


if __name__=='__main__':main()
