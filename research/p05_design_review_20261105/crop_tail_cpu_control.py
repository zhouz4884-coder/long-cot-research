"""Real tiny-Qwen3 CPU crop controls using isolated Transformers 4.55.2.

No pretrained model, GPU, remote worker or model download. The runtime and official
source files must already exist beside this script. No global package is changed.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(BASE/"runtime4552"))

import torch
import transformers
from transformers import Qwen3Config, Qwen3ForCausalLM
from transformers.cache_utils import Cache, DynamicCache, DynamicLayer
from transformers.generation.logits_process import RepetitionPenaltyLogitsProcessor
from transformers.generation.stopping_criteria import EosTokenCriteria, MaxLengthCriteria


PREFIX = [3, 7, 11, 5, 13, 17, 19]
PROPOSAL = [23, 29, 31]
SUFFIX = [37, 41]
SEEDS = [7, 17, 29, 43, 71]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pairs(cache):
    return [(layer.keys, layer.values) for layer in cache.layers]


def tensor_meta(t):
    return {"shape": list(t.shape), "stride": list(t.stride()), "dtype": str(t.dtype),
            "device": str(t.device), "data_ptr": t.data_ptr(),
            "storage_ptr": t.untyped_storage().data_ptr(), "storage_nbytes": t.untyped_storage().nbytes(),
            "logical_nbytes": t.numel()*t.element_size(), "storage_offset": t.storage_offset(),
            "contiguous": t.is_contiguous(), "autograd_base_present": t._base is not None,
            "inference_mode": torch.is_inference_mode_enabled()}


def cache_meta(cache):
    return {"cache_object_id": id(cache), "seq_length": cache.get_seq_length(),
            "layers":[{"layer":i,"layer_object_id":id(layer),
                       "K":tensor_meta(layer.keys),"V":tensor_meta(layer.values)}
                      for i,layer in enumerate(cache.layers)]}


def max_cache_delta(a,b):
    return max(float((x-y).abs().max()) for aa,bb in zip(pairs(a),pairs(b)) for x,y in zip(aa,bb))


def dist(a,b):
    a,b=a.double().cpu().flatten(),b.double().cpu().flatten()
    assert torch.isfinite(a).all() and torch.isfinite(b).all()
    p,q=a.softmax(-1),b.softmax(-1)
    return {"logit_max_abs":float((a-b).abs().max()),"TV":float((p-q).abs().sum()/2),
            "argmax_a":int(a.argmax()),"argmax_b":int(b.argmax()),"argmax_equal":bool(a.argmax()==b.argmax())}


def forward(model, ids, cache=None, start=None, mask=None, attentions=False, automatic_positions=False):
    n_past=cache.get_seq_length() if cache is not None else 0
    start=n_past if start is None else start
    length=n_past+len(ids)
    mask=[1]*length if mask is None else mask
    kwargs={"input_ids":torch.tensor([ids],dtype=torch.long,device="cpu"),
            "attention_mask":torch.tensor([mask],dtype=torch.long,device="cpu"),
            "past_key_values":cache,"use_cache":True,"return_dict":True,
            "output_attentions":attentions,"logits_to_keep":1}
    if not automatic_positions:
        kwargs["position_ids"]=torch.arange(start,start+len(ids),dtype=torch.long).unsqueeze(0)
        kwargs["cache_position"]=torch.arange(start,start+len(ids),dtype=torch.long)
    return model(**kwargs)


def future_mass(attentions,past,query_length):
    q=torch.arange(past,past+query_length)[:,None]
    k=torch.arange(past+query_length)[None,:]
    forbidden=k>q
    return max(float((a.float()*forbidden).sum(-1).max()) for a in attentions)


@torch.inference_mode()
def one_seed(seed):
    torch.manual_seed(seed)
    cfg=Qwen3Config(vocab_size=67,hidden_size=32,intermediate_size=64,num_hidden_layers=3,
        num_attention_heads=4,num_key_value_heads=2,head_dim=8,max_position_embeddings=2048,
        attention_dropout=0.0,layer_types=["full_attention"]*3,eos_token_id=31)
    cfg._attn_implementation="eager"
    model=Qwen3ForCausalLM(cfg).eval().to(device="cpu",dtype=torch.float32)
    pre=forward(model,PREFIX)
    cache=pre.past_key_values
    t_pre=cache.get_seq_length()
    pre_logits=pre.logits[0,-1].clone()
    # Deep copies create independent test controls, not a claimed production cost.
    reference=copy.deepcopy(cache)
    pre_meta=cache_meta(cache)
    time_r=time.perf_counter()
    proposed=forward(model,PROPOSAL,cache,start=t_pre)
    r_seconds=time.perf_counter()-time_r
    proposed_logits=proposed.logits[0,-1].clone()
    after_r_meta=cache_meta(cache)
    calls=[]
    original_methods=[]
    for i,layer in enumerate(cache.layers):
        original=layer.crop
        original_methods.append(original)
        def counted(n,original=original,i=i):
            calls.append(i)
            return original(n)
        layer.crop=counted
    time_crop=time.perf_counter()
    crop_return=cache.crop(t_pre)
    crop_seconds=time.perf_counter()-time_crop
    for layer,original in zip(cache.layers,original_methods):
        del layer.crop  # Restore class resolution, avoiding a copied bound-method reference.
    cropped_meta=cache_meta(cache)
    assert crop_return is None and calls==[0,1,2]
    assert cache.get_seq_length()==t_pre and max_cache_delta(cache,reference)==0.0
    cropped_for_other_controls=copy.deepcopy(cache)
    storage_checks=[]
    for before,after in zip(after_r_meta["layers"],cropped_meta["layers"]):
        for label in ["K","V"]:
            storage_checks.append({"layer":before["layer"],"kind":label,
                "same_backing_storage_as_after_R":before[label]["storage_ptr"]==after[label]["storage_ptr"],
                "backing_storage_not_shrunk":before[label]["storage_nbytes"]==after[label]["storage_nbytes"],
                "postcrop_logical_bytes":after[label]["logical_nbytes"],
                "postcrop_storage_bytes":after[label]["storage_nbytes"]})
    assert all(x["same_backing_storage_as_after_R"] and x["backing_storage_not_shrunk"] for x in storage_checks)
    # Same-path continuation: no R was ever written in reference.
    ref_read=forward(model,SUFFIX,reference,start=t_pre,attentions=True)
    crop_read=forward(model,SUFFIX,cache,start=t_pre,attentions=True)
    same_path=dist(ref_read.logits[0,-1],crop_read.logits[0,-1])
    assert same_path["logit_max_abs"]==0.0 and max_cache_delta(cache,reference)==0.0
    # Omitting both positions also works in this simple non-padded setting because
    # Qwen3 derives them from the now-cropped cache length.
    automatic=forward(model,SUFFIX,copy.deepcopy(cropped_for_other_controls),automatic_positions=True)
    auto=dist(ref_read.logits[0,-1],automatic.logits[0,-1])
    assert auto["logit_max_abs"]==0.0
    # Forgetting the generation loop's old cache_position can change RoPE and even
    # let an earlier new query see a later new token.
    badpos=forward(model,SUFFIX,copy.deepcopy(cropped_for_other_controls),start=t_pre+len(PROPOSAL),attentions=True)
    stale_positions={"position_ids":[t_pre+len(PROPOSAL)+i for i in range(len(SUFFIX))],
        "cache_position":[t_pre+len(PROPOSAL)+i for i in range(len(SUFFIX))],
        "correct_position_ids":[t_pre+i for i in range(len(SUFFIX))],
        "readout_delta":dist(ref_read.logits[0,-1],badpos.logits[0,-1]),
        "actual_future_key_mass_max":future_mass(badpos.attentions,t_pre,len(SUFFIX)),
        "control_future_key_mass_max":future_mass(ref_read.attentions,t_pre,len(SUFFIX))}
    assert stale_positions["control_future_key_mass_max"]==0.0
    assert stale_positions["actual_future_key_mass_max"]>0.0
    # Crop returns no logits; old proposal logits must not be reused as prefix logits.
    stale_logits=dist(pre_logits,proposed_logits)
    assert stale_logits["logit_max_abs"]>1e-6
    refresh=copy.deepcopy(cropped_for_other_controls)
    refresh.crop(t_pre-1)
    refreshed=forward(model,[PREFIX[-1]],refresh,start=t_pre-1)
    refresh_control=copy.deepcopy(cropped_for_other_controls)
    refresh_control.crop(t_pre-1)
    refreshed_control=forward(model,[PREFIX[-1]],refresh_control,start=t_pre-1)
    assert dist(refreshed.logits[0,-1],refreshed_control.logits[0,-1])["logit_max_abs"]==0.0
    duplicate=copy.deepcopy(cropped_for_other_controls)
    forward(model,[PREFIX[-1]],duplicate,start=t_pre)
    assert duplicate.get_seq_length()==t_pre+1
    # Actual processors/stopping criteria use input_ids, not only past_key_values.
    prefix_ids=torch.tensor([PREFIX],dtype=torch.long)
    post_ids=torch.tensor([PREFIX+PROPOSAL],dtype=torch.long)
    processor=RepetitionPenaltyLogitsProcessor(penalty=2.0)
    processor_delta=dist(processor(prefix_ids,pre_logits[None,:].clone()),
                         processor(post_ids,pre_logits[None,:].clone()))
    assert processor_delta["logit_max_abs"]>0.0
    eos=EosTokenCriteria(eos_token_id=31)
    max_length=MaxLengthCriteria(max_length=t_pre+2)
    stop={"EOS_preR":bool(eos(prefix_ids,pre_logits[None,:]).item()),
          "EOS_postR_input_ids_after_KV_crop":bool(eos(post_ids,pre_logits[None,:]).item()),
          "MaxLength_preR":bool(max_length(prefix_ids,pre_logits[None,:]).item()),
          "MaxLength_postR_input_ids_after_KV_crop":bool(max_length(post_ids,pre_logits[None,:]).item())}
    assert stop=={"EOS_preR":False,"EOS_postR_input_ids_after_KV_crop":True,
                 "MaxLength_preR":False,"MaxLength_postR_input_ids_after_KV_crop":True}
    # Sampling consumes RNG even when the candidate branch is later rejected.
    torch.manual_seed(1000+seed)
    rng0=torch.get_rng_state().clone()
    probs=pre_logits.softmax(-1)
    baseline_sample=int(torch.multinomial(probs,1))
    torch.set_rng_state(rng0)
    sampled_candidate=torch.multinomial(probs,3,replacement=True).tolist()
    rng_after_proposal=torch.get_rng_state().clone()
    no_op_cache=copy.deepcopy(cropped_for_other_controls)
    no_op_cache.crop(t_pre)
    assert torch.equal(rng_after_proposal,torch.get_rng_state())
    sample_without_rng_restore=int(torch.multinomial(probs,1))
    torch.set_rng_state(rng0)
    sample_with_rng_restore=int(torch.multinomial(probs,1))
    assert baseline_sample==sample_with_rng_restore
    rng={"seed":1000+seed,"sampled_candidate_proxy_tokens":sampled_candidate,
         "baseline_next_sample":baseline_sample,"after_crop_without_rng_restore":sample_without_rng_restore,
         "after_restoring_rng":sample_with_rng_restore,
         "state_changed_by_sampling":not torch.equal(rng0,rng_after_proposal),
         "crop_restored_rng":False,"scope":"Actual CPU multinomial/RNG test on fixed next-token probabilities; no semantic correctness claim."}
    # Middle masking leaves retained successors, unlike tail crop.
    full_ids=PREFIX+PROPOSAL
    mid=[2,3,4]
    mask=[0 if i in mid else 1 for i in range(len(full_ids))]
    late_prefill=forward(model,full_ids)
    early_prefill=forward(model,full_ids,mask=mask)
    early_cache=early_prefill.past_key_values
    late_cache=late_prefill.past_key_values
    survivor_delta=max(float((a[:,:,5:]-b[:,:,5:]).abs().max())
        for aa,bb in zip(pairs(late_cache),pairs(early_cache)) for a,b in zip(aa,bb))
    continued_mask=mask+[1]*len(SUFFIX)
    late_mid=forward(model,SUFFIX,late_cache,start=len(full_ids),mask=continued_mask)
    early_mid=forward(model,SUFFIX,early_cache,start=len(full_ids),mask=continued_mask)
    mid_delta=dist(late_mid.logits[0,-1],early_mid.logits[0,-1])
    assert survivor_delta>1e-6 and mid_delta["logit_max_abs"]>1e-6
    return {"model_seed":seed,"t_preR_actual_cache_length":t_pre,
        "positions":{"prefix":list(range(t_pre)),"R":list(range(t_pre,t_pre+len(PROPOSAL))),
                     "continuation_after_crop":list(range(t_pre,t_pre+len(SUFFIX)))},
        "cache_before_R":pre_meta,"cache_after_R":after_r_meta,"cache_after_crop":cropped_meta,
        "crop_layer_calls":calls,"crop_return_is_none":crop_return is None,
        "crop_seconds_single_observation_not_complexity_proof":crop_seconds,
        "proposal_forward_seconds":r_seconds,"proposal_extra_forward_tokens":len(PROPOSAL),
        "crop_KV_vs_preR_control_max_abs":0.0,"storage_checks":storage_checks,
        "same_path_continuation":same_path,"same_path_continued_KV_max_abs":0.0,
        "automatic_position_derivation_in_this_fixture":auto,
        "stale_position_counterexample":stale_positions,
        "saved_preR_vs_stale_R_logits":stale_logits,
        "one_last_token_refresh":{"forward_tokens":1,"crop_to":t_pre-1,"position":t_pre-1,
            "vs_saved_whole_prefill_logits":dist(pre_logits,refreshed.logits[0,-1]),
            "same_refresh_path_identity_max_abs":0.0,"incorrect_duplicate_last_token_length":duplicate.get_seq_length()},
        "processor_history_counterexample":processor_delta,"stop_history_counterexample":stop,
        "RNG_counterexample":rng,
        "middle_mask_contrast":{"masked_positions":mid,"surviving_successor_KV_max_abs":survivor_delta,
            "late_vs_early_same_position_logits":mid_delta,"tail_crop_claim_does_not_apply":True}}


def main():
    assert transformers.__version__=="4.55.2"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    source_manifest=json.loads((BASE/"official_sources"/"manifest.json").read_text(encoding="utf-8"))
    for item in source_manifest:
        assert digest(BASE/"runtime4552"/"transformers"/item["relative_path"])==item["sha256"]
        assert digest(BASE/"official_sources"/item["relative_path"])==item["sha256"]
    start=time.perf_counter()
    rows=[one_seed(seed) for seed in SEEDS]
    report={"status":"PASS_TAIL_CROP_PREFIX_REUSE_AND_COUNTEREXAMPLES",
        "environment":{"python":sys.version,"torch":torch.__version__,"transformers":transformers.__version__,
            "transformers_path":transformers.__file__,"device":"cpu","dtype":"float32",
            "gpu_used":False,"pretrained_model_used":False,"deterministic_algorithms":True,"threads":1},
        "source_sha256":digest(__file__),"official_source_manifest":source_manifest,
        "configuration":{"model":"tiny random Qwen3, full-attention eager","layers":3,"hidden_size":32,
            "Q_heads":4,"KV_heads":2,"head_dim":8,"vocab_size":67,"seeds":SEEDS,
            "prefix_ids":PREFIX,"proposal_ids":PROPOSAL,"forced_continuation_ids":SUFFIX,
            "test_control_deepcopies":"Independent comparison branches only; do not count them as necessary crop production operations."},
        "source_findings":{"Cache_crop_layer_loop":inspect.getsourcelines(Cache.crop)[1],
            "DynamicLayer_crop_views":inspect.getsourcelines(DynamicLayer.crop)[1],
            "DynamicLayer_update_cat":inspect.getsourcelines(DynamicLayer.update)[1],
            "asymptotics":"O(number_of_layers) view updates; fixed-layer metadata work is independent of prefix length. Not a universal O(1) transaction.",
            "crop_data_copy":"Standard dense DynamicLayer slices are views in these tests; backing allocations retain removed tail storage.",
            "append_cost":"DynamicLayer.update uses concatenation; writing a proposal and later appending can allocate/copy, separate from crop itself."},
        "summary":{"model_seed_count":len(rows),"same_path_crop_readout_logit_max_abs":max(r["same_path_continuation"]["logit_max_abs"] for r in rows),
            "crop_KV_prefix_max_abs":0.0,"all_crop_views_share_postR_storage":all(x["same_backing_storage_as_after_R"] for r in rows for x in r["storage_checks"]),
            "all_backing_storage_not_shrunk_by_crop":all(x["backing_storage_not_shrunk"] for r in rows for x in r["storage_checks"]),
            "stale_logits_argmax_changed_cases":sum(not r["saved_preR_vs_stale_R_logits"]["argmax_equal"] for r in rows),
            "RNG_next_sample_changed_without_restore_cases":sum(r["RNG_counterexample"]["baseline_next_sample"]!=r["RNG_counterexample"]["after_crop_without_rng_restore"] for r in rows),
            "stale_generation_positions_future_leak_cases":sum(r["stale_position_counterexample"]["actual_future_key_mass_max"]>0 for r in rows),
            "all_cases_passed":True},
        "rows":rows,"elapsed_seconds_excluding_imports":time.perf_counter()-start,
        "limitations":["No trained model, semantic W accuracy, GPU speed or universal device guarantee was measured.",
            "Qwen3 runtime is pinned to 4.55.2; CPU torch is 2.11.0, not the prior GPU torch 2.8.0.",
            "Equivalent output after complete state restoration is conditional noninterference, not correctness of an untrusted old state or verifier.",
            "Same-model tail prefix reuse is valid only for append-only causal caches with unchanged prefix and complete external state handling.",
            "Generation R/verifier wall time is real cost and cannot be restored by crop; hard-deadline effects can differ even if tokens are coupled."]}
    target=BASE/"crop_tail_cpu_control.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"environment":report["environment"],"summary":report["summary"],
                      "elapsed_seconds_excluding_imports":report["elapsed_seconds_excluding_imports"],"output":str(target)},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
