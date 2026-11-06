"""Post-D1 same-prefix execution-schedule control; no new answer generation."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

from native_engine import NativeEngine
from native_worker import write


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--model',required=True)
    ap.add_argument('--gpu',required=True);ap.add_argument('--worker',type=int,choices=[0,1],required=True);a=ap.parse_args()
    root=a.root;out=root/f'schedule_control/worker_{a.worker}';out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    assert json.loads((root/'native_launcher.json').read_text())['status']=='FINISHED'
    for f in ('native_prelaunch_freeze.json','schedule_control_freeze.json'):
        for row in json.loads((root/f).read_text())['files']:
            assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
    assert os.environ.get('CUDA_VISIBLE_DEVICES')==a.gpu
    busy=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True)
    assert not any(v.split(',')[0].strip()==a.gpu for v in busy.splitlines())
    import torch,numpy as np,transformers
    assert transformers.__version__=='4.55.2' and torch.__version__.split('+')[0]=='2.8.0'
    torch.set_num_threads(4);device=torch.device('cuda:0')
    sp=importlib.util.spec_from_file_location('schedule_assets',root/'p0_base_frozen.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    assets=m.model_file_manifest(a.model);assert assets['manifest_sha256']=='37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511'
    from transformers import AutoTokenizer,AutoModelForCausalLM
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,torch_dtype=torch.float16,attn_implementation='sdpa',low_cpu_mem_usage=True).eval().to(device)
    rows=[]
    for folder in sorted((root/f'native_results/worker_{a.worker}').glob('D1_*')):
        result=json.loads((folder/'result.json').read_text());cp=json.loads((folder/'checkpoint.json').read_text());k=cp['generated_checkpoint_tokens']
        assert cp['prefix_ids']==result['prompt_ids']+result['generated_ids'][:k]
        original=np.load(folder/'checkpoint_logits.npz')['hot'];engine=NativeEngine(model,tok,device);engine.stage='schedule_matched_cold_replay'
        with torch.inference_mode():
            cache,logits=engine.prefill(result['prompt_ids'])
            for token in result['generated_ids'][:k]:cache,logits=engine.forward([token],cache)
            fingerprints=engine.kv_fingerprints(cache)
            actual=logits.cpu().numpy();maxdiff=float(np.max(np.abs(actual-original)))
            state=torch.tensor(cp['RNG_state'],dtype=torch.uint8)
            continuation=engine.branch(copy.deepcopy(cache),logits,state,cp['diagnostic_horizon_tokens'])
        row={'case_id':folder.name,'prefix_sha256':cp['prefix_sha256'],'prompt_tokens':len(result['prompt_ids']),'generated_prefix_tokens':k,
            'max_abs_from_original_stream':maxdiff,'same_top1':int(actual.argmax())==int(original.argmax()),
            'same_all_KV_fingerprints':fingerprints==cp['original_KV_fingerprints'],'same_sampled_diagnostic_tokens':continuation==cp['hot_next_tokens'],
            'new_diagnostic_tokens':continuation,'ledger':engine.ledger,'scope':'Sameexecution schedule; noGold/newtrajectory/repair.'}
        row['pass']=maxdiff==0 and row['same_all_KV_fingerprints'] and row['same_sampled_diagnostic_tokens']
        write(out/(folder.name+'.json'),row);rows.append(row)
    write(out/'summary.json',{'status':'COMPLETE','cases':len(rows),'passed':sum(r['pass'] for r in rows),'rows':rows,'elapsed_seconds':time.monotonic()-started,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'algorithm_inputs_or_sampling_changed':False})


if __name__=='__main__':main()
