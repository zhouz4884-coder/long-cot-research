"""Reviewed feasibility of one value, with no optimum search or label access."""
from __future__ import annotations

from fractions import Fraction
from math import isqrt

from d47_problem_specs import PROBLEMS
from point_verifier import (
    EXACT_FEASIBILITY_WITNESS, EXACT_NECESSARY_PREDICATE, PROVEN_FEASIBLE, PROVEN_INFEASIBLE,
    UNKNOWN, PointEvidence,
)

CASES = {spec["objective_id"]: cid for cid, spec in PROBLEMS.items()}
INTEGER = {"2009-I-13", "2010-I-12", "2016-II-4", "2019-I-11", "2020-II-8"}
SCHUR = tuple((a, b, a+b) for a in range(1, 6) for b in range(a, 6-a))


def finish(cid, passed, details, meter):
    names = tuple(PROBLEMS[cid]["constraints"])
    if passed:
        for name in names:
            meter.charge("constraint:"+name)
        return PointEvidence(PROVEN_FEASIBLE, EXACT_FEASIBILITY_WITNESS, details, True, names)
    meter.charge("exclusion_proof")
    return PointEvidence(PROVEN_INFEASIBLE, EXACT_NECESSARY_PREDICATE, details, True, names)


def recurrence_sum(n, meter):
    meter.charge("quadratic_discriminant")
    delta = n*n-4*2009
    if delta < 0:
        return False, (("negative_discriminant", str(delta)),)
    meter.charge("integer_square_root")
    root = isqrt(delta)
    a, b = (n-root)//2, (n+root)//2
    if root*root != delta or (n-root) % 2 or a < 1 or a*b != 2009:
        return False, (("discriminant", str(delta)), ("integer_sqrt", root))
    return True, (("first_term", a), ("second_term", b))


def red(n: int) -> bool:
    return n < 9 or n >= 81


def monochromatic_endpoint(n, meter):
    if n < 3:
        return False, (("domain_lower", 3),)
    if n < 243:
        for a in range(3, isqrt(n)+1):
            for b in range(a, n//a+1):
                meter.charge("countercolour_product_checks")
                if red(a) == red(b) == red(a*b):
                    raise ValueError("The reviewed countercolour failed")
        return False, (("countercolour_rule", "red below 9 or at least 81"), ("endpoint", n))
    for mask in range(32):
        found = False
        for a, b, c in SCHUR:
            meter.charge("five_power_colour_triples")
            if (mask >> (a-1)) & 1 == (mask >> (b-1)) & 1 == (mask >> (c-1)) & 1:
                found = True
                break
        if not found:
            raise ValueError("The five-power universal proof failed")
    return True, (("certified_subset", "3,9,27,81,243"), ("colour_masks_checked", 32))


def coloured_volume(n, meter):
    meter.charge("integer_volume_divisions", 2)
    k, rem = divmod(n, 180)
    if rem or k <= 0 or 12 % k:
        return False, (("required_volume_multiple", 180), ("scale_must_divide", 12))
    a, b, c = 5*k, 3*k, 12//k
    template = (0,)*3 + (1,)*4 + (2,)*5
    rows = [[0]*3 for _ in range(a)]
    columns = [[0]*3 for _ in range(b)]
    for i in range(a):
        for j in range(b):
            start = ((i+j) % k)*c
            for colour in template[start:start+c]:
                meter.charge("constructed_cube_assignments")
                rows[i][colour] += 1
                columns[j][colour] += 1
    meter.charge("layer_vector_checks", a+b)
    if not all(row == [9, 12, 15] for row in rows) or not all(col == [15, 20, 25] for col in columns):
        raise ValueError("Cyclic witness violates an original layer count")
    return True, (("a", a), ("b", b), ("c", c), ("all_original_layer_counts", True))


def incenter_area(value, meter):
    meter.charge("exact_area_radicand")
    radicand = value*value/21-756
    # BX=12+sqrt(radicand), with X strictly between the endpoints.
    return value > 0 and 0 <= radicand < 400, (("offset_radicand", str(radicand)), ("strict_squared_offset_upper", 400))


def squared_diameter(value, meter):
    # Distances from the explicit center (5/2, 9sqrt(3)/2) to all six sides.
    squared_margins = (Fraction(243, 4), Fraction(243, 4), 48, 147, Fraction(147, 4), Fraction(147, 4))
    passed = value > 0
    for margin in squared_margins:
        meter.charge("exact_halfspace_squared_distances")
        passed &= value <= 4*margin
    return passed, (("opposite_cd_fa_squared_spacing", 147), ("center_x", "5/2"), ("center_y_over_sqrt3", "9/2"))


def excircle_perimeter(n, meter):
    meter.charge("perimeter_divisibility")
    k, rem = divmod(n, 20)
    if rem or k <= 0:
        return False, (("required_perimeter_multiple", 20),)
    a, b = 9*k, 2*k
    h2 = a*a-Fraction(b*b, 4)
    r, r_a = Fraction(b, 2*a+b), Fraction(b, 2*a-b)
    omega = r+2*r_a
    meter.charge("exact_tangency_equalities", 3)
    assert omega > 0 and omega-r_a == r+r_a
    assert a*a+h2*(1-r)**2 == h2*(omega+1)**2
    return True, (("equal_side", a), ("base", b), ("omega_radius_over_altitude", str(omega)))


def recursive_zero_sum(n, meter):
    meter.charge("exact_recursive_zero_sum")
    distinct = n*(n-1)//2+1
    total = n*distinct
    return total > 500000, (("distinct_zeros", str(distinct)), ("zero_sum", str(total)))


def ellipse_sum(value, meter):
    meter.charge("sum_of_focal_distance_bound")
    # The opposite-focus segment lengths are 26 and 20. At (14,15/2) both
    # triangles attain equality. A vertical ray there avoids both focal segments.
    return value >= 23, (("focal_distance_sum_lower", 46), ("ray_x", 14), ("ray_start_y", "15/2"))


FUNCTIONS = {
    "2009-I-13": recurrence_sum, "2010-I-12": monochromatic_endpoint, "2016-II-4": coloured_volume,
    "2018-I-13": incenter_area, "2018-I-8": squared_diameter, "2019-I-11": excircle_perimeter,
    "2020-II-8": recursive_zero_sum, "2022-II-12": ellipse_sum,
}


def check(binding, value: Fraction, meter) -> PointEvidence:
    cid = CASES[binding.objective_id]
    if binding.direction != PROBLEMS[cid]["direction"]:
        return PointEvidence(UNKNOWN)
    if cid in INTEGER:
        if value.denominator != 1 or value <= 0:
            return finish(cid, False, (("violated_positive_integer_domain", str(value)),), meter)
        value = value.numerator
    passed, details = FUNCTIONS[cid](value, meter)
    return finish(cid, passed, details, meter)
