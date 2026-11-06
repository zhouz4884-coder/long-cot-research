"""PBS-allocated single-GPU admission. No pretrained weights or task scores."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output);assert not output.exists(),'Preserve prior admission'
    started=time.time();report={'started_unix':started,'hostname':subprocess.check_output(['hostname'],text=True).strip(),
        'pbs_job_id':os.environ.get('PBS_JOBID'),'scope':'PBS allocation and finite random-model GPU interface only; no pretrained model performance'}
    try:
        assert report['pbs_job_id'],'Do not run GPU work on the login node'
        visible=os.environ.get('CUDA_VISIBLE_DEVICES')
        gpu_file=os.environ.get('PBS_GPUFILE');lines=[]
        if gpu_file and Path(gpu_file).exists():lines=Path(gpu_file).read_text().splitlines()
        report['pbs_gpu_file_entries']=lines
        if not visible:
            assert lines,'No scheduler GPU binding; do not guess an available device'
            match=re.search(r'(?:/|gpu)(\d+)$',lines[0])
            assert match,'Unknown Torque GPU file format'
            visible=match.group(1);os.environ['CUDA_VISIBLE_DEVICES']=visible
        assert ',' not in visible,'Admission requires one allocated GPU'
        report['visible_physical_gpu']=visible
        import torch,transformers
        report['torch_version']=torch.__version__;report['cuda_build']=torch.version.cuda
        report['transformers_version']=transformers.__version__;report['compiled_arches']=torch.cuda.get_arch_list()
        assert torch.cuda.is_available(),'CUDA initialization failed'
        prop=torch.cuda.get_device_properties(0)
        report.update({'gpu_name':prop.name,'compute_capability':[prop.major,prop.minor],
                       'total_memory_bytes':prop.total_memory,'native_bf16':prop.major>=8})
        assert (prop.major,prop.minor)==(7,0) and 'V100' in prop.name
        torch.manual_seed(20261105);torch.cuda.reset_peak_memory_stats()
        x=torch.randn((256,256),dtype=torch.float16,device='cuda')
        product=x@x.T;assert torch.isfinite(product).all();torch.cuda.synchronize()
        report['fp16_matmul_finite']=True
        from transformers import Qwen3Config,Qwen3ForCausalLM
        cfg=Qwen3Config(vocab_size=128,hidden_size=64,intermediate_size=128,num_hidden_layers=2,
            num_attention_heads=4,num_key_value_heads=2,head_dim=16,max_position_embeddings=1024)
        cfg._attn_implementation='eager'
        model=Qwen3ForCausalLM(cfg).eval().to(device='cuda',dtype=torch.float16)
        ids=torch.arange(128,device='cuda').remainder(127).view(1,-1)
        with torch.inference_mode():
            initial=model(input_ids=ids,use_cache=True)
            mask=torch.ones((1,129),device='cuda',dtype=torch.long);mask[:,24:48]=0
            resumed=model(input_ids=torch.tensor([[17]],device='cuda'),past_key_values=initial.past_key_values,
                          attention_mask=mask,use_cache=True,cache_position=torch.tensor([128],device='cuda'))
        assert torch.isfinite(resumed.logits).all()
        report.update({'tiny_qwen3_eager_fp16_forward_finite':True,'tiny_qwen3_masked_cached_forward_finite':True,
            'cache_length_after':int(resumed.past_key_values.get_seq_length()),
            'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
            'passed':True,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    except BaseException as error:
        report.update({'passed':False,'exception_type':type(error).__name__,'message':str(error)})
        raise
    finally:
        report['elapsed_seconds']=time.time()-started
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
