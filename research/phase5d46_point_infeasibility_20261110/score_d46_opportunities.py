"""Score frozen point proofs only after exact scope and comparison hashes are fixed."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d46_contracts import reconstruct, weak_satisfied
from d46_ordinary_controls import ordinary_point
from d46_point_domains import check
from freeze_d46_intake import HERE, load, sha, write_exclusive
from point_verifier import PROVEN_FEASIBLE, PROVEN_INFEASIBLE, WorkMeter
from score_d45_opportunities import accepted_labels

POINTS = ("early", "late")


def audit_labels(cohort, contracts, oracle, supplement, labels):
    proof = {r["case_id"]: r for r in contracts["rows"]}
    exact = {r["case_id"]: r for r in oracle["rows"]}
    alternative = {r["case_id"]: r for r in supplement["rows"]}
    if len(exact) != 11 or set(exact) != set(labels) or set(exact) != set(proof):
        raise ValueError("Complete oracle denominator changed")
    result = {}
    for case in cohort["rows"]:
        cid = case["case_id"]
        row, record = exact[cid], proof[cid]
        contract = reconstruct(record)
        if any(row[k] != case[k] for k in ("question_sha256", "direction")):
            raise ValueError("Exact optimum bound to a different question")
        optimum = row["optimum"]
        meter = WorkMeter(100_000)
        evidence = check(contract.binding, Fraction(optimum), meter)
        control_meter = WorkMeter(100_000)
        if evidence.status != PROVEN_FEASIBLE or ordinary_point(cid, Fraction(optimum), control_meter) is not True:
            raise ValueError(f"Exact optimum did not pass independent point validation: {cid}")
        alternate = alternative.get(cid)
        if alternate is not None and (alternate["optimum"] != optimum or alternate["question_sha256"] != case["question_sha256"]):
            raise ValueError("Compact structural complete control disagrees with exact oracle")
        closed = record["structural_full_control"]
        if cid == "2021-II-15":
            closed = alternate["completeness_argument"]
        # 2013 supplement is compact but separate validation adds work to the single-root point check.
        result[cid] = {
            "case_id": cid, "official_values": sorted(labels[cid]), "exact_optimum": optimum,
            "label_status": "VALIDATED_LITERAL_OPTIMUM" if labels[cid] == {optimum} else "OFFICIAL_LABEL_CONFLICT",
            "ordinary_complete_proof": row["proof"], "complete_paid_work": row["paid_work"],
            "complete_validation_paid_work": row["validation_paid_work"],
            "exact_optimum_is_feasible": True, "weak_condition_contains_optimum": weak_satisfied(cid, Fraction(optimum)),
            "independent_point_validation_work": dict(meter._charges),
            "ordinary_point_validation_work": dict(control_meter._charges),
            "closed_form_or_smaller_complete_control": closed,
            "supplementary_complete_control": alternate,
        }
    return result


def summarize(comparison, labels, scope_review):
    total = Counter()
    questions = {cid: {"case_id": cid, "native": Counter(), "points": Counter(),
                       "opportunities": [], "same_permission_complete_control": bool(row["closed_form_or_smaller_complete_control"])}
                 for cid, row in labels.items()}
    traces = []
    false = []
    attributable = []
    eligible_new = set()
    direct_opportunities = set()
    for row in comparison["rows"]:
        cid, sid = row["case_id"], row["sample_id"]
        q, label = questions[cid], labels[cid]
        final = row["native_final_value"]
        if row["native_final_eligible"]:
            outcome = "NATIVE_CORRECT" if final in label["official_values"] else "NATIVE_WRONG"
        else:
            outcome = "LENGTH_CAP" if row["termination"] == "LENGTH_CAP" else "NO_ELIGIBLE_NATIVE_FINAL"
        q["native"][outcome] += 1
        total[outcome] += 1
        valid = label["label_status"] == "VALIDATED_LITERAL_OPTIMUM"
        scored = {"case_id": cid, "sample_id": sid, "draw_index": row["draw_index"],
                  "official_native_status": outcome, "final_value": final, "points": {}}
        for point in POINTS:
            entry = row[point]
            if entry["status"] != "BOUND_POINT_CHECKED":
                scored["points"][point] = {"status": entry["status"], "observation": entry.get("observation_status")}
                continue
            value = Fraction(entry["value"])
            authority = entry["reviewed_point_authorizes"]
            verdict = entry["reviewed_point_status"]
            ordinary = entry["ordinary_point_status"]
            role = scope_review.get(sid+"@"+point)
            misbound = role is not None and role["decision"] == "WRONG_OBJECT"
            verified_scope = role is not None and role["decision"] == "BOUND"
            matched_wrong = valid and outcome == "NATIVE_WRONG" and final is not None and value == final
            q["points"][point+"_BOUND"] += 1
            q["points"][verdict] += 1
            total[point+"_BOUND"] += 1
            total[verdict] += 1
            event = {
                "value": str(value), "reviewed_point_status": verdict, "authorized": authority,
                "ordinary_status": ordinary, "weak_refutes": entry["weak_refutes"], "one_sided_refutes": entry["one_sided_refutes"],
                "role_audit": None if role is None else role["decision"], "literal_optimum": value == label["exact_optimum"],
                "same_value_as_eligible_wrong_delivery": matched_wrong,
            }
            if ordinary != verdict:
                total["POINT_STATUS_DISAGREEMENT"] += 1
            if authority and ((valid and value == label["exact_optimum"]) or misbound):
                false.append({"case_id": cid, "sample_id": sid, "point": point,
                              "reason": "WRONG_OBJECT" if misbound else "ACTUAL_OPTIMUM_REJECTED"})
            if authority and valid and not misbound and outcome == "NATIVE_CORRECT" and value != label["exact_optimum"]:
                total["AUTHORIZED_BEFORE_NATIVE_SELF_CORRECTION"] += 1
            if matched_wrong and authority and verified_scope:
                covered = ordinary == PROVEN_INFEASIBLE
                row_out = {"case_id": cid, "sample_id": sid, "point": point, "value": str(value),
                           "ordinary_point_also_rejects": covered, "weak_refutes": entry["weak_refutes"],
                           "one_sided_refutes": entry["one_sided_refutes"],
                           "complete_target_already_available": q["same_permission_complete_control"]}
                q["opportunities"].append(row_out)
                attributable.append(row_out)
                if covered:
                    direct_opportunities.add(cid)
                if not q["same_permission_complete_control"]:
                    eligible_new.add(cid)
            scored["points"][point] = event
        traces.append(scored)
    for q in questions.values():
        q["native"] = dict(q["native"])
        q["points"] = dict(q["points"])
    return {"independent_question_count": len(questions), "trace_count": len(traces), "totals": dict(total),
            "persistent_verified_points": attributable, "ordinary_point_opportunity_cases": sorted(direct_opportunities),
            "gpu_gate_candidate_questions": sorted(eligible_new), "false_authorizations": false,
            "question_rows": list(questions.values()), "trace_rows": traces}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("cohort", "contracts", "controls", "oracle", "supplement", "strict", "sensitivity", "scope-audit",
                "old-source", "new-source", "output"):
        cli.add_argument("--" + key, type=Path, required=True)
    cli.add_argument("--expected-strict-sha256", required=True)
    cli.add_argument("--expected-sensitivity-sha256", required=True)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Refuse to overwrite a scored result")
    began, cpu = perf_counter_ns(), thread_time_ns()
    if (sha(args.strict), sha(args.sensitivity)) != (args.expected_strict_sha256, args.expected_sensitivity_sha256):
        raise ValueError("Pre-gold comparison freezes differ from the requested hashes")
    cohort, contracts, controls, supplement, strict, sensitive, scope = map(
        load, (args.cohort, args.contracts, args.controls, args.supplement, args.strict, args.sensitivity, args.scope_audit),
    )
    for block in (strict, sensitive):
        if (block["status"] != "D46_BLIND_POINT_COMPARISONS_FROZEN_WITHOUT_GOLD"
                or block["input_sha256"]["cohort"] != sha(args.cohort)
                or block["input_sha256"]["contracts"] != sha(args.contracts)
                or block["input_sha256"]["controls"] != sha(args.controls)):
            raise ValueError("Scope and label authorization freezes do not agree")
    if scope["strict_claims_sha256"] != strict["input_sha256"]["claims"] or supplement["cohort_sha256"] != sha(args.cohort):
        raise ValueError("Scope or supplemental proof is tied to a different freeze")
    if sha(args.oracle) != controls["private_payloads"]["exact_oracles.json"]["sha256"]:
        raise ValueError("Complete solution file changed")
    exact = load(args.oracle)
    gold = accepted_labels(cohort, args.old_source, args.new_source)
    labels = audit_labels(cohort, contracts, exact, supplement, gold)
    review = {r["job_id"]: r for r in scope["rows"]}
    primary, sensitivity = summarize(strict, labels, review), summarize(sensitive, labels, review)
    gate = {
        "required_independent_eligible_questions": 2,
        "strict_questions": len(primary["gpu_gate_candidate_questions"]),
        "strict_false_authorizations": len(primary["false_authorizations"]),
        "admitted": len(primary["gpu_gate_candidate_questions"]) >= 2 and not primary["false_authorizations"],
    }
    result = {
        "status": "D46_FROZEN_POINT_OPPORTUNITIES_SCORED",
        "cohort_sha256": sha(args.cohort), "strict_comparison_sha256": sha(args.strict),
        "sensitivity_comparison_sha256": sha(args.sensitivity), "scope_audit_sha256": sha(args.scope_audit),
        "oracle_sha256": sha(args.oracle), "scorer_sha256": sha(Path(__file__)),
        "label_audit": list(labels.values()), "strict_primary": primary, "blind_scope_sensitivity": sensitivity,
        "gate": gate, "wall_ns": perf_counter_ns()-began, "cpu_ns": thread_time_ns()-cpu,
    }
    write_exclusive(args.output, result)
    print(result["status"], gate, sha(args.output))


if __name__ == "__main__":
    main()
