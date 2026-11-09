"""Recount a closed GPU shard, then grade exact scalar delivery offline."""

import argparse
from copy import deepcopy
from itertools import chain
import json
import sys

from audit_d36_receipts import audit_receipts
from point_verifier import PointVerifier
from prepare_d36_checkpoints import D3, FREEZE, ROOT, ids_sha, pinned, sha, write_once

sys.path.extend(str(ROOT.parent / name) for name in (
    "phase5d2_quarantined_rebase_20261107", "phase5d25_constraint_revision_20261109",
))
from complete_answer import _rational
from complete_answer_v2 import _number, _tree, backend_status, extract_final_answer, grade_final_answer
from independent_audit import work
from witness_contract import compile_contract


def read(path):
    return json.loads(path.read_bytes())


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def exact_answer(row):
    text = row["delivered_final_response"]
    if not row["EOS"] or not row["think_closed"] or not isinstance(text, str):
        return None, {"status": "not_delivered"}
    parsed = extract_final_answer(text, "scalar")
    if parsed.get("status") != "ok" or len(parsed.get("components", [])) != 1:
        return None, parsed
    value = _rational(parsed["components"][0])
    if value is None:
        try:
            node, expression = _tree(parsed["components"][0])
            value = _number(node, expression, {})
        except (ValueError, SyntaxError, ArithmeticError):
            return None, parsed
    return int(value) if value is not None and value.denominator == 1 else None, parsed


def count_events(row):
    events = row["point_audit_events"]
    return {"terminal_vetoes": sum(e["decision"]["veto"] for e in events),
            "new_valid_bounds_after_cue": sum(e["decision"]["action"] == "UPDATE_BOUND" for e in events),
            "infeasible_receipts": sum(e["decision"]["receipt"]["status"] == "CERTIFIED_INFEASIBLE" for e in events),
            "cached_receipts": sum(bool(e["decision"]["receipt"]["cached_from"]) for e in events),
            "model_modified_by_feedback": sum(r["phase"] != "initial_cue" and r["status"] == "APPENDED"
                                               for r in row["forced_feedback"])}


