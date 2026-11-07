"""Recount paid pairing work and identity receipts without opening Gold."""

from collections import Counter, defaultdict
from itertools import combinations
import json
from math import fsum

from recount_coverage_independent import ROOT, load, need, sha, token_sha, verify_selected


ARMS = ("InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck")
PAIR_MEMBERS = ("NativeContinue", "UnknownIdentity", *ARMS)


def verify_retrieval():
    manifest = load("PAIRING_RETRIEVAL_MANIFEST.json")
    launcher = load("pairing_launcher.json")
    need(manifest["status"] == "COMPLETE" and manifest["launcher"] == launcher
         and launcher["status"] == "FINISHED", "Pairing is not complete")
    receipts = {}
    for entry in manifest["files"]:
        name = entry["path"]
        path = (ROOT / name).resolve()
        need((name.startswith("paired_results/") or name in
              {"pairing_launcher.json", "logs/pairing_0.log", "logs/pairing_1.log"})
             and path.is_relative_to(ROOT) and name not in receipts, f"Unexpected receipt {name}")
        data = path.read_bytes()
        need(len(data) == entry["bytes"] and sha(data) == entry["sha256"], f"Receipt mismatch {name}")
        receipts[name] = entry["sha256"]
    files = {path.relative_to(ROOT).as_posix() for path in (ROOT / "paired_results").rglob("*") if path.is_file()}
    need(files <= receipts.keys(), "Unmanifested files under paired_results")
    need(set(receipts) - files == {"pairing_launcher.json", "logs/pairing_0.log", "logs/pairing_1.log"},
         "Missing pairing logs or launcher receipt")
    workers = {row["worker"]: row for row in launcher["workers"]}
    need(len(launcher["workers"]) == 2 and set(workers) == {0, 1}
         and all(w["exit_code"] == 0 and w["elapsed_seconds"] > 0 for w in workers.values())
         and len({w["gpu"] for w in workers.values()}) == 2, "Pair workers did not finish on two GPUs")
    return receipts, launcher, workers


def file_sha(name):
    return sha((ROOT / name).read_bytes())


def work(rows):
    total = Counter(forward_calls=0, forward_input_tokens=0, attention_pairs=0)
    for row in rows:
        width, past = row["input_tokens"], row["past_tokens"]
        need(type(width) is int and type(past) is int and width > 0
             and past >= 0 and row["position_start"] == past, "Invalid paid forward row")
        total.update(forward_calls=1, forward_input_tokens=width,
                     attention_pairs=sum(range(past + 1, past + width + 1)))
    return dict(total)


def expected(stage, start, end, width=1):
    return [{"stage": stage, "past_tokens": i, "position_start": i,
             "input_tokens": min(width, end - i)} for i in range(start, end, width)]


def validate_eos(result, key, arm, prompt, eos_id, capacity):
    ids = result["generated_ids"]
    need((result["case_id"], result["seed"]) == key and result["arm"] == arm,
         f"Case/arm mismatch {key}/{arm}")
    need(result["status"] == "COMPLETE" and result["stop_reason"] == "EOS" and result["EOS"]
         and not result["hit_context_cap"] and result["think_closed"]
         and ids and ids[-1] == eos_id and eos_id not in ids[:-1]
         and result["context_capacity"] == capacity and len(ids) + len(prompt) <= capacity,
         f"Terminal state mismatch {key}/{arm}")
    need(result["prompt_ids"] == prompt and result["prompt_sha256"] == token_sha(prompt)
         and result["new_tokens"] == len(ids) and result["generated_sha256"] == token_sha(ids),
         f"Prompt/output token receipt mismatch {key}/{arm}")


