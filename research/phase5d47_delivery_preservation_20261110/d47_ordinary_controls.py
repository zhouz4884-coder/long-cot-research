"""Independent fixed-value feasibility and complete question-only CPU controls."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from math import isqrt
from pathlib import Path
from time import get_clock_info, perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AUDIT_SHA = "2b80174877af53254ae91e68afb6e9dba592816a0cd73123a2d070d320726812"
COHORT_SHA = "2934940c86a5e632f5a0efa3e9fa1d3af5554f6f796dfc03fd252c8fe43dc1fe"
CASES = (
    "2009-I-13", "2010-I-12", "2016-II-4", "2018-I-8",
    "2018-I-13", "2019-I-11", "2020-II-8", "2022-II-12",
)
EXAMPLES = {
    "2009-I-13": (90, 294), "2010-I-12": (243, 244), "2016-II-4": (180, 360),
    "2018-I-8": (25, 100), "2018-I-13": (126, 127), "2019-I-11": (20, 40),
    "2020-II-8": (120, 121), "2022-II-12": (24, 25),
}


def digest(raw):
    return sha256(raw).hexdigest()


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


class ControlMeter:
    def __init__(self):
        self.counts = Counter()

    def charge(self, label, count=1):
        self.counts[label] += count


def _recurrence_pair(total, meter):
    discriminant = total * total - 4 * 2009
    meter.charge("quadratic_discriminant")
    if discriminant < 0:
        return None
    meter.charge("integer_square_root")
    root = isqrt(discriminant)
    if root * root != discriminant or (total - root) % 2 or total <= root:
        return None
    return (total - root) // 2, (total + root) // 2


def _triples(maximum, meter):
    constraints = []
    for a in range(3, isqrt(maximum) + 1):
        for b in range(a, maximum // a + 1):
            meter.charge("generate_multiplicative_clause")
            # Repeated factors give a two-variable inequality.
            constraints.append(tuple(sorted({a, b, a * b})))
    return constraints


def _schur_bound(meter):
    # Color 1=0 by global color symmetry. Exhaustively verify the explicit
    # obstruction on 1..5, which is valid on their powers of 3 at m>=243.
    triples = [(a, b, a + b) for a in range(1, 6) for b in range(a, 6 - a)]
    for suffix in product((0, 1), repeat=4):
        colors = (None, 0, *suffix)
        meter.charge("schur_colorings")
        found = False
        for a, b, c in triples:
            meter.charge("schur_triple_tests")
            if colors[a] == colors[b] == colors[c]:
                found = True
                break
        require(found, "Claimed finite Schur obstruction is invalid")
    return 3**5


def _propagate(constraints, assignment, meter):
    forces = []
    while True:
        changed = False
        for clause_index, clause in enumerate(constraints):
            meter.charge("nae_propagation_clause")
            bound = {assignment[var] for var in clause if assignment[var] != -1}
            if len(bound) != 1:
                continue
            unbound = [var for var in clause if assignment[var] == -1]
            if not unbound:
                return forces, clause_index
            if len(unbound) == 1:
                var = unbound[0]
                color = 1 - next(iter(bound))
                assignment[var] = color
                forces.append([var, color, clause_index])
                changed = True
        if not changed:
            return forces, None


def _dpll(constraints, variables, assignment, meter):
    meter.charge("nae_search_node")
    assignment = assignment.copy()
    forces, conflict = _propagate(constraints, assignment, meter)
    if conflict is not None:
        return None, {"forces": forces, "conflict": conflict}
    branch = next((var for var in variables if assignment[var] == -1), None)
    if branch is None:
        return assignment, None
    proof = {"forces": forces, "split": branch, "children": []}
    for color in (0, 1):
        assignment[branch] = color
        sat, subtree = _dpll(constraints, variables, assignment, meter)
        if sat is not None:
            return sat, None
        proof["children"].append(subtree)
    return None, proof


def _verify_unsat(node, constraints, assignment, meter):
    """Replay a complete finite contradiction tree, checking each unit reason."""
    meter.charge("nae_proof_node")
    assignment = assignment.copy()
    for variable, color, index in node["forces"]:
        meter.charge("nae_proof_unit")
        clause = constraints[index]
        require(variable in clause and assignment[variable] == -1 and color in (0, 1)
                and all(assignment[item] == 1 - color for item in clause if item != variable),
                "Invalid unit in NAE proof")
        assignment[variable] = color
    if "conflict" in node:
        meter.charge("nae_proof_conflict")
        bound = {assignment[var] for var in constraints[node["conflict"]]}
        require(len(bound) == 1 and -1 not in bound, "Invalid leaf in NAE proof")
        return
    variable = node["split"]
    require(assignment[variable] == -1 and len(node["children"]) == 2,
            "Incomplete split in NAE proof")
    for color, child in enumerate(node["children"]):
        assignment[variable] = color
        _verify_unsat(child, constraints, assignment, meter)


def _checked_coloring(maximum, constraints, colors, meter, kind):
    for clause in constraints:
        meter.charge("nae_counterexample_clause")
        require(len({colors[var] for var in clause}) == 2, "Invalid coloring counterexample")
    return False, {"kind": kind, "color_one": [i for i in range(3, maximum + 1) if colors[i] == 1],
                   "clauses": len(constraints)}


def coloring_property(maximum, meter, *, explicit=False):
    """Return whether every 2-coloring contains a product triple, and its evidence."""
    if maximum < 3:
        return False, {"kind": "BELOW_DOMAIN"}
    if maximum >= 243 and not explicit:
        require(_schur_bound(meter) == 243, "Wrong finite obstruction endpoint")
        return True, {"kind": "EXHAUSTIVE_POWER_OF_THREE_OBSTRUCTION"}
    constraints = _triples(maximum, meter)
    if not explicit:
        # Exponents log_3(x) in [1,2) or [4,5) have color zero.
        # Products within that color fall in [2,4) or exceed the domain.
        # Products with both exponents in [2,4) have exponent at least 4.
        meter.charge("explicit_floor_log_color_values", maximum - 2)
        colors = [int(9 <= i < 81) for i in range(maximum + 1)]
        return _checked_coloring(maximum, constraints, colors, meter, "EXPLICIT_FLOOR_LOG_COLORING")
    degree = Counter(var for clause in constraints for var in clause)
    variables = sorted(degree, key=lambda var: (-degree[var], var))
    # Complementing every color preserves every NAE clause.
    base = [-1] * (maximum + 1)
    base[3] = 0
    coloring, proof = _dpll(constraints, variables, base, meter)
    if coloring is not None:
        complete = [value if value != -1 else 0 for value in coloring]
        return _checked_coloring(maximum, constraints, complete, meter, "EXPLICIT_DPLL_COLORING")
    _verify_unsat(proof, constraints, base, meter)
    return True, {"kind": "COMPLETE_NAE_DPLL_PROOF", "clauses": len(constraints), "proof": proof}


def _cyclic_coloring(volume, meter):
    meter.charge("volume_division")
    k, residue = divmod(volume, 180)
    if residue or k < 1 or 12 % k:
        return None
    c = 12 // k
    colors = "RRRGGGGYYYYY"
    groups = [colors[i:i + c] for i in range(0, len(colors), c)]
    meter.charge("cyclic_color_construction", len(colors))
    require(len(groups) == k and all(len(group) == c for group in groups), "Wrong cyclic coloring shape")
    totals = Counter("".join(groups))
    require(3 * totals["R"] == 9 and 3 * totals["G"] == 12
            and 5 * totals["G"] == 20 and 5 * totals["Y"] == 25, "Cyclic color marginals differ")
    return {"dimensions": [5 * k, 3 * k, c], "colors_for_i_plus_j_mod_k": groups}


def _hexagon_geometry(meter):
    # y is stored as its coefficient of sqrt(3). Unit directions are exact.
    dirs = ((1, 0), (Fraction(1, 2), Fraction(1, 2)), (Fraction(-1, 2), Fraction(1, 2)),
            (-1, 0), (Fraction(-1, 2), Fraction(-1, 2)), (Fraction(1, 2), Fraction(-1, 2)))
    meter.charge("hexagon_closure_equations", 2)
    # The vertical equation gives EF+FA=18, and the horizontal gives FA-EF=14.
    lengths = (6, 8, 10, 12, (18 - 14) // 2, (18 + 14) // 2)
    vertices = [(0, 0)]
    for length, (dx, dy) in zip(lengths, dirs):
        meter.charge("exact_hexagon_coordinate")
        x, y = vertices[-1]
        vertices.append((x + length * dx, y + length * dy))
    require(vertices[-1] == vertices[0], "Hexagon fails exact closure")
    center = Fraction(5, 2), Fraction(9, 2)
    distances = []
    for (x, y), (dx, dy) in zip(vertices[:-1], dirs):
        meter.charge("exact_side_distance")
        distances.append(dx * (center[1] - y) - dy * (center[0] - x))
    cd, fa = dirs[2], dirs[5]
    require(tuple(-coord for coord in cd) == fa, "Opposite normal calculation differs")
    width = distances[2] + distances[5]
    require(2 * min(distances) == width, "Largest inscribed disk fails halfspace feasibility")
    return 3 * width * width, {"center_x_and_sqrt3_y_coefficient": [str(v) for v in center],
                               "side_distances_over_sqrt3": [str(v) for v in distances]}


def _incenter_area_geometry(meter):
    ab, bc, ac = 30, 32, 34
    meter.charge("incenter_exact_geometry", 8)
    projection = Fraction(ab * ab + bc * bc - ac * ac, 2 * bc)
    h2 = ab * ab - projection * projection
    # Substitute d^2=x^2-2*projection*x+AB^2 into the two products
    # from the squared A-to-incenter distances. Coefficients are (d,x,1).
    numerator = (ab + ac - bc, -2 * projection + ab - ac + bc, ab * ab + ab * (ac - bc))
    denominator = (ab + ac + bc, -2 * projection + ac + bc - ab, ab * ab + ab * (ac + bc))
    ratio = Fraction(numerator[0], denominator[0])
    require(all(a == ratio * b for a, b in zip(numerator, denominator)),
            "Incenter expression failed exact cancellation")
    cos_a = Fraction(ab * ab + ac * ac - bc * bc, 2 * ab * ac)
    area2_per_d2 = Fraction(ab * ac, 4) * ratio * (1 - cos_a) / 2
    require(0 < projection < bc, "Altitude foot does not lie inside the open side")
    return area2_per_d2 * h2, area2_per_d2 * max(ab * ab, ac * ac), {
        "altitude_projection": str(projection), "area_squared_over_AX_squared": str(area2_per_d2)}


def _excircle_at_scale(scale, meter):
    meter.charge("incircle_and_excircle_rational_checks", 3)
    s, b = 9 * scale, 2 * scale
    h2 = s * s - Fraction(b * b, 4)
    r, r_a = Fraction(b, 2 * s + b), Fraction(b, 2 * s - b)
    central = r + 2 * r_a
    require(h2 > 0 and central - r_a == r + r_a
            and s * s + h2 * (1 - r)**2 == h2 * (central + 1)**2,
            "Incircle center or tangency type differs")
    return {"equal_side": s, "base": b, "radius_over_height": str(central)}


def _zero_sum(n, meter):
    meter.charge("closed_zero_sum")
    return n * (n * (n - 1) // 2 + 1)


def _ellipse_geometry(meter):
    meter.charge("focal_matching_distance", 2)
    squared_distances = (24**2 + 10**2, 16**2 + 12**2)
    lengths = tuple(isqrt(n) for n in squared_distances)
    require(all(length * length == square for length, square in zip(lengths, squared_distances)),
            "Focal match distances differ")
    meter.charge("focal_chord_intersection", 2)
    # Left-to-upper/lower matching: lines (-4,0)->(20,10) and
    # (4,0)->(20,12). This point belongs to both closed segments.
    x, y = 14, Fraction(15, 2)
    require(-4 < x < 20 and 4 < x < 20 and y == Fraction(5, 12) * (x + 4)
            and y == Fraction(3, 4) * (x - 4), "Wrong attaining focal intersection")
    return Fraction(sum(lengths), 2), {"focal_match_distances": list(lengths),
                                       "attaining_intersection": [str(x), str(y)]}


def ordinary_point(case_id: str, value: Fraction, meter) -> bool | None:
    """Decide only this supplied value. No complete optimum is consulted."""
    if case_id not in CASES or type(value) is not Fraction:
        return None
    meter.charge("fixed_point")
    if case_id == "2018-I-8":
        meter.charge("exact_squared_diameter_range")
        return 0 < value <= 147
    if case_id == "2018-I-13":
        meter.charge("exact_incenter_area_range", 2)
        return value >= 126 and value * value < 34**2 * 21
    if case_id == "2022-II-12":
        meter.charge("exact_attainable_ellipse_sum_range")
        return value >= 23
    if value.denominator != 1 or value <= 0:
        return False
    n = value.numerator
    if case_id == "2009-I-13":
        return _recurrence_pair(n, meter) is not None
    if case_id == "2010-I-12":
        return coloring_property(n, meter)[0]
    if case_id == "2016-II-4":
        return _cyclic_coloring(n, meter) is not None
    if case_id == "2019-I-11":
        meter.charge("exact_perimeter_scale")
        return n % 20 == 0
    return _zero_sum(n, meter) > 500_000


POINT_PROOFS = {
    "2009-I-13": "Let q_n=a_n*a_(n+1)-2009. The exact recurrence gives q_(n+1)=q_n/(1+a_(n+1)). "
                 "A nonzero integer error cannot remain a nonzero integer indefinitely while halving in magnitude. "
                 "Thus the product must be 2009, which conversely gives a positive period-two solution. "
                 "At a fixed sum use the integer quadratic discriminant and root parity.",
    "2010-I-12": "At a fixed m, every unordered factor pair 3<=a<=b with ab<=m contributes a NAE clause "
                 "on distinct members of (a,b,ab). This includes a=b. A valid coloring negates feasibility. "
                 "For m<3^5, color log_3(x) in [1,2) or [4,5) with zero and in [2,4) with one. "
                 "Products of two low zeroes lie in the middle, products involving a high zero leave the domain, "
                 "and products of two ones start in the high zero interval or leave the domain. "
                 "For m>=3^5, the five powers of 3 realize the 2-color Schur obstruction on exponents 1..5. "
                 "The code checks every coloring up to global color symmetry.",
    "2016-II-4": "Green totals give a=5k,b=3k; total red, green, yellow are 45k,60k,75k. "
                 "Volume=180k=15k^2*c, so k divides 12. Conversely split 3R,4G,5Y into k equal groups of length c "
                 "and color stack (i,j) by group (i+j) mod k. Each row sees every group three times and each column five.",
    "2018-I-8": "The six directed sides turn through 60 degrees. Exact closure fixes EF=2 and FA=16. "
                "The distance between parallel supporting lines CD and FA is 7*sqrt(3), "
                "and center (5/2,9*sqrt(3)/2) has distance at least half that width to every side. "
                "Concentric smaller positive disks attain every smaller positive squared diameter. "
                "Squaring preserves the order of positive diameters.",
    "2018-I-13": "The altitude foot on BC is 12 from B and the height squared is 756. Set x=BX and d=AX. "
                 "For adjacent sides b,c, the squared distance from A to the incenter is bc(s-a)/s. "
                 "The two resulting semiperimeter ratios multiply to 1/3 after substituting d^2=x^2-24x+900. "
                 "The angle between the two bisectors at A is half of BAC. The resulting area squared is 21*d^2. "
                 "On the open segment BC, d ranges from sqrt(756) inclusively to 34 exclusively; the right branch "
                 "x=12+sqrt(d^2-756) realizes this full interval.",
    "2019-I-11": "Let the equal side be s, base b, height h, and t=b/(2s). The inradius over h is t/(1+t), "
                 "and the base-excircle radius over h is t/(1-t). The separately requested central circle has radius "
                 "R=r+2r_A by internal tangency because the incenter and base excenter are on opposite sides of BC. "
                 "The other excenters are (±s,h) above the base midpoint and their radii are h. "
                 "External tangency, squared between positive distances, reduces to (1+3t)^2=2(1-t). "
                 "This is (9t-1)(t+1)=0, so t=1/9. Integer sides are exactly s=9j,b=2j and perimeter 20j.",
    "2020-II-8": "Each nonnegative root y of f_(n-1) yields n-y and n+y. By induction the whole root set "
                 "is an arithmetic progression of step two centered at n, with radius n(n-1)/2. "
                 "Its nonnegative elements have constant parity and no gaps of more than two; their reflection "
                 "keeps this step through the center. Thus the sum of distinct roots is n(n(n-1)/2+1).",
    "2022-II-12": "The ellipse foci are (±4,0) and (20,10),(20,12). The two semimajor axes sum to half "
                 "the four focal distances. Triangle inequalities on crossed focal pairs give the lower bound "
                 "half the sum of their distances, attained at the segment intersection (14,15/2). "
                 "The vertical ray from that intersection avoids both focal segments, so a>4,b>1 throughout. "
                 "The sum of distances is continuous and unbounded on the ray, attaining every larger value.",
}


def exact_optimum(case_id, meter):
    if case_id == "2009-I-13":
        choices = []
        for divisor in range(1, isqrt(2009) + 1):
            meter.charge("factor_pair_trial")
            if 2009 % divisor == 0:
                choices.append((divisor + 2009 // divisor, divisor, 2009 // divisor))
        value, a, b = min(choices)
        return value, {"period_two": [a, b], "all_factor_pairs_tested": True}, (
            "The contracting product invariant reduces the complete domain to all factor pairs. Enumerate one "
            "member up to the integer square root and take the smallest sum.")
    if case_id == "2010-I-12":
        upper = _schur_bound(meter)
        lower = upper - 1
        low_ok, low_analytic = coloring_property(lower, meter)
        low_dpll, low_proof = coloring_property(lower, meter, explicit=True)
        high_dpll, high_proof = coloring_property(upper, meter, explicit=True)
        require(not low_ok and not low_dpll and high_dpll, "Independent endpoint coloring proofs disagree")
        return upper, {"below_floor_log_coloring": low_analytic, "below_dpll_coloring": low_proof,
                       "at_endpoint_complete_nae_proof": high_proof}, (
            "The floor-log coloring provides a certified false lower neighbor and the five powers force a true "
            "upper endpoint. Monotonicity rules out every smaller endpoint. Independent exact DPLL finds a checked "
            "coloring below and a checked contradiction tree at the endpoint; both computations are charged.")
    if case_id == "2016-II-4":
        witness = _cyclic_coloring(180, meter)
        require(witness is not None, "Base colored-box construction fails")
        return 180, witness, "All volumes are positive multiples of 180, and the first is feasible."
    if case_id == "2018-I-8":
        squared, witness = _hexagon_geometry(meter)
        require(squared.denominator == 1, "Unexpected exact squared diameter form")
        return int(squared), witness, "Use the opposite-side width and an exact feasible disk at that width."
    if case_id == "2018-I-13":
        smallest_squared, _, witness = _incenter_area_geometry(meter)
        meter.charge("integer_square_root")
        root = isqrt(smallest_squared.numerator)
        require(smallest_squared.denominator == 1 and root * root == smallest_squared, "Unexpected area form")
        return root, witness, "The minimum AX is at the altitude foot, which lies in the open segment."
    if case_id == "2019-I-11":
        return 20, _excircle_at_scale(1, meter), "The positive root t=1/9 forces s=9j,b=2j, with j=1 feasible."
    if case_id == "2020-II-8":
        lo, hi = 0, 128
        require(_zero_sum(hi, meter) > 500_000, "Search upper bound is not feasible")
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if _zero_sum(mid, meter) > 500_000:
                hi = mid
            else:
                lo = mid
        return hi, {"first_feasible_sum": _zero_sum(hi, meter),
                    "previous_sum": _zero_sum(lo, meter)}, (
            "The exact sum is strictly increasing on positive indices. Use a charged binary threshold search.")
    require(case_id == "2022-II-12", "Unknown complete control case")
    optimum, witness = _ellipse_geometry(meter)
    require(optimum.denominator == 1, "Unexpected focal optimum form")
    return int(optimum), witness, "Both triangle inequalities are tight at the same exact focal-segment intersection."


def _timed(call):
    meter = ControlMeter()
    wall, cpu = perf_counter_ns(), thread_time_ns()
    value = call(meter)
    return value, {"wall_ns": perf_counter_ns() - wall, "thread_cpu_ns": thread_time_ns() - cpu,
                   "paid_work": dict(sorted(meter.counts.items()))}


def _row(case, audit):
    cid = case["case_id"]
    (optimum, witness, proof), paid = _timed(lambda meter: exact_optimum(cid, meter))
    feasible, validation = _timed(lambda meter: ordinary_point(cid, Fraction(optimum), meter))
    require(feasible is True, "Complete optimum failed fixed-point validation")
    observed = []
    for value in EXAMPLES[cid]:
        feasible, cost = _timed(lambda meter: ordinary_point(cid, Fraction(value), meter))
        require(feasible is True and (value <= optimum if case["direction"] == "MAX" else value >= optimum),
                "Distinct feasible point disagrees with complete extremum")
        observed.append({"value": value, **cost})
    return {
        "case_id": cid, "question_sha256": audit["exact_question_sha256"], "direction": case["direction"],
        "optimum": optimum, "optimum_witness": witness, "point_proof": POINT_PROOFS[cid],
        "complete_proof": proof, "exact_solver_work": paid, "optimum_point_validation_work": validation,
        "distinct_feasible_examples": observed,
    }


def build(scope_path, cohort_path, question_only_path, output, private):
    scope_raw = scope_path.read_bytes()
    cohort_raw = cohort_path.read_bytes()
    q_raw = question_only_path.read_bytes()
    require(digest(scope_raw) == AUDIT_SHA and digest(cohort_raw) == COHORT_SHA, "Changed D47 question freeze")
    scope, cohort, questions = (json.loads(raw) for raw in (scope_raw, cohort_raw, q_raw))
    require(cohort["scope_audit_sha256"] == AUDIT_SHA and cohort["question_only_sha256"] == digest(q_raw)
            and cohort["source_shards"][0]["sha256"] == scope["source"]["draw00_sha256"], "Question source differs")
    audit = {row["case_id"]: row for row in scope["rows"]}
    frozen = {row["case_id"]: row for row in cohort["rows"]}
    visible = {row["case_id"]: row for row in questions["rows"]}
    require(set(audit) == set(frozen) == set(visible) == set(CASES)
            and len(scope["rows"]) == len(cohort["rows"]) == len(questions["rows"]) == 8, "Changed D47 cohort")
    for cid, expected in frozen.items():
        q = visible[cid]
        require(q["direction"] == expected["direction"] == audit[cid]["direction"]
                and digest(q["question"].encode()) == q["question_sha256"]
                == expected["question_sha256"] == audit[cid]["exact_question_sha256"], "Question identity differs")
    payload = private / "exact_oracles.json"
    require(not payload.exists() and not output.exists(), "Existing exact control freeze is immutable")
    source = {
        "scope_sha256": AUDIT_SHA, "cohort_freeze_sha256": COHORT_SHA,
        "question_only_sha256": digest(q_raw), "ordinary_code_sha256": digest(Path(__file__).read_bytes()),
        "source_shard_sha256": scope["source"]["draw00_sha256"],
    }
    rows = [_row(case, audit[case["case_id"]]) for case in cohort["rows"]]
    raw = encode({"status": "D47_QUESTION_ONLY_PRIVATE_EXACT_CONTROLS", **source, "rows": rows})
    private.mkdir(parents=True, exist_ok=True)
    with payload.open("xb") as stream:
        stream.write(raw)
    receipt = {
        "status": "D47_QUESTION_ONLY_EXACT_CONTROLS_FROZEN_BEFORE_TRACES_OR_GOLD",
        **source, "private_payloads": {"exact_oracles.json": {"sha256": digest(raw), "rows": len(rows)}},
        "scope": "Exact complete optima and feasible examples remain private. Ordinary point checks use no archive "
                 "text, labels, or complete-optimum artifact. Manual proof derivation was not instrumented.",
        "thread_cpu_resolution_seconds": get_clock_info("thread_time").resolution,
        "question_costs": [
            {"case_id": row["case_id"], "complete_solver": row["exact_solver_work"],
             "optimum_validation": row["optimum_point_validation_work"],
             "distinct_feasible_example_checks": [{k: v for k, v in record.items() if k != "value"}
                                                 for record in row["distinct_feasible_examples"]]}
            for row in rows],
    }
    with output.open("xb") as stream:
        stream.write(encode(receipt))
    print(receipt["status"], digest(output.read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, default=HERE / "D47_QUESTION_SCOPE_AUDIT.json")
    parser.add_argument("--cohort", type=Path, default=HERE / "D47_COHORT_FREEZE.json")
    parser.add_argument("--question-only", type=Path, default=ROOT / "outputs/d47_aime_source_20261110/d47_question_only.json")
    parser.add_argument("--output", type=Path, default=HERE / "D47_CONTROLS_FREEZE.json")
    parser.add_argument("--private", type=Path, default=ROOT / "outputs/d47_aime_source_20261110")
    args = parser.parse_args()
    build(args.scope, args.cohort, args.question_only, args.output, args.private)


if __name__ == "__main__":
    main()