def validate_rows(checkpoint):
    freeze = read(FREEZE)
    folder = ROOT / "gpu_results" / checkpoint
    receipt = read(ROOT / f"{checkpoint.upper()}_RETRIEVAL.json")
    need(receipt["status"] == "COMPLETE" and receipt["checkpoint"] == checkpoint, "Retrieval receipt incomplete")
    receipt_paths = set()
    for entry in receipt["files"]:
        p = ROOT / entry["path"]
        need(p.stat().st_size == entry["bytes"] and sha(p.read_bytes()) == entry["sha256"], f"Blob differs: {p}")
        receipt_paths.add(entry["path"])
    summary = read(folder / "summary.json")
    plan = read(folder / "SOURCE_BOUND_PLAN.json")
    packet_path = ROOT / "prepared" / f"{checkpoint}_checkpoint.json"
    packet = read(packet_path)
    source = read(ROOT / "D36_SOURCE_REFERENCE.json")
    checkpoint_source = source["checkpoints"][checkpoint]
    need(sha(packet_path.read_bytes()) == checkpoint_source["packet_sha256"] and
         ids_sha(packet["prompt_ids"] + packet["generated_ids"]) == checkpoint_source["prefix_sha256"] and
         packet["checkpoint_step"] == checkpoint_source["step"], "Prepared source packet differs")
    diagnostics = plan["replay_state_diagnostics"]
    prefix_len = len(packet["prompt_ids"]) + len(packet["generated_ids"])
    need(summary["status"] == "COMPLETE" and diagnostics["cache_sequence_length"] == prefix_len,
         "Replay cache length or worker summary does not close")
    need(diagnostics["observed_prefix_sha256"] == packet["observed_prefix_sha256"] and
         diagnostics["next_logits_numel"] > 0 and len(diagnostics["kv_layers"]) > 0,
         "Replay diagnostics do not bind the packet")
    need(all(pair["shape"][-2] == prefix_len for layer in diagnostics["kv_layers"] for pair in layer["kv"]),
         "KV positions do not match the packet")
    need(plan["historical_rng_sha256"] == source["checkpoints"][checkpoint]["rng_sha256"],
         "Stored native RNG was not the runtime source")
    ledger = read(folder / "actual_forward_ledger.json")
    replay_len = summary["actual_shared_replay"]["work"]["forward_calls"]
    need(work(ledger[:replay_len]) == summary["actual_shared_replay"]["work"] and
         work(ledger) == summary["actual_paid_work"], "Shared replay or full paid work differs")
    order = [(rep["id"], arm) for rep in freeze["replicates"] for arm in freeze["arms"]]
    need([(x["replicate"], x["arm"]) for x in summary["arms"]] == order, "A preregistered result is absent or out of order")
    required = {folder / p for p in ("manifest.json", "SOURCE_BOUND_PLAN.json", "summary.json", "actual_forward_ledger.json", "worker.log")}
    for rep in freeze["replicates"]:
        snapshot = folder / rep["id"] / "snapshot.json"
        required.add(snapshot)
        saved = read(snapshot)
        need(saved["continuation_seed"] == rep["seed"], "Frozen continuation seed differs")
        if rep["seed"] is None:
            need(saved["rng_sha256"] == checkpoint_source["rng_sha256"], "Historical replicate RNG differs")
    required.update(folder / replica / f"{arm}.json" for replica, arm in order)
    need(all(p.relative_to(ROOT).as_posix() in receipt_paths for p in required), "A required raw file lacks a retrieval hash")
    arms = {}
    expected_prefix = packet["generated_ids"]
    for replica, arm in order:
        row = read(folder / replica / f"{arm}.json")
        key = (replica, arm)
        need((row["replicate"], row["arm"]) == key and row["status"] == "COMPLETE", f"Invalid arm: {key}")
        need(row["prompt_ids"] == packet["prompt_ids"] and row["generated_ids"][:len(expected_prefix)] == expected_prefix and
             row["generated_sha256"] == ids_sha(row["generated_ids"]), f"Arm did not retain frozen input: {key}")
        need(row["stop_reason"] in {"EOS", "CONTEXT_CAP"} and row["EOS"] == (row["stop_reason"] == "EOS") and
             row["hit_context_cap"] == (row["stop_reason"] == "CONTEXT_CAP"),
             f"Unexpected terminal state: {key}")
        need(row["paid_work_after_cut"] == work(row["ledger_after_cut"]), f"Arm paid work differs: {key}")
        expected_cue = plan["initial_cue_token_ids"][arm]
        if expected_cue:
            need(row["forced_feedback"][0]["token_ids"] == expected_cue and
                 row["generated_ids"][len(expected_prefix):len(expected_prefix) + len(expected_cue)] == expected_cue,
                 f"Measured initial cue does not match plan: {key}")
        else:
            need(not row["forced_feedback"], f"Unexpected intervention in NativeContinue: {key}")
        need(row["teacher_forced_tokens"] == sum(f["tokens"] for f in row["forced_feedback"]), f"Forced work differs: {key}")
        discarded = sum(len(rejected["discarded_sampled_ids"]) for rejected in row["rejected_drafts"])
        need(row["sampled_continuation_tokens"] == len(row["generated_ids"]) - len(expected_prefix) -
             row["teacher_forced_tokens"] + discarded, f"Sampled work does not conserve tokens: {key}")
        if row["controller"] is not None:
            controller = row["controller"]
            need(controller["point_calls"] <= freeze["primary_point_budget"] and
                 controller["paid_operations"] <= freeze["arithmetic_work_budget"] and
                 controller["feedback_emitted"] <= freeze["feedback_budget"] and
                 len(row["terminal_restores"]) <= freeze["terminal_repair_attempts"], f"Frozen quota exceeded: {key}")
        for restore in row["terminal_restores"]:
            need(restore["post_draft_rng_before_restore_sha256"] == restore["rng_after_restore_sha256"],
                 f"A repair reset paid RNG: {key}")
        arms[key] = row
    need(ledger[replay_len:] == list(chain.from_iterable(row["ledger_after_cut"] for row in arms.values())),
         "The ordered branch ledgers do not reconstruct the shared ledger")
    need(arms["historical", "NativeContinue"]["generated_sha256"] == source["original_generated_sha256"],
         "Historical NativeContinue did not reproduce its frozen D3 continuation")
    for replica in {key[0] for key in arms}:
        invalid = arms[replica, "InvalidWitnessControl"]
        neutral = arms[replica, "NeutralReminder"]
        need(invalid["invalid_witness_control"]["exposed_to_model"] is False and
             invalid["generated_ids"] == neutral["generated_ids"], f"Failed invalid-witness paired control: {replica}")
    initial_cue = plan["initial_cue_token_ids"]
    need(initial_cue["VerifiedWitness"] == initial_cue["ProgressiveWitness"] == initial_cue["EveryStepAudit"],
         "Progressive comparison cue mismatch")
    return freeze, receipt, summary, packet, arms, plan


