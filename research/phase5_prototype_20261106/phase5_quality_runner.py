#!/usr/bin/env python3
"""One-shot shared-root-G quality prototype; no training, masks, probes or tail injection.

Real worker requires the frozen Qwen3-4B snapshot, HF4.55.2 and torch2.8/2.4.1.
CPU interface only: --model tiny-random --device cpu --cpu-interface-check
  --runtime-dir ../p05_design_review_20261105/runtime4552
The CPU fixture is random and uses deterministic chunk tokens, not a Qwen tokenizer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import traceback
from types import SimpleNamespace

BASE_SHA="246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b"
PARSER_SHA="c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed"
ADAPTER_SHA="3556baa0920b344e87f22037c584f7d2bde77bbdede9808c4e360fc00200890f"
DATA_SHA="93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1"
DATASET_HASH="5260ad988fd9dfe97c186ad9fb7970c7a8cc91540de86f6be59c3de26c6b723b"
MODEL_SHA="37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"
METHODS=("SharedGDirect","SharedGCompact","SharedGStepwise","VersionFrame")
ORDER=("T1_support_before_fault_E","T2_support_before_fault_E",
       "T1_support_before_fault_C","T2_support_before_fault_C",
       "T1_support_before_fault_W","T2_support_before_fault_W")
CPU_CASES={"T1_support_before_fault_E","T1_support_before_fault_C","T1_support_before_fault_W"}
LIMITS=[
 "Two arithmetic programs with E/C/W variants: exploratory development fixtures, not six independent natural tasks.",
 "G certifies constant roots parsed from visible original definitions; old y/z stay UNVERIFIED.",
 "All four methods share G/rules/graph/old records/R; no group or gold chooses a method or bypass.",
 "VersionFrame is one-shot prompted organization, not runtime node checking or certified final submission.",
 "No training, cache mask/crop, steering, teacher-forced scoring, auxiliary probes or forced tail window.",
 "Real free outputs continue to configured EOS or the 512-token safety guard; the random CPU fixture has an explicit shorter guard. No parser-based early stopping.",
 "Safety-cap/unknown/unparsed/failures remain visible; incomplete four-arm cases are not silently completed or replaced.",
 "Per-method quality/cost is not compared with the prior P0.5 run's different prompts/protocol.",
 "Shared input preparation and model loading are experimental overhead; actual per-request G/prompt/prefill/decode costs are separate.",
 "Numeric final-answer extraction is posthoc grading, not a runtime model/tool correctness gate.",
]
torch=None
np=None


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def digest(obj): return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def write_json(path,obj):
    path=Path(path); temp=path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    os.replace(temp,path)


def load_module(path,name,expected):
    path=Path(path).resolve(strict=True)
    if sha(path)!=expected: raise RuntimeError("Frozen source hash mismatch: "+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module,path


def dependency(explicit,filename,fallback):
    if explicit:return Path(explicit)
    here=Path(__file__).resolve().parent
    p=here/filename
    return p if p.is_file() else here.parent/fallback


class FixtureTokenizer:
    """Random-CPU interface fixture: exact ChatML text, 8-character ordinary chunks.

    Chunking keeps verbose shared-state prompts cheap for a tiny CPU attention test.
    It is explicitly not the production tokenizer or a language-performance model.
    """
    specials=("<|im_start|>","<|im_end|>","<think>","</think>")
    eos_token_id=4
    pad_token_id=0
    special_tokens_map={"eos_token":"<|im_end|>","pad_token":"<pad>"}
    chat_template="CPU fixture ChatML with nonthinking assistant; 8-char chunks"

    @staticmethod
    def template(messages):
        return "".join("<|im_start|>"+m["role"]+"\n"+m["content"]+"<|im_end|>\n" for m in messages)+"<|im_start|>assistant\n<think>\n\n</think>\n\n"

    @classmethod
    def split(cls,text):
        pattern="("+"|".join(re.escape(s) for s in cls.specials)+")"
        parts=[]
        for piece in re.split(pattern,text):
            if piece in cls.specials:parts.append(piece)
            elif piece:parts.extend(piece[i:i+8] for i in range(0,len(piece),8))
        return parts

    def __init__(self,messages):
        ordinary={p for m in messages for p in self.split(self.template(m)) if p not in self.specials}
        self.encoder={s:i+3 for i,s in enumerate(self.specials)}
        self.encoder.update({s:i+7 for i,s in enumerate(sorted(ordinary))})
        self.decoder={v:k for k,v in self.encoder.items()}; self.vocab_size=max(self.decoder)+1

    def apply_chat_template(self,messages,tokenize=False,add_generation_prompt=True,enable_thinking=False):
        if tokenize or not add_generation_prompt or enable_thinking:raise ValueError("Fixture template policy")
        return self.template(messages)

    def encode(self,text,add_special_tokens=False):
        if add_special_tokens:raise ValueError("No extra special tokens")
        return [self.encoder[p] for p in self.split(text)]

    def decode(self,ids,skip_special_tokens=False):
        return "".join(self.decoder.get(int(i),"") for i in ids if not(skip_special_tokens and int(i)<7))


def make_runner(base,model,tokenizer,device,output,progress):
    class QualityRunner(base.Runner):
        def __init__(self):
            super().__init__(model,tokenizer,device,output,progress);self.forward_ledger=[]
        def forward(self,ids,total_mask,start,cache=None,attentions=False,all_logits=False):
            if any(v!=1 for v in total_mask):raise RuntimeError("Quality protocol forbids key masking")
            old_len=cache.get_seq_length() if cache is not None else 0
            if start!=old_len:raise RuntimeError("Normal contiguous position/cache mismatch")
            self.sync(); begin=time.monotonic()
            out=super().forward(ids,total_mask,start,cache,attentions=attentions,all_logits=all_logits)
            self.sync()
            self.forward_ledger.append({"stage":progress.get("stage"),"job_id":progress.get("job_id"),
              "case_id":progress.get("case_id"),"method":progress.get("method"),"input_tokens":len(ids),
              "past_cache_length":old_len,"position_start":start,"attention_key_length":len(total_mask),
              "seconds":time.monotonic()-begin,"all_keys_readable":True,
              "allocated_bytes_after":torch.cuda.memory_allocated(device) if device.type=="cuda" else None})
            if not bool(torch.isfinite(out.logits).all()):raise RuntimeError("Nonfinite logits")
            return out
        def natural_greedy(self,prompt_ids,cache,initial_logits,eos_ids,limit,callback):
            # Same cached token loop as frozen base.greedy, except integer-newline
            # early stop is deliberately removed for the quality-first EOS trial.
            checkpoint_length=cache.get_seq_length()
            active=copy.deepcopy(cache); logits=initial_logits; tokens=[];stop="token_safety_cap"
            for step in range(limit):
                token=int(logits.argmax());tokens.append(token)
                if token in eos_ids:stop="eos";break
                if len(tokens)%32==0:callback(tokens,"GENERATION_PARTIAL")
                if step+1==limit:break
                out=self.forward([token],[1]*(len(prompt_ids)+len(tokens)),
                    len(prompt_ids)+len(tokens)-1,active)
                active=out.past_key_values;logits=out.logits[0,-1].float().cpu()
            if cache.get_seq_length()!=checkpoint_length:raise RuntimeError("Original branch checkpoint mutated")
            return {"token_ids":tokens,"text":tokenizer.decode(tokens,skip_special_tokens=True),
              "stop_reason":stop,"new_tokens":len(tokens),"additional_forward_tokens":max(0,len(tokens)-1),
              "hit_safety_cap":stop=="token_safety_cap","eos_reached":stop=="eos",
              "guard":limit,"no_dynamic_grader_stop":True,
              "input_checkpoint_cache_length_before_after":[checkpoint_length,cache.get_seq_length()]}
    return QualityRunner()


def cost(ledger):
    return {"forward_calls":len(ledger),"input_tokens":sum(r["input_tokens"] for r in ledger),
            "synchronized_forward_seconds":sum(r["seconds"] for r in ledger)}


def strict_eos_mock_control(base,output):
    """Exercise EOS vs integer-newline/cap branches, separate from real model costs."""
    class MockCache:
        def __init__(self,n):self.n=n
        def get_seq_length(self):return self.n
    class MockTokenizer:
        def decode(self,ids,skip_special_tokens=False):
            chars={7:"1",8:"2",9:"3",10:"\n",4:"<EOS>"}
            return "".join(chars.get(int(x),"") for x in ids if not(skip_special_tokens and x==4))
    class MockModel:
        def __init__(self,sequence):self.sequence=sequence;self.calls=0
        def forward(self,input_ids,past_key_values=None,**kwargs):
            past_key_values.n+=input_ids.shape[1];self.calls+=1
            nxt=self.sequence[min(self.calls,len(self.sequence)-1)]
            logits=torch.full((1,1,16),-100.0);logits[0,0,nxt]=100.0
            return SimpleNamespace(logits=logits,past_key_values=past_key_values)
        __call__=forward
    def run(sequence,limit):
        r=make_runner(base,MockModel(sequence),MockTokenizer(),torch.device("cpu"),output,{"stage":"CPU_MOCK_ONLY"})
        cache=MockCache(3);initial=torch.full((16,),-100.0);initial[sequence[0]]=100.0
        result=r.natural_greedy([0,0,0],cache,initial,{4},limit,lambda *_:None)
        return result,cache.get_seq_length(),r.forward_ledger
    eos,original_len,ledger=run([7,8,9,10,4],8)
    guard,guard_original_len,guard_ledger=run([7,8,9,10,7],3)
    checks={"integer_newline_does_not_stop":eos["token_ids"]==[7,8,9,10,4] and eos["stop_reason"]=="eos",
      "EOS_is_counted_and_no_post_EOS_forward":len(ledger)==4 and eos["new_tokens"]==5,
      "cap_without_EOS_is_reported":guard["new_tokens"]==3 and guard["hit_safety_cap"] and not guard["eos_reached"],
      "mock_original_cache_unchanged":original_len==guard_original_len==3}
    if not all(checks.values()):raise RuntimeError("Strict EOS mock contract failed")
    return {"scope":"Deterministic loop mock, not Qwen/model execution; excluded from model forward ledger.",
      "checks":checks,"passed":True,"EOS_case":eos,"cap_case":guard}


def summary(cases,basis,status,started,manifest,runner):
    complete=[r for r in cases if r.get("primary_complete")]
    out={"status":status,"elapsed_seconds":time.monotonic()-started,
      "planned_main_case_order":manifest.get("executed_main_order",[]),"complete_main_ids":[r["case_id"] for r in complete],
      "main_started":len(cases),"main_complete":len(complete),"basis_complete":sum(r.get("complete",False) for r in basis),
      "planned_basis_ids":manifest.get("basis_order",[]),"basis_results":[],"methods":{},
      "primary_denominator":"Complete four-method cases; no cap/parse/score-based exclusion within a complete case.",
      "grading":"Frozen parser numeric_correct; eos_and_correct is separately reported; no runtime correctness checker.",
      "experiment_scope":LIMITS}
    for method in METHODS:
        rows=[r["methods"][method] for r in complete]
        out["methods"][method]={"n":len(rows),"numeric_correct":sum(r["grade"]["numeric_correct"] for r in rows),
          "eos_and_correct":sum(r["grade"]["eos_and_correct"] for r in rows),
          "eos":sum(r["free"]["eos_reached"] for r in rows),"hit_cap":sum(r["free"]["hit_safety_cap"] for r in rows),
          "unparsed":sum(r["grade"]["parsed_value"] is None for r in rows),
          "generated_tokens":sum(r["free"]["new_tokens"] for r in rows)}
        out["methods"][method]["by_group"]={}
        for group in ("E","C","W"):
            group_rows=[r["methods"][method] for r in complete if r["hidden_evaluation_not_prompted"]["group"]==group]
            out["methods"][method]["by_group"][group]={"n":len(group_rows),
              "numeric_correct":sum(r["grade"]["numeric_correct"] for r in group_rows),
              "eos_and_correct":sum(r["grade"]["eos_and_correct"] for r in group_rows),
              "eos":sum(r["free"]["eos_reached"] for r in group_rows),
              "hit_cap":sum(r["free"]["hit_safety_cap"] for r in group_rows),
              "unparsed":sum(r["grade"]["parsed_value"] is None for r in group_rows),
              "generated_tokens":sum(r["free"]["new_tokens"] for r in group_rows)}
    for r in basis:
        if r.get("complete"):out["basis_results"].append({"basis_id":r["basis_id"],"kind":r["kind"],
            "grade":r["grade"],"stop_reason":r["free"]["stop_reason"],"new_tokens":r["free"]["new_tokens"],
            "linked_case_ids":r["rendering"]["provenance"]["linked_case_ids_not_prompted"]})
    if runner:
        out["actual_forward_cost"]=cost(runner.forward_ledger)
        peaks=[r["peak_allocated_bytes"] for r in runner.timing if r["peak_allocated_bytes"] is not None]
        out["observed_postload_peak_allocated_bytes"]=max(peaks) if peaks else None
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",required=True);ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--data",type=Path);ap.add_argument("--adapter-path");ap.add_argument("--base-path");ap.add_argument("--parser-path")
    ap.add_argument("--device",default="cuda:0");ap.add_argument("--standalone-gpu")
    ap.add_argument("--cpu-interface-check",action="store_true");ap.add_argument("--runtime-dir",type=Path)
    ap.add_argument("--max-seconds",type=int,default=270);ap.add_argument("--seed",type=int,default=20261106)
    args=ap.parse_args()
    if not 1<=args.max_seconds<=270:ap.error("max-seconds must be 1..270; no extension")
    started=time.monotonic();args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/"manifest.json").exists():raise RuntimeError("Use a fresh run directory; no overwrite/retry")
    manifest={};cases=[];basis=[];runner=None;status="STARTED";progress={"stage":"startup"};finished=threading.Event()
    def watchdog():
        if not finished.wait(args.max_seconds):
            write_json(args.output/"deadline.json",{"status":"HARD_DEADLINE","elapsed_seconds":time.monotonic()-started,
              "progress":progress.copy(),"partial_scope":"Only completed synchronized forwards in ledger; interrupted work remains in wall time."})
            if runner is not None:write_json(args.output/"forward_ledger_at_deadline.json",list(runner.forward_ledger))
            os._exit(124)
    threading.Thread(target=watchdog,daemon=True).start()
    def remaining():return args.max_seconds-(time.monotonic()-started)
    def save():
        write_json(args.output/"summary.json",summary(cases,basis,status,started,manifest,runner))
        if runner:
            write_json(args.output/"forward_ledger.json",runner.forward_ledger)
            write_json(args.output/"stage_timings.json",runner.timing)
    try:
        base,basepath=load_module(dependency(args.base_path,"p0_base_frozen.py","direction_selection_20261105/real_model_p0.py"),"quality_base",BASE_SHA)
        adapter,adapterpath=load_module(dependency(args.adapter_path,"prepare_cpu_input_adapter.py","phase5_prototype_20261106/prepare_cpu_input_adapter.py"),"quality_adapter",ADAPTER_SHA)
        grader,graderpath=load_module(dependency(args.parser_path,"frozen_answer_extractor.py","next_design_20261105/frozen_answer_extractor.py"),"quality_parser",PARSER_SHA)
        data_path=args.data or Path(__file__).resolve().parent.parent/"next_design_20261105/P05_topology_cases_v2.json"
        if sha(data_path)!=DATA_SHA:raise RuntimeError("Frozen topology-v2 data mismatch")
        prep_start=time.monotonic();data=adapter.prepare_dataset(data_path);prep_seconds=time.monotonic()-prep_start
        if data["hash"]!=DATASET_HASH or tuple(data["selected_order"])!=ORDER or tuple(data["methods"])!=METHODS:
            raise RuntimeError("Prepared data/messages mismatch")
        if args.device!="cpu" and (not args.standalone_gpu or not args.standalone_gpu.startswith("GPU-")):
            raise RuntimeError("Quality real worker requires one explicit full GPU UUID; no numeric/PBS auto-selection")
        binding=base.bind_device(args)
        if args.runtime_dir:sys.path.insert(0,str(args.runtime_dir.resolve(strict=True)))
        global torch,np
        import torch as tm
        import numpy as nm
        import transformers
        torch,np=tm,nm;base.torch,base.np=torch,np
        if transformers.__version__!="4.55.2":raise RuntimeError("All interface/real controls require HF4.55.2")
        if args.cpu_interface_check:
            if args.device!="cpu" or args.model!="tiny-random":raise ValueError("CPU requires cpu/tiny-random")
        elif torch.__version__.split("+")[0] not in {"2.8.0","2.4.1"}:
            raise RuntimeError("Real requires HF4.55.2 and torch2.8.0/2.4.1")
        torch.set_num_threads(min(4,os.cpu_count() or 1));torch.manual_seed(args.seed)
        device=torch.device(binding["device"])
        selected=[c for c in data["cases"] if not args.cpu_interface_check or c["case_id"] in CPU_CASES]
        job_specs=[]
        # Basis-first order is frozen; exact P/(P,R) dedup mapping is retained.
        for item in data["basis"]:
            job_specs.append(("basis",item,None,adapter.render_prompt(item,None)))
        for item in selected:
            for method in METHODS:job_specs.append(("main",item,method,adapter.render_prompt(item,method)))
        manifest={"schema_version":"phase5_quality_one_shot_v1","source_sha256":sha(__file__),
          "adapter_source_sha256":ADAPTER_SHA,"base_source_sha256":BASE_SHA,"parser_sha256":PARSER_SHA,
          "input_sha256":DATA_SHA,"prepared_dataset_hash":DATASET_HASH,"dependencies":{
             "base":str(basepath),"adapter":str(adapterpath),"parser":str(graderpath),"data":str(data_path)},
          "versions":{"python":sys.version,"torch":torch.__version__,"transformers":transformers.__version__},
          "binding":binding,"interface_only":args.cpu_interface_check,"quality_guard":8 if args.cpu_interface_check else 512,
          "greedy":True,"stopping":"Configured EOS only; safety cap separate. No integer-newline or parse-based stop.",
          "executed_main_order":[c["case_id"] for c in selected],"basis_order":[b["basis_id"] for b in data["basis"]],
          "method_order":list(METHODS),"execution_order":"six basis first, then each complete main case's four methods",
          "source_selection_scope":data["scope"],"dedupe_map":data["dedupe_map"],
          "shared_preparation_seconds":prep_seconds,"shared_preparation_scope":"Actual input preparation once; separate from per-request G recheck.",
          "hard_limit_seconds":args.max_seconds,"limitations":LIMITS,"no_runtime_derived_checker":True,
          "model_input_whitelist":"Only adapter.render_prompt()['messages']; never serialize whole case/controller/hidden evaluator.",
          "G_permission":"Exact constant roots x/r only; graph parsing and status bookkeeping. No new y/z evaluation.",
          "no_cache_modifications":True,"controller_forced_decode_tokens":0,"tail_injection":False}
        write_json(args.output/"manifest.json",manifest);write_json(args.output/"prepared_dataset.json",data)
        load_start=time.monotonic();progress["stage"]="model_assets_hash_and_load"
        if args.cpu_interface_check:
            from transformers import Qwen3Config,Qwen3ForCausalLM
            tokenizer=FixtureTokenizer([j[3]["messages"] for j in job_specs])
            cfg=Qwen3Config(vocab_size=tokenizer.vocab_size,hidden_size=32,intermediate_size=64,num_hidden_layers=3,
               num_attention_heads=4,num_key_value_heads=2,head_dim=8,max_position_embeddings=8192,
               attention_dropout=0.0,eos_token_id=4,pad_token_id=0,bos_token_id=1,layer_types=["full_attention"]*3)
            cfg._attn_implementation="eager";model=Qwen3ForCausalLM(cfg).eval().to(device)
            h=hashlib.sha256()
            for name,tensor in model.state_dict().items():h.update(name.encode());h.update(tensor.detach().cpu().numpy().tobytes())
            manifest["model_manifest_sha256"]=h.hexdigest();manifest["model_files"]={"scope":"RANDOM CPU FIXTURE"}
        else:
            from transformers import AutoTokenizer,AutoModelForCausalLM
            assets=base.model_file_manifest(args.model)
            if assets["manifest_sha256"]!=MODEL_SHA:raise RuntimeError("Frozen Qwen3-4B assets mismatch")
            manifest["model_files"]=assets;manifest["model_manifest_sha256"]=assets["manifest_sha256"]
            write_json(args.output/"manifest.json",manifest)
            tokenizer=AutoTokenizer.from_pretrained(args.model,local_files_only=True,trust_remote_code=False)
            model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,trust_remote_code=False,
                torch_dtype=torch.float16,attn_implementation="eager",low_cpu_mem_usage=True).eval().to(device)
        if model.config.model_type!="qwen3" or getattr(model.config,"_attn_implementation",None)!="eager":raise RuntimeError("Qwen3 eager required")
        if any(x!="full_attention" for x in model.config.layer_types):raise RuntimeError("Full-attention only")
        if not args.cpu_interface_check and next(model.parameters()).dtype!=torch.float16:raise RuntimeError("Real worker FP16 dtype mismatch")
        eos=model.generation_config.eos_token_id
        if eos is None:eos=tokenizer.eos_token_id
        eos_ids=set(eos if isinstance(eos,(list,tuple)) else [eos])
        manifest.update(load_and_hash_seconds=time.monotonic()-load_start,parameter_dtype=str(next(model.parameters()).dtype),
          model_config=model.config.to_dict(),tokenizer={"class":type(tokenizer).__name__,"chat_template":tokenizer.chat_template,
          "special_tokens_map":tokenizer.special_tokens_map},eos_token_ids=sorted(eos_ids))
        if device.type=="cuda":manifest["gpu"]={"name":torch.cuda.get_device_name(device),"total_memory_bytes":torch.cuda.get_device_properties(device).total_memory}
        jobs=[]
        for kind,item,method,render in job_specs:
            text=tokenizer.apply_chat_template(render["messages"],tokenize=False,add_generation_prompt=True,enable_thinking=False)
            if not text.endswith("<think>\n\n</think>\n\n"):raise RuntimeError("Nonthinking/no-scaffold template contract failed")
            ids=tokenizer.encode(text,add_special_tokens=False)
            if not ids or len(ids)+manifest["quality_guard"]>model.config.max_position_embeddings:raise RuntimeError("Prompt/context guard exceeded before any inference")
            jid=item["basis_id"] if kind=="basis" else item["case_id"]+"__"+method
            jobs.append({"job_id":jid,"kind":kind,"case_id":item.get("case_id"),"basis_id":item.get("basis_id"),
              "method":method,"messages":render["messages"],"provenance":render["provenance"],
              "prompt_text":text,"prompt_token_ids":ids,"position_ids":list(range(len(ids))),
              "prompt_tokens":len(ids),"item_ref":item})
        # Full evaluator records stay separate; only the message/token projection is an LM input.
        projection=[{k:v for k,v in j.items() if k!="item_ref"} for j in jobs]
        write_json(args.output/"rendered_jobs.json",projection)
        manifest["rendered_jobs_sha256"]=sha(args.output/"rendered_jobs.json")
        manifest["planned_model_outputs_this_run"]=len(jobs);manifest["planned_real_outputs"]=30
        write_json(args.output/"manifest.json",manifest)
        runner=make_runner(base,model,tokenizer,device,args.output,progress)
        if args.cpu_interface_check:
            write_json(args.output/"strict_EOS_mock_control.json",strict_eos_mock_control(base,args.output))
        main_lookup={};cpu_control_done=False
        with torch.inference_mode():
            for job in jobs:
                if remaining()<10:status="QUALITY_PARTIAL_TIME_BUDGET";break
                kind,item,method=job["kind"],job["item_ref"],job["method"]
                jid=job["job_id"];progress.update(stage="request_start",job_id=jid,case_id=job["case_id"],method=method)
                record={"job_id":jid,"kind":kind,"basis_id":job["basis_id"],"case_id":job["case_id"],"method":method,
                   "complete":False,"status":"IN_PROGRESS","rendering":{k:v for k,v in job.items() if k!="item_ref"},
                   "hidden_evaluation_not_prompted":item["hidden_evaluation"],
                   "source_sha256":manifest["source_sha256"],"adapter_sha256":ADAPTER_SHA,"data_sha256":DATA_SHA,
                   "model_manifest_sha256":manifest["model_manifest_sha256"]}
                path=args.output/(jid+".json");write_json(path,record)
                if kind=="basis":basis.append(record)
                else:
                    cid=item["case_id"]
                    if cid not in main_lookup:
                        case_record={"case_id":cid,"methods":{},"primary_complete":False,
                          "hidden_evaluation_not_prompted":item["hidden_evaluation"]}
                        main_lookup[cid]=case_record;cases.append(case_record)
                        write_json(args.output/(cid+".json"),case_record)
                save()  # A deadline inside the first request still leaves started/partial accounting.
                begin=time.monotonic();start_ledger=len(runner.forward_ledger)
                if kind=="main":
                    gate_start=time.monotonic();controller=adapter.build_controller(item["visible"])
                    record["G_cpu_seconds"]=time.monotonic()-gate_start
                    if adapter.digest(controller)!=adapter.digest(item["controller"]):raise RuntimeError("Visible-only controller drift")
                    if controller["derived_arithmetic_evaluations"]!=0:raise RuntimeError("Derived checker unexpectedly used")
                    record["G_and_bookkeeping"]={"gate":controller["gate"],"roots":controller["current_roots"],
                       "root_verifier_calls":controller["root_verifier_calls"],"derived_arithmetic_evaluations":0,
                       "old_derived_statuses":controller["old_derived_records"],"final_commit":controller["deterministic_final_commit"],
                       "scope":"Root G + symbolic input bookkeeping; not model proposal validation."}
                else:record["G_cpu_seconds"]=0.0;record["G_and_bookkeeping"]={"scope":"Not supplied to basis; no G/B input."}
                compile_start=time.monotonic();fresh=adapter.render_prompt(item,method)
                text=tokenizer.apply_chat_template(fresh["messages"],tokenize=False,add_generation_prompt=True,enable_thinking=False)
                ids=tokenizer.encode(text,add_special_tokens=False)
                record["prompt_compile_and_tokenize_seconds"]=time.monotonic()-compile_start
                if ids!=job["prompt_token_ids"] or fresh["messages"]!=job["messages"]:raise RuntimeError("Frozen prompt projection drift")
                out,record["prefill_timing"]=runner.timed("normal_prompt_prefill",lambda:runner.forward(ids,[1]*len(ids),0),job_id=jid,case_id=job["case_id"],method=method)
                cache=out.past_key_values;logits=out.logits[0,-1].float().cpu()
                record["prefix_cache_metadata"]=base.cache_metadata(cache)
                record["initial_logits"]={"vocab_size":len(logits),"min":float(logits.min()),"max":float(logits.max()),
                  "argmax":int(logits.argmax()),"float32_sha256":hashlib.sha256(logits.numpy().tobytes()).hexdigest()}
                before=None
                if args.cpu_interface_check and not cpu_control_done:
                    repeated,no_time=runner.timed("cpu_same_prompt_replay",lambda:runner.forward(ids,[1]*len(ids),0),job_id=jid,case_id=job["case_id"],method=method)
                    delta=base.distribution_metrics(logits,repeated.logits[0,-1].float().cpu())
                    if delta["logit_max_abs"]>1e-6:raise RuntimeError("CPU same-prompt no-op failed")
                    before=[(k.clone(),v.clone()) for k,v in base.cache_pairs(cache)]
                    record["CPU_interface_controls"]={"same_prompt_last_logits":delta,"timing":no_time,"scope":"Random CPU fixture only"}
                def partial(tokens,status_name):
                    record["partial_free"]={"token_ids":list(tokens),"text":tokenizer.decode(tokens,skip_special_tokens=True),
                       "new_tokens":len(tokens),"status":status_name,"not_final_graded":True}
                    write_json(path,record)
                generated,record["generation_timing"]=runner.timed("natural_EOS_greedy",lambda:runner.natural_greedy(ids,cache,logits,eos_ids,manifest["quality_guard"],partial),job_id=jid,case_id=job["case_id"],method=method)
                record["request_seconds_before_posthoc_grader"]=time.monotonic()-begin
                if before is not None:
                    delta=max(float((a-b).abs().max()) for aa,bb in zip(before,base.cache_pairs(cache)) for a,b in zip(aa,bb))
                    record["CPU_interface_controls"]["original_cache_after_generation_max_abs"]=delta
                    record["CPU_interface_controls"]["passed"]=delta==0.0
                    if delta!=0.0:raise RuntimeError("CPU original cache was mutated")
                    cpu_control_done=True
                grade_start=time.monotonic();extracted=grader.extract_answer(generated["text"])
                target=item["hidden_evaluation"]["required_final_value"]
                numeric_correct=extracted["value"]==target if extracted["value"] is not None else False
                record.update(free=generated,grade={"parsed_value":extracted["value"],"numeric_correct":numeric_correct,
                    "eos_and_correct":numeric_correct and generated["eos_reached"],"frozen_extraction":extracted,
                    "scope":"Posthoc final-value grading only; never used to stop or select model output."},
                    posthoc_grader_seconds=time.monotonic()-grade_start,complete=True,status="COMPLETE",
                    actual_forward_cost=cost(runner.forward_ledger[start_ledger:]))
                record.pop("partial_free",None);write_json(path,record)
                if kind=="main":
                    main_lookup[item["case_id"]]["methods"][method]=record
                    main_lookup[item["case_id"]]["primary_complete"]=set(main_lookup[item["case_id"]]["methods"])==set(METHODS)
                    write_json(args.output/(item["case_id"]+".json"),main_lookup[item["case_id"]])
                status="QUALITY_RUNNING";save()
                print(json.dumps({"job_id":jid,"stop":generated["stop_reason"],"tokens":generated["new_tokens"],
                    "parsed":extracted["value"],"remaining_seconds":remaining()},ensure_ascii=True),flush=True)
                del out,cache,logits
            else:status="CPU_INTERFACE_ONLY_COMPLETE" if args.cpu_interface_check else "QUALITY_COMPLETE"
        save()
        result=summary(cases,basis,status,started,manifest,runner)
        text=["# Phase5 quality: "+status,"",f"Complete four-method cases: {result['main_complete']}; basis complete: {result['basis_complete']}.",
          "","One-shot prompt prototypes, no runtime derived-value checker. Guard/EOS and parser score are separate.","",
          "| Method | N | Numeric correct | EOS and correct | Hit cap | Unparsed |","|---|---:|---:|---:|---:|---:|"]
        text.extend(f"| {m} | {r['n']} | {r['numeric_correct']} | {r['eos_and_correct']} | {r['hit_cap']} | {r['unparsed']} |" for m,r in result["methods"].items())
        text += ["","## Scope",""]+["- "+x for x in LIMITS]
        if args.cpu_interface_check:text += ["","Random tiny CPU fixture/chunk tokenizer only; no trained-model quality evidence."]
        (args.output/"RESULT.md").write_text("\n".join(text)+"\n",encoding="utf-8")
        return 0
    except Exception as exc:
        status="QUALITY_EXECUTION_ERROR"
        write_json(args.output/"error.json",{"error":str(exc),"traceback":traceback.format_exc(),"progress":progress,
           "elapsed_seconds":time.monotonic()-started})
        save();traceback.print_exc();return 1
    finally:finished.set()


if __name__=="__main__":raise SystemExit(main())
