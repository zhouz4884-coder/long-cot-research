"""Score exact prelabel D4.7 outputs and audit the complete mathematical controls."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d47_contracts import reconstruct
from d47_ordinary_controls import ordinary_point
from d47_point_domains import check
from freeze_d47_intake import load, project, sha, verified_shards, write_exclusive
from point_verifier import PROVEN_FEASIBLE, WorkMeter

LABEL_COLUMNS = ("problem_id", "sample_id", "draw_index", "response_sha256", "accepted_answer_integers")


def accepted_labels(cohort, old, new):
    _, paths, assets = verified_shards(old, new)
    if assets != cohort["source_shards"]:
        raise ValueError("Gold source differs from frozen archived bytes")
    cases = {r["case_id"]: r for r in cohort["rows"]}
    result = {}
    for draw, path in paths.items():
        rows = project(path, LABEL_COLUMNS, sorted(cases))
        if len(rows) != len(cases) or {r["problem_id"] for r in rows} != set(cases):
            raise ValueError("Gold source denominator differs")
        for row in rows:
            cid = row["problem_id"]
            expected, = (r for r in cases[cid]["draws"] if r["draw_index"] == draw)
            if any(row[k] != expected[k] for k in ("sample_id", "draw_index", "response_sha256")):
                raise ValueError("Gold attached to another draw")
            values = frozenset(row["accepted_answer_integers"])
            if not values or any(type(v) is not int or not 0 <= v <= 999 for v in values):
                raise ValueError("Unexpected official scalar contract")
            if result.setdefault(cid, values) != values:
                raise ValueError("Gold changes between archived repeated draws")
    return result


def labels_audit(cohort, contracts, oracle, gold, complete_scope):
    exact = {r["case_id"]: r for r in oracle["rows"]}
    proof = {r["case_id"]: r for r in contracts["rows"]}
    if set(exact) != set(gold) or set(proof) != set(gold) or set(complete_scope["question_scope"]) != set(gold):
        raise ValueError("Complete solve did not cover the frozen cohort")
    result = {}
    for case in cohort["rows"]:
        cid = case["case_id"]
        row, contract = exact[cid], reconstruct(proof[cid])
        if row["question_sha256"] != case["question_sha256"] or row["direction"] != case["direction"]:
            raise ValueError("Complete solver used a different original scope")
        value = row["optimum"]
        meter, control = WorkMeter(20_000), WorkMeter(20_000)
        verified = check(contract.binding, Fraction(value), meter)
        if verified.status != PROVEN_FEASIBLE or ordinary_point(cid, Fraction(value), control) is not True:
            raise ValueError("Complete optimum is not independently feasible")
        result[cid] = {
            "case_id": cid, "direction": case["direction"], "unit": case["unit"], "optimum": value,
            "official_values": sorted(gold[cid]), "label_status": "VALIDATED_LITERAL_OPTIMUM" if gold[cid] == {value} else "OFFICIAL_LABEL_CONFLICT",
            "ordinary_complete_proof": row["complete_proof"], "complete_control_scope": complete_scope["question_scope"][cid],
            "exact_solver_work": row["exact_solver_work"], "optimum_point_validation_work": row["optimum_point_validation_work"],
            "independent_validation_point_work": dict(meter._charges), "independent_ordinary_point_work": dict(control._charges),
        }
    return result


def correctness(value, gold):
    return None if value is None else Fraction(value) in gold


def score(comparison, labels, roles):
    totals, decisions, costs = Counter(), Counter(), Counter()
    cases = {cid: {"case_id": cid, "native": Counter(), "decisions": Counter(), "verified_regressions": [],
                   "simple_retention_repairs": 0, "numeric_only_harms": 0}
             for cid in labels}
    regressions, false, trace_rows = [], [], []
    residual = set()
    for row in comparison["rows"]:
        cid, sid = row["case_id"], row["sample_id"]
        label, case = labels[cid], cases[cid]
        correct = correctness(row["native_final_value"], label["official_values"])
        outcome = ("NATIVE_CORRECT" if correct else "NATIVE_WRONG") if correct is not None else (
            "LENGTH_CAP" if row["termination"] == "LENGTH_CAP" else "NO_ELIGIBLE_NATIVE_FINAL"
        )
        totals[outcome] += 1
        case["native"][outcome] += 1
        decision, naive = row["preservation"]["decision"], row["naive_best_verified"]
        status = decision["status"]
        decisions[status] += 1
        case["decisions"][status] += 1
        proposed = correctness(decision["proposed_value"], label["official_values"])
        simple = correctness(naive["proposed_value"], label["official_values"])
        raw_numeric = correctness(row["numeric_only_value"], label["official_values"])
        if row["same_scalar_as_naive"]:
            totals["PRESERVATION_EQUALS_NAIVE"] += 1
        if proposed:
            totals["PRESERVATION_CORRECT"] += 1
        if simple:
            totals["NAIVE_CORRECT"] += 1
        if raw_numeric:
            totals["NUMERIC_ONLY_CORRECT"] += 1
        if correct is True and raw_numeric is False:
            totals["NUMERIC_ONLY_HARM"] += 1
            case["numeric_only_harms"] += 1
        if correct is False and simple:
            totals["NAIVE_REPAIR"] += 1
            case["simple_retention_repairs"] += 1
        ledger = row["custody_work"]
        costs.update({k: ledger[k] for k in ("custody_requests", "point_checker_calls", "point_work", "custody_cpu_ns", "custody_wall_ns")})
        costs["ordinary_point_named_work"] += sum(row["ordinary_work"].values())
        costs["preserver_comparisons"] += decision["comparison_operations"] + sum(
            item["comparison_operations"] for item in row["preservation"]["updates"])
        costs["naive_comparisons"] += naive["comparison_operations"]
        for slot, item in row["slot_checks"].items():
            if item["status"] == "NO_SCOPE_AUTHORITY":
                continue
            totals["POINT_CHECK_"+slot] += 1
            totals["VERDICT_"+str(item["proof_status"])] += 1
            if item["proof_status"] != item["ordinary"]["status"]:
                totals["POINT_STATUS_DISAGREEMENT"] += 1
        if decision["action"] == "RETAIN_CERTIFIED_INCUMBENT":
            incumbent_slot, = (slot for slot in ("early", "late")
                               if row["slot_checks"][slot].get("ticket", {}).get("receipt_sha256") == decision["incumbent_ticket_sha256"])
            role_checks = [roles.get(sid+"@"+slot, "UNKNOWN") for slot in (incumbent_slot, "final_point")]
            valid_label = label["label_status"] == "VALIDATED_LITERAL_OPTIMUM"
            if "WRONG_OBJECT" in role_checks or (valid_label and correct is True and proposed is False):
                false.append({"case_id": cid, "sample_id": sid, "reason": "WRONG_OBJECT_OR_NATIVE_CORRECT_HARM"})
            if status == "FEASIBLE_REGRESSION" and valid_label and correct is False and role_checks == ["BOUND", "BOUND"]:
                item = {"case_id": cid, "sample_id": sid, "earlier_stage": incumbent_slot,
                        "earlier_feasible": decision["incumbent_value"], "native_final_feasible": row["native_final_value"],
                        "preservation_repairs": proposed is True, "naive_repairs": simple is True,
                        "complete_ordinary_control_available": bool(
                            label["ordinary_complete_proof"] and label["complete_control_scope"])}
                case["verified_regressions"].append(item)
                regressions.append(item)
                if simple is not True and not item["complete_ordinary_control_available"]:
                    residual.add(cid)
        trace_rows.append({"case_id": cid, "sample_id": sid, "native_outcome": outcome, "native_value": row["native_final_value"],
                           "preserved_value": decision["proposed_value"], "naive_value": naive["proposed_value"],
                           "numeric_only_value": row["numeric_only_value"], "delivery_status": status,
                           "preservation_correct": proposed, "naive_correct": simple, "numeric_only_correct": raw_numeric})
    for case in cases.values():
        case["native"] = dict(case["native"])
        case["decisions"] = dict(case["decisions"])
    return {"trace_count": len(trace_rows), "independent_question_count": len(cases), "totals": dict(totals),
            "decisions": dict(decisions), "verified_regressions": regressions, "verified_regression_questions": sorted({r["case_id"] for r in regressions}),
            "unresolved_questions_beyond_same_evidence_and_complete_control": sorted(residual),
            "false_authorizations": false, "work": dict(costs), "case_rows": list(cases.values()), "trace_rows": trace_rows}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("cohort", "contracts", "controls", "oracle", "complete-scope", "strict", "sensitivity",
                 "scope-audit", "old-source", "new-source", "output"):
        cli.add_argument("--"+name, type=Path, required=True)
    cli.add_argument("--expected-strict-sha256", required=True)
    cli.add_argument("--expected-sensitivity-sha256", required=True)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Refuse to overwrite scored D4.7 results")
    begin, cpu = perf_counter_ns(), thread_time_ns()
    if (sha(args.strict), sha(args.sensitivity)) != (args.expected_strict_sha256, args.expected_sensitivity_sha256):
        raise ValueError("Prelabel comparison SHA differs")
    cohort, contracts, controls, complete_scope, strict, sensitivity, scope = map(
        load, (args.cohort, args.contracts, args.controls, args.complete_scope, args.strict, args.sensitivity, args.scope_audit),
    )
    for block in (strict, sensitivity):
        if (block["status"] != "D47_BLIND_DELIVERY_COMPARISONS_FROZEN_WITHOUT_GOLD"
                or block["input_sha256"]["cohort"] != sha(args.cohort)
                or block["input_sha256"]["contracts"] != sha(args.contracts)
                or block["input_sha256"]["controls"] != sha(args.controls)):
            raise ValueError("Delivery decisions not tied to prelabel freezes")
    if scope["strict_readout_sha256"] != strict["input_sha256"]["readout"]:
        raise ValueError("Scope review belongs to a different strict readout")
    if sha(args.oracle) != controls["private_payloads"]["exact_oracles.json"]["sha256"]:
        raise ValueError("Complete question-only solver output changed")
    oracle = load(args.oracle)
    gold = accepted_labels(cohort, args.old_source, args.new_source)
    labels = labels_audit(cohort, contracts, oracle, gold, complete_scope)
    roles = {row["job_id"]: row["decision"] for row in scope["rows"]}
    primary, sensitive = score(strict, labels, roles), score(sensitivity, labels, roles)
    gate = {
        "required_independent_regression_questions": 2,
        "strict_independent_verified_regressions": len(primary["verified_regression_questions"]),
        "strict_unresolved_independent_questions": len(primary["unresolved_questions_beyond_same_evidence_and_complete_control"]),
        "strict_false_authorizations": len(primary["false_authorizations"]),
        "admitted": len(primary["unresolved_questions_beyond_same_evidence_and_complete_control"]) >= 2 and not primary["false_authorizations"],
    }
    result = {"status": "D47_FROZEN_DELIVERY_COMPARISONS_SCORED", "cohort_sha256": sha(args.cohort),
              "strict_sha256": sha(args.strict), "sensitivity_sha256": sha(args.sensitivity), "scope_audit_sha256": sha(args.scope_audit),
              "oracle_sha256": sha(args.oracle), "complete_scope_sha256": sha(args.complete_scope),
              "scorer_sha256": sha(Path(__file__)), "label_audit": list(labels.values()), "strict_primary": primary,
              "blind_scope_sensitivity": sensitive, "gate": gate, "wall_ns": perf_counter_ns()-begin, "cpu_ns": thread_time_ns()-cpu}
    write_exclusive(args.output, result)
    print(result["status"], gate, sha(args.output))


if __name__ == "__main__":
    main()