def native_postcheck(freeze, contract, evaluated, gold):
    """Evaluate a passive model+point policy on separately paid native continuations."""
    output = []
    for k in freeze["point_budgets"]:
        api = PointVerifier(contract, point_budget=k, work_budget=freeze["arithmetic_work_budget"])
        admitted = []
        for row in evaluated:
            value = row["exact_delivered"]
            if value is not None:
                checked = api.check(value)
                admitted.append({"replicate": row["replicate"], "value": value, "point": checked.as_dict()})
        viable = [r["value"] for r in admitted if r["point"]["status"] == "CERTIFIED_FEASIBLE"]
        result = max(viable, default=None)
        metered = api.report()
        output.append({"point_budget": k, "point_calls": metered["point_calls"],
                       "paid_operations": metered["paid_operations"], "point_cpu_seconds": metered["point_check_seconds"],
                       "admitted": admitted,
                       "best_feasible": result, "exact_final_value_matches_reference": result == gold,
                       "model_continuations": len(evaluated),
                       "model_input_tokens_after_shared_cut": sum(row["gpu_inputs_after_cut"] for row in evaluated),
                       "full_objective_certificate": False})
    return output


def budget_matched_native(freeze, contract, graded, gold):
    """Use measured native arms only, with the conditioned seed first and no answer-dependent order."""
    native = [row for row in graded if row["arm"] == "NativeContinue"]
    rows = []
    for trial in (row for row in graded if row["arm"] == "ProgressiveWitness"):
        ordered = sorted(native, key=lambda row: row["replicate"] != trial["replicate"])
        input_limit = trial["gpu_inputs_after_cut"]
        pair_limit = trial["attention_pairs_after_cut"]
        selected = []
        used_input = used_pairs = 0
        for row in ordered:
            inputs = used_input + row["gpu_inputs_after_cut"]
            pairs = used_pairs + row["attention_pairs_after_cut"]
            if inputs > input_limit or pairs > pair_limit:
                break
            selected.append(row)
            used_input, used_pairs = inputs, pairs
        k = freeze["primary_point_budget"]
        baseline, = native_postcheck({**freeze, "point_budgets": [k]}, contract, selected, gold)
        rows.append({"conditioned_replicate": trial["replicate"], "gpu_input_budget": input_limit,
                     "attention_pair_budget": pair_limit, "included_replicates": [r["replicate"] for r in selected],
                     "actual_gpu_inputs": used_input, "actual_attention_pairs": used_pairs,
                     "all_archived_native_seeds_used": len(selected) == len(ordered),
                     "baseline": baseline})
    return rows


