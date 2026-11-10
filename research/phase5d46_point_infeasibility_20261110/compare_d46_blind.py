"""Freeze point proofs and controls on actual observed prefixes before scoring."""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d46_contracts import canonical, reconstruct, weak_satisfied
from d46_ordinary_controls import ordinary_point
from d46_point_domains import check
from freeze_d46_intake import HERE, digest, load, sha, write_exclusive
from point_verifier import (
    ASSERTED_ORIGINAL_CANDIDATE, PROVEN_FEASIBLE, PROVEN_INFEASIBLE,
    UNKNOWN, CandidateReceipt, PointVerifier, WorkMeter, _BudgetExhausted, exact_literal,
)


POINTS = ("early", "late")


def issue(row, point, observation, sample, binding, policy_sha):
    start, stop = observation["observation_char_span_in_response"]
    prefix = sample["response"][start:stop]
    ast, aend = observation["assertion_span"]
    nstart, nend = observation["numeric_span"]
    literal = observation["numeric_text"]
    if not (
        digest(prefix.encode()) == observation["observation_prefix_sha256"]
        and 0 <= ast <= nstart < nend <= aend <= len(prefix)
        and prefix[nstart:nend] == literal
        and digest(prefix[ast:aend].encode()) == observation["assertion_sha256"]
        and exact_literal(literal) == Fraction(observation["value"])
        and observation["assertion_role"] == ASSERTED_ORIGINAL_CANDIDATE
        and observation["direction"] == binding.direction
    ):
        raise ValueError(f"Source assertion or candidate literal changed: {row['sample_id']} {point}")
    review = canonical({"issuer": policy_sha, "sample_id": row["sample_id"], "point": point,
                        "source_assertion": observation["assertion_sha256"], "scope": binding.scope_sha256,
                        "independent_role_review": observation.get("scope_review_sha256")})
    receipt = CandidateReceipt(
        binding, row["sample_id"], row["response_sha256"], observation["observation_prefix_sha256"],
        (nstart, nend), literal, (ast, aend), observation["assertion_sha256"], ASSERTED_ORIGINAL_CANDIDATE, review,
    )
    return receipt, prefix


