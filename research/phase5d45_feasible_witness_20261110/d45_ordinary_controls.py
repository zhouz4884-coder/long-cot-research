"""Question-only direct construction and complete exact finite controls for D4.5."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from math import gcd, isqrt, lcm, prod
from pathlib import Path
from time import perf_counter_ns, thread_time_ns


COHORT_SHA256 = "f6e2c37da342ac2dfe3893fedb0551034ce1ed9d2b5a3f3dd1c0a3833c06918b"
QUESTION_FIELDS = {"case_id", "question", "question_sha256", "direction", "objective_id",
                   "description", "fields", "constraints", "role_patterns"}


def digest(value):
    return sha256(value).hexdigest()


def wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def digit_sum(n, work):
    digits = str(n)
    work["decimal_digits_read"] += len(digits)
    return sum(int(digit) for digit in digits)


def factors(n, work):
    found = []
    p = 2
    while p * p <= n:
        work["trial_remainders"] += 1
        if n % p:
            p = 3 if p == 2 else p + 2
        else:
            found.append(p)
            n //= p
            work["exact_factor_divisions"] += 1
    return found + ([n] if n > 1 else [])


def histogram_row(b, c, d, work):
    counts = (350 - b - c - d, b, c, d)
    work["candidate_histograms"] += 1
    if min(counts) < 0:
        return None
    work["histogram_terms"] += 16
    length = sum(counts)
    first = sum(k * n for k, n in enumerate(counts, 1))
    fourth = sum(k**4 * n for k, n in enumerate(counts, 1))
    second = sum(k*k*n for k, n in enumerate(counts, 1))
    if (length, first, fourth) != (350, 513, 4745):
        return None
    return second, {"counts": list(counts)}


def ordinary_histogram(work):
    # Subtract the length from both given moments, then eliminate the count of twos.
    remainder = ((4745 - 350) - 15 * (513 - 350)) // 10
    d_step = 5  # 21 d == remainder (mod 5), and remainder == 0 (mod 5).
    d = d_step * ((remainder // 21) // d_step)
    c = (remainder - 21 * d) // 5
    b = 513 - 350 - 2 * c - 3 * d
    work["affine_eliminations"] += 1
    return histogram_row(b, c, d, work)


def exact_histogram(work, _):
    best = None
    for d in range(351):
        for c in range(351 - d):
            work["count_pairs_visited"] += 1
            b = 513 - 350 - 2 * c - 3 * d
            row = histogram_row(b, c, d, work)
            if row is not None and (best is None or row[0] < best[0]):
                best = row
    return best


def grape_row(children):
    quotient, remainder = divmod(2009, children)
    winner = quotient + children - 1
    if remainder or winner + 2 - 2 * children < 0:
        return None
    return winner, {"winner": winner, "children": children}


def ordinary_grapes(work):
    # The smaller factor closest to sqrt(total) minimizes the sum of the pair.
    for children in range(isqrt(2009), 1, -1):
        work["children_candidates"] += 1
        row = grape_row(children)
        if row is not None:
            return row
    return None


def exact_grapes(work, _):
    rows = []
    for children in range(2, 2010):
        work["children_candidates"] += 1
        row = grape_row(children)
        if row is not None:
            rows.append(row)
    return min(rows, key=lambda row: row[0])


def floor_sum(n, work):
    work["floor_log_terms"] += 100
    return sum(len(str(k * n)) - 1 for k in range(1, 101))


def ordinary_floor(work):
    # In [100, 111], ceil(1000/n)=10. The other active threshold needs
    # ceil(10000/n)>=92, equivalently 91 n < 10000.
    n = (10000 - 1) // 91
    assert 100 <= n < n + 1 <= 111 and floor_sum(n, work) <= 300 < floor_sum(n + 1, work)
    return n, {"n": n}


def exact_floor(work, _):
    lo, hi = 1, 10000
    assert floor_sum(lo, work) <= 300 < floor_sum(hi, work)
    while lo + 1 < hi:
        work["binary_search_steps"] += 1
        mid = (lo + hi) // 2
        if floor_sum(mid, work) <= 300:
            lo = mid
        else:
            hi = mid
    return lo, {"n": lo}


def polynomial_row(n, left, right, work):
    result = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            work["coefficient_products"] += 1
            result[i+j] += a*b
    if n > 0 and result == [63, -n, 0, 0, 1]:
        return n, {"n": n, "left": left, "right": right}
    return None


def quadratic_pair(b, d, work):
    work["coefficient_square_tests"] += 1
    a = isqrt(b + d)
    if a*a != b+d:
        return None
    return polynomial_row(a * (b-d), [b, a, 1], [d, -a, 1], work)


def ordinary_polynomial(work):
    # Near-square positive constant factors minimize their difference.
    for d in range(isqrt(63), 0, -1):
        work["constant_divisor_checks"] += 1
        if 63 % d == 0:
            row = quadratic_pair(63 // d, d, work)
            if row is not None:
                return row
    return None


def exact_polynomial(work, _):
    rows = []
    for r in range(1, 64):
        work["constant_divisor_checks"] += 1
        if 63 % r:
            continue
        n = r**3 + 63 // r
        row = polynomial_row(n, [-r, 1], [r**3 - n, r*r, r, 1], work)
        assert row is not None
        rows.append(row)
        if r*r <= 63:
            row = quadratic_pair(63 // r, r, work)
            if row is not None:
                rows.append(row)
    return min(rows, key=lambda row: row[0])


def ordinary_digits(work):
    # Use a tens carry without a units carry and maximize the two suffix digits.
    tens, units = 9, 9 - 4
    n = 100 * (20 - tens - units) + 10 * tens + units
    assert digit_sum(n, work) == digit_sum(n + 864, work) == 20
    return n, {"n": n}


def exact_digits(work, bound):
    for n in range(1, bound + 1):
        work["candidate_integers"] += 1
        if digit_sum(n, work) == 20 and digit_sum(n + 864, work) == 20:
            return n, {"n": n}
    return None


def ordinary_four_primes(work):
    p = 11
    # m == 0 mod 11 first lifts to m == 11 mod 121. Lift that root once more.
    for t in range(p):
        m = p + p*p*t
        value = m*m - m + 11
        work["modular_lifts_checked"] += 1
        if value % p**3 == 0:
            ps = [p] * 3 + factors(value // p**3, work)
            assert len(ps) >= 4 and prod(ps) == value and all(factors(q, work) == [q] for q in ps)
            return m, {"m": m, "primes": ps}
    return None


def exact_four_primes(work, bound):
    for m in range(1, bound + 1):
        work["candidate_integers"] += 1
        ps = factors(m*m - m + 11, work)
        if len(ps) >= 4:
            return m, {"m": m, "primes": ps}
    return None


def mixed_row(a, b, c, work):
    work["radix_equalities"] += 1
    n = 121*a + 11*b + c
    return (n, {"a": a, "b": b, "c": c}) if n == 512 + 64*b + 8*c + a else None


def ordinary_mixed(work):
    a = (512 + 119) // 120
    for b in range(8):
        work["affine_digit_divisions"] += 1
        c, rem = divmod(120*a - 512 - 53*b, 7)
        if not rem and 0 <= c <= 7:
            return mixed_row(a, b, c, work)
    return None


def exact_mixed(work, _):
    rows = [row for a, b, c in product(range(1, 8), range(8), range(8))
            if (row := mixed_row(a, b, c, work)) is not None]
    return min(rows, key=lambda row: row[0])


def ordinary_powers(work):
    # n=p^2, m=p q. Choosing q>=2p gives v_p(m^m)>=v_p(n^n).
    for p in range(2, 12):
        work["gcd_calls"] += 1
        if gcd(p, 210) == 1:
            break
    for q in range(2*p, 2*p + 210):
        m, n = p*q, p*p
        work["construction_candidates"] += 1
        work["gcd_calls"] += 1
        if gcd(m + n, 210) == 1 and q % p:
            work["full_modular_power_calls"] += 1
            assert pow(m, m, n**n) == 0 and m % n != 0
            return m + n, {"m": m, "n": n}
    return None


def exact_powers(work, bound):
    for s in range(2, bound + 1):
        work["gcd_calls"] += 1
        if gcd(s, 210) != 1:
            continue
        for n in range(1, s):
            m = s - n
            work["positive_pairs_visited"] += 1
            if m % n == 0:
                continue
            work["gcd_calls"] += 1
            if gcd(m, n) == 1:
                continue
            work["full_modular_power_calls"] += 1
            if pow(m, m, n**n) == 0:
                return s, {"m": m, "n": n}
    return None


def ordinary_modular(work):
    # For n>=3 the mod-eight requirement forces n==5 (mod 8).
    for n in (1, 2):
        work["modular_power_calls"] += 2
        if (pow(2, n, 1000) + pow(5, n, 1000) - n) % 1000 == 0:
            return n, {"n": n}
    for n in range(5, 1003, 8):
        work["modular_power_calls"] += 1
        if pow(2, n, 125) == n % 125:
            return n, {"n": n}
    return None


def exact_modular(work, _):
    a, b = 1, 1
    rows = []
    for n in range(1, 1003):
        a, b = 2*a % 1000, 5*b % 1000
        work["modular_recurrence_updates"] += 2
        work["residue_checks"] += 1
        if (a + b - n) % 1000 == 0:
            rows.append(n)
    n = min(rows)
    return n, {"n": n}


def adult_row(initial, work):
    work["exact_ratio_evaluations"] += 2
    start = Fraction(5 * initial, 12)
    end = Fraction(11 * (initial + 50), 25)
    if start.denominator == end.denominator == 1 and 0 <= end - start <= 50:
        return int(end), {"initial_crowd": initial, "bus_adults": int(end - start)}
    return None


def ordinary_adults(work):
    work["lcm_calls"] += 1
    return adult_row(lcm(12, 25), work)


def exact_adults(work, bound):
    # The verified final adult count bounds initial size by the original final ratio.
    maximum_initial = (25 * bound) // 11 - 50
    rows = [row for initial in range(1, maximum_initial + 1) if (row := adult_row(initial, work)) is not None]
    return min(rows, key=lambda row: row[0])


def cubic_row(p, a, b, work):
    work["cubic_and_triangle_checks"] += 1
    x, y = a*(a*a - 3*b*b), b*(3*a*a - b*b)
    if min(x, y) > 0 and abs(x-y) < p < x+y:
        return p, {"p": p, "a": a, "b": b}
    return None


def ordinary_complex(work):
    for p in range(999, 1, -1):
        work["candidate_norms"] += 1
        if p != 2 and p % 4 != 1:
            continue
        if factors(p, work) != [p]:
            continue
        for a in range(1, isqrt(p) + 1):
            work["square_complements"] += 1
            b = isqrt(p - a*a)
            if b > a or a*a + b*b != p:
                continue
            ar, br = a, b
            for _ in range(4):
                row = cubic_row(p, ar, br, work)
                if row is not None:
                    return row
                ar, br = -br, ar
    return None


def exact_complex(work, _):
    best = None
    radius = isqrt(999)
    for a, b in product(range(-radius, radius+1), repeat=2):
        work["signed_coordinate_pairs"] += 1
        p = a*a+b*b
        if 2 <= p < 1000 and factors(p, work) == [p]:
            row = cubic_row(p, a, b, work)
            if row is not None and (best is None or p > best[0]):
                best = row
    return best


# Ordinary proof labels distinguish direct same-permission construction from
# cases where the natural construction itself already proves the optimum.
CASES = {
    "2009-I-14": ("MIN", ordinary_histogram, exact_histogram, True,
        "Eliminate the count of twos from the two given moment residuals. The count of fours is a multiple of five and the second moment decreases with it. Verify the largest feasible such count.",
        "Every histogram has two counts in the enumerated length simplex; the first moment fixes the remaining two. Test the original constraints and compare all feasible second moments."),
    "2009-II-4": ("MIN", ordinary_grapes, exact_grapes, True,
        "Factor the total as children times winner-plus-one-minus-children. The valid divisor closest to the square root minimizes the factor sum.",
        "Positive total implies the child count divides it and cannot exceed it. Visit every possible child count and verify the last child is nonnegative."),
    "2010-I-14": ("MAX", ordinary_floor, exact_floor, True,
        "Use the two active powers of ten in a narrow bracket to derive a candidate and verify its immediate successor violates the prescribed sum.",
        "Each term is nondecreasing; at the proved upper sentinel every term already exceeds the allowed mean. Binary search the last feasible integer using exact decimal lengths."),
    "2010-II-6": ("MIN", ordinary_polynomial, exact_polynomial, True,
        "Choose the closest distinct odd constant pair with square sum. In degree two plus two the linear magnitude is at least the minimal odd-pair gap times the lower square-root bound; in degree one plus three a positive integer root gives a larger coefficient.",
        "Normalize integer factors to be monic. Degree one plus three is determined by a positive divisor root; degree two plus two by a positive constant divisor pair, a square sum, and a sign of the linear term."),
    "2015-I-8": ("MIN", ordinary_digits, exact_digits, True,
        "Equal digit sums require exactly two carries when adding the shift. Every three-digit candidate already carries at the hundreds place; choose the smallest prefix from the two possibilities for the other carry.",
        "The constructive witness bounds the minimum. Scan every smaller positive integer using the original two decimal digit sums."),
    "2016-I-12": ("MIN", ordinary_four_primes, exact_four_primes, False,
        "Lift a root of the quadratic modulo eleven to its cube, then factor the remaining quotient and check the complete product.",
        "The verified construction gives an upper index. Trial-divide the positive polynomial at every smaller positive index, retaining prime multiplicity."),
    "2020-I-3": ("MIN", ordinary_mixed, exact_mixed, True,
        "Eliminate the common represented integer. The smallest possible leading digit is feasible, and its equation fixes the remaining digits uniquely within the base-eight ranges.",
        "All three symbols occur in base eight, the leading base-eleven digit is positive, and the finite product of those digit domains is complete."),
    "2020-I-10": ("MIN", ordinary_powers, exact_powers, False,
        "Use a squared prime for one argument and one copy of that prime in the other. A small cofactor meets the original sum coprimality and exponent-valuation conditions.",
        "A feasible sum bounds the minimum. Enumerate every smaller positive ordered pair by sum, applying gcd and exact modular exponentiation to the original divisibilities."),
    "2021-II-13": ("MIN", ordinary_modular, exact_modular, True,
        "Check the two preperiod indices. Beyond them, reduction modulo eight restricts the index to one progression; test the remaining congruence modulo 125 in order.",
        "For n>=3, the two powers modulo eight and 125 have periods dividing 1000, as does the subtracted index. Check the two preperiod indices and a full tail period by exact recurrence."),
    "2022-II-1": ("MIN", ordinary_adults, exact_adults, True,
        "Integrality of both stated ratios forces the initial size to be a positive multiple of the two denominators' least common multiple; the first such crowd gives feasible bus occupancy.",
        "The constructive final adult count bounds the initial crowd by the strictly increasing original final ratio. Check both exact ratios and bus occupancy at every eligible initial size."),
    "2023-I-15": ("MAX", ordinary_complex, exact_complex, True,
        "Try prime norms in descending order, using parity to rule out impossible norms, square complements to represent them, and quarter turns to orient the cubic coordinates positively.",
        "The strict norm cap bounds each signed integer coordinate absolutely. Enumerate the entire resulting square, test primality and exact positive cubic triangle sides, and retain the maximum."),
}


def measured(function, *args):
    work = Counter()
    wall_start, cpu_start = perf_counter_ns(), thread_time_ns()
    result = function(work, *args)
    cpu_ns, wall_ns = thread_time_ns() - cpu_start, perf_counter_ns() - wall_start
    if result is None:
        raise ValueError("No feasible result within the proved search domain")
    objective, witness = result
    return {"objective": objective, "witness": witness, "work": dict(work), "cpu_ns": cpu_ns, "wall_ns": wall_ns}


def run(question_only, cohort, problem_specs, ordinary_path, exact_path, freeze):
    cohort_bytes = cohort.read_bytes()
    if digest(cohort_bytes) != COHORT_SHA256:
        raise ValueError("Unexpected ordered cohort identity")
    cohort_data = json.loads(cohort_bytes)
    question_bytes, specs_bytes = question_only.read_bytes(), problem_specs.read_bytes()
    if (digest(question_bytes) != cohort_data["question_only_sha256"]
            or digest(specs_bytes) != cohort_data["problem_specs_sha256"]):
        raise ValueError("Question-only or reviewed specs bytes differ from the cohort")
    visible = json.loads(question_bytes)
    ordered = visible["rows"]
    case_ids = [row["case_id"] for row in ordered]
    if (case_ids != [row["case_id"] for row in cohort_data["rows"]]
            or len(case_ids) != len(CASES) or set(case_ids) != set(CASES)):
        raise ValueError("Independent controls and nominated ordered cohort differ")
    ordinary_rows, exact_rows, public_rows = [], [], []
    for item, selected in zip(ordered, cohort_data["rows"]):
        cid = item["case_id"]
        qsha = digest(item["question"].encode())
        if (set(item) != QUESTION_FIELDS or qsha != item["question_sha256"]
                or any(item[key] != selected[key] for key in QUESTION_FIELDS - {"question"})):
            raise ValueError("Question-only scope or reviewed original constraints differ")
        sense, ordinary_fn, exact_fn, ordinary_proves, ordinary_proof, exact_proof = CASES[cid]
        if sense != item["direction"]:
            raise ValueError("Ordinary control direction differs from the original objective")
        ordinary = measured(ordinary_fn)
        exact = measured(exact_fn, ordinary["objective"])
        if set(ordinary["witness"]) != set(item["fields"]) or set(exact["witness"]) != set(item["fields"]):
            raise ValueError("A witness does not use the reviewed representation")
        weak, optimum = ordinary["objective"], exact["objective"]
        if (sense == "MIN" and weak < optimum) or (sense == "MAX" and weak > optimum) or (ordinary_proves and weak != optimum):
            raise ValueError("Independent feasible or exact controls disagree")
        binding = {"case_id": cid, "question_sha256": qsha, "direction": sense, "objective_id": item["objective_id"]}
        ordinary_rows.append({**binding, "witness": ordinary["witness"], "bound": weak,
                              "bound_direction": "UPPER" if sense == "MIN" else "LOWER",
                              "derivation": ordinary_proof, "attempted_control_calls": 1,
                              "work": ordinary["work"], "cpu_ns": ordinary["cpu_ns"], "wall_ns": ordinary["wall_ns"]})
        exact_rows.append({**binding, "witness": exact["witness"], "optimum": optimum,
                           "finite_completeness_proof": exact_proof, "ordinary_proves_optimum": ordinary_proves,
                           "same_numeric_bound_as_ordinary": weak == optimum, "attempted_oracle_calls": 1,
                           "work": exact["work"], "cpu_ns": exact["cpu_ns"], "wall_ns": exact["wall_ns"]})
        public_rows.append({**binding,
                            "ordinary_proof": ordinary_proof, "exact_completeness_proof": exact_proof,
                            "ordinary_work": ordinary["work"], "ordinary_cpu_ns": ordinary["cpu_ns"], "ordinary_wall_ns": ordinary["wall_ns"],
                            "oracle_cpu_ns": exact["cpu_ns"], "oracle_wall_ns": exact["wall_ns"]})
    provenance = {"cohort_freeze_sha256": COHORT_SHA256, "scope_audit_sha256": cohort_data["scope_audit_sha256"],
                  "question_only_sha256": digest(question_bytes), "problem_specs_sha256": digest(specs_bytes),
                  "control_source_sha256": digest(Path(__file__).read_bytes()),
                  "cost_boundary": "Per control call includes construction/search and arithmetic checks. Named counters record selected concrete operations or loop visits with different unit costs. Source I/O, hashing and artifact encoding are outside these measurements."}
    ordinary_raw = wire({"status": "QUESTION_ONLY_ORDINARY_BOUNDS_FROZEN", **provenance, "rows": ordinary_rows})
    exact_raw = wire({"status": "QUESTION_ONLY_COMPLETE_ORACLES_FROZEN_OFFLINE", **provenance, "rows": exact_rows})
    write(ordinary_path, ordinary_raw)
    write(exact_path, exact_raw)
    write(freeze, wire({"status": "INDEPENDENT_ORDINARY_AND_EXACT_CONTROLS_FROZEN_BEFORE_LABELS",
                        **provenance, "ordinary_bounds_sha256": digest(ordinary_raw), "complete_oracles_sha256": digest(exact_raw),
                        "cases": len(ordinary_rows),
                        "oracle_boundary": "Numeric exact oracles, complete-search counters, and agreement with ordinary bounds are isolated from claim observation and blind scoring.",
                        "ordinary_total_cpu_ns": sum(row["ordinary_cpu_ns"] for row in public_rows),
                        "oracle_total_cpu_ns": sum(row["oracle_cpu_ns"] for row in public_rows), "rows": public_rows}))
    print(f"Frozen {len(ordinary_rows)} ordinary and exact controls from question-only projection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("question-only", "cohort", "problem-specs", "ordinary-bounds", "complete-oracles", "freeze"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    outputs = (args.ordinary_bounds, args.complete_oracles, args.freeze)
    if len({path.resolve() for path in outputs}) != 3 or any(path.exists() for path in outputs):
        parser.error("Expected three distinct new output paths")
    run(args.question_only, args.cohort, args.problem_specs, *outputs)
