"""Real-model admission checks; failures are retained and block label training."""
import argparse
import copy
import inspect
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import Engine, grade, public, digest_ids, stable_seed, append_jsonl


def main():
    p=argparse.ArgumentParser();p.add_argument("--model",required=True);p.add_argument("--n",type=int,default=24)
    args=p.parse_args();out=Path("results/protocol");out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(x) for x in Path("data/math500_smoke.jsonl").read_text().splitlines()][:args.n]
    e=Engine(args.model); torch=e.torch
    report={"scoring":[],"cache":[],"tokenizer":{},"model":args.model,"n":args.n}
    examples=[(r"\boxed{\frac{1}{2}}","0.5",1),(r"\boxed{3} then corrected: \boxed{4}","4",1),
        (r"\boxed{\sqrt{2}}",r"\sqrt{2}",1),(r"\boxed{3}","4",0),("no answer","4",0),
        (r"\boxed{\frac{2}{3}}",r"\frac{4}{6}",1)]
    for text,gold,expected in examples:
        result=grade(text,gold);result.update(text=text,gold=gold,expected=expected)
        report["scoring"].append(result)
    report["scoring_pass"]=all(x["correct"]==x["expected"] and x["parse_status"]!="grader_error" for x in report["scoring"])
    report["tokenizer"]={"endthink":e.endthink,"skipped":e.tok.decode([e.endthink],skip_special_tokens=True),"retained":e.tok.decode([e.endthink],skip_special_tokens=False)}
    if not report["scoring_pass"]:
        (out/"checks.json").write_text(json.dumps(report,indent=2));raise SystemExit("Scoring gate failed")
    # Cache replay, chunked restoration, same-state cloning, and controlled sampling.
    for row in rows[:5]:
        prompt=e.prompt(row["question"])
        content=e.decode(prompt,128,stable_seed(row["problem_id"],"prefix"),until="eos")
        prompt=prompt+content["ids"]
        split=max(1,len(prompt)//2)
        full_cache,full_logits=e.forward(prompt)
        chunk_cache,_=e.forward(prompt[:split])
        chunk_cache,chunk_logits=e.forward(prompt[split:],chunk_cache)
        absolute=float((full_logits.float()-chunk_logits.float()).abs().max().item())
        probability=float((full_logits.float().softmax(-1)-chunk_logits.float().softmax(-1)).abs().max().item())
        total_variation=float((full_logits.float().softmax(-1)-chunk_logits.float().softmax(-1)).abs().sum().item()/2)
        top=torch.topk(full_logits,20).indices
        top_abs=float((full_logits[top].float()-chunk_logits[top].float()).abs().max().item())
        relative_l2=float((full_logits.float()-chunk_logits.float()).norm().item()/full_logits.float().norm().item())
        seed=stable_seed(row["problem_id"],"cache")
        a=e.decode(prompt,16,seed,until="eos",initial=(full_cache,full_logits))
        b=e.decode(prompt,16,seed,until="eos",initial=(chunk_cache,chunk_logits))
        passed=relative_l2<=0.01 and total_variation<=0.01 and a["ids"]==b["ids"]
        check={"problem_id":row["problem_id"],"prefix_hash":digest_ids(prompt),"max_abs_logit":absolute,
               "max_abs_prob":probability,"total_variation":total_variation,"top20_abs_logit":top_abs,"relative_l2":relative_l2,
               "same_sampled_ids":a["ids"]==b["ids"],"passed":passed,
               "replay_ids":a["ids"],"restored_ids":b["ids"]}
        report["cache"].append(check);print(json.dumps({"cache_check":check}),flush=True)
    report["cache_pass"]=all(x["passed"] for x in report["cache"])
    (out/"checks.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["cache_pass"]:
        raise SystemExit("Cache gate failed; do not train on branch labels")
    # A small, real natural-end/forced-end comparison; all detailed outputs survive.
    finished=set()
    if (out/"ending.jsonl").exists():
        finished={json.loads(x)["problem_id"] for x in (out/"ending.jsonl").read_text().splitlines()}
    for i,row in enumerate(rows):
        if row["problem_id"] in finished:continue
        prompt=e.prompt(row["question"]);seed=stable_seed(20261008,row["problem_id"],0)
        trace=e.decode(prompt,4096,seed,capture=True)
        natural=trace["stop_reason"]=="natural_end"
        thought=prompt+trace["ids"]
        answer=e.answer(thought,seed,natural_closed=natural)
        scoring=grade(answer["text"],row["gold"])
        # Replacing an observed natural delimiter by the identical intervention
        # must produce exactly the same answer prefix and controlled output.
        if natural:
            repeated=e.answer(thought[:-1],seed,natural_closed=False)
            same_ids=answer["ids"]==repeated["ids"]
            same_prefix=answer["answer_prefix_hash"]==repeated["answer_prefix_hash"]
        else:
            repeated=None;same_ids=None;same_prefix=None
        record={"problem_id":row["problem_id"],"seed":seed,"gold":row["gold"],"question":row["question"],
            "trace":public(trace),"answer":public(answer),"grade":scoring,"natural_closed":natural,
            "same_forced_prefix":same_prefix,"same_forced_answer":same_ids,
            "repeat_answer":public(repeated) if repeated else None}
        append_jsonl(out/"ending.jsonl",record)
        print(json.dumps({"protocol":i+1,"problem_id":row["problem_id"],"thought_tokens":trace["tokens"],
            "natural":natural,"grade":scoring,"same_forced_answer":same_ids}),flush=True)
    records=[json.loads(x) for x in (out/"ending.jsonl").read_text().splitlines()]
    report["ending_n"]=len(records)
    report["parse_failures"]=sum(r["grade"]["parse_status"]!="ok" for r in records)
    report["format_failures"]=sum(not r["grade"].get("format_ok",False) for r in records)
    report["censored_n"]=sum(not r["natural_closed"] for r in records)
    report["ending_equivalence_pass"]=all(r["same_forced_prefix"] and r["same_forced_answer"] for r in records if r["natural_closed"])
    report["admitted"]=report["cache_pass"] and report["scoring_pass"] and report["ending_equivalence_pass"] and report["format_failures"]/len(records)<0.03 and any(r["natural_closed"] for r in records)
    (out/"checks.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report),flush=True)
    if not report["admitted"]:raise SystemExit("Protocol gate did not pass")


if __name__=="__main__":main()
