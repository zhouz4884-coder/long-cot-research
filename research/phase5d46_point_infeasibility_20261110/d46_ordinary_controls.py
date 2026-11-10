"""Question-only ordinary fixed-point checks and separately paid CPU controls."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, product
import json
from math import comb, isqrt
from pathlib import Path
from time import get_clock_info, perf_counter_ns, thread_time_ns


PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
AUDIT_SHA = "bad72b5b950df0b3e5d80e92b31f56c5f32e0d87863f199751555eff856d4215"
COHORT_SHA = "b37ca3a8574e4cbe2eb7da7ccfe379c2138395ffdf2b8eb91d4cf81c1866219b"
EDGE_VALUES = (189, 320, 287, 234)
EDGE_SUM = sum(EDGE_VALUES)
CASES = (
    "2009-I-7", "2010-II-3", "2010-II-12", "2011-I-12", "2013-II-6", "2015-I-11",
    "2015-II-3", "2015-II-5", "2017-II-5", "2019-I-14", "2021-II-15",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def encoded(data):
    return (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


class ControlMeter:
    def __init__(self):
        self.counts = Counter()

    def charge(self, label, count=1):
        self.counts[label] += count


def _power_of_five(x, meter):
    while x > 1:
        meter.charge("base_five_division")
        x, remainder = divmod(x, 5)
        if remainder:
            return False
    return x == 1


def _divides_difference_product(n, meter):
    if not 1 <= n < 950:
        return False
    modulus = 1 << n
    residue = 1
    for difference in range(1, 20):
        meter.charge("group_modular_power")
        residue = (residue * pow(difference, 20 - difference, modulus)) % modulus
        if residue == 0:
            return True
    return False


def _equal_area_sides(perimeter, meter):
    meter.charge("fixed_scale_division")
    k, remainder = divmod(15 * perimeter, 338)
    if remainder or k <= 0 or perimeter <= 16 * k:
        return None
    bases = 8 * k, 7 * k
    if any((perimeter - b) % 2 for b in bases):
        return None
    sides = [(b, (perimeter - b) // 2) for b in bases]
    meter.charge("squared_area_product", 2)
    scaled = [b * b * (4 * side * side - b * b) for b, side in sides]
    return sides if scaled[0] == scaled[1] else None


def _run_counts(women, meter):
    gaps = women + 1
    meter.charge("binomial", 2)
    two, three = comb(gaps, 2), comb(gaps, 3)
    return gaps + 2 * two, gaps + 3 * two + three


def _square_free(n, meter):
    first = 1000 * n
    meter.charge("integer_square_root", 2)
    return isqrt(first - 1) == isqrt(first + 999)


def _incenter_sides(perimeter, meter):
    for base in range(12, 16):
        meter.charge("fixed_base_incenter_test")
        side, remainder = divmod(perimeter - base, 2)
        if not remainder and 2 * side > base and base * base * side == 64 * perimeter:
            return base, side
    return None


def _digit_sum(number, meter):
    total = 0
    while number:
        meter.charge("decimal_digit_division")
        number, digit = divmod(number, 10)
        total += digit
    return total


def _odd_prime_factor(p, meter):
    if p < 17 or p % 16 != 1:
        return False
    meter.charge("factor_modular_power")
    if pow(2019, 8, p) != p - 1:
        return False
    for divisor in range(3, isqrt(p) + 1, 2):
        meter.charge("prime_trial_division")
        if p % divisor == 0:
            return False
    return True


def _recursive_pair(n, meter):
    meter.charge("integer_square_root")
    k = isqrt(n - 1) + 1
    h = k if (k - n) % 2 == 0 else k + 1
    return k * k - n + k, h * h - n + h


def _exclude_missing_opposite(meter):
    # If the two missing edges were opposite, the known edges would have to
    # form two other opposite pairs with equal sum. These are all partitions.
    first, *tail = EDGE_VALUES
    for other in tail:
        meter.charge("known_opposite_partition")
        if first + other == EDGE_SUM - first - other:
            raise ValueError("The checked item has an unhandled missing-opposite branch")


def _realize_edges(pair, meter):
    """Realize one assigned known opposite pair with exact four-vertex values."""
    left, right = pair
    opposite_sum = left + right
    other, fourth = (x for x in EDGE_VALUES if x not in pair)
    missing = opposite_sum - other, opposite_sum - fourth
    opposite_pairs = (pair, (other, missing[0]), (fourth, missing[1]))
    wanted = sorted((*EDGE_VALUES, *missing))
    # The three edges incident to a vertex choose one member of each opposite
    # pair. Permuting the three pairs only relabels the other vertices.
    for star in product(*opposite_pairs):
        meter.charge("edge_orientation")
        a = Fraction(sum(star) - opposite_sum, 2)
        values = (a, *(Fraction(x) - a for x in star))
        if len(set(values)) != 4:
            continue
        meter.charge("rational_edge_sum", 6)
        if sorted(a + b for a, b in combinations(values, 2)) == wanted:
            return values, missing
    return None


def _fixed_edge_sum(value, meter):
    _exclude_missing_opposite(meter)
    opposite_sum = (EDGE_SUM + value) / 3
    for pair in combinations(EDGE_VALUES, 2):
        meter.charge("fixed_known_pair_comparison")
        if sum(pair) == opposite_sum and _realize_edges(pair, meter) is not None:
            return True
    return False


def ordinary_point(case_id: str, value: Fraction, meter) -> bool | None:
    """Check only the proposed objective value; never call a complete solver."""
    if case_id not in CASES or type(value) is not Fraction:
        return None
    meter.charge("fixed_point")
    if case_id == "2017-II-5":
        return _fixed_edge_sum(value, meter)
    if value.denominator != 1:
        return False
    n = value.numerator
    if case_id == "2009-I-7":
        return n > 1 and _power_of_five(3 * n + 2, meter)
    if n < 1:
        return False
    if case_id == "2010-II-3":
        return _divides_difference_product(n, meter)
    if case_id == "2010-II-12":
        return _equal_area_sides(n, meter) is not None
    if case_id == "2011-I-12":
        favorable, total = _run_counts(n, meter)
        return 100 * favorable <= total
    if case_id == "2013-II-6":
        return _square_free(n, meter)
    if case_id == "2015-I-11":
        return _incenter_sides(n, meter) is not None
    if case_id == "2015-II-3":
        meter.charge("divisibility_by_17")
        return n % 17 == 0 and _digit_sum(n, meter) == 17
    if case_id == "2015-II-5":
        meter.charge("grid_probability_product")
        return n >= 2 and n * (n + 1) > 4 * 2015
    if case_id == "2019-I-14":
        return _odd_prime_factor(n, meter)
    f, g = _recursive_pair(n, meter)
    return 7 * f == 4 * g


POINT_PROOFS = {
    "2009-I-7": "The ratio (3j+5)/(3j+2) is 5^(a_(j+1)-a_j). "
                "Multiplying telescopes to 5^a_k=3k+2, so integrality is exactly the power test.",
    "2010-II-3": "Difference d occurs 20-d times for d=1..19. Evaluate that exact product mod 2^n. "
                 "There are 190 factors each below 2^5, so n>=950 cannot divide the nonzero product.",
    "2010-II-12": "Put bases 8k,7k. For perimeter P and base b the lateral sides are (P-b)/2, "
                  "and 16 times the squared area is b^2 P(P-2b). Equality reduces to 15P=338k. "
                  "Positive integer lateral sides and P>16k are necessary and sufficient; distinct bases imply noncongruence.",
    "2011-I-12": "With no singleton man, the ordered run sizes are (6), (2,4), (4,2), (3,3), (2,2,2). "
                 "Choose distinct gaps among w+1 to place each ordered run. The first three lists are favorable. "
                 "Permutations within the male and female ranks multiply every binary pattern by the same count.",
    "2013-II-6": "The inclusive interval [1000N,1000N+999] contains no square iff the integer "
                 "square root at its top equals the integer square root immediately before its bottom.",
    "2015-I-11": "With equal sides s and base b, height h satisfies h^2=s^2-b^2/4 and inradius r=bh/P. "
                 "Then BI^2=b^2/4+r^2=b^2 s/P. Setting this to 64 gives s=64b/(b^2-128). "
                 "Positivity and 2s>b force 128<b^2<256, hence b in 12..15. These exact tests suffice.",
    "2015-II-3": "An integer is feasible iff it is positive, divisible by 17, and has decimal digit sum 17.",
    "2015-II-5": "For n>=2 there are 2n(n-1) adjacent unordered pairs among choose(n^2,2). "
                 "The probability reduces to 4/[n(n+1)], so compare n(n+1) strictly with 4*2015.",
    "2017-II-5": "Each opposite pair sums to S, the sum of the four distinct vertices, so x+y=3S-1030. "
                 "Both missing edges opposite would force a partition of the four known edges into two equal-sum pairs. "
                 "The three partitions fail. Otherwise one known pair is opposite and the missing values are "
                 "S minus each remaining known edge. Each labeled star takes one edge from each opposite pair. "
                 "Reordering the pairs only permutes its other vertices. Reconstruct the center as (sum(star)-S)/2, "
                 "verify every edge multiplicity, and require four distinct rational values.",
    "2019-I-14": "Any odd prime factor has multiplicative order exactly 16 for 2019 modulo that prime. "
                 "Thus it is 1 mod 16. Test that class, then the original modular power and exact primality.",
    "2021-II-15": "Let k be the first integer with k^2>=n and h the first such integer with h^2 congruent "
                  "to n mod 2. Unrolling each recurrence gives f(n)=k^2-n+k and g(n)=h^2-n+h.",
}


def simple_witness(case_id, meter):
    """Independent feasible construction. Never consumes the exact optimum artifact."""
    if case_id == "2009-I-7":
        meter.charge("fixed_exponent_construction")
        return (5**3 - 2) // 3, {"a_k": 3}, "Choose a_k=3, an odd exponent beyond the initial term."
    if case_id == "2010-II-3":
        meter.charge("even_difference_group_count", 9)
        even_factors = sum(20 - d for d in range(2, 20, 2))
        return even_factors, {"even_difference_factors": even_factors}, (
            "Count one factor of 2 from every even difference, ignoring their additional powers.")
    if case_id == "2010-II-12":
        sides = _equal_area_sides(676, meter)
        return 676, {"triangles_base_and_lateral_side": sides}, (
            "Take k=30, a common multiple of 15 and 2, and use P=338k/15.")
    if case_id == "2011-I-12":
        counts = _run_counts(600, meter)
        return 600, {"favorable_and_conditioned_counts": counts}, "Choose a round women count and verify its exact runs."
    if case_id == "2013-II-6":
        meter.charge("neighboring_square_construction", 2)
        n = 901**2 // 1000 + 1
        return n, {"neighboring_squares": [901**2, 902**2]}, (
            "Choose the first whole thousand block after the fixed square 901² and check its upper endpoint.")
    if case_id == "2015-I-11":
        meter.charge("fixed_base_construction")
        return 108, {"base": 12, "lateral_side": 48}, "Choose base 12 and solve the positive lateral side equation."
    if case_id == "2015-II-3":
        meter.charge("chosen_suffix_digit_balance")
        return 629, {"suffix": 29, "leading_digit": 6}, (
            "Choose suffix 29 and place digit 6 to meet the sum. Directly verify divisibility by 17.")
    if case_id == "2015-II-5":
        meter.charge("round_grid_construction")
        return 100, {"adjacent_probability_denominator_after_canceling": 100 * 101}, (
            "Choose a round n=100 and check the strict probability comparison.")
    if case_id == "2017-II-5":
        _exclude_missing_opposite(meter)
        pair = EDGE_VALUES[:2]
        witness = _realize_edges(pair, meter)
        require(witness is not None, "Simple edge witness disappeared")
        vertices, missing = witness
        return sum(missing), {"vertices": [str(x) for x in vertices], "missing_edges": list(missing)}, (
            "Choose the first two source values as one opposite pair. Solve their exact rational realization.")
    if case_id == "2019-I-14":
        # Charge all attempted modular candidates, even those failing before trial division.
        for p in range(4097, 16, -16):
            meter.charge("descending_bounded_factor_candidate")
            if _odd_prime_factor(p, meter):
                return p, {"modular_residue": p - 1}, (
                    "Use a bounded descending scan in the order-16 residue class, ending at the first feasible prime. "
                    "The scan does not exclude lower prime factors.")
        raise ValueError("No feasible divisor in the declared descending construction")
    require(case_id == "2021-II-15", "Unknown simple witness case")
    meter.charge("chosen_square_interval")
    return 488, {"k": 23, "h": 24, "f_and_g": _recursive_pair(488, meter)}, (
        "Choose k=23, then set f=8(k+1)/3 and n=k^2+k-f. Verify n is even and in the interval for k.")


def exact_optimum(case_id, meter):
    """Complete independent question-only solver, charged and used separately."""
    if case_id == "2009-I-7":
        meter.charge("minimal_exponent_residue_argument")
        return (5**3 - 2) // 3, "Powers equal 2 mod 3 only for odd exponents; exponent 1 is the excluded k=1."
    if case_id == "2010-II-3":
        answer = 0
        for d in range(1, 20):
            meter.charge("difference_valuation")
            v2 = (d & -d).bit_length() - 1
            answer += (20 - d) * v2
        return answer, "Add each factor group's exact 2-adic valuation."
    if case_id == "2010-II-12":
        meter.charge("primitive_scale_and_parity_argument")
        return 676, "Coprimality in 15P=338k gives k=15j, P=338j. Integrality requires even j; j=2 is feasible."
    if case_id == "2011-I-12":
        meter.charge("quadratic_discriminant_square_root")
        w = (592 + isqrt(592**2 + 4 * 594)) // 2
        if w * w - 592 * w - 594 < 0:
            w += 1
        return w, "Divide the exact run inequality by w+1 to obtain w^2-592w-594>=0. Use its sole nonnegative root."
    if case_id == "2013-II-6":
        for n in range(1, 1002):
            if ordinary_point(case_id, Fraction(n), meter):
                return n, "Search the entire positive integer prefix ending at the first feasible square-free block."
        raise ValueError("Square-free-block upper bound failed")
    if case_id == "2015-I-11":
        candidates = []
        for base in range(12, 16):
            meter.charge("complete_base_case")
            side, remainder = divmod(64 * base, base * base - 128)
            if not remainder and 2 * side > base:
                candidates.append(2 * side + base)
        return min(candidates), "Check every possible base 12..15 using the exact derived lateral-side formula."
    if case_id == "2015-II-3":
        for multiplier in range(1, 92, 9):
            n = 17 * multiplier
            if ordinary_point(case_id, Fraction(n), meter):
                return n, "Digit sum fixes n modulo 9, hence the multiplier is 1 mod 9. Search that prefix exactly."
        raise ValueError("Decimal witness upper bound failed")
    if case_id == "2015-II-5":
        meter.charge("strict_quadratic_threshold_square_root")
        floor = (isqrt(1 + 4 * (4 * 2015)) - 1) // 2
        return floor + 1, "The strictly increasing quadratic passes strictly after its nonnegative root."
    if case_id == "2017-II-5":
        _exclude_missing_opposite(meter)
        values = []
        for pair in combinations(EDGE_VALUES, 2):
            meter.charge("complete_known_opposite_pair")
            if _realize_edges(pair, meter) is not None:
                values.append(3 * sum(pair) - EDGE_SUM)
        return max(values), "Enumerate every possible known opposite pair and require an exact distinct-vertex realization."
    if case_id == "2019-I-14":
        for p in range(17, 4098, 16):
            meter.charge("ascending_prime_factor_candidate")
            if _odd_prime_factor(p, meter):
                return p, "All odd prime factors are 1 mod 16. Test the allowed class in ascending order through the hit."
        raise ValueError("No odd factor in the independent bounded complete prefix")
    require(case_id == "2021-II-15", "Unknown exact optimum case")
    meter.charge("minimum_square_parity_argument")
    k = 17
    return k * k + k - 8 * (k + 1) // 3, (
        "Same parity gives f=g and fails. Otherwise h=k+1, so f=8(k+1)/3. "
        "The interval (k-1)^2<n<=k^2 gives k<=f<=3k-2, hence k>=14. "
        "Integrality gives k=2 mod 3 and f even, so n=k^2+k-f is even and k odd. "
        "Thus k=5 mod 6, with first permissible k=17. The derived n is feasible there, "
        "and later square intervals contain strictly larger n.")


def control_row(case, routine, *, oracle):
    case_id = case["case_id"]
    meter = ControlMeter()
    began_wall, began_cpu = perf_counter_ns(), thread_time_ns()
    result = routine(case_id, meter)
    construction_wall = perf_counter_ns() - began_wall
    construction_cpu = thread_time_ns() - began_cpu
    if oracle:
        value, proof = result
        witness = None
    else:
        value, witness, proof = result
    validation = ControlMeter()
    checked_wall, checked_cpu = perf_counter_ns(), thread_time_ns()
    require(ordinary_point(case_id, Fraction(value), validation) is True, "Control did not verify its returned point")
    check_wall = perf_counter_ns() - checked_wall
    check_cpu = thread_time_ns() - checked_cpu
    return {
        "case_id": case_id, "question_sha256": case["exact_question_sha256"], "direction": case["direction"],
        ("optimum" if oracle else "bound"): value, "feasible_witness": witness, "proof": proof,
        "ordinary_point_proof": POINT_PROOFS[case_id], "paid_work": dict(sorted(meter.counts.items())),
        "validation_paid_work": dict(sorted(validation.counts.items())),
        "construct_wall_ns": construction_wall, "construct_thread_cpu_ns": construction_cpu,
        "validation_wall_ns": check_wall, "validation_thread_cpu_ns": check_cpu,
    }


def build(scope_path, cohort_path, question_only, output, private):
    raw_scope = scope_path.read_bytes()
    require(digest(raw_scope) == AUDIT_SHA, "Changed question-only scope freeze")
    scope = json.loads(raw_scope)
    cases = scope["rows"]
    require(tuple(row["case_id"] for row in cases) == CASES, "Changed fixed case order")
    raw_cohort = cohort_path.read_bytes()
    require(digest(raw_cohort) == COHORT_SHA, "Changed question-only cohort freeze")
    cohort = json.loads(raw_cohort)
    raw_questions = question_only.read_bytes()
    require(cohort["scope_audit_sha256"] == AUDIT_SHA and cohort["question_only_sha256"] == digest(raw_questions)
            and cohort["source_shards"][0]["sha256"] == scope["source"]["draw00_sha256"],
            "Question projection authority differs")
    rows = json.loads(raw_questions)["rows"]
    observed = {row["case_id"]: digest(row["question"].encode()) for row in rows}
    require(len(rows) == len(CASES) and observed == {r["case_id"]: r["exact_question_sha256"] for r in cases}
            == {r["case_id"]: r["question_sha256"] for r in cohort["rows"]},
            "Question-only source differs")
    require(not output.exists() and not any((private / name).exists() for name in ("simple_bounds.json", "exact_oracles.json")),
            "Existing controls are immutable")
    provenance = {"scope_sha256": AUDIT_SHA, "cohort_freeze_sha256": COHORT_SHA,
                  "question_only_sha256": digest(raw_questions), "source_shard_sha256": scope["source"]["draw00_sha256"],
                  "ordinary_code_sha256": digest(Path(__file__).read_bytes()),
                  "source_projection": ["case_id", "question", "reviewed objective metadata"]}
    simple = [control_row(case, simple_witness, oracle=False) for case in cases]
    exact = [control_row(case, exact_optimum, oracle=True) for case in cases]
    for b, e in zip(simple, exact):
        require(b["bound"] >= e["optimum"] if b["direction"] == "MIN" else b["bound"] <= e["optimum"],
                "Feasible witness contradicts exact complete solver")
        b["same_value_as_independent_complete_optimum"] = b["bound"] == e["optimum"]
    private.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for name, records in (("simple_bounds.json", simple), ("exact_oracles.json", exact)):
        raw = encoded({"status": "QUESTION_ONLY_CONTROL_RESULTS", **provenance, "rows": records})
        with (private / name).open("xb") as stream:
            stream.write(raw)
        payloads[name] = {"sha256": digest(raw), "rows": len(records)}
    receipt = {
        "status": "D46_QUESTION_ONLY_CONTROLS_FROZEN_BEFORE_ARCHIVE_TRACE_OR_GOLD",
        **provenance, "private_payloads": payloads, "selected_questions": len(cases),
        "simple_constructs_at_the_complete_optimum_after_independent_comparison":
            sum(row["same_value_as_independent_complete_optimum"] for row in simple),
        "ordinary_point_authority": "Fixed-value feasibility only. A feasible point does not prove an optimum.",
        "timing_scope": "Executable construction and subsequent independent call to the ordinary point predicate "
                        "are measured separately. Manual derivation was not instrumented. "
                        "Zero short thread CPU durations are below timer resolution, not free work.",
        "thread_cpu_resolution_seconds": get_clock_info("thread_time").resolution,
    }
    with output.open("xb") as stream:
        stream.write(encoded(receipt))
    print(receipt["status"], digest(output.read_bytes()))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scope", type=Path, default=PHASE / "D46_QUESTION_SCOPE_AUDIT.json")
    cli.add_argument("--cohort", type=Path, default=PHASE / "D46_COHORT_FREEZE.json")
    cli.add_argument("--question-only", type=Path, default=ROOT / "outputs/d46_aime_source_20261110/d46_question_only.json")
    cli.add_argument("--output", type=Path, default=PHASE / "D46_CONTROLS_FREEZE.json")
    cli.add_argument("--private", type=Path, default=ROOT / "outputs/d46_aime_source_20261110")
    args = cli.parse_args()
    build(args.scope, args.cohort, args.question_only, args.output, args.private)


if __name__ == "__main__":
    main()
