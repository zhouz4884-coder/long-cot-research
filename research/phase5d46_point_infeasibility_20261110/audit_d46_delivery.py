"""Reconcile the complete D4.6 CPU experiment and conditional GPU decision."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import subprocess

from freeze_d46_intake import HERE, ROOT, check_prior, digest, load, sha, write_exclusive
from score_d45_opportunities import accepted_labels


def audit(old: Path, new: Path, blind_path: Path) -> dict:
    prior = check_prior()
    names = {
        "cohort": "D46_COHORT_FREEZE.json", "contracts": "D46_CONTRACTS_FREEZE.json",
        "controls": "D46_CONTROLS_FREEZE.json", "calibration": "D46_DEVELOPMENT_CALIBRATION.json",
        "readout": "D46_CLAIM_READOUT_FREEZE.json", "scope": "D46_SCOPE_AUDIT.json",
        "strict": "D46_BLIND_COMPARISON_FREEZE.json", "sensitivity": "D46_SCOPE_SENSITIVITY_COMPARISON.json",
        "score": "D46_RESULTS.json", "postscore": "D46_POSTSCORE_FAILURE_MODES.json",
    }
    files = {key: HERE / name for key, name in names.items()}
    evidence = {key: sha(path) for key, path in files.items()}
    rows = {key: load(path) for key, path in files.items()}
    cohort, contracts, controls, calibration, score = (rows[k] for k in ("cohort", "contracts", "controls", "calibration", "score"))
    assert cohort["baseline_commit"] == prior["baseline_commit"]
    assert len(cohort["rows"]) == 11 and cohort["planned_trace_count"] == 88
    assert [r["draw"] for r in cohort["source_shards"]] == list(range(8))
    assert Counter(r["direction"] for r in cohort["rows"]) == {"MIN": 9, "MAX": 2}
    assert contracts["cohort_sha256"] == controls["cohort_freeze_sha256"] == evidence["cohort"]
    assert contracts["verifier_source_sha256"] == sha(HERE / "point_verifier.py")
    assert cohort["point_domain_sha256"] == sha(HERE / "d46_point_domains.py")
    assert controls["ordinary_code_sha256"] == sha(HERE / "d46_ordinary_controls.py")
    assert calibration["counts"] == {"old_cases": 3, "strict_old_positive": 1, "prior_blind_review_positive": 1,
                                      "threshold_without_candidate_or_call": 1, "adversarial_controls_without_call": 9}
    assert score["strict_comparison_sha256"] == evidence["strict"] and score["sensitivity_comparison_sha256"] == evidence["sensitivity"]
    assert score["scope_audit_sha256"] == evidence["scope"] and rows["scope"]["decisions"] == {"BOUND": 83}
    assert rows["postscore"]["results_sha256"] == evidence["score"]
    assert score["scorer_sha256"] == sha(HERE / "score_d46_opportunities.py")
    assert rows["readout"]["blind_input_sha256"] == sha(blind_path)

    raw = {r["sample_id"]: r for r in load(blind_path)["rows"]}
    cost = Counter()
    for row in rows["readout"]["rows"]:
        source = raw[row["sample_id"]]
        assert digest(source["response"].encode()) == row["response_sha256"]
        for key in ("input_tokens", "output_tokens"):
            assert source[key] == row[key]
            cost[key] += row[key]
    assert len(raw) == len(rows["readout"]["rows"]) == 88
    assert cost == {"input_tokens": 7880, "output_tokens": 1326510}

    gold = accepted_labels(cohort, old, new)
    exact = {r["case_id"]: r for r in score["label_audit"]}
    assert set(gold) == set(exact) and all(
        gold[cid] == {row["exact_optimum"]} and row["label_status"] == "VALIDATED_LITERAL_OPTIMUM"
        for cid, row in exact.items()
    )
    per_block = {}
    for key, score_key, count, rejects in (("strict", "strict_primary", 11, 1), ("sensitivity", "blind_scope_sensitivity", 83, 6)):
        block, scored = rows[key], score[score_key]
        outcomes, verdicts = Counter(), Counter()
        checked_work = ordinary_work = 0
        denied_cases = set()
        for row in block["rows"]:
            cid = row["case_id"]
            if row["native_final_eligible"]:
                outcome = "correct" if row["native_final_value"] in gold[cid] else "wrong"
            else:
                outcome = "cap" if row["termination"] == "LENGTH_CAP" else "format"
            outcomes[outcome] += 1
            for point in ("early", "late"):
                event = row[point]
                if event["status"] != "BOUND_POINT_CHECKED":
                    continue
                verdict = event["reviewed_point_status"]
                assert verdict == event["ordinary_point_status"]
                receipt = event["reviewed_point_receipt"]
                assert receipt["candidate_sha256"] == event["candidate_sha256"]
                assert receipt["work"] == sum(value for _, value in receipt["operation_charges"])
                checked_work += receipt["work"]
                ordinary_work += event["ordinary_named_work_units"]
                verdicts[verdict] += 1
                if event["reviewed_point_authorizes"]:
                    assert verdict == "PROVEN_INFEASIBLE" and outcome == "wrong"
                    assert not event["weak_refutes"] and not event["one_sided_refutes"]
                    denied_cases.add(cid)
        assert outcomes == {"correct": 73, "wrong": 7, "cap": 7, "format": 1}
        assert verdicts == {"PROVEN_FEASIBLE": count-rejects, "PROVEN_INFEASIBLE": rejects}
        assert len(scored["persistent_verified_points"]) == rejects and denied_cases == {"2011-I-12"}
        assert not scored["false_authorizations"] and not scored["gpu_gate_candidate_questions"]
        assert all(r["complete_target_already_available"] for r in scored["persistent_verified_points"])
        per_block[key] = {"checked_points": count, "point_verdicts": dict(verdicts), "denied_cases": sorted(denied_cases),
                          "native_outcomes": dict(outcomes), "point_named_work": checked_work, "ordinary_named_work": ordinary_work}
    failure = rows["postscore"]["feasible_final_regression"]
    assert failure["thought_optimum"] == 791 and failure["wrong_native_final"] == 533 and failure["both_values_feasible"]
    assert score["gate"] == {"required_independent_eligible_questions": 2, "strict_questions": 0,
                             "strict_false_authorizations": 0, "admitted": False}
    changes = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", prior["baseline_commit"], "--"], cwd=ROOT,
    ).decode().split("\0")
    prefix = HERE.relative_to(ROOT).as_posix() + "/"
    assert all(not p or p in {"README.md", "docs/phases/INDEX_ZH.md"} or p.startswith(prefix) for p in changes)
    return {
        "status": "COMPLETE_NO_GO_ONLY_ONE_INDEPENDENT_POINT_ERROR_CASE_AND_COMPLETE_CONTROL_AVAILABLE",
        "baseline_commit": prior["baseline_commit"], "new_gpu_runs": 0,
        "independent_questions": 11, "traces": 88, "verified_label_matches": len(gold),
        "source_paid_tokens": dict(cost), "results": per_block, "gate": score["gate"], "evidence_sha256": evidence,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("old-source", "new-source", "blind", "output"):
        cli.add_argument("--" + arg, type=Path, required=True)
    args = cli.parse_args()
    out = audit(args.old_source, args.new_source, args.blind)
    write_exclusive(args.output, out)
    print(out["status"], out["gate"])


if __name__ == "__main__":
    main()
