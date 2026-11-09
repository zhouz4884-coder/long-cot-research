"""Reconcile archive support, exact negative replays and paid ordinary controls."""

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BASE = "52078309c43f11dfa209c591ac3b2e1e8ab31dac"
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def load(name):
    return json.loads((ROOT / name).read_bytes())


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def accepted_expert_rows(report):
    rows = {}
    for case, item in report["per_case"].items():
        rows[case] = []
        for attempt in item["attempts"]:
            require(hashlib.sha256(attempt["source"].encode()).hexdigest() == attempt["source_sha256"],
                    "A checked expert source does not match its receipt")
            if attempt["status"] == "KERNEL_ACCEPTED":
                require(bool(attempt["axioms"]) and all(set(ax) <= ALLOWED_AXIOMS for ax in attempt["axioms"].values()),
                        "An expert proof has an unexpected axiom closure")
                rows[case].append(attempt["method"])
    return rows


def run():
    old = ("research/phase5d25_constraint_revision_20261109", "research/phase5d35_witness_gated_revision_20261109",
           "research/phase5d36_progressive_witness_20261109", "research/phase5d37_scoped_repair_20261110",
           "research/phase5d38_proof_release_20261110", "research/phase5d39_blueprint_trace_20261110")
    subprocess.run(["git", "diff", "--exit-code", BASE, "--", *old], cwd=REPO, check=True)
    freeze = load("D40_SOURCE_SELECTION_FREEZE.json")
    raw = subprocess.check_output(["git", "show", f"{BASE}:{freeze['source']}"], cwd=REPO)
    require(hashlib.sha256(raw).hexdigest() == freeze["source_sha256"] and len(freeze["unresolved"]) == 11 and
            len(freeze["same_family_author_rescan_solved"]) == 20, "Frozen archive cohort differs")
    ledger, summary = load("support_ledger.json"), load("support_summary.json")
    require(summary["ledger_sha256"] == digest("support_ledger.json") and summary["index_sha256"] == digest("support_index.json"),
            "Static support hashes differ")
    for cohort, (states, episodes, steps, checks) in {"unresolved": (11, 66, 528, 440),
            "same_family_solved": (20, 120, 673, 579), "same_target_overlap_sentinel": (1, 6, 48, 40)}.items():
        rows = [row for row in ledger["episodes"] if row["cohort"] == cohort]
        require(len({row["state_id"] for row in rows}) == states and len(rows) == episodes and
                sum(len(row["steps"]) for row in rows) == steps and sum(row["author_verifier_calls"] for row in rows) == checks,
                "An archived support denominator differs")
    require(summary["cohorts"]["unresolved"]["states_with_explicit_split_or_intermediate"] == 11 and
            summary["cohorts"]["unresolved"]["source_counts"]["visible_current_module_steps"] == 383,
            "Support visibility report differs")
    source = load("cases_source_receipt.json")
    require(source["status"] == "ARCHIVE_BOUND_TARGET_SLOTS_ONLY" and source["freeze_sha256"] == digest("D40_SOURCE_SELECTION_FREEZE.json") and
            len(source["initial_source_archive_readback"]) == 24 and not source["offline_positive_reference"]["reference_in_authoring_slots"],
            "Inert source slots or offline positive isolation differ")
    negatives = load("cases_archive_failure_runtime.json")
    require(negatives["status"] == "PASS_EXACT_ARCHIVED_NEGATIVES_REPRODUCED" and len(negatives["cases"]) == 3 and
            negatives["review_receipt_sha256"] == digest("cases_archive_failure_receipt.json"), "Archived negative run scope differs")
    for item in negatives["cases"].values():
        require(item["same_archived_failure_reproduced"] and not item["kernel_proof_accepted"] and
                item["compiler_error_classes_and_lines_equal"] and item["target_axiom_closure_equal"],
                "A sampled archived failure was not reproduced")
    line_edit = load("cases_p14_one_line_edit_runtime.json")
    require(line_edit["status"] == "EDITED_REPLAY_NEXT_FAILURE" and not line_edit["original_source_changed"] and
            not line_edit["kernel_proof_accepted"] and all(row["class"] != "INTRO_NO_BINDER" for row in line_edit["local_errors"]),
            "The single-edit execution diagnostic differs")
    baseline = load("baseline_runtime_approved.json")
    require(baseline["status"] == "COMPLETE_APPROVED_CPU_BASELINE" and baseline["source_receipt_sha256"] ==
            digest("cases_source_receipt.json") and baseline["protocol_sha256"] == digest("baseline_runtime_protocol.json"),
            "Baseline environment or target binding differs")
    comparison = {}
    for case, record in baseline["cases"].items():
        successes = [a for a in record["trials"] if a["status"] == "KERNEL_ACCEPTED"]
        require(record["absence_control"]["status"] == "REJECTED" and record["target_header_sha256"] ==
                source["source_cases"][case]["target_header_sha256"], "No proof of clean imported target scope")
        require(len(successes) == len(record["accepted_actions"]), "A baseline acceptance count differs")
        comparison[case] = {"paid_submissions": len(record["trials"]), "accepted": len(successes),
                            "first_accepted_action": record["first_accepted_action"]}
    require(sum(row["paid_submissions"] for row in comparison.values()) == 59 and
            sum(row["accepted"] for row in comparison.values()) == 1 and
            baseline["same_family_p40_separate_offline"]["status"] == "KERNEL_ACCEPTED" and
            baseline["same_family_p40_separate_offline"]["matches_archived_axioms"] and
            not baseline["same_family_p40_separate_offline"]["reference_used_for_baseline_generation"],
            "The matched baseline or offline positive proof is incomplete")
    initial, retry = (load(name) for name in ("expert_split_control_results.json", "expert_split_recheck_results.json"))
    require(initial["input_sha256"] == retry["input_sha256"] == digest("cases_source_receipt.json") and
            retry["retry_freeze_sha256"] == digest("D40_EXPERT_RETRY_FREEZE.json"), "Ordinary proof controls differ from their source")
    first_proofs, retried_proofs = accepted_expert_rows(initial), accepted_expert_rows(retry)
    require(len(first_proofs["p14"]) == len(retried_proofs["p41"]) == 2 and
            "direct_bounded_decide" in retried_proofs["p138"] and len(retried_proofs["p138"]) == 3,
            "An expected ordinary proof control is missing")
    files = ("D40_SOURCE_SELECTION_FREEZE.json", "D40_CONTROL_PROTOCOL.json", "support_freeze.json", "support_ledger.json",
             "support_summary.json", "support_index.json", "support_probe.json", "support_accepted_overlap.json",
             "cases_source_receipt.json", "cases_archive_failure_receipt.json", "cases_archive_failure_runtime.json",
             "cases_p14_one_line_edit_runtime.json", "baseline_runtime_protocol.json", "baseline_runtime_approved.json",
             "expert_split_control_results.json", "D40_EXPERT_RETRY_FREEZE.json", "expert_split_recheck_results.json")
    result = {"status": "COMPLETE_NO_GO_NEW_LEMMA_METHOD_NOT_ADMITTED", "baseline_commit": BASE,
              "archive_cohorts": {"unresolved": 11, "same_family_solved": 20, "cohort_archived_steps": 1201,
                                  "same_target_overlap_sentinel_excluded_from_cohort": True,
                                  "unresolved_with_visible_split_or_intermediate": 11},
              "actual_sampled_archive_failures_reproduced": 3,
              "closed_graph_search_over_all_archived_support": False,
              "finite_evidence_scope": "Three exact admitted module snapshots and one explicitly edited diagnostic. All other historical support combinations remain outside local replay and cannot be declared exhausted.",
              "standard_same_import_cpu": comparison,
              "standard_resident_complete_sequence_wall_seconds": baseline["resident_sequence_total_wall_seconds"],
              "offline_p40_positive_same_family": True,
              "ordinary_proof_controls_accepted": {"p14": first_proofs["p14"], **retried_proofs},
              "new_lemma_mechanism_qualifying_independent_targets": 0, "model_tokens": 0, "gpu_seconds": 0,
              "independent_model_test_denominator": 0,
              "evidence_sha256": {name: digest(name) for name in files}}
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    target = ROOT / "D40_DELIVERY_AUDIT.json"
    if target.exists():
        require(target.read_bytes() == raw, "D4.0 final audit differs on replay")
    else:
        target.write_bytes(raw)
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: result[k] for k in ("status", "archive_cohorts", "standard_same_import_cpu",
                                            "ordinary_proof_controls_accepted", "new_lemma_mechanism_qualifying_independent_targets")}, indent=2))
