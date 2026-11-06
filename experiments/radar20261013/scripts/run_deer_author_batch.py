"""Audited full author state-machine batch, not M1's DEER confidence proxy.

This separate vLLM/author-protocol comparator does not inherit the formal SDPA
FULL timing or risk certificate. Batch wall is not single-request latency.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deer_author_bridge import AuthorBridge
from deer_author_source import pinned_path, load_author_module, invoke_author_batch


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_idle_gpu(gpu_uuid):
    visible=os.environ.get('CUDA_VISIBLE_DEVICES','')
    assert visible.isdigit(),'Use one physical GPU index with all devices visible to NVML'
    identity=subprocess.run(['nvidia-smi','--id='+visible,'--query-gpu=uuid','--format=csv,noheader'],
                            capture_output=True,text=True,check=True).stdout.strip()
    assert identity==gpu_uuid,'GPU index/UUID mismatch; do not inspect one device and execute on another'
    result=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader,nounits'],
                          capture_output=True,text=True,check=True)
    active=[line for line in result.stdout.splitlines() if line.split(',')[0].strip()==gpu_uuid]
    assert not active,'Selected GPU has live compute processes; do not start a second measurement: '+repr(active)


def prepare_inputs(benchmark_root,model,execution):
    benchmark_root=Path(benchmark_root)
    formal_path=benchmark_root/'provenance/formal_protocol.json'
    formal=json.loads(formal_path.read_text(encoding='utf-8'))
    assert model in formal['admitted_model_paths']
    for name,sha in formal['source_sha256'].items():
        assert digest(benchmark_root/name)==sha,'Frozen primary source changed: '+name
    assert digest(benchmark_root/'provenance/data_freeze.json')==formal['data_freeze_sha256']
    binding={'formal_protocol_sha256':digest(formal_path),'model_path':model,
             'formal_runtime_and_risk_guarantee_inherited':False}
    if execution=='preflight':
        return [{'problem_id':'deer-gpu-interface-only','question':'What is 2 + 3?'}],binding
    # Even admission waits for M1; the supervisor can dispatch a new stage during
    # an apparently idle gap between development, selection and training.
    for shard in [0,1]:
        assert (benchmark_root/f'results/online_m1_selection_{shard}.complete.json').exists(),'M1 actual selection not complete'
    analysis_path=benchmark_root/'results/m1_online_analysis.json'
    assert analysis_path.exists(),'Review complete M1 before this additional GPU comparator'
    analysis=json.loads(analysis_path.read_text(encoding='utf-8'))
    assert analysis['formal_protocol_sha256']==binding['formal_protocol_sha256'] and analysis['model_path']==model
    assert analysis['integrity_controls_passed'],'Resolve primary data/identity errors first'
    assert len(analysis['statistics'])==12 and all(value['n']==265 for value in analysis['statistics'].values())
    expected_raw={f'results/online_m1_selection_{g}.jsonl' for g in [0,1]}
    assert set(analysis['raw_source_sha256'])==expected_raw
    for name,sha in analysis['raw_source_sha256'].items():
        assert digest(benchmark_root/name)==sha,'M1 raw outputs changed after complete audit'
    binding['m1_complete_analysis_sha256']=digest(analysis_path)
    if execution=='admission':
        return [{'problem_id':'deer-gpu-interface-only','question':'What is 2 + 3?'}],binding
    # No final-test/calibration entry exists.
    path=benchmark_root/'data/selection.jsonl'
    freeze=json.loads((benchmark_root/'provenance/data_freeze.json').read_text(encoding='utf-8'))
    assert digest(path)==freeze['splits']['selection']['sha256']
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(rows)==265
    binding.update({'selection_sha256':digest(path),'expected_ids':[row['problem_id'] for row in rows]})
    return [{'problem_id':row['problem_id'],'question':row['question']} for row in rows],binding


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--execution',choices=['preflight','admission','selection'],default='preflight')
    p.add_argument('--mode',choices=['raw_source','declared_greedy_identity_repair','paper_pro_declared_greedy'],required=True)
    p.add_argument('--benchmark-root',required=True)
    p.add_argument('--model',required=True)
    p.add_argument('--gpu-uuid')
    p.add_argument('--output-dir')
    p.add_argument('--dtype',choices=['float16','bfloat16'],default='float16')
    p.add_argument('--max-len',type=int,default=16384)
    p.add_argument('--think-ratio',type=float,default=.8)
    p.add_argument('--batch-size',type=int,default=1)
    p.add_argument('--gpu-memory-utilization',type=float,default=.85)
    args=p.parse_args()
    assert 0<args.think_ratio<1 and args.max_len>=128 and args.batch_size>=1
    path=pinned_path()
    questions,binding=prepare_inputs(args.benchmark_root,args.model,args.execution)
    versions={}
    for name in ['torch','transformers','vllm','numpy','nltk','joblib','regex','tqdm']:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    source_names=['deer_author_source.py','deer_author_bridge.py','deer_trial_score.py','deer_pro.py','scripts/run_deer_author_batch.py']
    report={'execution':args.execution,'mode':args.mode,'source_sha256':{name:digest(ROOT/name) for name in source_names},
            'vendor_qwen_sha256':digest(path),'package_versions':versions,'binding':binding,
            'request_protocol_differences':['vLLM instead of primary SDPA','source system/user roles',
                'source ATP stop/re-tokenization/Wait restoration','source total budget and thinking ratio',
                'source greedy main decoding','source trial cue and 20-token cap',
                'source final regeneration, not candidate-bound commit',
                'source variable remaining answer budget, not primary answer192'],
            'scope':'Full author state-machine batch with declared repairs/PRo extension. Not a same-protocol M1 comparator, per-request latency, task performance before actual generation, or inherited risk certificate.'}
    if args.execution=='preflight':
        print(json.dumps(report,indent=2));return
    assert versions['vllm']=='0.10.2' and versions['torch']=='2.8.0+cu128','Use the inspected separate runtime'
    assert versions['nltk']=='3.9.1' and versions['joblib']=='1.4.2','Load pinned isolated wheel target; do not modify formal .venv'
    assert args.gpu_uuid and args.output_dir
    assert len(os.environ.get('CUDA_VISIBLE_DEVICES','').split(','))==1 and os.environ.get('CUDA_VISIBLE_DEVICES'), 'Use exactly one admitted physical GPU'
    import fcntl
    lock=(Path(args.benchmark_root)/'logs/continuation.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise AssertionError('Primary continuation supervisor still owns dispatch; preserve it')
    require_idle_gpu(args.gpu_uuid)
    identity_path=Path(args.benchmark_root)/'provenance/qwen3_4b_verified.json'
    identity=json.loads(identity_path.read_text(encoding='utf-8'))
    model_checks=[]
    for item in identity['files']:
        model_file=Path(args.model)/item['name']
        value=hashlib.sha256()
        with model_file.open('rb') as stream:
            for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
        assert value.hexdigest()==item['sha256'],'Live model file changed: '+item['name']
        model_checks.append({'name':item['name'],'sha256':value.hexdigest()})
    report['live_model_file_checks']=model_checks
    report['model_identity_manifest_sha256']=digest(identity_path)
    directory=Path(args.output_dir)
    assert not directory.exists(),'Preserve all earlier runs; choose a fresh output directory'
    directory.mkdir(parents=True)
    (directory/'pre_generation_binding.json').write_text(json.dumps(report,indent=2)+'\n')
    arguments=SimpleNamespace(model_name_or_path=args.model,dataset_dir=str(directory),dataset='math',output_path=str(directory/'source_output'),
        dtype=args.dtype,max_len=args.max_len,think_ratio=args.think_ratio,batch_size=args.batch_size,
        threshold=.95,prob_check_max_tokens=20,max_judge_steps=10,points=1,policy='avg2',temperature=0.,top_p=1.,
        gpu_memory_utilization=args.gpu_memory_utilization,trust_remote_code=False,run_time=1,
        no_thinking=1 if args.execution=='admission' else 0,rep=0,af=0)
    started=time.perf_counter()
    try:
        with (directory/'author_stdout.log').open('w',encoding='utf-8') as stdout,(directory/'author_stderr.log').open('w',encoding='utf-8') as stderr,redirect_stdout(stdout),redirect_stderr(stderr):
            author=load_author_module()
            tokenizer=author.AutoTokenizer.from_pretrained(args.model,local_files_only=True)
            endthink_ids=tokenizer.encode('</think>',add_special_tokens=False)
            assert len(endthink_ids)==1,'Qwen score repair requires one actual endthink token'
            bridge=AuthorBridge(args.mode,directory/'engine_calls.jsonl',endthink_ids[0])
            bridge.attach(author)
            rows=invoke_author_batch(author,questions,arguments)
        with (directory/'raw_outputs.jsonl').open('w',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        report.update({'complete_author_outputs':len(rows),'expected_author_outputs':len(questions),
                       'actual_batch_wall_ms_including_import_init_warmup_logging_output':1000*(time.perf_counter()-started),
                       'not_per_request_latency':True,'author_arguments':vars(arguments),'gold_supplied_to_generation':False,
                       'no_quality_claim_before_external_frozen_regrade':True})
        (directory/'complete.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    except BaseException as error:
        failure={'exception_type':type(error).__name__,'message':str(error),'elapsed_ms':1000*(time.perf_counter()-started),
                 'complete':False,'partial_engine_costs_preserved':'engine_calls.jsonl'}
        (directory/'failed.json').write_text(json.dumps(failure,indent=2)+'\n')
        raise
    finally:
        lock.close()


if __name__=='__main__':main()
