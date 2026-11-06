"""Synthetic structural resume contracts only; no bank/Gold/model/GPU."""
import copy
import hashlib
import json
from pathlib import Path

from resume_planner import METHODS, PAIRS, plan_resume


def main():
    checks = []
    def ok(name, condition):
        if not condition: raise AssertionError(name)
        checks.append(name)
    def rejected(name, jobs, worker, rows):
        try: plan_resume(jobs, worker, rows)
        except ValueError: ok(name, True)
        else: ok(name, False)
    jobs = []
    for rank in range(1, 5):
        for method in METHODS:
            prefill = r"Final answer: \boxed{" if method == "ForcedBoxCue" else ""
            jobs.append({"job_id": f"{rank:02}__{method}", "rank": rank, "bank_id": f"S{rank:03}", "method": method,
                         "prompt_ids": [10,11,12], "prompt_tokens": 3, "prompt_text": "SYNTHETIC" + prefill,
                         "assistant_prefill": prefill, "scoring_prefix": r"\boxed{" if prefill else "",
                         "contract_hash": "synthetic-contract", "shared_packet_sha256": "synthetic-packet" if method in ("FullContractEvidence", "ProjectedContractEvidence") else None})
    by = {j["job_id"]: j for j in jobs}
    def saved(jid, text="synthetic", cap=False):
        j = by[jid]
        return {k: j[k] for k in ("job_id","rank","bank_id","method","prompt_tokens","contract_hash","shared_packet_sha256")} | {
            "text": text, "answer_text": j["scoring_prefix"] + text, "token_ids": [10]*384 if cap else [10,2],
            "new_tokens": 384 if cap else 2, "eos_reached": not cap, "hit_cap": cap}
    no = plan_resume(jobs, 0, [])
    ok("no_saved_all14_missing", len(no["missing_job_ids"]) == 14 and len(no["batches"]) == 8)
    ok("original_pair_order", [b["job_ids"] for b in no["batches"]] == [[f"{r:02}__{m}" for m in pair] for r in (1,3) for pair in PAIRS])
    all_rows = [saved(jid) for jid in no["missing_job_ids"]]
    yes = plan_resume(jobs, 0, all_rows)
    ok("all_saved_skips8", not yes["missing_job_ids"] and not yes["batches"] and len(yes["skipped_complete_batch_ids"]) == 8)
    one = saved("01__ForcedBoxCue")
    partial = plan_resume(jobs, 0, [one]); b = partial["batches"][0]
    ok("partial_pair_preserves_shape", b["job_ids"] == ["01__ForcedBoxCue","01__FullContinue"])
    ok("partial_pair_missing_and_discard", b["missing_job_ids"] == ["01__FullContinue"] and b["discard_job_ids"] == ["01__ForcedBoxCue"])
    full_pair = plan_resume(jobs, 0, [one,saved("01__FullContinue")])
    ok("full_pair_skipped", full_pair["skipped_complete_batch_ids"] == ["01_ForcedBoxCue"] and len(full_pair["batches"]) == 7)
    restart = plan_resume(jobs, 0, [saved("01__RestartP")])
    ok("single_restart_skip", "01_RestartP" in restart["skipped_complete_batch_ids"] and len(restart["batches"]) == 7)
    empty = plan_resume(jobs, 0, [saved("01__ForcedBoxCue", text="")])
    ok("empty_EOS_answer_kept", empty == partial)
    capped = plan_resume(jobs, 0, [saved("01__ForcedBoxCue", cap=True)])
    ok("cap_answer_kept", capped == partial)
    poison = copy.deepcopy(one); poison["grade"] = {"correct": False,"gold":"a"}
    p2 = copy.deepcopy(one); p2["grade"] = {"correct": True,"gold":"b"}
    ok("Gold_grade_poison_irrelevant", plan_resume(jobs,0,[poison]) == plan_resume(jobs,0,[p2]) == partial)
    snapshot = copy.deepcopy((jobs, all_rows)); plan_resume(jobs,0,all_rows)
    ok("inputs_not_mutated", (jobs,all_rows) == snapshot)
    ok("input_order_not_quality_ranking", plan_resume(list(reversed(jobs)),0,list(reversed(all_rows))) == yes)
    rejected("duplicate_saved_rejected", jobs,0,[one,copy.deepcopy(one)])
    unknown = copy.deepcopy(one);unknown["job_id"]="99__FullContinue"
    rejected("unknown_saved_rejected", jobs,0,[unknown])
    rejected("other_worker_saved_rejected",jobs,0,[saved("02__FullContinue")])
    for field, value in [("rank",3),("bank_id","WRONG"),("method","RestartP"),("prompt_tokens",4),
                         ("contract_hash","WRONG"),("shared_packet_sha256","WRONG"),("answer_text","WRONG"),
                         ("new_tokens",1),("eos_reached",False),("token_ids",[True,2])]:
        bad=copy.deepcopy(one);bad[field]=value
        rejected("bad_saved_"+field,jobs,0,[bad])
    bad=copy.deepcopy(one);bad["rank"]=True
    rejected("boolean_rank_rejected",jobs,0,[bad])
    bad=saved("01__ForcedBoxCue",cap=True);bad["new_tokens"]=383;bad["token_ids"]=bad["token_ids"][:383]
    rejected("wrong_cap_limit_rejected",jobs,0,[bad])
    bad=copy.deepcopy(jobs);bad.append(copy.deepcopy(jobs[0]))
    rejected("duplicate_compiled_rejected",bad,0,[])
    rejected("missing_compiled_condition_rejected",jobs[1:],0,[])
    bad=copy.deepcopy(jobs);bad[0]["prompt_tokens"]=2
    rejected("bad_compiled_promptlen_rejected",bad,0,[])
    bad=copy.deepcopy(jobs);bad[0]["scoring_prefix"]=""
    rejected("bad_compiled_prefix_rejected",bad,0,[])
    bad=copy.deepcopy(jobs);bad[0]["prompt_text"]="missing prefill"
    rejected("absent_prompt_suffix_rejected",bad,0,[])
    rejected("boolean_worker_rejected",jobs,True,[])
    root=Path(__file__).resolve().parent
    report={"status":"PASS","passed":len(checks),"checks":checks,
            "planner_sha256":hashlib.sha256((root/"resume_planner.py").read_bytes()).hexdigest(),
            "scope":"Synthetic4ranks x7conditions. No bank, real output, Gold, model, remote or GPU. Grade poisoning is a synthetic independence check."}
    (root/"CPU_RESUME_PLANNER.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
