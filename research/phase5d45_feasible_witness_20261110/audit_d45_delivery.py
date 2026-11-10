"""Reconcile D4.5 source, blind receipts, costs and the conditional GPU gate."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
import subprocess

from freeze_d45_intake import HERE, ROOT, check_prior, digest, load, sha, write_exclusive
from score_d45_opportunities import accepted_labels


def audit(old: Path, new: Path, blind_path: Path) -> dict:
    prior = check_prior()
    names = {
        "cohort": "D45_COHORT_FREEZE.json", "witness": "D45_WITNESS_FREEZE.json",
        "ordinary": "D45_ORDINARY_CONTROLS_FREEZE.json", "calibration": "D45_DEVELOPMENT_CALIBRATION.json",
        "strict_readout": "D45_CLAIM_READOUT_FREEZE.json", "scope_audit": "D45_SCOPE_SENSITIVITY_AUDIT.json",
        "strict": "D45_BLIND_COMPARISON_FREEZE.json", "sensitivity": "D45_SCOPE_SENSITIVITY_COMPARISON.json",
        "score": "D45_RESULTS.json", "postscore": "D45_POSTSCORE_DIAGNOSTICS.json",
    }
    files = {key: HERE / name for key, name in names.items()}
    evidence = {key: sha(path) for key, path in files.items()}
    rows = {key: load(path) for key, path in files.items()}
    cohort, witness, ordinary, score = (rows[k] for k in ("cohort", "witness", "ordinary", "score"))
    assert cohort["baseline_commit"] == prior["baseline_commit"]
    assert len(cohort["rows"]) == 11 and cohort["planned_trace_count"] == 88
    assert Counter(row["direction"] for row in cohort["rows"]) == {"MIN": 9, "MAX": 2}
    assert [row["draw"] for row in cohort["source_shards"]] == list(range(8))
    assert witness["cohort_freeze_sha256"] == ordinary["cohort_freeze_sha256"] == evidence["cohort"]
    assert witness["verifier_source_sha256"] == sha(HERE / "feasible_witness.py")
    assert ordinary["control_source_sha256"] == sha(HERE / "d45_ordinary_controls.py")
    assert score["strict_comparison_sha256"] == evidence["strict"] and score["sensitivity_comparison_sha256"] == evidence["sensitivity"]
    assert rows["postscore"]["results_sha256"] == evidence["score"]
    assert rows["scope_audit"]["strict_readout_sha256"] == evidence["strict_readout"]
    assert rows["scope_audit"]["review_decisions"] == {"BOUND": 55, "UNKNOWN": 3}
    assert rows["strict_readout"]["blind_input_sha256"] == sha(blind_path)
    assert score["scorer_sha256"] == sha(HERE / "score_d45_opportunities.py")

    raw = {row["sample_id"]: row for row in load(blind_path)["rows"]}
    source_cost = {"input_tokens": 0, "output_tokens": 0}
    for row in rows["strict_readout"]["rows"]:
        sample = raw[row["sample_id"]]
        assert digest(sample["response"].encode()) == row["response_sha256"]
        for key in source_cost:
            assert sample[key] == row[key]
            source_cost[key] += row[key]
    assert len(raw) == len(rows["strict_readout"]["rows"]) == 88
    assert source_cost == {"input_tokens": 8392, "output_tokens": 1536889}

    labels = accepted_labels(cohort, old, new)
    exact = {row["case_id"]: row for row in score["label_audit"]}
    assert set(labels) == set(exact) and all(labels[cid] == {row["exact_optimum"]} for cid, row in exact.items())
    assert all(row["ordinary_bound_equals_optimum"] and row["weak_condition_contains_exact_optimum"] for row in exact.values())
    assert sum(row["ordinary_already_proves_optimum"] for row in exact.values()) == 9
    assert sum(row["witness_bound_equals_optimum"] for row in exact.values()) == 6
    counts = Counter(r["status"] for item in witness["rows"] for r in item["independent_witness_receipts"])
    assert counts == {"CERTIFIED_FEASIBLE_BOUND": 15, "WITNESS_INFEASIBLE": 3}
    assert all(item["adversarial_control"]["receipt"]["status"] == "WITNESS_INFEASIBLE" for item in witness["rows"])
    assert len(witness["rows"]) == 11
    assert all(row["label_status"] == "VALIDATED_LITERAL_OPTIMUM" for row in exact.values())

    observed = {}
    for label, score_key, expected in (
        ("strict", "strict_primary", 15), ("sensitivity", "blind_scope_sensitivity", 70),
    ):
        block = rows[label]
        count, native, authorized = 0, Counter(), Counter()
        bounds = {r["case_id"]: r for r in block["questions"]}
        for row in block["rows"]:
            cid = row["case_id"]
            if row["native_final_eligible"]:
                native["correct" if row["native_final_value"] in labels[cid] else "wrong"] += 1
            else:
                assert row["termination"] == "LENGTH_CAP"
                native["cap"] += 1
            for point in ("early", "late"):
                event = row[point]
                if event["eligibility"] != "BOUND_INTEGER_OPTIMUM":
                    continue
                count += 1
                for arm in ("witness", "ordinary"):
                    bound = Fraction(bounds[cid][arm + "_bound"])
                    value = event["value"]
                    direct = value < bound if exact[cid]["direction"] == "MAX" else value > bound
                    assert direct == event[arm + "_refuted"]
                for arm in ("weak_condition", "witness", "ordinary"):
                    authorized[arm] += event[arm + "_refuted"]
        assert count == expected and block["work"]["weak_necessary_evaluations"] == expected
        assert native == {"correct": 65, "wrong": 2, "cap": 21} and not any(authorized.values())
        assert not score[score_key]["incremental_witness_question_ids"]
        observed[label] = {"exact_scoped_observations": count, "native_outcomes": dict(native),
                           "observed_authorizations": dict(authorized)}
    assert score["gate"] == {"required_incremental_independent_questions": 2,
                             "observed_incremental_independent_questions": 0,
                             "false_mathematical_authorizations": 0, "admitted": False}
    diagnosis = rows["postscore"]
    assert diagnosis["early_false_binding"]["semantic_role"] == "THRESHOLD_ON_FLOOR_LOG_SUM_NOT_AN_ASSERTED_INPUT"
    assert [row["value"] for row in diagnosis["true_persistent_wrong_candidates"]] == [23, 397]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", prior["baseline_commit"], "--"], cwd=ROOT,
    ).decode().split("\0")
    prefix = HERE.relative_to(ROOT).as_posix() + "/"
    assert all(not path or path in {"README.md", "docs/phases/INDEX_ZH.md"} or path.startswith(prefix) for path in changed)
    return {
        "status": "COMPLETE_NO_GO_NO_INCREMENTAL_FEASIBLE_WITNESS_OPPORTUNITIES",
        "baseline_commit": prior["baseline_commit"], "independent_questions": 11, "traces": 88,
        "verified_official_label_matches": len(labels), "new_gpu_runs": 0,
        "source_generation_tokens": source_cost, "results": observed, "gate": score["gate"],
        "evidence_sha256": evidence,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("old-source", "new-source", "blind", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    report = audit(args.old_source, args.new_source, args.blind)
    write_exclusive(args.output, report)
    print(report["status"], report["gate"])


if __name__ == "__main__":
    main()
