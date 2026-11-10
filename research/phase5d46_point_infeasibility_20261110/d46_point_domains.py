"""Exact original-constraint tests at one supplied value, without optimizing."""
from __future__ import annotations

from fractions import Fraction
from itertools import permutations
from math import comb, isqrt

from d46_problem_specs import PROBLEMS
from point_verifier import (
    COMPLETE_FIXED_VALUE_FIBER, EXACT_FEASIBILITY_WITNESS, EXACT_NECESSARY_PREDICATE,
    PROVEN_FEASIBLE, PROVEN_INFEASIBLE, UNKNOWN, PointEvidence,
)

CASE_BY_OBJECTIVE = {row["objective_id"]: cid for cid, row in PROBLEMS.items()}
EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
OPPOSITE = ((0, 5), (1, 4), (2, 3))
KNOWN = (189, 320, 287, 234)


def deliver(cid: str, feasible: bool, details: tuple, meter, fiber: int | None = None) -> PointEvidence:
    scope = tuple(PROBLEMS[cid]["constraints"])
    if feasible:
        for name in scope:
            meter.charge("constraint:" + name)
        return PointEvidence(PROVEN_FEASIBLE, EXACT_FEASIBILITY_WITNESS, details, True, scope)
    meter.charge("exclusion_proof")
    kind = EXACT_NECESSARY_PREDICATE if fiber is None else COMPLETE_FIXED_VALUE_FIBER
    return PointEvidence(PROVEN_INFEASIBLE, kind, details, True, scope, fiber, fiber)


def decimal_sum(n: int, meter) -> int:
    total = 0
    while n:
        meter.charge("digit_remainder_steps")
        n, r = divmod(n, 10)
        total += r
    return total


def modular_product_power(a: int, n: int, m: int, meter) -> int:
    result = 1 % m
    a %= m
    while n:
        if n & 1:
            meter.charge("modular_multiply_steps")
            result = result * a % m
        n >>= 1
        if n:
            meter.charge("modular_square_steps")
            a = a * a % m
    return result


def is_prime(n: int, meter) -> bool:
    if n < 2:
        return False
    for k in range(2, isqrt(n) + 1):
        meter.charge("prime_trial_remainders")
        if n % k == 0:
            return False
    return True


def ceil_square_root(n: int, meter) -> int:
    meter.charge("integer_square_root")
    k = isqrt(n)
    return k if k * k == n else k + 1


def telescoping_index(n, meter):
    v = 3 * n + 2
    exponent = 0
    while v % 5 == 0:
        meter.charge("power_of_five_divisions")
        v //= 5
        exponent += 1
    return n > 1 and v == 1, (("remaining_factor", v), ("power_of_five_exponent", exponent))


def power_two(n, meter):
    if n >= 950:
        return False, (("strict_product_bit_upper", 950),)
    modulus = 1 << n
    result = 1
    for d in range(1, 20):
        for _ in range(20 - d):
            meter.charge("product_modular_steps")
            result = result * d % modulus
            if result == 0:
                return True, (("modular_product", 0), ("exponent", n))
    return False, (("modular_product", str(result)), ("exponent", n))


def equal_area_isosceles(n, meter):
    meter.charge("equal_area_base_scale_relation")
    k, remainder = divmod(15 * n, 338)
    if remainder or k <= 0:
        return False, (("scale_remainder", remainder), ("base_scale", k))
    a, b = 8 * k, 7 * k
    meter.charge("perimeter_side_checks", 2)
    sides = all((n - base) % 2 == 0 and n > 2 * base for base in (a, b))
    meter.charge("squared_area_products", 2)
    lhs, rhs = a*a*n*(n - 2*a), b*b*n*(n - 2*b)
    return sides and lhs == rhs, (("base_one", a), ("base_two", b), ("scaled_area_squared", str(lhs)))


def conditioned_run_count(n, meter):
    gaps = n + 1
    meter.charge("small_binomial_evaluations", 2)
    pair, triple = comb(gaps, 2), comb(gaps, 3)
    favorable = gaps + 2 * pair
    all_valid = gaps + 3 * pair + triple
    return 100 * favorable <= all_valid, (("favorable_patterns", str(favorable)), ("conditioned_patterns", str(all_valid)))


