"""Exact CPU calibration on the three predeclared older development cases."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
D44 = HERE.parent / "phase5d44_candidate_generation_20261110"
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
BASE = "a80ed124068fe2ac19b8899d7f51fc5dd5af9826"
DEV = {"2009-II-12", "2012-I-4", "2016-I-9"}


def digest(raw):
    return sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_bindings():
    baseline_path = HERE / "D45_BASELINE_FREEZE.json"
    cohort_path = HERE / "D45_COHORT_FREEZE.json"
    baseline_raw, cohort_raw = baseline_path.read_bytes(), cohort_path.read_bytes()
    baseline, cohort = map(json.loads, (baseline_raw, cohort_raw))
    require(baseline["baseline_commit"] == cohort["baseline_commit"] == BASE
            and set(baseline["development_cases_only"]) == DEV, "Unexpected development baseline")
    admitted = {row["case_id"] for row in cohort["rows"]}
    require(len(admitted) == cohort["selected_question_count"] == 11 and DEV.isdisjoint(admitted),
            "Development and heldout cohorts must be disjoint")
    hashes = {}
    sources = {D44 / name: expected for name, expected in baseline["d44_evidence_sha256"].items()}
    sources.update({D44 / "D44_MECHANISM_AUDIT_ZH.md": None, D44 / "D44_LABEL_CONFLICT_ZH.md": None,
                    D43 / "D43_DISPUTE_AUDIT_ZH.md": None})
    for path, expected in sources.items():
        relative = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=REPO, timeout=15)
        observed = digest(raw)
        require(path.read_bytes() == raw and (expected is None or expected == observed), "Published source bytes differ")
        hashes[relative] = observed
    return {"baseline_commit": BASE, "baseline_freeze_sha256": digest(baseline_raw),
            "heldout_cohort_identity_only_sha256": digest(cohort_raw), "heldout_cases_disjoint": True,
            "development_case_ids": sorted(DEV), "published_sources_sha256": hashes}


def cyclic_witness(k, work):
    work.update({"integer_parity_and_division": 2, "integer_increment": 1})
    require(type(k) is int and k > 0 and k % 2 == 1, "Cyclic packing requires positive odd size")
    shift, right_start = k // 2, k + 1
    work.update({"integer_addition": 3 * k, "integer_remainder": k})
    return [(i + 1, right_start + ((i + shift) % k)) for i in range(k)]


def pairing_constraints(n, pairs, work):
    seen, sums = set(), set()
    checks = dict(ordered_in_range=True, all_endpoints_distinct=True, all_sums_distinct=True, all_sums_bounded=True)
    for a, b in pairs:
        s = a + b
        in_range = (1 <= a, a < b, b <= n)
        free = (a not in seen, b not in seen, a != b)
        checks["ordered_in_range"] &= all(in_range)
        checks["all_endpoints_distinct"] &= all(free)
        checks["all_sums_distinct"] &= s not in sums
        checks["all_sums_bounded"] &= s <= n
        seen.update((a, b))
        sums.add(s)
        work.update({"integer_addition": 1, "integer_comparison": 5, "set_membership": 3, "set_insert": 3})
    work.update({"diagnostic_sum_range_comparison": 2 * max(0, len(sums) - 1)})
    return checks, {"pair_count": len(pairs), "distinct_endpoint_count": len(seen), "distinct_sum_count": len(sums),
                    "minimum_sum": min(sums) if sums else None, "maximum_sum": max(sums) if sums else None}


def check_packing(work, pairs, candidate, *, n=2009, compact=False, direction="MAX", objective="maximum_pair_count"):
    header = {"candidate": candidate, "universe_upper": n, "request_direction": direction, "request_objective": objective}
    work.update({"binding_comparison": 2})
    direction_matches, objective_matches = direction == "MAX", objective == "maximum_pair_count"
    if not (direction_matches and objective_matches):
        return {"status": "ABSTAIN_WRONG_OBJECTIVE_OR_DIRECTION", **header, "original_constraints": None}
    proposed = cyclic_witness(pairs, work) if compact else pairs
    checks, detail = pairing_constraints(n, proposed, work)
    if not all(checks.values()):
        status = "REJECT_INFEASIBLE_WITNESS"
    else:
        work.update({"strict_objective_comparison": 1})
        status = "REFUTE_AS_MAXIMUM" if len(proposed) > candidate else "ABSTAIN_NO_STRICT_IMPROVEMENT"
    return {"status": status, **header, "original_constraints": checks, **detail,
            "witness_encoding": "compact_cyclic_size_expanded_and_verified" if compact else "explicit_pairs"}


def ordinary_packing(work):
    n = 2009
    work.update({"integer_multiply": 3, "integer_subtraction": 1, "integer_division": 1,
                 "integer_addition": 1, "integer_comparison": 2})
    numerator = 2 * n - 1
    upper = numerator // 5
    require(5 * upper <= numerator < 5 * (upper + 1), "Ordinary upper-bound integer cut differs")
    checks, detail = pairing_constraints(n, cyclic_witness(upper, work), work)
    work.update({"strict_objective_comparison": 1})
    require(all(checks.values()) and detail["pair_count"] == upper, "Ordinary upper bound is not attained")
    return {"status": "PROVED_EXACT_ORDINARY_OPTIMUM", "upper": upper, "attaining_witness": detail,
            "original_constraints": checks,
            "proof": "For k>0, the 2k distinct endpoints sum to at least k(2k+1). The k distinct sums each at most n total at most nk-k(k-1)/2. Divide by positive k and combine to get 5k≤2n-1. The exact cyclic construction attains the integer upper bound. k=0 already satisfies the bound."}


class QuadraticField:
    """Pairs (a,b) denote a+b√6 with rational a and b."""
    def __init__(self, work):
        self.work = work

    def add(self, x, y):
        self.work.update({"quadratic_field_addition": 1})
        return (x[0] + y[0], x[1] + y[1])

    def sub(self, x, y):
        self.work.update({"quadratic_field_subtraction": 1})
        return (x[0] - y[0], x[1] - y[1])

    def mul(self, x, y):
        self.work.update({"quadratic_field_multiplication": 1})
        return (x[0] * y[0] + 6 * x[1] * y[1], x[0] * y[1] + x[1] * y[0])

    def sign(self, x):
        self.work.update({"quadratic_field_sign": 1})
        a, b = x
        sign_a, sign_b = (a > 0) - (a < 0), (b > 0) - (b < 0)
        if sign_a == 0 or sign_b == 0 or sign_a == sign_b:
            return sign_a or sign_b
        self.work.update({"opposed_terms_exact_square_comparison": 1})
        difference = a * a - 6 * b * b
        return sign_a * ((difference > 0) - (difference < 0))

    def eq(self, x, y):
        self.work.update({"quadratic_field_equality": 1})
        return x == y


def q(a, b=0):
    return (Fraction(a), Fraction(b))


def coordinates(values):
    return [str(v) for v in values]


def check_geometry(work, tangent, candidate):
    f, t = QuadraticField(work), Fraction(tangent)
    work.update({"rational_parameter_operations": 6})
    scale_squared = Fraction(1) / (1 + t * t)
    w, b = q(40), q(40 * t)
    c, h = f.mul(q(Fraction(31, 5)), q(-t, 2)), f.mul(q(Fraction(31, 5)), q(1, 2 * t))
    norm_b = f.mul(q(scale_squared), f.add(f.mul(w, w), f.mul(b, b)))
    norm_c = f.mul(q(scale_squared), f.add(f.mul(c, c), f.mul(h, h)))
    cross = f.mul(q(scale_squared), f.sub(f.mul(w, h), f.mul(b, c)))
    b_in_segment = (f.sign(b) >= 0, f.sign(f.sub(h, b)) >= 0)
    c_in_segment = (f.sign(c) >= 0, f.sign(f.sub(w, c)) >= 0)
    checks = {"rectangle_width_and_height_positive": all((f.sign(w) > 0, f.sign(h) > 0)),
              "length_ab_squared": f.eq(norm_b, q(1600)), "length_ac_squared": f.eq(norm_c, q(961)),
              "positive_cross_for_sine_one_fifth": f.eq(cross, q(248)),
              "b_on_segment_qr": all(b_in_segment), "c_on_segment_rs": all(c_in_segment)}
    area = f.mul(q(scale_squared), f.mul(w, h))
    strictly_larger = f.sign(f.sub(area, q(candidate))) > 0
    support_lines_only = all(v for k, v in checks.items() if k not in {"b_on_segment_qr", "c_on_segment_rs"})
    if not all(checks.values()):
        status = "REJECT_INFEASIBLE_WITNESS"
    else:
        status = "REFUTE_AS_MAXIMUM" if strictly_larger else "ABSTAIN_NO_STRICT_IMPROVEMENT"
    return {"status": status, "tangent": str(t),
            "candidate_area": candidate, "uniform_scale_squared": str(scale_squared),
            "unscaled_b": [coordinates(w), coordinates(b)], "unscaled_c": [coordinates(c), coordinates(h)],
            "area_coefficients_for_a_plus_b_sqrt6": coordinates(area), "original_constraints": checks,
            "geometry_only_strict_objective_comparison": strictly_larger,
            "invalid_support_line_only_checker_would_refute": support_lines_only and strictly_larger and not all(checks.values())}


def synchronize(work, a, b, *, left_event=2, right_event=2):
    work.update({"event_identity_comparison": 1})
    if left_event != right_event:
        return {"status": "ABSTAIN_EVENT_SCOPE_MISMATCH", "milestones": [left_event, right_event]}
    work.update({"rational_subtraction": 1, "rational_equality": 1})
    gap = Fraction(b) - Fraction(a)
    return {"status": "REFUTE_PROPOSED_SIMULTANEITY" if gap else "ABSTAIN_NO_TIME_CONFLICT",
            "same_milestone": left_event, "ordered_pair_hours": [a, b], "right_minus_left_hours": str(gap),
            "authorized_object": "simultaneity at this proposed milestone under the supplied arrival times",
            "earliest_feasible_event_or_n_plus_t_certified": False}


def reject_unbound_order(work):
    work.update({"claim_projection_binding_comparison": 1, "integer_addition": 2, "integer_comparison": 2})
    earlier, later = (8, 10), (1, 12)
    require(earlier[1] < later[1] and sum(earlier) > sum(later), "Algebraic ordering negative control differs")
    return {"status": "ABSTAIN_NO_AUTHORIZED_ORDER_PROJECTION", "bare_candidate": "n+t",
            "illustrative_untyped_pairs_n_t": [list(earlier), list(later)],
            "pairs_are_claimed_feasible_motion": False,
            "reason": "An algebraic counterexample defeats a bare projection rule. Complete legal forward trajectories may admit a monotonicity proof, which this local simultaneity receipt does not provide."}


def measured(name, expected, check):
    work = Counter()
    cpu, start = thread_time_ns(), perf_counter_ns()
    observed = check(work)
    timing = {"thread_cpu_ns": thread_time_ns() - cpu, "wall_ns": perf_counter_ns() - start}
    require(observed["status"] == expected, f"Unexpected calibration status for {name}")
    # Windows can quantize individual thread CPU readings to whole scheduler ticks.
    repeats, batch = 0, 32
    profile_cpu, profile_start = thread_time_ns(), perf_counter_ns()
    while repeats < 65536 and thread_time_ns() - profile_cpu < 31_250_000:
        count = min(batch, 65536 - repeats)
        for _ in range(count):
            repeated_work = Counter()
            require(check(repeated_work) == observed and repeated_work == work,
                    "Repeated exact calibration differs")
        repeats += count
        batch *= 2
    profile = {"repetitions": repeats, "thread_cpu_ns": thread_time_ns() - profile_cpu,
               "wall_ns": perf_counter_ns() - profile_start,
               "includes_repeat_equality_checks": True}
    return {"control": name, "expected_status": expected, **observed,
            "charged_operations": dict(sorted(work.items())), "charged_operation_total": sum(work.values()),
            **timing, "batch_cpu_profile": profile}


def run():
    sources = source_bindings()
    sample = [(1, 6), (2, 4), (3, 5)]
    cases = {
        "2009-II-12": [
            ("cyclic_701_refutes_669", "REFUTE_AS_MAXIMUM", lambda work: check_packing(work, 701, 669, compact=True)),
            ("ordinary_bound_803_and_feasible_attainment", "PROVED_EXACT_ORDINARY_OPTIMUM", ordinary_packing),
            ("small_finite_positive", "REFUTE_AS_MAXIMUM", lambda work: check_packing(work, sample, 2, n=8)),
            ("duplicate_endpoints", "REJECT_INFEASIBLE_WITNESS", lambda work: check_packing(work, [(1, 6), (2, 4), (1, 4)], 2, n=8)),
            ("duplicate_sums", "REJECT_INFEASIBLE_WITNESS", lambda work: check_packing(work, [(1, 6), (2, 5), (3, 4)], 2, n=8)),
            ("sum_exceeds_cap", "REJECT_INFEASIBLE_WITNESS", lambda work: check_packing(work, [(1, 6), (2, 4), (3, 8)], 2, n=8)),
            ("equality_is_not_refutation", "ABSTAIN_NO_STRICT_IMPROVEMENT", lambda work: check_packing(work, sample, 3, n=8)),
            ("wrong_direction", "ABSTAIN_WRONG_OBJECTIVE_OR_DIRECTION", lambda work: check_packing(work, sample, 2, n=8, direction="MIN")),
            ("wrong_target", "ABSTAIN_WRONG_OBJECTIVE_OR_DIRECTION", lambda work: check_packing(work, sample, 2, n=8, objective="maximum_single_pair_sum")),
        ],
        "2016-I-9": [
            ("feasible_rectangle_above_640", "REFUTE_AS_MAXIMUM", lambda work: check_geometry(work, "1/2", 640)),
            ("support_lines_pass_but_beyond_segment", "REJECT_INFEASIBLE_WITNESS", lambda work: check_geometry(work, "1", 640)),
        ],
        "2012-I-4": [
            ("same_post_unequal_times", "REFUTE_PROPOSED_SIMULTANEITY", lambda work: synchronize(work, "5/12", "17/30")),
            ("equal_times_no_conflict", "ABSTAIN_NO_TIME_CONFLICT", lambda work: synchronize(work, "5/12", "5/12")),
            ("different_milestones_no_authority", "ABSTAIN_EVENT_SCOPE_MISMATCH", lambda work: synchronize(work, "5/12", "17/30", right_event=3)),
            ("bare_distance_plus_time_no_order_authority", "ABSTAIN_NO_AUTHORIZED_ORDER_PROJECTION", reject_unbound_order),
        ],
    }
    results = {case: [measured(*spec) for spec in controls] for case, controls in cases.items()}
    expected_single_faults = {"duplicate_endpoints": "all_endpoints_distinct", "duplicate_sums": "all_sums_distinct",
                              "sum_exceeds_cap": "all_sums_bounded"}
    for row in results["2009-II-12"]:
        if row["control"] in expected_single_faults:
            require([k for k, value in row["original_constraints"].items() if not value] == [expected_single_faults[row["control"]]],
                    "Adversarial packing does not isolate the intended missed constraint")
    bad_geometry = results["2016-I-9"][1]
    require(bad_geometry["invalid_support_line_only_checker_would_refute"]
            and [k for k, v in bad_geometry["original_constraints"].items() if not v] == ["b_on_segment_qr"],
            "Adversarial geometry does not isolate the omitted segment check")
    charges = [row for controls in results.values() for row in controls]
    return {"status": "PASS_D45_OLD_DEVELOPMENT_CALIBRATION", "sources": sources, "cases": results,
            "scope": "Older exact CPU proof controls only. No fresh question text, trajectory, label, or GPU execution. The geometry case remains outside the rational live checker.",
            "cost_scope": "Per-control primitive algorithm operations plus measured thread CPU and wall time. Set and quadratic-field counts are separate primitive units. Timing includes witness construction when selected and all executed checks. These are correctness controls, not matched performance measurements.",
            "controls_passed": len(charges), "total_thread_cpu_ns": sum(row["thread_cpu_ns"] for row in charges),
            "total_control_wall_ns": sum(row["wall_ns"] for row in charges),
            "total_repeated_profile_thread_cpu_ns": sum(row["batch_cpu_profile"]["thread_cpu_ns"] for row in charges),
            "cpu_profile_scope": "Repeated equal outcomes and equal operation ledgers expose quantized CPU cost. Per-control profile cost includes repeat comparisons and is separate from the single mathematical call.",
            "calibration_code_sha256": digest(Path(__file__).read_bytes())}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=HERE / "D45_DEVELOPMENT_CALIBRATION.json")
    args = cli.parse_args()
    require(not args.output.exists(), "Refuse to overwrite calibration receipt")
    report = run()
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with args.output.open("xb") as handle:
        handle.write(raw)
    print(json.dumps({"status": report["status"], "sha256": digest(raw), "controls": report["controls_passed"]}))
