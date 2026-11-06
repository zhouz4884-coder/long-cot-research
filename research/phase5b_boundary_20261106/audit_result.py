"""Post-run independent recount from saved bytes. No GPU or output mutation."""
import hashlib
import json
from pathlib import Path
import time

import boundary_core as core

ROOT = Path(__file__).resolve().parent


def load(p): return json.loads(p.read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    out=ROOT/"results/round_01";source=ROOT.parent/"direction_selection_20261105/real_model_p0.py"
    quality=ROOT.parent/"phase5_prototype_20261106/phase5_quality_runner.py"
    for row in load(ROOT/"prelaunch_freeze.json")["remote_files"]:
        path={"p0_base_frozen.py":source,"phase5_quality_frozen.py":quality}.get(row["path"],ROOT/row["path"])
        assert sha(path)==row["sha256"],row["path"]
    retrieval=load(ROOT/"RETRIEVAL_MANIFEST.json")
    for row in retrieval["files"]:
        path=ROOT/row["path"];assert sha(path)==row["sha256"] and path.stat().st_size==row["bytes"]
    manifest=load(out/"manifest.json");summary=load(out/"summary.json");jobs=load(out/"rendered_jobs.json")
    assert jobs==load(ROOT/"rendered_prelaunch.json")
    assert sha(out/"rendered_jobs.json")==manifest["rendered_jobs_sha256"]
    assert manifest["source_sha256"]==sha(ROOT/"boundary_runner.py") and manifest["core_sha256"]==sha(ROOT/"boundary_core.py")
    data=load(ROOT/"CONTROL_DATASET.json");cases={c["case_id"]:c for c in data["cases"]};records=[]
    # Independent symbolic evaluator, separate from core.cold/evaluate.
    from sympy import sympify
    values={};start=time.perf_counter()
    for name,expr in data["cases"][0]["visible"]["rules"].items():values[name]=int(sympify(expr).subs(values))
    oracle_time=time.perf_counter()-start;assert values["z"]==420 and values["r"]==153 and values["x"]==23
    for job in jobs:
        path=out/(job["job_id"]+".json")
        if not path.exists():continue
        row=load(path);assert row["rendering"]==job
        if not row.get("complete"):continue
        text=row["free"]["text"];extracted=core.extract_integer(text)
        assert extracted==row["grade"]["extraction"]
        assert (extracted["value"]==values["z"])==row["grade"]["numeric_correct"]
        assert row["free"]["new_tokens"]==len(row["free"]["token_ids"])
        assert row["free"]["input_checkpoint_cache_length_before_after"]==[job["prompt_tokens"]]*2
        if row["free"]["eos_reached"]:assert row["free"]["token_ids"][-1] in manifest["eos_ids"]
        else:assert row["free"]["hit_safety_cap"] and row["free"]["new_tokens"]==768
        if row["method"] in ("SharedGFull","BoundaryProjection"):
            state=core.controller(cases[row["case_id"]]["visible"])
            assert state==row["G_and_bookkeeping"] and state["target_branch_evaluations"]==0
            assert core.render(cases[row["case_id"]]["visible"],row["method"],state)==job["messages"]
        else:assert row["G_and_bookkeeping"] is None
        records.append(row)
    ledger=load(out/"forward_ledger.json")
    assert len(records)==summary["complete_outputs"]
    assert len(ledger)==sum(r["free"]["new_tokens"] for r in records)==summary["forward_cost"]["forward_calls"]
    assert all(r["all_keys_readable"] for r in ledger)
    prompt=sum(r["rendering"]["prompt_tokens"] for r in records)
    generated=sum(r["free"]["new_tokens"] for r in records)
    assert sum(r["input_tokens"] for r in ledger)==prompt+generated-len(records)==summary["forward_cost"]["input_tokens"]
    method_rows={}
    for name in ("RawFull","SharedGFull","BoundaryProjection","RestartP"):
        rr=[r for r in records if r["method"]==name]
        method_rows[name]={"n":len(rr),"correct":sum(r["grade"]["numeric_correct"] for r in rr),
                          "eos_correct":sum(r["grade"]["eos_and_correct"] for r in rr),
                          "eos":sum(r["free"]["eos_reached"] for r in rr),"cap":sum(r["free"]["hit_safety_cap"] for r in rr),
                          "unparsed":sum(r["grade"]["extraction"]["value"] is None for r in rr),
                          "prompt_tokens":sum(r["rendering"]["prompt_tokens"] for r in rr),
                          "generated_tokens":sum(r["free"]["new_tokens"] for r in rr),
                          "request_seconds_including_G":sum(r["request_seconds_including_G"] for r in rr),
                          "G_cpu_seconds_included":sum(r["G_cpu_seconds"] for r in rr)}
    projected=[r for r in records if r["method"]=="BoundaryProjection"]
    repeated_same=len({tuple(r["free"]["token_ids"]) for r in projected})<=1
    launch=load(ROOT/"launcher_01.json")
    result={"status":"PASS","run_status":summary["status"],"complete_outputs":len(records),"planned_outputs":len(jobs),
            "independent_programs":1,"primary_groups":summary["groups"],"methods":method_rows,
            "all_EOS":sum(r["free"]["eos_reached"] for r in records),"all_cap":sum(r["free"]["hit_safety_cap"] for r in records),
            "generated_tokens":generated,"prompt_tokens":prompt,"forward_ledger":summary["forward_cost"],
            "same_projected_input_same_output":repeated_same,
            "launcher_seconds":launch["elapsed_seconds"],"single_GPU_minutes":launch["conservative_single_GPU_minutes"],
            "simple_exact_interpreter_control":{"value":values["z"],"evaluated_nodes":len(values),"local_sympy_seconds":oracle_time,
                "scope":"Exact synthetic semantics validation; this full interpreter already solves the known program. Not an LLM gain, not a GPU latency comparison."},
            "retrieval_files_verified":len(retrieval["files"]),
            "scope":"Known-DAG/scoped-exact-checker conditional pilot. All LM calls fresh-prefill; not warm-cache continuation serving or natural graph extraction.",
            "cost_notes":"Per-request G/compile/prefill/decode nested within request; all requests/hash/load within study wall. No double addition."}
    (ROOT/"RESULT_AUDIT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
