"""Check D4.2 evidence identities and the frozen comparison boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE = "ad202e572534c8e7376d9fba7f8191fb7b3012d6"
PHASE = HERE.relative_to(ROOT).as_posix()
NAVIGATION = {"README.md", "docs/phases/INDEX_ZH.md"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def load(name: str) -> dict:
    return json.loads((HERE / name).read_bytes())


def digest(name: str) -> str:
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def check_frozen_baseline() -> None:
    expected = [
        ("unresolved", 440, 417, 304, 291, 115, 68),
        ("solved_controls", 577, 491, 288, 282, 116, 47),
    ]
    freeze = load("D42_ERROR_ORDER_FREEZE.json")
    archived = load("cascade_audit.json")
    sources = load("causal_cases_source_receipt.json")
    assert freeze["baseline"] == sources["baseline"] == BASELINE
    ledger = git(
        "show", f"{BASELINE}:research/phase5d41_lean_scope_20261110/"
        "diagnostic_ledger.jsonl",
    )
    assert hashlib.sha256(ledger).hexdigest() == freeze["ledger_sha256"]
    assert archived["ledger_sha256"] == freeze["ledger_sha256"]
    assert sources["ledger_sha256"] == freeze["ledger_sha256"]
    assert freeze["diagnostic_message_counts"] == {
        "TYPE_APPLICATION_OR_CALC": 683,
        "TACTIC_PROOF_STEP_FAILURE": 806,
    }
    assert archived["input_freeze_sha256"] == digest("D42_ERROR_ORDER_FREEZE.json")
    assert archived["selection_freeze_sha256"] == digest("cascade_selection_freeze.json")
    assert sources["source_selection_sha256"] == archived["selection_freeze_sha256"]
    anchors = freeze["anchored_multi_error_candidates"]
    assert len(anchors) == archived["raw_verified_frozen_candidates"] == 115
    assert len({row["target_id"] for row in anchors}) == 10
    counters = (
        "checks", "checks_with_error", "multi_error_checks",
        "same_import_multi_error_checks", "same_import_multi_error_first_type_or_tactic",
        "first_report_line_not_earliest",
    )
    for cohort, *values in expected:
        assert [archived["cohort_check_counts"][cohort][k] for k in counters] == values
    assert set(sources["cases"]) == {"p104", "p113", "p41"}
    selected = {row["target_id"]: row for row in archived["selected_primary_cases"]}
    for case in sources["cases"].values():
        selected_case = selected[case["target_id"]]
        assert selected_case["source_sha256"] == case["archive_candidate_sha256"]
        assert selected_case["source_member"] == case["archive_source_member"]
        assert selected_case["attempt_sha256"] == case["archive_attempt_sha256"]
        assert case["exact_imports"] == selected_case["checked_imports"]
        variants = case["variants"]
        original, noop = variants["original"], variants["noop"]
        edited, placebo = variants["edited"], variants["placebo"]
        assert original["source_sha256"] == noop["source_sha256"] == case["archive_candidate_sha256"]
        assert original["bytes"] == noop["bytes"]
        assert edited["bytes"] == placebo["bytes"]
        assert edited["source_sha256"] != placebo["source_sha256"]
    changed = git("diff", "--name-only", "-z", BASELINE, "--").decode().split("\0")
    assert all(
        not name or name in NAVIGATION or name.startswith(PHASE + "/")
        for name in changed
    ), "A path outside D4.2 and its navigation changed"


def check_controls() -> None:
    synthetic = load("cascade_runtime_trusted.json")
    assert synthetic["status"] == "PASS_TRUSTED_CASCADE"
    assert synthetic["freeze_sha256"] == digest("cascade_runtime_freeze.json")
    assert len(synthetic["checks"]) == 7 and all(synthetic["checks"].values())
    for transport in ("cold", "resident"):
        assert [synthetic[transport][k]["status"] for k in (
            "broken", "unrelated_edit", "root_edit", "standard_tactic",
        )] == ["REJECTED", "REJECTED", "KERNEL_ACCEPTED", "KERNEL_ACCEPTED"]
    p14 = load("p14_control_results.json")
    freeze = load("D42_P14_VARIANT_FREEZE.json")
    assert freeze["control_protocol_sha256"] == digest("D42_P14_CONTROL_PROTOCOL.json")
    assert p14["freeze_sha256"] == digest("D42_P14_VARIANT_FREEZE.json")
    assert p14["new_model_tokens"] == p14["gpu_seconds"] == 0
    errors = {
        "archived_exact": ["INTRO_NO_BINDER"],
        "neutral_binder_rename": ["INTRO_NO_BINDER"],
        "replace_intro_with_skip": ["UNSOLVED_GOALS", "MISSING_NAME", "ALREADY_CLOSED_GOAL"],
        "skip_and_commutativity": ["MISSING_NAME", "ALREADY_CLOSED_GOAL"],
        "ordinary_local_witness_patch": [],
        "whole_exact_query": ["OTHER_LEAN_ERROR"],
        "ordinary_whole_induction": [],
    }
    assert p14["resident"].keys() == errors.keys()
    for action, expected in errors.items():
        row = p14["resident"][action]
        assert row["source_sha256"] == freeze["variants"][action]["source_sha256"]
        assert [e["category"] for e in row["errors_in_emitted_order"]] == expected
        assert row["status"] == ("REJECTED" if expected else "KERNEL_ACCEPTED")
    assert p14["cold"]["archived_exact"]["status"] == "REJECTED"
    assert p14["cold"]["ordinary_whole_induction"]["status"] == "KERNEL_ACCEPTED"
    accepted_path = (
        "research/phase5d40_proof_authoring_20261110/baseline_runtime_approved.json"
    )
    p40 = json.loads(git("show", f"{BASELINE}:{accepted_path}"))[
        "same_family_p40_separate_offline"
    ]
    assert p40["status"] == "KERNEL_ACCEPTED"
    assert p40["matches_archived_axioms"] and not p40["reference_used_for_baseline_generation"]


def check_primary() -> dict:
    source = load("causal_cases_source_receipt.json")
    trusted = load("cascade_runtime_trusted.json")
    causal = load("causal_cases_runtime.json")
    ordinary = load("cascade_runtime_ordinary.json")
    freeze = load("cascade_runtime_ordinary_freeze.json")
    source_digest = digest("causal_cases_source_receipt.json")
    assert causal["status"] == "PASS_CAUSAL_CONTROL_REPLAY"
    assert ordinary["status"] == "COMPLETE_APPROVED_ORDINARY_CPU_BASELINE"
    assert causal["source_review_sha256"] == ordinary["source_receipt_sha256"] == source_digest
    assert ordinary["action_freeze_sha256"] == digest("cascade_runtime_ordinary_freeze.json")
    assert not causal["model_generation"] and not causal["gpu_used"]
    assert ordinary["model_tokens"] == ordinary["gpu_seconds"] == 0
    assert causal["environment"] == ordinary["environment"] == trusted["environment"]
    assert set(causal["cases"]) == set(ordinary["cases"]) == set(source["cases"])
    assert ordinary["resident_attempts"] == 22 and ordinary["cold_plain_attempts"] == 3
    result = {}
    for case, ref in source["cases"].items():
        replay = causal["cases"][case]
        baseline = ordinary["cases"][case]
        assert replay["target"] == baseline["target"] == ref["target"]
        assert baseline["target_header_sha256"] == ref["immutable_target_header_sha256"]
        assert baseline["exact_imports"] == ref["exact_imports"]
        assert baseline["original_slot_sha256"] == ref["target_slot"]["source_sha256"]
        assert replay["control_integrity"]
        assert replay["transports_agree_on_ordered_mapped_errors_and_strict_status"]
        comparison = replay["resident_comparison"]
        assert comparison["first_site_removed"]
        assert comparison["original_author_columns_minus_current_scalar_zero_based"] == (
            [0] * len(ref["original_error_lines"])
        )
        for name, source_row in ref["variants"].items():
            cold = replay["cold_raw"][name]
            warm = replay["resident_raw"]["checks"][name]
            assert cold["source_sha256"] == warm["source_sha256"] == source_row["source_sha256"]
        assert all(
            comparison["variants"][name]["strict_target_status"] == "REJECTED"
            for name in ("original", "noop", "placebo")
        )
        observed = [
            {"id": row["action"], "proof_body_sha256": row["proof_body_sha256"]}
            for row in baseline["resident"]
        ]
        assert observed == freeze["actions_by_case"][case]
        accepted = [row["action"] for row in baseline["resident"] if row["status"] == "KERNEL_ACCEPTED"]
        assert accepted == baseline["accepted"]
        assert baseline["cold_resident_plain_status_and_axioms_agree"]
        assert comparison["variants"]["edited"]["strict_target_status"] == "REJECTED"
        assert "sorryAx" in comparison["variants"]["edited"]["target_axioms_reported_even_if_rejected"]
        result[case] = {
            "original_errors": len(comparison["variants"]["original"]["errors"]),
            "edited_errors": len(comparison["variants"]["edited"]["errors"]),
            "edited_status": comparison["variants"]["edited"]["strict_target_status"],
            "removed_original_lines": comparison["removed_original_lines"],
            "persistent_original_lines": comparison["persistent_original_lines"],
            "new_mapped_original_lines": comparison["new_mapped_original_lines"],
            "ordinary_accepted_actions": accepted,
        }
    assert ordinary["accepted_cases"] == sum(bool(row["ordinary_accepted_actions"]) for row in result.values())
    assert ordinary["accepted_cases"] == 2
    assert result["p104"]["removed_original_lines"] == [8, 8]
    assert result["p104"]["new_mapped_original_lines"] == [9, 7]
    assert result["p113"]["persistent_original_lines"] == [16, 34, 41]
    assert result["p41"]["persistent_original_lines"] == [44]
    correction = load("cascade_runtime_plain_correction.json")
    correction_freeze = load("cascade_runtime_plain_correction_freeze.json")
    assert correction["status"] == "PASS_SINGLE_ORDINARY_CORRECTION"
    assert correction["freeze_sha256"] == digest("cascade_runtime_plain_correction_freeze.json")
    assert correction_freeze["original_matrix_sha256"] == digest("cascade_runtime_ordinary.json")
    assert correction_freeze["approved_source_receipt_sha256"] == source_digest
    assert correction_freeze["edits"]["reconstructed_exact"]
    assert correction_freeze["edits"]["new"] == ""
    assert correction_freeze["edits"]["old"].strip().startswith("change ")
    for transport in ("cold", "resident"):
        run = correction[transport]
        assert run["status"] == "KERNEL_ACCEPTED"
        assert run["source_sha256"] == correction_freeze["corrected_source_sha256"]
        assert run["axioms"] == {source["cases"]["p113"]["target"]: [
            "propext", "Classical.choice", "Quot.sound",
        ]}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    check_frozen_baseline()
    check_controls()
    result = {
        "status": "COMPLETE_NO_GO_CASCADE_METHOD_NOT_ADMITTED",
        "baseline": BASELINE,
        "historical_cases": check_primary(),
        "ordinary_complete_targets_first_matrix": 2,
        "ordinary_complete_targets_with_separate_lint_correction": 3,
        "independent_beyond_ordinary_local_repair_demonstrated": 0,
        "independent_gain_required": 2,
        "scope": "Observed effects of approved ordinary local edits and comparison CPU actions only.",
        "author_positive_control_from_frozen_d40": "p40",
        "prior_edit_calibration_excluded_from_primary": "p14",
        "new_model_tokens": 0,
        "gpu_seconds": 0,
        "evidence_sha256": {p.name: digest(p.name) for p in sorted(HERE.glob("*.json"))
                            if p.name != "D42_DELIVERY_AUDIT.json"},
    }
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with args.output.open("xb") as stream:
            stream.write(encoded.encode())
    print(result["status"])


if __name__ == "__main__":
    main()
