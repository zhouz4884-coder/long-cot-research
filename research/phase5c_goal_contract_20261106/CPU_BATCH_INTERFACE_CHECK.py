"""CPU-only tests of the exact paired_readout.generate_batch implementation.

Synthetic prompts only. No real bank, evaluation file, Gold, model weights or GPU.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import string
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "p05_design_review_20261105/runtime4552"
sys.path.insert(0, str(RUNTIME.resolve(strict=True)))


class FixtureTokenizer:
    pad_token_id = 0
    bos_token_id = 1
    eos_token_id = 2
    def __init__(self):
        self.encoder = {c: i+3 for i,c in enumerate(sorted(set(string.printable)))}
        self.decoder = {v:k for k,v in self.encoder.items()}
        self.vocab_size = max(self.decoder)+1
    def encode(self, text, add_special_tokens=False):
        if add_special_tokens: raise ValueError("No additional specials")
        return [self.encoder[c] for c in text]
    def decode(self, ids, skip_special_tokens=False):
        return "".join(self.decoder.get(int(i), "") for i in ids
                       if not (skip_special_tokens and int(i) in (0,1,2)))
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        assert not tokenize and add_generation_prompt and not enable_thinking
        return "".join("<|im_start|>"+m["role"]+"\n"+m["content"]+"<|im_end|>\n" for m in messages)+"<|im_start|>assistant\n<think>\n\n</think>\n\n"


def main():
    source = HERE/"paired_readout.py"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    spec=importlib.util.spec_from_file_location("paired_readout_cpu_contract",source)
    paired=importlib.util.module_from_spec(spec);spec.loader.exec_module(paired)
    import torch
    import transformers
    from transformers import Qwen3Config,Qwen3ForCausalLM
    assert transformers.__version__=="4.55.2"
    torch.set_num_threads(2);torch.manual_seed(20261106)
    device=torch.device("cpu");tok=FixtureTokenizer();checks=[]
    def ok(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    def row(name,text,method="CPU",prefix=""):
        ids=tok.encode(text)
        return {"job_id":name,"rank":1,"bank_id":"CPU-synthetic","method":method,
                "prompt_ids":ids,"prompt_tokens":len(ids),"scoring_prefix":prefix,
                "shared_packet_sha256":None,"contract_hash":"CPU-only"}
    cfg=Qwen3Config(vocab_size=tok.vocab_size,hidden_size=32,intermediate_size=64,
        num_hidden_layers=3,num_attention_heads=4,num_key_value_heads=2,head_dim=8,
        max_position_embeddings=512,attention_dropout=0.0,eos_token_id=2,pad_token_id=0,
        bos_token_id=1,layer_types=["full_attention"]*3)
    cfg._attn_implementation="sdpa"
    model=Qwen3ForCausalLM(cfg).eval().to(device)
    ok("target_CPU_transformers_4552_SDPA",model.config._attn_implementation=="sdpa")
    a,b,c=row("A","pqr"),row("B","stuvw"),row("C","ABCDEFG")
    audits=[];first_cache_refs=[]
    def audit_hook(mod,args,kwargs):
        value=kwargs.get("input_ids",args[0] if args else None)
        cache=kwargs.get("past_key_values")
        pos=kwargs.get("position_ids")
        audits.append({"sequence":value.shape[1],"batch":value.shape[0],
                       "mask":kwargs["attention_mask"].detach().cpu().tolist(),
                       "position_ids":None if pos is None else pos.detach().cpu().tolist(),
                       "past_len_before":cache.get_seq_length() if cache is not None else 0,
                       "cache_object":cache})
    handle=model.register_forward_pre_hook(audit_hook,with_kwargs=True)
    run_logs=[]
    def run(rows):
        before=len(audits)
        result,ledger=paired.generate_batch(model,tok,rows,device,8)
        calls=audits[before:]
        ok("fresh_cache_entry_"+str(len(run_logs)),calls[0]["past_len_before"]==0)
        if calls[0]["cache_object"] is not None:first_cache_refs.append(calls[0]["cache_object"])
        run_logs.append({"rows":[r["job_id"] for r in rows],"outputs":result,"ledger":ledger,
                         "first_mask":calls[0]["mask"],"first_position_ids":calls[0]["position_ids"]})
        return result,ledger
    batch,ledger=run([a,b]);single_a,_=run([a]);single_b,_=run([b])
    ok("left_pad_rowA_matches_single",batch[0]["token_ids"]==single_a[0]["token_ids"])
    ok("left_pad_rowB_matches_single",batch[1]["token_ids"]==single_b[0]["token_ids"])
    ok("actual_left_padding",run_logs[0]["first_mask"]==[[0,0,1,1,1],[1,1,1,1,1]])
    if run_logs[0]["first_position_ids"] is not None:
        ok("semantic_positions_after_padding",run_logs[0]["first_position_ids"][0][-3:]==[0,1,2]
           and run_logs[0]["first_position_ids"][1]==[0,1,2,3,4])
    changed,_=run([a,c]);reversed_rows,_=run([b,a]);repeat,_=run([a,b])
    ok("changing_other_row_does_not_change_A",changed[0]["token_ids"]==batch[0]["token_ids"])
    ok("row_permutation_invariance",reversed_rows[1]["token_ids"]==batch[0]["token_ids"] and reversed_rows[0]["token_ids"]==batch[1]["token_ids"])
    ok("repeated_batch_same_outputs",[r["token_ids"] for r in repeat]==[r["token_ids"] for r in batch])
    ok("nonvacuous_fresh_cache_object_observation",len(first_cache_refs)==len(run_logs))
    ok("cache_objects_distinct_across_calls",all(a is not b for i,a in enumerate(first_cache_refs) for b in first_cache_refs[i+1:]))
    ok("padded_and_unpadded_accounting",ledger["padded_prefill_tokens"]==10 and ledger["unpadded_prompt_tokens"]==8)
    ok("physical_forward_ledger_count",ledger["physical_forward_input_tokens"]==sum(c["physical_input_tokens"] for c in ledger["forward_calls"]))
    handle.remove()
    # Uncached replay measures decision margins, independently of batch caches.
    # These extra verification forwards are not added to generate_batch ledgers.
    margins=[]
    with torch.inference_mode():
        for r,generated in zip((a,b),batch):
            for step,token in enumerate(generated["token_ids"]):
                ids=torch.tensor([r["prompt_ids"]+generated["token_ids"][:step]])
                logits=model(input_ids=ids,attention_mask=torch.ones_like(ids),use_cache=False,logits_to_keep=1).logits[0,-1].float()
                top=torch.topk(logits,2).values
                margins.append(float(top[0]-top[1]))
                ok("uncached_argmax_"+r["job_id"]+"_"+str(step),int(logits.argmax())==token)
    ok("fixture_not_near_tie",min(margins)>1e-5)

    class MockModel(torch.nn.Module):
        """Deterministic batch padding/stop oracle, not a Qwen quality model."""
        def __init__(self,sequences):
            super().__init__();self.sequences=sequences
            self.generation_config=SimpleNamespace(eos_token_id=2)
            self.fresh_generate_calls=[]
        def forward(self,input_ids,attention_mask=None,past_key_values=None,**kwargs):
            return SimpleNamespace(logits=torch.zeros((input_ids.shape[0],1,tok.vocab_size)))
        def generate(self,input_ids,attention_mask,max_new_tokens,do_sample,use_cache,eos_token_id,pad_token_id,return_dict_in_generate):
            self.fresh_generate_calls.append(True)
            self(input_ids=input_ids,attention_mask=attention_mask,past_key_values=None)
            length=min(max(len(s) for s in self.sequences),max_new_tokens)
            generated=[]
            for seq in self.sequences:
                seq=seq[:length]
                generated.append(seq+[pad_token_id]*(length-len(seq)))
            for step in range(1,length):
                self(input_ids=torch.tensor([[seq[step-1]] for seq in generated]),attention_mask=attention_mask,past_key_values=None)
            return torch.cat([input_ids,torch.tensor(generated)],dim=1)
    mock=MockModel([[tok.encoder["x"],2],[tok.encoder[ch] for ch in "abcd"]+[2]])
    mixed,mixed_ledger=paired.generate_batch(mock,tok,[a,b],device,8)
    ok("mock_early_EOS_trimmed",mixed[0]["new_tokens"]==2 and mixed[0]["token_ids"][-1]==2)
    ok("mock_late_EOS_retained",mixed[1]["new_tokens"]==5 and mixed[1]["token_ids"][-1]==2)
    ok("mock_no_finished_row_PAD_scored",tok.pad_token_id not in mixed[0]["token_ids"])
    ok("mock_logical_tokens7",mixed_ledger["logical_generated_tokens"]==7)
    ok("mock_physical_inputs18",mixed_ledger["physical_forward_input_tokens"]==18 and mixed_ledger["padded_prefill_tokens"]==10)
    ok("mock_EOS_rows_not_cap",all(r["eos_reached"] and not r["hit_cap"] for r in mixed))
    capmock=MockModel([[tok.encoder["z"]]*8,[tok.encoder["y"]]*8])
    caprows,_=paired.generate_batch(capmock,tok,[a,b],device,8)
    ok("mock_no_EOS_hits_cap",all(not r["eos_reached"] and r["hit_cap"] and r["new_tokens"]==8 for r in caprows))

    def compile_job(name,prefill,scoring):
        return {"job_id":name,"rank":1,"bank_id":"CPU-synthetic","method":"ForcedBoxCue" if prefill else "FullContinue",
                "messages":[{"role":"user","content":"Return the whole ordered triple."}],
                "assistant_prefill":prefill,"scoring_prefix":scoring,
                "shared_packet_sha256":None,"contract_hash":"CPU-only"}
    ordinary=paired.compile_jobs(tok,[compile_job("normal","","")])[0]
    forced=paired.compile_jobs(tok,[compile_job("forced",r"Final answer: \boxed{",r"\boxed{")])[0]
    ok("forced_prefix_counted_in_prompt",forced["prompt_tokens"]-ordinary["prompt_tokens"]==len(tok.encode(r"Final answer: \boxed{")))
    ok("forced_prefix_is_exact_suffix",forced["prompt_text"]==ordinary["prompt_text"]+r"Final answer: \boxed{")
    tuple_ids=tok.encode("(2,3,4)}")+[2]
    tuplemock=MockModel([tuple_ids])
    tuple_out,tuple_ledger=paired.generate_batch(tuplemock,tok,[forced],device,16)
    ok("forced_complete_tuple_not_cut_at_first_component",tuple_out[0]["answer_text"]==r"\boxed{(2,3,4)}")
    ok("forced_score_prefix_not_generated_tokens",tuple_out[0]["new_tokens"]==len(tuple_ids) and tuple_out[0]["text"]=="(2,3,4)}")
    ok("forced_prompt_in_physical_ledger",tuple_ledger["padded_prefill_tokens"]==forced["prompt_tokens"])
    ok("forced_tuple_EOS_only",tuple_out[0]["eos_reached"] and not tuple_out[0]["hit_cap"])
    ok("source_unchanged_during_check",hashlib.sha256(source.read_bytes()).hexdigest()==source_sha)
    result={"status":"PASS","passed":len(checks),"checks":checks,"paired_readout_source_sha256":source_sha,
            "scope":"Synthetic target-HF CPU random-tiny SDPA and deterministic mocks only; no32-case bank, eval/Gold, real model or GPU.",
            "versions":{"torch":torch.__version__,"transformers":transformers.__version__},
            "random_fixture":{"seed":20261106,"layers":3,"hidden_size":32,"max_new_tokens":8,"backend":"sdpa",
                "minimum_uncached_top2_margin":min(margins),"output_EOS_rows_in_initial_batch":sum(r["eos_reached"] for r in batch),
                "batch_single_equal":True,"all_calls_fresh_cache":True,"observed_fresh_cache_objects":len(first_cache_refs),"run_logs":run_logs},
            "mock_early_late_EOS":{"outputs":mixed,"ledger":mixed_ledger},
            "mock_cap":{"outputs":caprows},
            "mock_forced_tuple":{"output":tuple_out[0],"ledger":tuple_ledger,"mock_limit":16},
            "limitations":["Random fixture is not Qwen3-4B quality or CUDA/FP16 equivalence.",
                "Real tiny EOS coverage is explicitly reported; mixed early/late EOS branch coverage belongs to mock.",
                "Physical forward counts include left padding and finished rows until batch terminates; logical scored outputs stop at each row EOS.",
                "Scoring prefix is supplied input, not generated evidence; exact tuple parser correctness remains a separate grader test."]}
    (HERE/"CPU_BATCH_INTERFACE.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("checks","random_fixture","mock_early_late_EOS","mock_cap","mock_forced_tuple")},ensure_ascii=False,indent=2))
    print("minimum_top2_margin",min(margins))


if __name__=="__main__":main()