def replay_budget_on_fixed_events(freeze, contract, row):
    """Recheck actual observations under each cap without making counterfactual generation claims."""
    ordered = [event["receipt"]["objective"] for event in row["initial_point_receipts"]]
    ordered += [event["candidate"]["value"] for event in row["point_audit_events"]]
    sensitivity = []
    for k in freeze["point_budgets"]:
        api = PointVerifier(contract, point_budget=k, work_budget=freeze["arithmetic_work_budget"])
        feasible = []
        unknown = 0
        for value in ordered:
            checked = api.check(value)
            if checked.status == "CERTIFIED_FEASIBLE":
                feasible.append(value)
            elif checked.status == "UNKNOWN":
                unknown += 1
        sensitivity.append({"budget": k, "ordered_observations": len(ordered), "unknown_observations": unknown,
                            "best_feasible_on_fixed_trace": max(feasible, default=None), **api.report()})
    return sensitivity


def clock_accounting(checkpoint, receipt, summary):
    clocks = read(ROOT / "D36_CLOCK_INTERVALS.json")
    intervals = clocks["intervals"].get(checkpoint, [])
    need(all(item["stage"] == "shared_observed_prefix_replay" for item in intervals),
         "A pause outside shared replay requires separate clock reconciliation")
    excluded = sum(item["excluded_seconds"] for item in intervals)
    gross_replay = summary["actual_shared_replay"]["wall_seconds"]
    gross_study = summary["elapsed_seconds"]
    gross_worker = receipt["worker_wall_seconds_including_load_approx"]
    need(0 <= excluded < min(gross_replay, gross_study, gross_worker), "Suspension exceeds an enclosing clock")
    return {"scope": "Elapsed clocks measured around GPU/CPU work. Not GPU kernel busy time. Resident allocation includes pause.",
            "user_pause_seconds": excluded,
            "gross_shared_replay_seconds": gross_replay, "pause_adjusted_shared_replay_seconds": gross_replay - excluded,
            "gross_study_seconds": gross_study, "pause_adjusted_study_seconds": gross_study - excluded,
            "gross_worker_seconds": gross_worker, "pause_adjusted_worker_seconds": gross_worker - excluded}


def stable_audit(output):
    """Ignore only CPU timings measured by this local audit, not the frozen worker clocks."""
    report = deepcopy(output)
    passive = report["native_llm_plus_verifier"]
    local_baselines = list(chain.from_iterable(passive["per_seed"].values())) + passive["pooled_resampling"]
    local_baselines.extend(row["baseline"] for row in report["budget_matched_paid_native_resampling"]["rows"])
    for row in local_baselines:
        row.pop("point_cpu_seconds", None)
    for row in report["fixed_trace_point_budget_sensitivity"]["rows"]:
        for case in row["curves"]:
            case.pop("point_check_seconds", None)
    return report


