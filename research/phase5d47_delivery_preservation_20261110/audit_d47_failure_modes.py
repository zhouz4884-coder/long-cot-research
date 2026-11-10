"""Postscore proof of the observed failure classes, without changing any gate."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d47_contracts import reconstruct
from d47_point_domains import check
from freeze_d47_intake import digest, load, sha, write_exclusive
from point_verifier import PROVEN_FEASIBLE, PROVEN_INFEASIBLE, WorkMeter


def analyze(score_path, comparison_path, readout_path, contracts_path, blind_path):
    begin, cpu = perf_counter_ns(), thread_time_ns()
    scored, comparison, readout, contracts, blind = map(load, (score_path, comparison_path, readout_path, contracts_path, blind_path))
    if scored["sensitivity_sha256"] != sha(comparison_path) or comparison["input_sha256"]["readout"] != sha(readout_path):
        raise ValueError("Postscore audit has different frozen outputs")
    if readout["blind_input_sha256"] != sha(blind_path):
        raise ValueError("Postscore audit has different source text")
    label = {r["case_id"]: r for r in scored["label_audit"]}
    exact = {r["case_id"]: reconstruct(r) for r in contracts["rows"]}
    source = {r["sample_id"]: r for r in blind["rows"]}
    by_trace = {r["sample_id"]: r for r in comparison["rows"]}
    scopes = {r["sample_id"]: r for r in readout["rows"]}
    wrong = []
    for trace in scored["blind_scope_sensitivity"]["trace_rows"]:
        if trace["native_outcome"] != "NATIVE_WRONG":
            continue
        sid, cid, value = trace["sample_id"], trace["case_id"], trace["native_value"]
        raw, comp, obs = source[sid], by_trace[sid], scopes[sid]
        assert digest(raw["response"].encode()) == raw["response_sha256"]
        assert obs["late"]["status"] == "EXPLICIT_SCOPED_POINT" and obs["late"]["value"] == value
        meter, best_meter = WorkMeter(20_000), WorkMeter(20_000)
        point = check(exact[cid].binding, Fraction(value), meter)
        optimum = label[cid]["optimum"]
        best = check(exact[cid].binding, Fraction(optimum), best_meter)
        assert best.status == PROVEN_FEASIBLE
        assert point.status == comp["slot_checks"]["late"]["proof_status"] == comp["slot_checks"]["final_point"]["proof_status"]
        assert comp["preservation"]["decision"]["action"] == "KEEP_NATIVE"
        wrong.append({
            "sample_id": sid, "response_sha256": raw["response_sha256"], "late_value": value, "native_final_value": value,
            "case_id": cid, "point_status": point.status, "point_details": dict(point.details),
            "literal_optimum": optimum, "optimum_feasibility_details": dict(best.details),
            "point_work": dict(meter._charges), "oracle_value_validation_work": dict(best_meter._charges),
            "late_source_excerpt_sha256": obs["late"].get("source_excerpt_sha256"),
            "final_source_excerpt_sha256": obs["final_point"]["official_final_box_receipt"]["source_excerpt_sha256"],
        })
    assert len(wrong) == 6 and Counter(r["point_status"] for r in wrong) == {PROVEN_FEASIBLE: 4, PROVEN_INFEASIBLE: 2}
    return {
        "status": "D47_POSTSCORE_DIAGNOSIS_ONLY", "score_sha256": sha(score_path),
        "sensitivity_comparison_sha256": sha(comparison_path), "no_gate_or_model_change": True,
        "wrong_native_finals": wrong, "all_wrong_values_already_in_late_thinking": True,
        "wall_ns": perf_counter_ns()-begin, "cpu_ns": thread_time_ns()-cpu,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "comparison", "readout", "contracts", "blind", "output"):
        cli.add_argument("--"+name, type=Path, required=True)
    args = cli.parse_args()
    out = analyze(args.results, args.comparison, args.readout, args.contracts, args.blind)
    write_exclusive(args.output, out)
    print(out["status"], len(out["wrong_native_finals"]), sha(args.output))


if __name__ == "__main__":
    main()
