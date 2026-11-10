"""Verify the D4.7 denominators, scope, paid evidence, gate and prior freezes."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
import subprocess

from freeze_d47_intake import HERE, ROOT, check_prior, digest, load, sha, write_exclusive
from score_d47_delivery import accepted_labels


def audit(old, new, blind_path):
    prior = check_prior()
    names = {
        "cohort": "D47_COHORT_FREEZE.json", "contracts": "D47_CONTRACTS_FREEZE.json",
        "controls": "D47_CONTROLS_FREEZE.json", "calibration": "D47_DEVELOPMENT_CALIBRATION.json",
        "readout": "D47_DELIVERY_READOUT_FREEZE.json", "scope": "D47_SCOPE_AUDIT.json",
        "strict": "D47_BLIND_COMPARISON_FREEZE.json", "sensitivity": "D47_SCOPE_SENSITIVITY_COMPARISON.json",
        "score": "D47_RESULTS.json", "diagnosis": "D47_POSTSCORE_FAILURE_MODES.json",
    }
    paths = {key: HERE / name for key, name in names.items()}
    evidence = {key: sha(path) for key, path in paths.items()}
    data = {key: load(path) for key, path in paths.items()}
    cohort, contracts, controls, calibration, score = (data[k] for k in ("cohort", "contracts", "controls", "calibration", "score"))
    assert cohort["baseline_commit"] == prior["baseline_commit"] and cohort["planned_trace_count"] == 64
    assert len(cohort["rows"]) == 8 and Counter(r["direction"] for r in cohort["rows"]) == {"MIN": 7, "MAX": 1}
    assert [r["draw"] for r in cohort["source_shards"]] == list(range(8))
    assert contracts["cohort_sha256"] == controls["cohort_freeze_sha256"] == evidence["cohort"]
    assert contracts["preservation_source_sha256"] == sha(HERE / "delivery_preservation.py")
    assert cohort["point_domain_sha256"] == sha(HERE / "d47_point_domains.py")
    assert controls["ordinary_code_sha256"] == sha(HERE / "d47_ordinary_controls.py")
    assert calibration["status"] == "PASS_D47_ACTUAL_OLD_DELIVERY_CALIBRATION"
    assert score["strict_sha256"] == evidence["strict"] and score["sensitivity_sha256"] == evidence["sensitivity"]
    assert score["scope_audit_sha256"] == evidence["scope"] and data["scope"]["counts"] == {"BOUND": 103, "WRONG_OBJECT": 1}
    assert score["scorer_sha256"] == sha(HERE / "score_d47_delivery.py")
    assert data["diagnosis"]["score_sha256"] == evidence["score"]
    assert data["readout"]["blind_input_sha256"] == sha(blind_path)
    source = {row["sample_id"]: row for row in load(blind_path)["rows"]}
    cost = Counter()
    for row in data["readout"]["rows"]:
        raw = source[row["sample_id"]]
        assert digest(raw["response"].encode()) == row["response_sha256"]
        for key in ("input_tokens", "output_tokens"):
            assert raw[key] == row[key]
            cost[key] += row[key]
    assert len(source) == len(data["readout"]["rows"]) == 64
    assert cost == {"input_tokens": 8184, "output_tokens": 1289672}

    labels = accepted_labels(cohort, old, new)
    audited = {r["case_id"]: r for r in score["label_audit"]}
    assert set(labels) == set(audited) and all(
        labels[cid] == {row["optimum"]} and row["label_status"] == "VALIDATED_LITERAL_OPTIMUM"
        for cid, row in audited.items()
    )
    observed = {}
    for name, scored_key, expected_calls in (("strict", "strict_primary", 13), ("sensitivity", "blind_scope_sensitivity", 103)):
        comparison, scored = data[name], score[scored_key]
        outcomes, statuses, proof = Counter(), Counter(), Counter()
        work = 0
        tied_cases = set()
        for row in comparison["rows"]:
            cid = row["case_id"]
            final = row["native_final_value"]
            if row["native_final_eligible"]:
                assert final is not None
                native = "correct" if final in labels[cid] else "wrong"
            else:
                native = "cap" if row["termination"] == "LENGTH_CAP" else "format"
            outcomes[native] += 1
            native_decision, simple = row["preservation"]["decision"], row["naive_best_verified"]
            assert native_decision["proposed_value"] == simple["proposed_value"]
            assert native_decision["action"] == simple["action"] == "KEEP_NATIVE"
            assert row["same_scalar_as_naive"]
            statuses[native_decision["status"]] += 1
            if native_decision["status"] == "FEASIBLE_TIE":
                assert Fraction(native_decision["incumbent_value"]) == Fraction(final)
                tied_cases.add(cid)
            for slot in row["slot_checks"].values():
                if slot["status"] == "NO_SCOPE_AUTHORITY":
                    continue
                assert slot["proof_status"] == slot["ordinary"]["status"]
                receipt = slot["ticket"]["point_receipt"]
                assert receipt["work"] == sum(value for _, value in receipt["operation_charges"])
                proof[slot["proof_status"]] += 1
                work += receipt["work"]
        assert outcomes == {"correct": 45, "wrong": 6, "cap": 12, "format": 1}
        assert sum(proof.values()) == expected_calls and not scored["verified_regressions"] and not scored["false_authorizations"]
        assert scored["totals"]["PRESERVATION_EQUALS_NAIVE"] == 64
        if name == "sensitivity":
            assert statuses == {"FEASIBLE_TIE": 49, "FINAL_CONTEXT_CAP": 12, "FINAL_INFEASIBLE": 2, "FINAL_FORMAT_FAILURE": 1}
            assert len(tied_cases) == 7
        else:
            assert statuses == {"FINAL_SCOPE_UNKNOWN": 51, "FINAL_CONTEXT_CAP": 12, "FINAL_FORMAT_FAILURE": 1}
        observed[name] = {"original_native_outcomes": dict(outcomes), "delivery_statuses": dict(statuses),
                          "point_proofs": dict(proof), "named_point_work": work, "independent_tied_questions": len(tied_cases)}
    assert data["diagnosis"]["all_wrong_values_already_in_late_thinking"]
    assert len(data["diagnosis"]["wrong_native_finals"]) == 6
    assert not score["gate"]["admitted"] and score["gate"]["strict_independent_verified_regressions"] == 0
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", prior["baseline_commit"], "--"], cwd=ROOT,
    ).decode().split("\0")
    prefix = HERE.relative_to(ROOT).as_posix() + "/"
    assert all(not name or name in {"README.md", "docs/phases/INDEX_ZH.md"} or name.startswith(prefix) for name in changed)
    return {
        "status": "COMPLETE_NO_GO_NO_FEASIBLE_DELIVERY_REGRESSIONS_BEYOND_SIMPLE_CONTROL",
        "baseline_commit": prior["baseline_commit"], "new_gpu_runs": 0,
        "independent_questions": 8, "traces": 64, "verified_label_matches": len(labels),
        "source_paid_tokens": dict(cost), "results": observed, "gate": score["gate"], "evidence_sha256": evidence,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("old-source", "new-source", "blind", "output"):
        cli.add_argument("--"+name, type=Path, required=True)
    args = cli.parse_args()
    out = audit(args.old_source, args.new_source, args.blind)
    write_exclusive(args.output, out)
    print(out["status"], out["gate"])


if __name__ == "__main__":
    main()