def audit_case(entry, review, source, folder, capacity):
    key = (entry["case_id"], entry["seed"])
    prompt, native_ids = source["prompt_ids"], source["generated_ids"]
    size, cp_len = len(prompt), entry["generated_count"]
    end_prefix = size + cp_len
    recorded = load(f"{folder}/checkpoint.json")
    execution = json.dumps(recorded["execution"], sort_keys=True, separators=(",", ":")).encode()
    need(recorded["prefix_sha256"] == entry["observed_prefix_sha256"]
         and recorded["checkpoint_id"] == f"{key[0]}_{key[1]}_{entry['step']}"
         and recorded["execution_sha256"] == sha(execution)
         and recorded["prompt_tokens"] == size and recorded["generated_tokens"] == cp_len
         and recorded["cache_position"] == end_prefix and recorded["thinking_open"]
         and recorded["stop_reason"] == "RUNNING", f"Invalid checkpoint for {key}")
    summary = load(f"{folder}/summary.json")
    need((summary["case_id"], summary["seed"]) == key, f"Invalid summary identity {key}")
    results = {arm: load(f"{folder}/{arm}.json") for arm in PAIR_MEMBERS}
    for arm, result in results.items():
        validate_eos(result, key, arm, prompt, native_ids[-1], capacity)
    need(native_ids == results["NativeContinue"]["generated_ids"] == results["UnknownIdentity"]["generated_ids"],
         f"Full native/UNKNOWN output IDs mismatch {key}")
    diag = load(f"{folder}/UNKNOWN_IDENTITY.json")
    gate = load(f"{folder}/IDENTITY_GATE.json")
    need(gate == {"status": "PASS", "criteria": diag} and diag == summary["identity"]
         and all(results[arm]["identity_diagnostics"] == diag for arm in PAIR_MEMBERS[:2]),
         f"Identity gate receipts mismatch {key}")
    flags = ("proposal_prefix_equal", "RNG_equal_at_compared_steps", "terminal_RNG_equal",
             "sampled_tokens_equal", "same_terminal_status", "original_snapshot_unmodified",
             "matches_recorded_native_full_ids")
    remaining = len(native_ids) - cp_len
    reflection = diag["proposal_tokens"]
    need(all(diag[flag] is True for flag in flags) and diag["maximum_logit_difference"] == 0.0
         and 0 < reflection < remaining and diag["logit_comparisons_after_proposal"] == remaining - reflection
         and diag["compared_continuation_tokens"] == remaining and diag["proposal_boundary"] == "COMPLETED_STEP",
         f"Recorded logit/RNG gate mismatch {key}")
    ledger = load(f"{folder}/all_paid_forwards.json")
    setup = expected("checkpoint_schedule_replay", 0, size, 256)
    setup += expected("checkpoint_schedule_replay", size, end_prefix)
    need(ledger[:len(setup)] == setup and recorded["setup_paid_work"] == work(setup),
         f"Checkpoint replay work mismatch {key}")
    identity_end = len(setup) + 2 * (remaining - 1)
    identity = ledger[len(setup):identity_end]
    for stage, start, stop in (
        ("reflection_proposal", end_prefix, end_prefix + reflection),
        ("NativeContinue_decode", end_prefix, size + len(native_ids) - 1),
        ("UnknownIdentity_decode", end_prefix + reflection, size + len(native_ids) - 1),
    ):
        need([row for row in identity if row["stage"] == stage] == expected(stage, start, stop),
             f"Identity ledger positions differ {key}/{stage}")
    need(len(identity) == 2 * (remaining - 1) and work(identity) == diag["joint_paid_work"]
         and all(diag["proposal_cost"][field] == reflection for field in
                 ("generated_tokens", "forward_calls", "forward_input_tokens")), f"Identity paid work differs {key}")

    repair = load(f"{folder}/repair/REPAIR_STATUS.json")
    need((repair["case_id"], repair["seed"]) == key and repair == summary["repair"]
         and repair["status"] == "NOT_ELIGIBLE" and repair["reason"] == "NO_ACTIONABLE_CHALLENGE"
         and repair["arms"] == [] and not review["role_certificate"]
         and repair["metadata"]["role_status"] == "MISSING"
         and repair["metadata"]["source_prefix_sha256"] == recorded["prefix_sha256"],
         f"Repair qualification differs {key}")
    need([arm["arm"] for arm in summary["arms"]] == list(ARMS), f"Unexpected check arms {key}")
    checks = {}
    cursor = identity_end
    for arm, arm_summary in zip(ARMS, summary["arms"]):
        result = results[arm]
        cue = result["audit_cue"]
        proposal = result["proposal"]
        ids = result["generated_ids"]
        cue_end = cp_len + len(cue["token_ids"])
        proposal_end = cue_end + len(proposal["token_ids"])
        need(result["event_step"] == entry["step"] and cue["status"] == "APPENDED"
             and cue["tokens"] == len(cue["token_ids"])
             and ids[:proposal_end] == native_ids[:cp_len] + cue["token_ids"] + proposal["token_ids"],
             f"Cue/proposal source differs {key}/{arm}")
        checker = result["proposal_check"]
        need(result["disposition"] == "UNKNOWN" and checker["status"] == "UNKNOWN"
             and checker["checker_result"]["status"] == "UNKNOWN"
             and checker["unscoped"] == (arm == "UnscopedIsolatedCheck")
             and result["discarded_proposal_tokens"] == 0 and result["redirect"] is None
             and result["rollback_copy_cost"] is None and result["RNG_after_rejection"] == "adopted shadow RNG",
             f"Check disposition differs {key}/{arm}")
        prefix = expected("standalone_native_prefill", 0, size, 256)
        prefix += expected("standalone_native_prefix", size, end_prefix)
        audit = expected(arm + "_audit_cue", end_prefix, size + cue_end)
        audit += expected("reflection_proposal", size + cue_end, size + proposal_end)
        audit += expected(arm + "_decode", size + proposal_end, size + len(ids) - 1)
        standalone = prefix + audit
        need(result["ledger"] == audit and result["standalone_ledger"] == standalone
             and ledger[cursor:cursor + len(standalone)] == standalone
             and result["paid_work"] == arm_summary["paid_work"] == work(audit)
             and result["standalone_paid_work"] == arm_summary["standalone_paid_work"] == work(standalone),
             f"Standalone ledger work mismatch {key}/{arm}")
        cursor += len(standalone)
        need(proposal["stop_reason"] == "COMPLETED_STEP"
             and all(proposal["cost"][field] == len(proposal["token_ids"]) for field in
                     ("generated_tokens", "forward_calls", "forward_input_tokens"))
             and result["continuation"]["continuation_tokens"] == len(ids) - proposal_end
             and result["visible_assistant_tokens"] == len(ids)
             and result["sampled_tokens_including_discarded"] == len(ids) - cue["tokens"]
             and result["teacher_forced_audit_and_redirect_tokens"] == cue["tokens"],
             f"Sampling/teacher-forcing accounting differs {key}/{arm}")
        need(result["peak_allocated_bytes"] == arm_summary["peak_allocated_bytes"]
             and result["standalone_end_to_end_seconds"] == arm_summary["standalone_end_to_end_seconds"]
             and result["elapsed_seconds"] > 0
             and result["standalone_end_to_end_seconds"] >= result["elapsed_seconds"]
             and arm_summary["disposition"] == result["disposition"]
             and arm_summary["tokens"] == result["new_tokens"] and arm_summary["EOS"],
             f"Arm timing/memory summary mismatch {key}/{arm}")
        checks[arm] = {"generated_tokens": len(ids), "EOS": result["EOS"],
                       "generated_sha256": result["generated_sha256"],
                       "proposal_tokens": len(proposal["token_ids"]), "proposal_sha256": token_sha(proposal["token_ids"]),
                       "audit_cue_tokens": cue["tokens"], "audit_cue_sha256": token_sha(cue["token_ids"]),
                       "checker_status": checker["status"], "checker_reason": checker["checker_result"]["reason"],
                       "disposition": result["disposition"], "standalone_paid_work": work(standalone),
                       "audit_postcheckpoint_paid_work": work(audit),
                       "standalone_seconds": result["standalone_end_to_end_seconds"],
                       "audit_postcheckpoint_seconds": result["elapsed_seconds"],
                       "peak_allocated_bytes": result["peak_allocated_bytes"]}
    need(cursor == len(ledger) and work(ledger) == summary["all_paid_work"],
         f"Unallocated paid work {key}")
    pairwise = {a + "__" + b: results[a]["generated_ids"] == results[b]["generated_ids"]
                for a, b in combinations(ARMS, 2)}
    need(summary["peak_allocated_bytes"] ==
         max(summary["identity_joint_peak_allocated_bytes"], summary["repair_peak_allocated_bytes"],
             *(arm["peak_allocated_bytes"] for arm in checks.values())), f"Case peak mismatch {key}")
    phases = {"checkpoint_replay": recorded["setup_seconds"], "identity_joint": diag["joint_wall_seconds"],
              **{arm: checks[arm]["standalone_seconds"] for arm in ARMS}}
    need(summary["elapsed_seconds"] >= fsum(phases.values()) > 0, f"Case timing mismatch {key}")
    return {"case_id": key[0], "seed": key[1], "checkpoint_tokens": cp_len,
            "paired_source_sha256": entry["source_result_sha256"], "checkpoint_sha256": recorded["prefix_sha256"],
            "execution_sha256": recorded["execution_sha256"], "native_and_unknown_full_ids_equal": True,
            "native_and_unknown_full_ids_match_coverage": True, "native_generated_tokens": len(native_ids),
            "native_generated_sha256": token_sha(native_ids), "all_arms_EOS": True,
            "identity_receipt": {k: diag[k] for k in (*flags, "maximum_logit_difference",
                                                      "logit_comparisons_after_proposal", "proposal_tokens")},
            "check_generated_ids_equal": pairwise,
            "check_cue_and_proposal_ids_equal": all(
                results[a][field]["token_ids"] == results[b][field]["token_ids"]
                for a, b in combinations(ARMS, 2) for field in ("audit_cue", "proposal")),
            "native_and_check_ids_equal": {arm: results[arm]["generated_ids"] == native_ids for arm in ARMS},
            "repair_status": repair["status"], "repair_reason": repair["reason"],
            "repair_role_review_status": review["role_review_status"], "repair_arms": len(repair["arms"]),
            "peak_allocated_bytes": summary["peak_allocated_bytes"],
            "identity_joint_peak_allocated_bytes": summary["identity_joint_peak_allocated_bytes"],
            "repair_peak_allocated_bytes": summary["repair_peak_allocated_bytes"],
            "all_paid_work": work(ledger), "checkpoint_replay_paid_work": work(setup),
            "identity_joint_paid_work": work(identity), "case_seconds": summary["elapsed_seconds"],
            "timed_phases_seconds": phases,
            "unpartitioned_case_seconds": summary["elapsed_seconds"] - fsum(phases.values()),
            "checks": checks}, ledger, summary, recorded["execution"]


