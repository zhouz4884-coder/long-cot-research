"""Postscore exact diagnosis of repeated infeasible points and a feasible final regression."""
from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d46_contracts import reconstruct
from d46_point_domains import check
from freeze_d46_intake import digest, load, sha, write_exclusive
from point_verifier import PROVEN_FEASIBLE, WorkMeter


def analyze(results_path: Path, contracts_path: Path, claims_path: Path, blind_path: Path) -> dict:
    begin, cpu = perf_counter_ns(), thread_time_ns()
    results, contracts, claims, blind = map(load, (results_path, contracts_path, claims_path, blind_path))
    if claims["blind_input_sha256"] != sha(blind_path) or claims["scope_audit_sha256"] != results["scope_audit_sha256"]:
        raise ValueError("Postscore diagnosis not tied to the observed source")
    traces = {row["sample_id"]: row for row in results["blind_scope_sensitivity"]["trace_rows"]}
    raw = {row["sample_id"]: row for row in blind["rows"]}
    observed = {row["sample_id"]: row for row in claims["rows"]}
    targets = {row["case_id"]: reconstruct(row) for row in contracts["rows"]}
    assert len(results["blind_scope_sensitivity"]["persistent_verified_points"]) == 6
    evidence = []
    for point in results["blind_scope_sensitivity"]["persistent_verified_points"]:
        if point["case_id"] != "2011-I-12":
            raise ValueError("Unexpected independent question in repeated point errors")
        n = int(point["value"])
        g = n + 1
        exact = Fraction(6*g, g*g + 6*g - 1)
        slack = n*n - 592*n - 594
        assert exact > Fraction(1, 100) and slack < 0
        evidence.append({"sample_id": point["sample_id"], "women": n, "correct_probability": str(exact),
                         "threshold_polynomial": slack,
                         "same_value_in_original_wrong_final": traces[point["sample_id"]]["final_value"] == n})
    assert 593**2 - 592*593 - 594 == -1 and 594**2 - 592*594 - 594 == 594

    sid = "2017-II-5:draw-05"
    trace, source = traces[sid], raw[sid]
    assert trace["official_native_status"] == "NATIVE_WRONG" and trace["final_value"] == 533
    assert trace["points"]["late"]["value"] == "791" and trace["points"]["late"]["literal_optimum"]
    assert digest(source["response"].encode()) == source["response_sha256"]
    assert observed[sid]["late"]["value"] == 791
    point_cases = []
    for value in (791, 533):
        meter = WorkMeter(100_000)
        legal = check(targets["2017-II-5"].binding, Fraction(value), meter)
        if legal.status != PROVEN_FEASIBLE:
            raise ValueError("Regression diagnosis did not verify both original points")
        point_cases.append({"value": value, "independently_feasible_vertices": dict(legal.details),
                            "named_point_work": dict(meter._charges)})
    # Final text first recognizes a smaller feasible value, then calls that same value maximal.
    # It also labels an edge with a value contradicted by its own listed vertices.
    _, mark, final = source["response"].partition("</think>")
    assert mark and "c + d = 418" in final and "123 + 209 = 332" in final
    before, after = final.rfind("c + d = 418"), final.rfind("123 + 209 = 332")
    assert 0 <= before < after and 123 + 209 == 332 != 418
    return {
        "status": "POSTSCORE_FAILURE_MODE_DIAGNOSIS_ONLY",
        "results_sha256": sha(results_path), "scope_readout_sha256": sha(claims_path),
        "no_new_model_work_or_preregistered_gate_change": True,
        "repeated_conditional_count_case": {
            "case_id": "2011-I-12", "persistent_infeasible_points": evidence,
            "closed_form_solution": 594, "threshold_at_predecessor": -1,
            "proof": "With g=w+1 gaps the conditional probability is 6g/(g²+6g−1). "
                     "The 1% requirement is w²−592w−594≥0, with first admissible w=594.",
        },
        "feasible_final_regression": {
            "sample_id": sid, "response_sha256": source["response_sha256"], "thought_optimum": 791,
            "wrong_native_final": 533, "difference": 258, "both_values_feasible": True,
            "postscore_independent_checks": point_cases, "fixed_simple_bound": 497,
            "later_edge_assertion_sha256": digest(final[before:before+len("c + d = 418")].encode()),
            "conflicting_final_edge_arithmetic_sha256": digest(final[after:after+len("123 + 209 = 332")].encode()),
        },
        "wall_ns": perf_counter_ns()-begin, "cpu_ns": thread_time_ns()-cpu,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "contracts", "claims", "blind", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    out = analyze(args.results, args.contracts, args.claims, args.blind)
    write_exclusive(args.output, out)
    print(out["status"], len(out["repeated_conditional_count_case"]["persistent_infeasible_points"]), sha(args.output))


if __name__ == "__main__":
    main()