def square_free_block(n, meter):
    low, high = 1000*n, 1000*n + 999
    k = ceil_square_root(low, meter)
    return k*k > high, (("next_square", k*k), ("interval_upper", high))


def incenter_fiber(n, meter):
    # BI²=b²(P-b)/(2P)=64 and P>2b force 128<b²<256.
    for b in range(12, 16):
        meter.charge("fiber_points")
        if n > 2*b and (n-b) % 2 == 0 and b*b*(n-b) == 128*n:
            return True, (("equal_side", (n-b)//2), ("base", b)), None
    return False, (("first_possible_base", 12), ("last_possible_base", 15)), 4


def digit_and_divisibility(n, meter):
    meter.charge("original_modular_predicates")
    digit = decimal_sum(n, meter)
    r = n % 17
    return r == 0 and digit == 17, (("modulo_17", r), ("decimal_digit_sum", digit))


def grid_adjacency(n, meter):
    meter.charge("cross_multiplied_probability")
    product = n*(n+1)
    return n >= 2 and product > 8060, (("n_times_n_plus_one", str(product)), ("required_strict_threshold", 8060))


def missing_edges_fiber(value, meter):
    total = (sum(KNOWN) + value) / 3
    for assigned in permutations(range(6), len(KNOWN)):
        meter.charge("fiber_points")
        weights = dict(zip(assigned, KNOWN, strict=True))
        possible = True
        for a, b in OPPOSITE:
            meter.charge("opposite_edge_checks")
            if a in weights and b in weights:
                if weights[a] + weights[b] != total:
                    possible = False
                    break
            elif a in weights:
                weights[b] = total - weights[a]
            elif b in weights:
                weights[a] = total - weights[b]
            else:
                # Both missing opposite would force total=515. No given pair sums to 515.
                possible = False
                break
        if not possible:
            continue
        a = (weights[0] + weights[1] + weights[2] - total) / 2
        nums = (a, weights[0]-a, weights[1]-a, weights[2]-a)
        if len(set(nums)) == 4 and all(nums[i]+nums[j] == weights[k] for k, (i, j) in enumerate(EDGES)):
            return True, tuple((f"vertex_{i}", str(n)) for i, n in enumerate(nums)), None
    return False, (("candidate_vertex_total", str(total)), ("assignments_exhausted", 360)), 360


def odd_prime_factor(n, meter):
    prime = n % 2 == 1 and is_prime(n, meter)
    r = (modular_product_power(2019, 8, n, meter) + 1) % n
    return prime and r == 0, (("prime_and_odd", prime), ("original_expression_remainder", r))


def recursive_ratio(n, meter):
    k = ceil_square_root(n, meter)
    ell = k if k % 2 == n % 2 else k + 1
    f, g = k*k-n+k, ell*ell-n+ell
    meter.charge("exact_ratio_cross_products", 2)
    return 7*f == 4*g, (("f_at_point", f), ("g_at_point", g))


PREDICATES = {
    "2009-I-7": telescoping_index, "2010-II-3": power_two, "2010-II-12": equal_area_isosceles,
    "2011-I-12": conditioned_run_count, "2013-II-6": square_free_block, "2015-II-3": digit_and_divisibility,
    "2015-II-5": grid_adjacency, "2019-I-14": odd_prime_factor, "2021-II-15": recursive_ratio,
}


def check(binding, value: Fraction, meter) -> PointEvidence:
    cid = CASE_BY_OBJECTIVE[binding.objective_id]
    if binding.direction != PROBLEMS[cid]["direction"]:
        return PointEvidence(UNKNOWN)
    if cid == "2017-II-5":
        passed, details, paid_fiber = missing_edges_fiber(value, meter)
        return deliver(cid, passed, details, meter, paid_fiber)
    if value.denominator != 1 or value <= 0:
        fiber = 0 if cid == "2015-I-11" else None
        return deliver(cid, False, (("violated_positive_integer_domain", str(value)),), meter, fiber)
    if value > 1_000_000:
        return PointEvidence(UNKNOWN)
    n = value.numerator
    if cid == "2015-I-11":
        passed, details, paid_fiber = incenter_fiber(n, meter)
        return deliver(cid, passed, details, meter, paid_fiber)
    passed, details = PREDICATES[cid](n, meter)
    return deliver(cid, passed, details, meter)