def audit(checkpoint):
    freeze, receipt, summary, packet, arms, plan = validate_rows(checkpoint)
    manifest = read(ROOT / "gpu_results" / checkpoint / "manifest.json")
    receipt_audit = audit_receipts(packet, plan, arms, freeze, manifest)
    grading_backend = backend_status()
    need(grading_backend["status"] == "ok", f"Pinned grading backend is required: {grading_backend}")
    evaluation = pinned(D3 / "prepared_data/bank/eval_only.jsonl")
    bank = json.loads(pinned(D3 / "D3_DATA_FREEZE.json"))["banks"]["bank"]
    need(sha(evaluation) == bank["eval_only_sha256"], "Scoring reference differs from D3 freeze")
    reference, = (r["gold"] for r in map(json.loads, evaluation.splitlines()) if r["case_id"] == packet["case_id"])
    gold = int(reference)
    graded = []
    for (replica, arm), row in arms.items():
        answer, parsed = exact_answer(row)
        grade = grade_final_answer(parsed, str(gold))
        need(grade["status"] in {"ok", "not_delivered", "candidate_parse_unknown"}, f"F2 grader failed: {grade}")
        control = row["controller"] or {}
        graded.append({"replicate": replica, "arm": arm, "correct": grade["correct"] is True,
                       "exact_delivered": answer, "readout": parsed, "frozen_f2_grade": grade, "eos": row["EOS"],
                       "technical_cap": row["hit_context_cap"], "delivery": row["final_delivery"],
                       "model_generated_samples": row["sampled_continuation_tokens"],
                       "forced_tokens": row["teacher_forced_tokens"],
                       "gpu_inputs_after_cut": row["paid_work_after_cut"]["forward_input_tokens"],
                       "attention_pairs_after_cut": row["paid_work_after_cut"]["attention_pairs"],
                       "seconds_after_cut": row["elapsed_seconds"],
                       "point_calls": control.get("point_calls", 0), "point_ops": control.get("paid_operations", 0),
                       "point_cpu_seconds": control.get("point_check_seconds", 0),
                       "rejected_drafts_replayed": len(row["rejected_drafts"]), **count_events(row)})
    matched = []
    for replica in (r["id"] for r in freeze["replicates"]):
        group = {x["arm"]: x for x in graded if x["replicate"] == replica}
        for test, baseline in (("NumericWitness", "NeutralReminder"), ("VerifiedWitness", "NumericWitness"),
                               ("ProgressiveWitness", "VerifiedWitness"), ("EveryStepAudit", "ProgressiveWitness")):
            trial, control = group[test], group[baseline]
            matched.append({"replicate": replica, "method": test, "baseline": baseline,
                            "quality_delta": int(trial["correct"]) - int(control["correct"]),
                            "after_cut_input_delta": trial["gpu_inputs_after_cut"] - control["gpu_inputs_after_cut"],
                            "after_cut_seconds_delta": trial["seconds_after_cut"] - control["seconds_after_cut"]})
    native = [row for row in graded if row["arm"] == "NativeContinue"]
    contract = compile_contract(packet["question"])
    passive = {"scope": "Post-run passive checks on the paid native EOS responses. No change to generation, no direct optimality certification.",
               "per_seed": {r["replicate"]: native_postcheck(freeze, contract, [r], gold) for r in native},
               "pooled_resampling": native_postcheck(freeze, contract, native, gold)}
    resampling = {"scope": "Uses only the three paid native continuations. Stops before the next full natural continuation would exceed either measured GPU-work cap; may leave surplus. Same checker cap; no additional generated trace.",
                  "rows": budget_matched_native(freeze, contract, graded, gold)}
    sensitivity = {"scope": "Rechecks observed candidate order only. New budgets do not change generation in this analysis and cannot establish a live accuracy curve.",
                   "rows": [{"replicate": rep, "arm": arm, "curves": replay_budget_on_fixed_events(freeze, contract, row)}
                            for (rep, arm), row in arms.items() if row["controller"] is not None]}
    output = {"status": "PASS", "checkpoint": checkpoint, "historical_reference_after_close": gold,
              "grading_backend": grading_backend,
              "source_and_action_receipt_audit": receipt_audit,
              "model_arms": graded, "matched_contrasts": matched, "native_llm_plus_verifier": passive,
              "budget_matched_paid_native_resampling": resampling, "fixed_trace_point_budget_sensitivity": sensitivity,
              "clock_accounting": clock_accounting(checkpoint, receipt, summary),
              "shared_replay": summary["actual_shared_replay"], "paid_study": summary["actual_paid_work"],
              "peak_allocated_bytes": summary["peak_allocated_bytes"], "next_logits_sha256": plan["replay_state_diagnostics"]["next_logits_sha256_fp32"],
              "scope": "One historical E15 development question. Fixed prefix per shard; continuation RNG replicates are not independent questions."}
    destination = ROOT / f"{checkpoint.upper()}_GPU_AUDIT.json"
    if destination.exists():
        first = read(destination)
        need(stable_audit(first) == stable_audit(output), "Published audit fields differ on replay")
        return first
    write_once(destination, output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", choices=("early", "late"))
    result = audit(parser.parse_args().checkpoint)
    print(json.dumps({"status": result["status"], "checkpoint": result["checkpoint"],
                      "outcomes": [[r["replicate"], r["arm"], r["exact_delivered"], r["correct"], r["eos"]]
                                   for r in result["model_arms"]]}, indent=2))
