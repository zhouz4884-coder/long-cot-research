"""Finish fixed missing jobs after the user extended time; old results immutable."""
import argparse
import json
import os
from pathlib import Path
import time

import paired_readout as original
from resume_planner import plan_resume


def existing_rows(root):
    rows=[]
    for directory in (root/'results').glob('*worker_*'):
        for path in directory.glob('*.json'):
            value=json.loads(path.read_text())
            if isinstance(value,dict) and 'job_id' in value and 'token_ids' in value:rows.append(value)
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--model',required=True)
    ap.add_argument('--gpu',required=True);ap.add_argument('--worker',type=int,required=True);args=ap.parse_args()
    root=args.root;started=time.monotonic()
    if json.loads((root/'launcher.json').read_text())['status']!='FINISHED':raise ValueError('Original wave is still active')
    for file in ('prelaunch_freeze.json','resume_freeze.json'):
        for row in json.loads((root/file).read_text())['files']:
            if original.sha(root/row['path'])!=row['sha256']:raise ValueError('Frozen dependency mismatch '+row['path'])
    if os.environ.get('CUDA_VISIBLE_DEVICES')!=args.gpu:raise ValueError('UUID binding')
    import subprocess
    busy=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True)
    if any(line.split(',')[0].strip()==args.gpu for line in busy.splitlines()):raise ValueError('GPU occupied')
    out=root/f'results/resume_worker_{args.worker}';out.mkdir(parents=True,exist_ok=False)
    compiled=json.loads((root/'rendered_prelaunch.json').read_text())
    prior=[row for row in existing_rows(root) if (row['rank']-1)%2==args.worker]
    plan=plan_resume(compiled,args.worker,prior)
    original.write(out/'resume_plan.json',plan)
    if not plan['missing_job_ids']:
        original.write(out/'summary.json',{'status':'COMPLETE','outputs':0,'planned_missing':0,'elapsed_seconds':time.monotonic()-started,'job_ids':[]})
        return
    import torch,transformers
    if transformers.__version__!='4.55.2' or torch.__version__.split('+')[0]!='2.8.0':raise ValueError('Runtime mismatch')
    torch.set_num_threads(4);torch.manual_seed(20261106);device=torch.device('cuda:0')
    helper=original.load_module(root/'p0_base_frozen.py','p5c_resume_assets');assets=helper.model_file_manifest(args.model)
    if assets['manifest_sha256']!='37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511':raise ValueError('Model mismatch')
    from transformers import AutoTokenizer,AutoModelForCausalLM
    tok=AutoTokenizer.from_pretrained(args.model,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,trust_remote_code=False,torch_dtype=torch.float16,
        attn_implementation='sdpa',low_cpu_mem_usage=True).eval().to(device)
    assert model.config._attn_implementation=='sdpa' and next(model.parameters()).dtype==torch.float16
    jobs=json.loads((root/'jobs.json').read_text());assert original.compile_jobs(tok,jobs)==compiled
    original.write(out/'manifest.json',{'source_sha256':original.sha(__file__),'original_generator_sha256':original.sha(root/'paired_readout.py'),
        'resume_planner_sha256':original.sha(root/'resume_planner.py'),'GPU':args.gpu,'worker':args.worker,'model_files':assets,
        'hash_load_seconds':time.monotonic()-started,'same_generate_batch_function':True,'guard':384,'seed':20261106,'backend':'sdpa',
        'torch':torch.__version__,'transformers':transformers.__version__,'scope':'Missing-job continuation only; no outcome-based retries.'})
    by={j['job_id']:j for j in compiled};batches=[];written=[];discarded=[]
    for batch in plan['batches']:
        rows=[by[j] for j in batch['job_ids']]
        original.write(out/'in_progress.json',{'jobs':batch['job_ids'],'missing':batch['missing_job_ids'],'elapsed_seconds':time.monotonic()-started})
        results,ledger=original.generate_batch(model,tok,rows,device,384)
        ledger['batch_id']=batch['batch_id'];ledger['discard_existing_ids']=batch['discard_job_ids'];batches.append(ledger)
        for result in results:
            if result['job_id'] in batch['missing_job_ids']:
                original.write(out/(result['job_id']+'.json'),result);written.append(result['job_id'])
            else:discarded.append(result)
        original.write(out/'batches.json',batches);original.write(out/'discarded_recomputations.json',discarded)
        original.write(out/'progress.json',{'outputs':len(written),'planned_missing':len(plan['missing_job_ids']),
            'elapsed_seconds':time.monotonic()-started,'last_job':batch['job_ids'][-1]})
    assert len(written)==len(set(written)) and set(written)==set(plan['missing_job_ids'])
    original.write(out/'summary.json',{'status':'COMPLETE','outputs':len(written),'planned_missing':len(plan['missing_job_ids']),
        'discarded_recomputed_rows':len(discarded),'elapsed_seconds':time.monotonic()-started,'job_ids':written})


if __name__=='__main__':main()