def main():
    receipts, launcher, workers = verify_retrieval()
    selection = load("PAIR_SELECTION.json")
    reviews = load("ROLE_REVIEWS.json")
    freeze = load("pairing_freeze.json")
    frozen = {row["path"]: row["sha256"] for row in freeze["files"]}
    selection_sha = file_sha("PAIR_SELECTION.json")
    need(selection["status"] == "FROZEN" and freeze["status"] == "FROZEN"
         and selection_sha == reviews["selection_sha256"] == frozen["PAIR_SELECTION.json"]
         and file_sha("ROLE_REVIEWS.json") == frozen["ROLE_REVIEWS.json"], "Pair selection/reviews are not bound")
    entries = selection["selected"]
    review_rows = {(r["case_id"], r["seed"], r["event_step"]): r for r in reviews["reviews"]}
    need(len(entries) == 4 and len({e["case_id"] for e in entries}) == 4
         and len(reviews["reviews"]) == len(review_rows) == 4, "Pair problem/role denominator differs")
    coverage = load("COVERAGE_RETRIEVAL_MANIFEST.json")
    source_receipts = {row["path"]: row for row in coverage["files"]}
    rows, combined = [], []
    summary_by_worker = defaultdict(list)
    model_hashes = set()
    for entry in entries:
        name = entry["source_result"]
        worker_folder = name.split("/")[1]
        worker = int(worker_folder.rsplit("_", 1)[1])
        case = f"{entry['case_id']}_{entry['seed']}"
        need(name == f"native_results/{worker_folder}/{case}/result.json", "Unexpected source path")
        source = load(name)
        digest = file_sha(name)
        need(source_receipts[name]["sha256"] == digest and source["EOS"] and source["think_closed"],
             "Native source receipt mismatch")
        verify_selected(entry, source, name, digest)
        pairing_manifest = load(f"paired_results/{worker_folder}/manifest.json")
        native_manifest = load(f"native_results/{worker_folder}/manifest.json")
        for key in ("gpu", "model_files", "torch", "transformers", "dtype", "backend",
                    "context_capacity", "sampling", "scientific_new_token_cap"):
            need(pairing_manifest[key] == native_manifest[key], f"Pair runtime drift {worker}/{key}")
        need(workers[worker]["gpu"] == pairing_manifest["gpu"] and pairing_manifest["scientific_new_token_cap"] is None,
             "Launcher GPU/cap receipt differs")
        folder = f"paired_results/{worker_folder}/{case}"
        review = review_rows[(entry["case_id"], entry["seed"], entry["step"])]
        row, ledger, summary, execution = audit_case(entry, review, source, folder, pairing_manifest["context_capacity"])
        runtime = {k: pairing_manifest[k] for k in ("gpu", "torch", "transformers")}
        assets = pairing_manifest["model_files"]
        tokenizer = [r for r in assets["files"] if r["name"].startswith(
            ("tokenizer", "vocab", "merges", "special_tokens", "added_tokens", "chat_template"))]
        need(execution["model_sha256"] == assets["manifest_sha256"]
             and execution["tokenizer_sha256"] == sha(json.dumps(tokenizer, sort_keys=True).encode())
             and execution["engine_sha256"] == frozen["native_engine.py"] and json.loads(execution["runtime"]) == runtime
             and execution["backend"] == pairing_manifest["backend"] and execution["dtype"] == pairing_manifest["dtype"]
             and execution["sampling_config"] == pairing_manifest["sampling"], "Snapshot runtime identity differs")
        model_hashes.add(execution["model_sha256"])
        rows.append(row)
        combined.extend(ledger)
        summary_by_worker[worker].append(summary)
    need(len(model_hashes) == 1, "Paired model hashes differ")
    for worker, summaries in summary_by_worker.items():
        saved = load(f"paired_results/worker_{worker}/summary.json")
        need(saved == {"status": "COMPLETE", "completed": len(summaries), "cases": summaries},
             f"Worker summary mismatch {worker}")
    groups = defaultdict(list)
    for item in combined:
        groups[item["stage"]].append(item)
    seconds = fsum(w["elapsed_seconds"] for w in workers.values())
    case_seconds = fsum(r["case_seconds"] for r in rows)
    timed = {name: fsum(r["timed_phases_seconds"][name] for r in rows)
             for name in ("checkpoint_replay", "identity_joint", *ARMS)}
    need(seconds >= case_seconds >= fsum(timed.values()), "Stage timing exceeds paid worker wall")
    report = {
        "status": "PASS", "date": "2026-11-07", "retrieval_manifest_sha256": file_sha("PAIRING_RETRIEVAL_MANIFEST.json"),
        "selection_sha256": selection_sha, "role_reviews_sha256": frozen["ROLE_REVIEWS.json"],
        "pairing_freeze_sha256": file_sha("pairing_freeze.json"), "verified_retrieval_members": len(receipts),
        "verified_source_results": len(rows), "verified_result_arm_files": len(rows) * len(PAIR_MEMBERS),
        "EOS_results": sum(len(PAIR_MEMBERS) for r in rows if r["all_arms_EOS"]),
        "identity_gate_passes": len(rows), "postproposal_logit_comparisons": sum(
            r["identity_receipt"]["logit_comparisons_after_proposal"] for r in rows),
        "maximum_postproposal_logit_difference": max(r["identity_receipt"]["maximum_logit_difference"] for r in rows),
        "check_dispositions": dict(Counter(c["disposition"] for r in rows for c in r["checks"].values())),
        "check_checker_reasons": dict(Counter(c["checker_reason"] for r in rows for c in r["checks"].values())),
        "repair_qualification": dict(Counter(r["repair_status"] for r in rows)),
        "repair_role_review_statuses": dict(Counter(r["repair_role_review_status"] for r in rows)),
        "launcher_worker_seconds": {str(k): v["elapsed_seconds"] for k, v in workers.items()},
        "launcher_GPU_seconds": seconds, "launcher_GPU_minutes": seconds / 60,
        "parallel_launcher_wall_seconds": launcher["elapsed_seconds"], "sum_case_seconds": case_seconds,
        "timed_phases_seconds": timed, "timed_phases_GPU_minutes": {k: v / 60 for k, v in timed.items()},
        "unpartitioned_case_seconds": case_seconds - fsum(timed.values()),
        "worker_outside_cases_seconds": seconds - case_seconds, "paid_forwards": work(combined),
        "paid_forwards_by_stage": {name: work(ledger) for name, ledger in sorted(groups.items())},
        "peak_allocated_bytes": max(r["peak_allocated_bytes"] for r in rows),
        "model_asset_manifest_sha256": next(iter(model_hashes)), "cases": rows,
        "scope": "Gold-blind. IDs and ledgers are rechecked directly. RNG and post-proposal logits are verified against runtime receipts. Per-token proposal-internal logits were not serialized. Timing uses measured worker and arm elapsed time, not CUDA kernel time.",
    }
    (ROOT / "INDEPENDENT_PAIR_RECOUNT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "paid_forwards_by_stage")}, indent=2))


if __name__ == "__main__":
    main()
