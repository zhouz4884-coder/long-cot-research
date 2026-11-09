"""Validate closed model records before opening the historical integer reference."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
sys.path.append(str(D3))
from complete_answer import _rational
from complete_answer_v2 import extract_final_answer
from independent_audit import work


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


MODEL_ARMS = {"e12": ("NativeContinue", "SameEvidencePrompt"),
              "e15": ("NativeContinue", "WitnessOnlyPrompt", "GenericRewind", "SCOPE-RebaseCarry")}
TOOL_ARMS = {"e12": ("LastThoughtAnswer", "DirectVerifier", "WitnessGatedCommit"), "e15": ("BoundedSearch",)}


def audit(case):
    receipt = read(ROOT / f"{case.upper()}_RETRIEVAL.json")
    if receipt["status"] != "COMPLETE":
        raise ValueError("No complete retrieval receipt")
    for entry in receipt["files"]:
        raw = (ROOT / entry["path"]).read_bytes()
        if len(raw) != entry["bytes"] or sha(raw) != entry["sha256"]:
            raise ValueError("Retrieved worker artifact changed")
    folder = ROOT / "gpu_results" / case
    summary = read(folder / "summary.json")
    plan = read(folder / "SOURCE_BOUND_PLAN.json")["plan"]
    ledger = read(folder / "actual_forward_ledger.json")
    arms = {name: read(folder / (name + ".json")) for name in (*MODEL_ARMS[case], *TOOL_ARMS[case])}
    original = read(ROOT / "DEVELOPMENT_SOURCE_COMPARISON.json")["cases"][case]
    native = arms["NativeContinue"]
    original_matches = native["generated_sha256"] == original["full_ids_sha256"]
    ledger_ok = work(ledger) == summary["actual_paid_work"]
    for name in MODEL_ARMS[case]:
        row = arms[name]
        ledger_ok = ledger_ok and row["paid_work_after_cut"] == work(row["ledger_after_cut"])
    paid_total = summary["actual_shared_replay_work"]["forward_input_tokens"] + sum(
        arms[name]["paid_work_after_cut"]["forward_input_tokens"] for name in MODEL_ARMS[case])
    ledger_ok = ledger_ok and paid_total == summary["actual_paid_work"]["forward_input_tokens"]
    closed = summary["status"] == "COMPLETE" and all(row["status"] == "COMPLETE" for row in arms.values())
    if not closed or not ledger_ok:
        raise ValueError("Incomplete or inconsistent computation evidence")
    # This opens the historical reference only after all raw artifacts have
    # closed. It is absent from the remote worker payload.
    gold_bytes = (D3 / "prepared_data/bank/eval_only.jsonl").read_bytes()
    data = read(D3 / "D3_DATA_FREEZE.json")
    if sha(gold_bytes) != data["banks"]["bank"]["eval_only_sha256"]:
        raise ValueError("Historical reference bytes changed")
    gold = next(row["gold"] for row in map(json.loads, gold_bytes.splitlines()) if row["case_id"] == summary["case_id"])
    gold_value = _rational(gold)
    if gold_value is None:
        raise ValueError("This development audit expects an exact scalar reference")
    graded = []
    for name, row in arms.items():
        actual_model = name in MODEL_ARMS[case]
        output = row.get("final_response") or ""
        if actual_model and (not row["EOS"] or not row["think_closed"]):
            selected = {"status": "not_delivered", "reason": "native_output_not_committed"}
        else:
            selected = extract_final_answer(output, "scalar")
        answer = _rational(selected["components"][0]) if selected.get("status") == "ok" and len(selected.get("components", ())) == 1 else None
        graded.append({"arm": name, "correct": answer == gold_value if answer is not None else False,
                       "readout": selected, "exact_delivered_value": None if answer is None else str(answer),
                       "natural_EOS": row.get("EOS") if actual_model else None,
                       "paid_gpu_inputs_after_cut": row.get("paid_work_after_cut", row.get("paid_work", {})).get("forward_input_tokens"),
                       "sampled_continuation_tokens": row.get("sampled_continuation_tokens"),
                       "bridge_tokens": row.get("teacher_forced_bridge_tokens"),
                       "actual_seconds_after_cut": row.get("elapsed_seconds"),
                       "standalone_shared_replay_through_cut": row.get("sequential_shared_replay_through_cut"),
                       "delivery_mode": row.get("delivery_mode")})
    action = (arms["WitnessGatedCommit"].get("verification") or {}).get("action") if case == "e12" else plan["verdict"]["action"]
    intended = "VETO_DRAFT_AND_DELIVER_CERTIFIED" if case == "e12" else "RETRACT_EXTREMUM_ONLY"
    return {"status": "PASS" if original_matches and action == intended else "FAIL", "case": case,
            "scope": "Single historical development trajectory and fixed RNG. No independent test performance.",
            "baseline_exact_generated_id_match": original_matches, "ledger_validated": ledger_ok,
            "actual_authorized_action": action, "historical_gold_after_close": str(gold_value), "scores": graded,
            "paid_study": summary,
            "worker_wall_seconds_including_model_load_approx": receipt["worker_wall_seconds_through_summary_approx"],
            "tool_and_replay_costs_in_raw_arm_records": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=tuple(MODEL_ARMS))
    args = parser.parse_args()
    result = audit(args.case)
    destination = ROOT / f"{args.case.upper()}_GPU_AUDIT.json"
    raw = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode()
    if destination.exists() and destination.read_bytes() != raw:
        raise ValueError("Existing frozen model audit differs")
    destination.write_bytes(raw)
    print(json.dumps({**{key: value for key, value in result.items() if key != "scores"},
                      "scores": [[x["arm"], x["correct"], x["exact_delivered_value"], x["natural_EOS"]] for x in result["scores"]]}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
