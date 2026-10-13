from __future__ import annotations

from collections import deque
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time

REFLECTION = re.compile(r"\b(wait|alternatively|reconsider|re-evaluat\w*|let me (?:check|verify)|double.check|however|but wait)\b", re.I)


def digest_ids(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def stable_seed(*parts):
    return int.from_bytes(hashlib.sha256(":".join(map(str, parts)).encode()).digest()[:8], "big") % (2**31)


def uniform(seed, phase, position):
    value = int.from_bytes(hashlib.sha256(f"{seed}:{phase}:{position}".encode()).digest()[:8], "big")
    return (value + 0.5) / 2**64


def escaped(text, index):
    count=0
    for previous in range(index-1,-1,-1):
        if text[previous]!='\\':break
        count+=1
    return count%2==1


def brace_balance(text):
    return sum((1 if char=='{' else -1) for i,char in enumerate(text)
               if char in '{}' and not escaped(text,i))


def boundary(text):
    """Conservative observed paragraph boundary; no future tokens are inspected."""
    if not text.endswith("\n\n"):
        return False
    return (brace_balance(text)==0
            and text.count(r"\[") == text.count(r"\]")
            and text.count("$$") % 2 == 0
            and len(re.findall(r"(?<![\\$])\$(?!\$)",text)) % 2 == 0
            and text.count("```") % 2 == 0)


def cheap_features(ids, text, statistics, kind):
    start = time.perf_counter()
    window = list(statistics)[-10:]
    ngrams = [tuple(ids[i:i+4]) for i in range(max(0, len(ids)-511), max(0, len(ids)-3))]
    result = {
        "length": len(ids), "log_length": math.log1p(len(ids)),
        "entropy": sum(x[0] for x in window) / max(1,len(window)),
        "margin": sum(x[1] for x in window) / max(1,len(window)),
        "logprob": sum(x[2] for x in window) / max(1,len(window)),
        "reflection_count": len(REFLECTION.findall(text)),
        "repeat4": 1 - len(set(ngrams)) / max(1,len(ngrams)) if ngrams else 0.0,
        "steps": text.count("\n\n"), "reflective": int(kind == "reflective"),
    }
    return result, 1000 * (time.perf_counter()-start)


class Engine:
    def __init__(self, model_path, attn="sdpa", dtype="float16"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.set_num_threads(4)
        torch.manual_seed(20261008)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
            torch_dtype=getattr(torch,dtype), attn_implementation=attn).to("cuda").eval()
        self.device = self.model.device
        self.endthink = self.tok.convert_tokens_to_ids("</think>")
        eos = self.model.generation_config.eos_token_id
        self.eos = set(eos if isinstance(eos,list) else [eos])
        self.answer_cue = "Final answer: \\boxed{"
        self.suffix = self.tok.encode("</think>\n\n"+self.answer_cue, add_special_tokens=False)
        self.model_path = model_path
        self.attn = attn
        self.model_ms = 0.0
        self.feature_gpu_ms = 0.0

    def prompt(self, question):
        return self.tok.apply_chat_template([{"role":"user", "content":question +
            "\nPlease reason step by step, and put your final answer within \\boxed{}."}],
            tokenize=True, add_generation_prompt=True, enable_thinking=True)

    def forward(self, ids, cache=None):
        torch = self.torch
        x=torch.tensor([ids], device=self.device,dtype=torch.long)
        torch.cuda.synchronize(); start=time.perf_counter()
        with torch.inference_mode():
            output=self.model(input_ids=x,past_key_values=cache,use_cache=True,logits_to_keep=1)
        torch.cuda.synchronize(); self.model_ms +=1000*(time.perf_counter()-start)
        return output.past_key_values, output.logits[0,-1,:]

    def sample(self, logits, seed, phase, position, stats=True):
        torch=self.torch
        if not torch.isfinite(logits).all():
            raise RuntimeError("Nonfinite generation logits")
        start=time.perf_counter()
        z=logits.float()
        if stats:
            lp=z.log_softmax(-1); probs=lp.exp()
            entropy=-(probs*lp).sum()
            top_raw=torch.topk(probs,2).values
        values, indices=torch.topk(z/0.6,20)
        sampling=values.softmax(-1)
        remove=sampling.cumsum(-1)-sampling > 0.95
        sampling=sampling.masked_fill(remove,0)
        sampling=sampling/sampling.sum()
        index=int(torch.searchsorted(sampling.cumsum(-1),torch.tensor(uniform(seed,phase,position),device=self.device)).clamp(max=19).item())
        token=int(indices[index].item())
        info=(float(entropy.item()),float((top_raw[0]-top_raw[1]).item()),float(lp[token].item())) if stats else None
        self.feature_gpu_ms +=1000*(time.perf_counter()-start) if stats else 0
        return token,info

    def decode(self, prefix, max_tokens, seed, phase="think", offset=0,
               until="think", checkpoint_hook=None, capture=False, initial=None):
        """A serial cache decoder. Every sampled token is consumed exactly once."""
        torch=self.torch; torch.cuda.synchronize(); start=time.perf_counter()
        model_before=self.model_ms; feature_before=self.feature_gpu_ms
        if initial is None:
            cache,logits=self.forward(prefix)
        else:
            cache,logits=initial
        prefill_ms=self.model_ms-model_before
        tokens=[];text="";history=deque(maxlen=10);points=[];past_text=""
        paused_ms=0.0;paused_model_ms=0.0;paused_feature_ms=0.0
        last_checkpoint=-128;stop_reason="limit"; last_kind="natural";answer_depth=1
        for i in range(max_tokens):
            token,stat=self.sample(logits,seed,phase,offset+i,stats=capture)
            tokens.append(token)
            piece=self.tok.decode([token],skip_special_tokens=False)
            text+=piece
            if until=="boxed":
                answer_depth=1+brace_balance(text)
            if stat is not None:
                history.append(stat)
            cache,logits=self.forward([token],cache)
            if until=="boxed" and answer_depth<=0:
                stop_reason="answer_box_complete";break
            if token in self.eos:
                stop_reason="eos";break
            if until in ["think","step"] and token==self.endthink:
                stop_reason="natural_end";break
            natural=boundary(text)
            completed_paragraph=text.split("\n\n")[-2] if natural else ""
            kind="reflective" if REFLECTION.search(completed_paragraph) else "natural"
            eligible=natural and i+1>=128 and i+1-last_checkpoint>=128
            if (capture or checkpoint_hook is not None) and eligible:
                features,feature_ms=cheap_features(tokens,text,history,kind) if capture else ({"length":len(tokens)},0.0)
                point={"offset":i+1,"kind":kind,"features":features,"feature_ms":feature_ms,
                       "prefix_hash":digest_ids(prefix+tokens),"elapsed_ms":1000*(time.perf_counter()-start)-paused_ms,
                       "model_ms_sofar":self.model_ms-model_before-paused_model_ms}
                points.append(point); last_checkpoint=i+1;last_kind=kind
                if checkpoint_hook is not None:
                    pause_start=time.perf_counter();pause_model=self.model_ms;pause_feature=self.feature_gpu_ms
                    outcome=checkpoint_hook(point,prefix+tokens,cache,logits)
                    if isinstance(outcome,dict) and outcome.get("offline_branching"):
                        paused_ms+=1000*(time.perf_counter()-pause_start)
                        paused_model_ms+=self.model_ms-pause_model
                        paused_feature_ms+=self.feature_gpu_ms-pause_feature
                        outcome=False
                    elif isinstance(outcome,dict):
                        if outcome.get("disable_capture"):
                            capture=False
                        outcome=outcome.get("stop",False)
                    if outcome:
                        stop_reason="policy_stop";break
            if until=="step" and natural and i+1>=16:
                stop_reason="step_end";break
            past_text=text
        torch.cuda.synchronize()
        return {"ids":tokens,"text":text,"tokens":len(tokens),"ms":1000*(time.perf_counter()-start)-paused_ms,
            "offline_branching_ms":paused_ms,"model_ms":self.model_ms-model_before-paused_model_ms,"prefill_model_ms":prefill_ms,
            "feature_gpu_ms":self.feature_gpu_ms-feature_before-paused_feature_ms,
            "stop_reason":stop_reason,"length_censored":stop_reason=="limit","checkpoints":points,
            "cache":cache,"logits":logits}

    def answer(self, prefix, seed, natural_closed=False, initial=None):
        self.torch.cuda.synchronize();start=time.perf_counter();model_before=self.model_ms
        if not natural_closed:
            suffix=self.suffix
            begin=self.tok.convert_tokens_to_ids("<think>")
            if begin not in prefix:
                suffix=self.tok.encode("<think>\n",add_special_tokens=False)+suffix
        else:
            # Natural close and forced close use identical delimiter + two newlines.
            suffix=self.tok.encode("\n\n"+self.answer_cue,add_special_tokens=False)
        prefix=prefix+suffix
        had_cache=initial is not None
        if initial is not None:
            initial=self.forward(suffix,initial[0])
        else:
            initial=self.forward(prefix)
        prefill_ms=self.model_ms-model_before
        first_lp=initial[1].float().log_softmax(-1)
        first_entropy=float(-(first_lp.exp()*first_lp).sum().item())
        result=self.decode(prefix,192,seed,phase="answer",until="boxed",initial=initial)
        result["generated_text"]=result["text"]
        result["text"]=r"\boxed{"+result["text"]
        self.torch.cuda.synchronize();result["ms"]=1000*(time.perf_counter()-start)
        result["model_ms"]=self.model_ms-model_before
        result["prefill_model_ms"]=prefill_ms
        result["cached_prefix"]=had_cache
        result["eat_entropy"]=first_entropy
        result["control_prefix_input_tokens"]=len(suffix)
        result["answer_prefix_hash"]=digest_ids(prefix)
        return result

    def entropy_probe(self, cache, logits):
        self.torch.cuda.synchronize();start=time.perf_counter();before=self.model_ms
        original_length=cache.get_seq_length()
        try:
            _,after=self.forward(self.suffix,cache)
            lp=after.float().log_softmax(-1)
            entropy=float(-(lp.exp()*lp).sum().item())
        finally:
            cache.crop(original_length)
        self.torch.cuda.synchronize()
        return {"entropy":entropy,"ms":1000*(time.perf_counter()-start),"model_ms":self.model_ms-before,
                "probe_input_tokens":len(self.suffix),"cache_strategy":"append_then_crop"}


def public(result):
    return {k:v for k,v in result.items() if k not in ["cache","logits"]}


def last_box(text):
    boxes=[]
    for match in re.finditer(r"\\boxed\s*\{",text):
        start=match.end();depth=1
        for i in range(start,len(text)):
            if text[i]=="{" and not escaped(text,i):depth+=1
            elif text[i]=="}" and not escaped(text,i):depth-=1
            if depth==0:
                boxes.append(text[start:i]);break
    return boxes[-1] if boxes else None


def normalize_math_surface(text):
    """Unambiguous numeric products and common missing TeX log command only."""
    numeric_group=r'\([+-]?\d+(?:\.\d+)?\)'
    text=re.sub('('+numeric_group+r')\s*(?='+numeric_group+')',lambda m:m.group(1)+r'\cdot',text)
    return re.sub(r'(?<![A-Za-z\\])log(?=\s*[_({])',lambda m:r'\log',text)


def grade(text, gold):
    """Keep parse failure distinct; mathematical equality uses Math-Verify."""
    from math_verify import parse, verify, LatexExtractionConfig, ExprExtractionConfig
    configs=(LatexExtractionConfig(), ExprExtractionConfig())
    try:
        gold_surface=normalize_math_surface(str(gold))
        target=parse(r"\boxed{"+gold_surface+"}",extraction_config=configs,parsing_timeout=5)
        boxed=last_box(text)
        if boxed is None and not re.search(r"(?:final answer|answer is)\s*[:=]?",text,re.I):
            return {"correct":0,"parse_status":"parse_failed","format_ok":False,"boxed":None,"reason":"missing_complete_final_answer"}
        surface=normalize_math_surface(boxed if boxed is not None else text)
        candidate=parse(r"\boxed{"+surface+"}" if boxed is not None else surface,extraction_config=configs,parsing_timeout=5)
        status="ok" if candidate and not isinstance(candidate[0],str) else "fallback_only" if candidate else "parse_failed"
        correct=int(bool(candidate) and bool(target) and verify(target,candidate,timeout_seconds=5))
        normalization='unambiguous_math_surface' if surface!=(boxed if boxed is not None else text) or gold_surface!=str(gold) else None
        if not correct and candidate and target:
            from sympy import MatrixBase,Tuple
            gold_object=target[0];prediction=candidate[0]
            if isinstance(gold_object,MatrixBase) and 1 in gold_object.shape and len(gold_object)>1:
                if isinstance(prediction,MatrixBase) and 1 in prediction.shape:
                    coordinates=list(prediction)
                elif isinstance(prediction,(Tuple,tuple,list)):
                    coordinates=list(prediction)
                else:coordinates=None
                if coordinates is not None and len(coordinates)==len(gold_object):
                    correct=int(all(verify([expected],[actual],timeout_seconds=5)
                                    for expected,actual in zip(list(gold_object),coordinates)))
                    normalization='ordered_vector_coordinates'
        return {"correct":correct,"parse_status":status,"boxed":boxed,"format_ok":boxed is not None,
            "parsed":str(candidate),"gold_parsed":str(target),"normalization":normalization,"normalized_surface":surface,"scorer_version":"math_verify_0.9_surface_vector_v3"}
    except Exception as e:
        return {"correct":0,"parse_status":"grader_error","error":type(e).__name__+": "+str(e)}


def append_jsonl(path, row):
    with Path(path).open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n");f.flush()