def compare(args) -> dict:
    began, cpu = perf_counter_ns(), thread_time_ns()
    paths = {k: getattr(args, k) for k in ("cohort", "claims", "blind", "contracts", "controls", "bounds", "rules")}
    data = {k: load(path) for k, path in paths.items()}
    shas = {k: sha(path) for k, path in paths.items()}
    cohort, claims, blind, contracts, controls, bounds, rules = (
        data[k] for k in ("cohort", "claims", "blind", "contracts", "controls", "bounds", "rules")
    )
    if not (
        claims["status"] == "FROZEN_D46_SCOPE_BOUND_POINTS_WITHOUT_GOLD"
        and claims["cohort_freeze_sha256"] == contracts["cohort_sha256"] == controls["cohort_freeze_sha256"] == shas["cohort"]
        and blind["cohort_freeze_sha256"] == shas["cohort"]
        and claims["blind_input_sha256"] == shas["blind"]
        and cohort["gate_rules_sha256"] == shas["rules"]
        and cohort["observation_rules_sha256"] == claims["observation_rules_sha256"]
        and contracts["contract_source_sha256"] == sha(HERE / "d46_contracts.py")
        and contracts["verifier_source_sha256"] == sha(HERE / "point_verifier.py")
        and cohort["point_domain_sha256"] == sha(HERE / "d46_point_domains.py")
        and controls["ordinary_code_sha256"] == sha(HERE / "d46_ordinary_controls.py")
        and controls["private_payloads"]["simple_bounds.json"]["sha256"] == shas["bounds"]
        and claims["extractor_sha256"] == sha(HERE / "extract_d46_points.py")
    ):
        raise ValueError("Point comparison inputs differ from prelabel source bindings")
    by_question = {row["case_id"]: row for row in contracts["rows"]}
    by_bound = {row["case_id"]: row for row in bounds["rows"]}
    by_sample = {row["sample_id"]: row for row in blind["rows"]}
    if len(by_question) != 11 or set(by_question) != set(by_bound) or len(by_sample) != 88:
        raise ValueError("Original point experiment denominator changed")
    if len(claims["rows"]) != 88 or {row["sample_id"] for row in claims["rows"]} != set(by_sample):
        raise ValueError("Different scope readout cohort")
    issued = {}
    approvals = defaultdict(list)
    for row in claims["rows"]:
        sample = by_sample[row["sample_id"]]
        cid = row["case_id"]
        contract = reconstruct(by_question[cid])
        if row["question_sha256"] != contract.binding.question_sha256 or sample["response_sha256"] != row["response_sha256"]:
            raise ValueError("Claim refers to a different question or response")
        for point in POINTS:
            obs = row[point]
            if obs["status"] != "EXPLICIT_SCOPED_POINT" or obs["scope_status"] != "ORIGINAL_REQUESTED_SCALAR":
                continue
            receipt, prefix = issue(row, point, obs, sample, contract.binding, shas["claims"])
            issued[row["sample_id"], point] = (receipt, prefix)
            approvals[cid].append(receipt.sha256)

    work_limit = rules["bounded_named_work_units_per_case_per_arm"]
    call_limit = rules["bounded_calls_per_case_per_arm"]
    engines, ordinary_meters, bound_reports, ordinary_calls = {}, {}, [], defaultdict(int)
    for cid, record in by_question.items():
        contract = reconstruct(record)
        engines[cid] = PointVerifier(
            contract, record["contract_sha256"], check, approved_candidate_sha256=approvals[cid],
            call_budget=call_limit, work_budget=work_limit,
        )
        ordinary_meters[cid] = WorkMeter(work_limit)
        bound = by_bound[cid]
        if bound["question_sha256"] != contract.binding.question_sha256 or bound["direction"] != contract.binding.direction:
            raise ValueError("One-sided ordinary construction used a different question")
        meter = WorkMeter(work_limit)
        start, cpu_start = perf_counter_ns(), thread_time_ns()
        checked = check(contract.binding, Fraction(bound["bound"]), meter)
        if checked.status != PROVEN_FEASIBLE or checked.covered_constraints != contract.required_constraints:
            raise ValueError(f"Original feasible bound was not independently verified: {cid}")
        bound_reports.append({
            "case_id": cid, "bound": bound["bound"], "direction": bound["direction"],
            "work": dict(meter._charges), "cpu_ns": thread_time_ns()-cpu_start,
            "wall_ns": perf_counter_ns()-start, "details": list(checked.details),
        })

    rows = []
    weak_evals = side_evals = weak_cpu = side_cpu = 0
    for row in claims["rows"]:
        sid, cid = row["sample_id"], row["case_id"]
        result = {"case_id": cid, "sample_id": sid, "draw_index": row["draw_index"],
                  "termination": row["termination"], "native_final_eligible": row["native_final_eligible"],
                  "native_final_value": row["final"]["value"]}
        for point in POINTS:
            if (sid, point) not in issued:
                result[point] = {"status": "UNBOUND_ABSTAIN", "observation_status": row[point]["status"]}
                continue
            candidate, prefix = issued[sid, point]
            value = Fraction(row[point]["value"])
            begin = thread_time_ns()
            weak = weak_satisfied(cid, value)
            weak_evals += 1
            weak_cpu += thread_time_ns()-begin
            begin = thread_time_ns()
            bound = Fraction(by_bound[cid]["bound"])
            side = value < bound if by_bound[cid]["direction"] == "MAX" else value > bound
            side_evals += 1
            side_cpu += thread_time_ns()-begin
            engine = engines[cid]
            proof = engine.check(candidate, prefix)
            authorized = engine.authorizes_exclusion(candidate, proof)
            meter = ordinary_meters[cid]
            begin, begin_cpu, prior_work = perf_counter_ns(), thread_time_ns(), meter._spent
            ordinary_status = UNKNOWN
            reason = "ORDINARY_POINT_UNRESOLVED"
            if ordinary_calls[cid] < call_limit and meter._spent < work_limit:
                ordinary_calls[cid] += 1
                try:
                    direct = ordinary_point(cid, value, meter)
                except _BudgetExhausted:
                    direct = None
                if direct is not None:
                    ordinary_status = PROVEN_FEASIBLE if direct else PROVEN_INFEASIBLE
                    reason = "ORDINARY_EXACT_POINT_ONLY"
            result[point] = {
                "status": "BOUND_POINT_CHECKED", "value": str(value), "candidate_sha256": candidate.sha256,
                "weak_refutes": weak is False, "one_sided_refutes": side,
                "ordinary_point_status": ordinary_status, "ordinary_reason": reason,
                "ordinary_named_work_units": meter._spent - prior_work,
                "ordinary_cpu_ns": thread_time_ns()-begin_cpu, "ordinary_wall_ns": perf_counter_ns()-begin,
                "reviewed_point_status": proof.status, "reviewed_point_authorizes": authorized,
                "reviewed_point_receipt": proof.as_dict(),
                "scope_review_sha256": row[point].get("scope_review_sha256"),
            }
        rows.append(result)
    return {
        "status": "D46_BLIND_POINT_COMPARISONS_FROZEN_WITHOUT_GOLD", "input_sha256": shas,
        "comparison_source_sha256": sha(Path(__file__)), "rows": rows,
        "candidate_count": len(issued), "bound_readback": bound_reports,
        "work": {
            "wall_ns": perf_counter_ns()-began, "cpu_ns": thread_time_ns()-cpu,
            "weak_evaluations": weak_evals, "weak_cpu_ns": weak_cpu, "side_comparisons": side_evals, "side_cpu_ns": side_cpu,
            "ordinary_calls": sum(ordinary_calls.values()), "ordinary_work": {cid: dict(m._charges) for cid, m in ordinary_meters.items()},
            "reviewed_work": {cid: engine.report()["used"] for cid, engine in engines.items()},
        },
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("cohort", "claims", "blind", "contracts", "controls", "bounds", "rules", "output"):
        cli.add_argument("--" + arg, type=Path, required=True)
    args = cli.parse_args()
    out = compare(args)
    write_exclusive(args.output, out)
    print(out["status"], out["candidate_count"], sha(args.output))


if __name__ == "__main__":
    main()
