"""Record additional question-only closed-form complete controls before observations."""
from __future__ import annotations

import argparse
from fractions import Fraction
from math import isqrt
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d46_ordinary_controls import ControlMeter, ordinary_point
from freeze_d46_intake import HERE, load, sha, write_exclusive


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    begin, cpu = perf_counter_ns(), thread_time_ns()
    cohort_path = HERE / "D46_COHORT_FREEZE.json"
    cohort = {r["case_id"]: r for r in load(cohort_path)["rows"]}
    k = 500 + isqrt(999)
    n = k*k//1000 + 1
    assert k*k < 1000*n and (k+1)**2 > 1000*n + 999
    threshold = 14
    first = threshold + (5-threshold) % 6
    delta = (5*first+8)//3
    assert delta % 2 == 1 and delta <= 2*first-2
    result = first*first-delta
    cases = (
        ("2013-II-6", n, {"integer_square_roots": 1, "scalar_boundary_formulas": 3},
         "For k<500 adjacent square gaps are at most 999 and cannot skip a complete block. "
         "For k=500+t the thousand-block index is 250+t+floor(t²/1000). "
         "The first skipped block occurs at t=isqrt(999)=31, before (t+1)² crosses 1000."),
        ("2021-II-15", result, {"affine_parity_boundary_formulas": 3},
         "With k=ceil sqrt(n) and δ=k²-n, opposite parity is necessary. "
         "Then 3δ=5k+8, δ is odd and δ<=2k-2. Thus k>=14 and k=5 mod 6, "
         "so the first valid k is 17. Every later square block has larger n."),
    )
    rows = []
    for cid, value, work, proof in cases:
        meter = ControlMeter()
        if ordinary_point(cid, Fraction(value), meter) is not True:
            raise ValueError(f"Closed-form point validation failed for {cid}")
        rows.append({"case_id": cid, "question_sha256": cohort[cid]["question_sha256"], "optimum": value,
                     "completeness_argument": proof, "construction_named_work": work,
                     "separate_validation_work": dict(meter.counts)})
    out = {"status": "QUESTION_ONLY_STRUCTURAL_COMPLETE_CONTROLS_BEFORE_HELDOUT", "cohort_sha256": sha(cohort_path),
           "cost_scope": "Fixed exact formulas and separately charged validation. No archive response, gold or ordinary complete-oracle output read.",
           "rows": rows, "wall_ns": perf_counter_ns()-begin, "cpu_ns": thread_time_ns()-cpu}
    write_exclusive(args.output, out)
    print(out["status"], len(rows), sha(args.output))


if __name__ == "__main__":
    main()
