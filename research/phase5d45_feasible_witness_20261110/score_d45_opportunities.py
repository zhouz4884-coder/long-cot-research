"""Score previously frozen opportunities and audit accepted labels against independent optima."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d45_contracts import reconstruct, weak_satisfied
from freeze_d45_intake import load, project, sha, verified_shards, write_exclusive
from freeze_d45_witnesses import verifier


ARMS = ("weak_condition", "ordinary", "witness")
POINTS = ("early", "late")
LABEL_COLUMNS = ("problem_id", "sample_id", "draw_index", "response_sha256", "accepted_answer_integers")


def accepted_labels(cohort: dict, old: Path, new: Path) -> dict:
    _, paths, readback = verified_shards(old, new)
    if readback != cohort["source_shards"]:
        raise ValueError("Gold projection used different data bytes")
    ids = {r["case_id"]: r for r in cohort["rows"]}
    gold = {}
    for draw, path in paths.items():
        samples = project(path, LABEL_COLUMNS, sorted(ids))
        if len(samples) != 11 or {row["problem_id"] for row in samples} != set(ids):
            raise ValueError("Accepted-label denominator changed")
        for row in samples:
            cid = row["problem_id"]
            item, = (x for x in ids[cid]["draws"] if x["draw_index"] == draw)
            if any(row[k] != item[k] for k in ("sample_id", "draw_index", "response_sha256")):
                raise ValueError("Label attached to a different archive draw")
            labels = frozenset(row["accepted_answer_integers"])
            if not labels or not all(type(n) is int and 0 <= n <= 999 for n in labels):
                raise ValueError("Unexpected official output contract")
            if gold.setdefault(cid, labels) != labels:
                raise ValueError("Accepted labels differ across repeated draws")
    return gold


def qualify_labels(cohort: dict, proof: dict, ordinary: dict, oracle: dict, gold: dict, rules: dict) -> dict:
    exact = {row["case_id"]: row for row in oracle["rows"]}
    reviewed = {row["case_id"]: row for row in proof["rows"]}
    controls = {row["case_id"]: row for row in ordinary["questions"]}
    if set(exact) != set(reviewed) or set(exact) != set(controls):
        raise ValueError("Full oracle did not cover the frozen cohort")
    results = {}
    for q in cohort["rows"]:
        cid = q["case_id"]
        solution, contract_record = exact[cid], reviewed[cid]
        contract = reconstruct(contract_record)
        if any(solution[key] != q[key] for key in ("question_sha256", "objective_id", "direction")):
            raise ValueError("Exact oracle was computed for a different mathematical target")
        engine = verifier(contract_record, rules)
        receipt = engine.verify(contract.binding, solution["witness"])
        optimum = solution["optimum"]
        if receipt.status != "CERTIFIED_FEASIBLE_BOUND" or Fraction(receipt.objective) != Fraction(optimum):
            raise ValueError("Exact oracle optimum fails the independent feasibility checker")
        witness_bound = Fraction(controls[cid]["witness_bound"])
        ordinary_bound = Fraction(controls[cid]["ordinary_bound"])
        if q["direction"] == "MAX" and max(witness_bound, ordinary_bound) > optimum:
            raise ValueError("A verified lower bound beats the purported exact optimum")
        if q["direction"] == "MIN" and min(witness_bound, ordinary_bound) < optimum:
            raise ValueError("A verified upper bound beats the purported exact optimum")
        results[cid] = {
            "case_id": cid, "objective_id": q["objective_id"], "direction": q["direction"],
            "label_status": "VALIDATED_LITERAL_OPTIMUM" if gold[cid] == {optimum} else "OFFICIAL_LABEL_CONFLICT",
            "official_values": sorted(gold[cid]), "exact_optimum": optimum,
            "oracle_feasibility_receipt": receipt.as_dict(),
            "oracle_complete_proof": solution["finite_completeness_proof"],
            "ordinary_bound_equals_optimum": ordinary_bound == optimum,
            "witness_bound_equals_optimum": witness_bound == optimum,
            "ordinary_already_proves_optimum": solution["ordinary_proves_optimum"],
            "weak_condition_contains_exact_optimum": weak_satisfied(cid, optimum),
            "oracle_measured_work": solution["work"], "oracle_measured_cpu_ns": solution["cpu_ns"],
            "oracle_measured_wall_ns": solution["wall_ns"],
        }
    return results


def score(comparison: dict, labels: dict) -> dict:
    total = Counter()
    questions = {cid: {"case_id": cid, "status": info["label_status"], "counts": Counter(),
                       "earliest_opportunities": {}, "same_claim_wrong_draws": []}
                 for cid, info in labels.items()}
    cases = []
    for row in comparison["rows"]:
        cid = row["case_id"]
        label = labels[cid]
        case = questions[cid]
        count = case["counts"]
        native_value = row["native_final_value"]
        eligible_final = row["native_final_eligible"]
        if not eligible_final:
            native = "LENGTH_CAP" if row["termination"] == "LENGTH_CAP" else "NO_ELIGIBLE_NATIVE_FINAL"
        else:
            native = "NATIVE_CORRECT" if native_value in label["official_values"] else "NATIVE_WRONG"
        count[native] += 1
        valid = label["label_status"] == "VALIDATED_LITERAL_OPTIMUM"
        per_trace = {"case_id": cid, "sample_id": row["sample_id"], "draw": row["draw"], "native_status": native,
                     "native_final_value": native_value, "label_status": label["label_status"], "points": {}}
        for point in POINTS:
            observed = row[point]
            eligibility = observed["eligibility"]
            event = {"eligibility": eligibility}
            per_trace["points"][point] = event
            if eligibility != "BOUND_INTEGER_OPTIMUM":
                count[point + "_" + eligibility] += 1
                continue
            count[point + "_BOUND_INTEGER_OPTIMUM"] += 1
            value = observed["value"]
            truth = value == label["exact_optimum"]
            persisted_wrong = valid and native == "NATIVE_WRONG" and value == native_value and not truth
            if persisted_wrong:
                case["same_claim_wrong_draws"].append({"draw": row["draw"], "point": point, "value": value})
            event.update({"value": value, "matches_literal_optimum": truth,
                          "same_candidate_in_eligible_wrong_native_final": persisted_wrong})
            if valid and not truth:
                direction = label["direction"]
                optimistic = value > label["exact_optimum"] if direction == "MAX" else value < label["exact_optimum"]
                event["wrong_claim_side"] = "MORE_OPTIMISTIC_THAN_OPTIMUM" if optimistic else "LESS_OPTIMISTIC_THAN_OPTIMUM"
                count[event["wrong_claim_side"]] += 1
            for arm in ARMS:
                refuted = observed[arm + "_refuted"]
                event[arm + "_refuted"] = refuted
                if refuted:
                    count[arm + "_refuted"] += 1
                if valid and truth and refuted:
                    count[arm + "_mathematical_false_authorization"] += 1
                if valid and not truth and refuted and native == "NATIVE_CORRECT":
                    count[arm + "_refuted_before_native_self_correction"] += 1
                if persisted_wrong and refuted:
                    count[arm + "_persistent_opportunities"] += 1
                    previous = case["earliest_opportunities"].get(arm)
                    candidate = {"point": point, "draw": row["draw"], "value": value}
                    if previous is None or (POINTS.index(point), row["draw"]) < (POINTS.index(previous["point"]), previous["draw"]):
                        case["earliest_opportunities"][arm] = candidate
            if persisted_wrong and observed["witness_refuted"] and not (
                observed["weak_condition_refuted"] or observed["ordinary_refuted"]
            ):
                count["incremental_witness_opportunities"] += 1
        cases.append(per_trace)
    for row in questions.values():
        total.update(row["counts"])
        row["counts"] = dict(row["counts"])
    per_arm = {arm: [cid for cid, row in questions.items() if arm in row["earliest_opportunities"]] for arm in ARMS}
    incremental = [cid for cid, row in questions.items() if row["counts"].get("incremental_witness_opportunities")]
    return {
        "trace_count": len(cases), "question_count": len(questions), "counts": dict(total),
        "independent_opportunity_questions_by_arm": per_arm, "incremental_witness_question_ids": incremental,
        "question_rows": list(questions.values()), "trace_rows": cases,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("cohort", "witness", "ordinary-freeze", "oracle", "rules", "strict", "sensitivity",
                 "old-source", "new-source", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--expected-strict-sha256", required=True)
    cli.add_argument("--expected-sensitivity-sha256", required=True)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Refuse to overwrite a scored result")
    began, cpu = perf_counter_ns(), thread_time_ns()
    if sha(args.strict) != args.expected_strict_sha256 or sha(args.sensitivity) != args.expected_sensitivity_sha256:
        raise ValueError("Prelabel frozen comparison SHA differs")
    cohort, proof, ordinary_freeze, rules, strict, sensitivity = map(
        load, (args.cohort, args.witness, args.ordinary_freeze, args.rules, args.strict, args.sensitivity),
    )
    if any(
        block["status"] != "D45_ALL_MATCHED_COMPARISONS_FROZEN_WITHOUT_GOLD"
        or block["cohort_freeze_sha256"] != sha(args.cohort)
        or block["witness_freeze_sha256"] != sha(args.witness)
        or block["ordinary_freeze_sha256"] != sha(args.ordinary_freeze)
        or block["rules_sha256"] != sha(args.rules)
        for block in (strict, sensitivity)
    ):
        raise ValueError("Prelabel selection and control bindings differ")
    if sha(args.oracle) != ordinary_freeze["complete_oracles_sha256"]:
        raise ValueError("Complete oracle freeze differs")
    oracle = load(args.oracle)
    gold = accepted_labels(cohort, args.old_source, args.new_source)
    labels = qualify_labels(cohort, proof, strict, oracle, gold, rules)
    strict_score, sensitivity_score = score(strict, labels), score(sensitivity, labels)
    incremental = strict_score["incremental_witness_question_ids"]
    false = strict_score["counts"].get("witness_mathematical_false_authorization", 0)
    report = {
        "status": "D45_FROZEN_OPPORTUNITIES_SCORED",
        "cohort_sha256": sha(args.cohort), "strict_comparison_sha256": sha(args.strict),
        "sensitivity_comparison_sha256": sha(args.sensitivity), "oracle_sha256": sha(args.oracle),
        "scorer_sha256": sha(Path(__file__)), "label_audit": list(labels.values()),
        "strict_primary": strict_score, "blind_scope_sensitivity": sensitivity_score,
        "gate": {"required_incremental_independent_questions": 2, "observed_incremental_independent_questions": len(incremental),
                 "false_mathematical_authorizations": false, "admitted": len(incremental) >= 2 and false == 0},
        "wall_ns": perf_counter_ns() - began, "cpu_ns": thread_time_ns() - cpu,
    }
    write_exclusive(args.output, report)
    print(report["status"], report["gate"], sha(args.output))


if __name__ == "__main__":
    main()
