"""Independent exact construction and local-check controls for four D4.9 questions."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from time import perf_counter_ns, thread_time_ns


COHORT_SHA = "2ef60c97ae05c2b811f873457682c8be4a650fdd9556f26c332e1203b2671617"
QUESTION_SHA = "f71dd6d85c8b7b50db88eb5e3b0fa020077906de72083224e024829fd6356b2a"
IDS = ("EGMO-2016-P5", "EGMO-2019-P2-80", "ELMO-2014-P6", "IMO-2023-P5-8")


def digest(raw):
    return sha256(raw).hexdigest()


def wire(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timed(fn, *args):
    work = Counter()
    began, cpu = perf_counter_ns(), thread_time_ns()
    value = fn(work, *args)
    return value, {"wall_ns": perf_counter_ns()-began, "thread_cpu_ns": thread_time_ns()-cpu, "named_work": dict(work)}


def coordinate(value, n, offset=0):
    if type(value) not in (tuple, list) or len(value) != 2 or any(
            type(x) is not int or not offset <= x < n+offset for x in value):
        return None
    return tuple(x-offset for x in value)


def bar_cells(value, n=19, k=10):
    if type(value) not in (tuple, list) or len(value) != 2:
        return None
    first, last = (coordinate(item, n) for item in value)
    if first is None or last is None:
        return None
    r, c = first
    a, b = last
    if r == a and b-c+1 == k:
        return tuple((r, j) for j in range(c, b+1))
    if c == b and a-r+1 == k:
        return tuple((i, c) for i in range(r, a+1))
    return None


def bars_check(work, candidate, complete=True):
    if type(candidate) not in (tuple, list):
        return {"status": "INVALID_FORMAT"}
    n, k = 19, 10
    grid = [[None]*n for _ in range(n)]
    for index, bar in enumerate(candidate):
        work["bar_endpoint_checks"] += 1
        cells = bar_cells(bar, n, k)
        if cells is None:
            return {"status": "INVALID_FORMAT", "bar_index": index}
        for r, c in cells:
            work["bar_cell_overlap_checks"] += 1
            if grid[r][c] is not None:
                return {"status": "OVERLAP", "conflict_cell": (r, c), "committed_bar_support": (grid[r][c], index)}
            grid[r][c] = index
    if not complete:
        return {"status": "UNKNOWN_COMPLETION"}
    for direction in ("ROW", "COL"):
        for fixed in range(n):
            gap = 0
            for i in range(n):
                work["line_cell_visits"] += 1
                r, c = (fixed, i) if direction == "ROW" else (i, fixed)
                gap = gap+1 if grid[r][c] is None else 0
                if gap >= k:
                    first = (r, c-k+1) if direction == "ROW" else (r-k+1, c)
                    return {"status": "ADDABLE_BAR", "empty_bar_endpoints": (first, (r, c))}
    return {"status": "VALID", "objective": len(candidate)}


def bars_solve(work):
    n, k = 19, 10
    work["axis_center_and_gap_bound_evaluations"] += 2
    require(n == 2*k-1 and 2*(n-k+1) > n, "The centered extremal argument needs the frozen n,k")
    bars = []
    for r in range(n):
        work["alternating_bar_constructions"] += 1
        c = (n-k)*(r % 2)
        bars.append(((r, c), (r, c+k-1)))
    return n, bars


def bars_adversaries(work, witness, target):
    duplicate = bars_check(work, [witness[0], witness[0]], complete=False)
    partial = bars_check(work, witness[:-1], complete=False)
    complete = bars_check(work, witness[:-1], complete=True)
    require(duplicate["status"] == "OVERLAP" and partial["status"] == "UNKNOWN_COMPLETION"
            and complete["status"] == "ADDABLE_BAR", "Bar local evidence escaped its scope")
    return {"two_bar_monotone_overlap": duplicate, "identical_partial": partial, "declared_complete": complete}


def neighbors(r, c, n):
    if r:
        yield r-1, c
    if r+1 < n:
        yield r+1, c
    if c:
        yield r, c-1
    if c+1 < n:
        yield r, c+1


def domino_check(work, candidate, n=160):
    if type(candidate) not in (tuple, list) or len(candidate) > n*n or len(candidate) % 2:
        return {"status": "INVALID_FORMAT"}
    cells = set()
    for i in range(0, len(candidate), 2):
        work["domino_endpoint_pair_checks"] += 1
        a, b = (coordinate(value, n, 1) for value in candidate[i:i+2])
        if a is None or b is None or sum(abs(s-t) for s, t in zip(a, b)) != 1 or a in cells or b in cells:
            return {"status": "INVALID_DOMINO", "domino_index": i//2}
        cells.update((a, b))
    for r in range(n):
        for c in range(n):
            work["exact_one_neighbor_constraint_checks"] += 1
            count = 0
            for x in neighbors(r, c, n):
                work["neighbor_membership_reads"] += 1
                count += x in cells
            if count != 1:
                return {"status": "BAD_NEIGHBOR_COUNT", "cell_zero_based": (r, c), "count": count}
    return {"status": "VALID", "objective": len(cells)//2}


def domino_solve(work):
    n = 160
    prior = [0]*n
    row = [int(j % 4 >= 2) for j in range(n)]
    occupied = []
    for _ in range(n):
        occupied.append(row)
        following = []
        for j in range(n):
            work["affine_row_recurrence_values"] += 1
            value = 1-prior[j]-(row[j-1] if j else 0)-(row[j+1] if j+1 < n else 0)
            require(value in (0, 1), "The proposed top boundary does not propagate a binary occupancy")
            following.append(value)
        prior, row = row, following
    require(not any(row), "The independently propagated bottom boundary is nonzero")
    flat = []
    for r, values in enumerate(occupied):
        for c, covered in enumerate(values):
            work["occupied_endpoint_scans"] += 1
            if not covered:
                continue
            partner = None
            for a, b in neighbors(r, c, n):
                work["occupied_partner_membership_reads"] += 1
                if occupied[a][b]:
                    require(partner is None, "An occupied endpoint has two partners")
                    partner = a, b
            require(partner is not None, "An occupied endpoint has no partner")
            if (r, c) < partner:
                flat.extend(((r+1, c+1), (partner[0]+1, partner[1]+1)))
    return len(flat)//2, flat


def domino_partial(work, center, known):
    if coordinate(center, 160) is None or type(known) is not dict:
        return {"status": "INVALID_FORMAT"}
    bound = []
    for cell in neighbors(*center, 160):
        work["local_neighbor_reads"] += 1
        if cell in known:
            if type(known[cell]) is not int or known[cell] not in (0, 1):
                return {"status": "INVALID_FORMAT"}
            bound.append((cell, known[cell]))
    occupied = tuple(cell for cell, value in bound if value)
    if len(occupied) >= 2:
        return {"status": "TOO_MANY_OCCUPIED_NEIGHBORS", "support": occupied[:2]}
    if len(bound) < len(tuple(neighbors(*center, 160))):
        return {"status": "UNKNOWN"}
    return {"status": "LOCAL_PASS" if occupied else "NO_OCCUPIED_NEIGHBOR"}


def domino_adversaries(work, witness, target):
    r, c = 4, 4
    too_many = domino_partial(work, (r, c), {(r, c-1): 1, (r, c+1): 1})
    unknown = domino_partial(work, (r, c), {(r, c-1): 1})
    zero = domino_partial(work, (r, c), {x: 0 for x in neighbors(r, c, 160)})
    require(too_many["status"] == "TOO_MANY_OCCUPIED_NEIGHBORS" and unknown["status"] == "UNKNOWN"
            and zero["status"] == "NO_OCCUPIED_NEIGHBOR", "Partial exact-one evidence escaped its scope")
    return {"monotone_two_selected_neighbors": too_many, "single_selected_with_unseen_neighbors": unknown, "closed_zero": zero,
            "two_compatible_committed_dominoes_zero_based": [((r, c-2), (r, c-1)), ((r, c+1), (r, c+2))]}


def forest_check(work, candidate, n=17):
    if type(candidate) not in (tuple, list) or len(candidate) != n or any(type(row) not in (list, tuple) or len(row) != n for row in candidate):
        return {"status": "INVALID_FORMAT"}
    parent = list(range(n*n))
    occupied = 0
    for row in candidate:
        for value in row:
            work["binary_cell_checks"] += 1
            if type(value) is not str or value not in ("0", "1"):
                return {"status": "INVALID_FORMAT"}
            occupied += value == "1"

    def root(x):
        while x != parent[x]:
            work["dsu_parent_steps"] += 1
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r, row in enumerate(candidate):
        for c, value in enumerate(row):
            if value == "0":
                continue
            for a, b in ((r+1, c), (r, c+1)):
                if a >= n or b >= n:
                    continue
                work["right_down_neighbor_reads"] += 1
                if candidate[a][b] == "0":
                    continue
                v, w = root(r*n+c), root(a*n+b)
                work["forest_edge_checks"] += 1
                if v == w:
                    return {"status": "CYCLE", "closing_edge": ((r, c), (a, b))}
                parent[v] = w
    return {"status": "VALID", "objective": occupied}


def forest_solve(work):
    def holes(n):
        work["subdivision_levels"] += 1
        if n == 2:
            work["recursive_holes_written"] += 1
            return {(0, 0)}
        k = (n-1)//2
        child = holes(k+1)
        result = {(r, c) for r in range(1, n, 2) for c in range(1, n, 2)}
        work["recursive_holes_written"] += len(result) + len(child)
        result.update((2*r, 2*c) for r, c in child)
        return result

    n = 17
    removed = holes(n)
    work["edge_bound_formula_evaluations"] += 1
    require(len(removed) == ((n-1)**2+2)//3, "Recursive forest does not meet the edge-count bound")
    work["matrix_cells_written"] += n*n
    return n*n-len(removed), [["0" if (r, c) in removed else "1" for c in range(n)] for r in range(n)]


def forest_adversaries(work, witness, target):
    cycle = ((0, 0), (0, 1), (1, 1), (1, 0))
    work["cycle_vertex_distinctness_checks"] += 1
    require(len(set(cycle)) == 4, "The alleged finite cycle repeats a vertex")
    for a, b in zip(cycle, cycle[1:]+cycle[:1]):
        work["cycle_neighbor_edge_checks"] += 1
        require(sum(abs(x-y) for x, y in zip(a, b)) == 1, "Cycle closure is not an original edge")
    board = [["0"]*17 for _ in range(17)]
    for r, c in cycle:
        board[r][c] = "1"
    independently = forest_check(work, board)
    require(independently["status"] == "CYCLE", "Full checker accepts the certified occupied cycle")
    return {"minimal_closed_occupied_support": cycle, "checked_complete_counterexample": independently}


def ninja_matrix(columns):
    return [[0 if c > r else 2 if c == col else 1 for c in range(8)] for r, col in enumerate(columns)]


def ninja_check(work, candidate):
    if type(candidate) not in (list, tuple) or len(candidate) != 8:
        return {"status": "INVALID_FORMAT"}
    previous = []
    for r, row in enumerate(candidate):
        if type(row) not in (list, tuple) or len(row) != 8:
            return {"status": "INVALID_FORMAT"}
        reds = 0
        current = []
        for c, value in enumerate(row):
            work["triangle_cell_checks"] += 1
            if type(value) is not int or (c <= r and value not in (1, 2)) or (c > r and value != 0):
                return {"status": "INVALID_FORMAT"}
            if c > r:
                continue
            reds += value == 2
            parents = [previous[k] for k in (c-1, c) if 0 <= k < len(previous)]
            work["predecessor_path_values_read"] += len(parents)
            current.append(max(parents, default=0)+(value == 2))
        if reds != 1:
            return {"status": "INVALID_RED_COUNT", "row": r}
        previous = current
    return {"status": "VALID", "objective": max(previous)}


def ninja_solve(work):
    # Antichain sizes 1,2,4,1, with columns increasing and row-minus-column decreasing.
    columns = (0, 0, 2, 0, 2, 4, 6, 0)
    layers = ((0,), (1, 2), (3, 4, 5, 6), (7,))
    for layer in layers:
        for i, j in zip(layer, layer[1:]):
            work["antichain_order_checks"] += 1
            require(columns[i] < columns[j] and i-columns[i] > j-columns[j], "Upper construction layer is not an antichain")
    work["antichain_cardinality_contradiction_checks"] += 2
    require(8-1-2 == 5 and 5-1 > 3, "The three-layer lower contradiction no longer applies")
    work["matrix_cells_written"] += 64
    return len(layers), ninja_matrix(columns)


def ninja_adversaries(work, witness, target):
    bad = ninja_matrix([0]*8)
    finite_prefix = [(r, 0) for r in range(target+1)]
    for r, c in finite_prefix:
        work["confirmed_path_red_checks"] += 1
        require(bad[r][c] == 2, "The purported cap witness includes a non-red circle")
    for (r, c), (a, b) in zip(finite_prefix, finite_prefix[1:]):
        work["explicit_path_step_checks"] += 1
        require(a == r+1 and b in (c, c+1), "The purported cap witness skips a permitted step")
    independent = ninja_check(work, bad)
    require(independent["status"] == "VALID" and independent["objective"] > target, "Feasibility and objective were conflated")
    return {"target_upper_bound": target, "bound_red_path_prefix": finite_prefix, "full_recheck": independent}


def ninja_exhaustive(work, expected):
    histogram = Counter()
    for columns in product(*(range(r+1) for r in range(8))):
        work["legal_row_position_vectors"] += 1
        rank = []
        for i, c in enumerate(columns):
            best = 0
            for j in range(i):
                work["red_reachability_checks"] += 1
                if 0 <= c-columns[j] <= i-j:
                    best = max(best, rank[j])
            rank.append(best+1)
        histogram[max(rank)] += 1
    require(min(histogram) == expected and sum(histogram.values()) == 40320, "Exhaustive finite control disagrees")
    return {"histogram_by_longest_red_chain": dict(histogram)}


CASES = (
    (bars_solve, bars_check, bars_adversaries,
     "Every bar crosses its axis center. A horizontal at a top-half row blocks every vertical through its own length-ten interval from that row and every row above it. Thus these rows must all have horizontals, or the same interval is addable. The bottom case is symmetric, so horizontal rows form a prefix and suffix. Vertical columns do likewise. A central horizontal blocks its whole interval from every vertical globally, forcing horizontals in all rows. A central vertical is symmetric. In a mixed solution the middle gap of each central line has length below ten, forcing at least ten cards of each orientation. Any one-orientation saturated solution requires nineteen bars. Alternating left- and right-aligned horizontal rows attains nineteen and blocks every vertical length-ten interval."),
    (domino_solve, domino_check, domino_adversaries,
     "Let A be the symmetric grid adjacency matrix and x the binary occupied-cell vector. Every legal solution satisfies Ax=1. Propagate each new row from the two known rows and lateral neighbors, starting with a repeating 0011 top row and zero exterior. The full independent checker validates the resulting vector w and its pairing. For any legal occupancy x, 1-transpose times x equals (Aw)-transpose times x, which equals w-transpose times Ax and therefore the occupied count of w. All legal placements have that same objective."),
    (forest_solve, forest_check, forest_adversaries,
     "With W white cells, removing their incident edges removes at most 4W edges. A nonempty remaining forest has at most n squared minus W minus 1 edges. The original grid has 2n(n-1) edges, so W is at least the ceiling of (n-1) squared over 3. Remove all odd-odd cells. The remaining graph is a one-subdivision of the smaller even-even grid. Recursively remove the smaller grid holes at even-even positions. Any unused subdivider is isolated or pendant, so cycles correspond exactly to compressed cycles. Start with one deleted corner on the 2 by 2 grid. The 17 by 17 construction attains the lower bound."),
    (ninja_solve, ninja_check, ninja_adversaries,
     "Map red (r,c) to (c,r-c). Reachability is coordinatewise dominance. For any m-point antichain the ordered first coordinates grow by at least one and the second decrease by at least one, so every member has r at least m-1. If the longest chain were at most three, the origin is rank one and rank two contains row one, giving at most two members in rank two. Rank three then has at least five members, all in rows four or later. That leaves rows one through three in rank two, a contradiction. The explicit construction partitions the eight reds into four antichains and attains four."),
)


def run(cohort_path, questions_path):
    cohort_bytes, questions_bytes = cohort_path.read_bytes(), questions_path.read_bytes()
    require(digest(cohort_bytes) == COHORT_SHA and digest(questions_bytes) == QUESTION_SHA, "Question-only input differs from freeze")
    cohort, questions = json.loads(cohort_bytes), json.loads(questions_bytes)
    chosen = {r["id"]: r for r in cohort["rows"]}
    visible = {r["id"]: r for r in questions["rows"]}
    require(set(IDS) <= set(chosen) and set(IDS) <= set(visible), "One of four original scopes is absent")
    rows, witnesses = [], []
    for cid, (solve, check, adversaries, proof) in zip(IDS, CASES, strict=True):
        q = visible[cid]
        require(q["question_sha256"] == chosen[cid]["question_sha256"] == digest(q["query"].encode())
                and q["instruction_sha256"] == chosen[cid]["instruction_sha256"] == digest(q["instruction"].encode()),
                "Question or construction format digest differs")
        (target, witness), construction_cost = timed(solve)
        validation, validation_cost = timed(check, witness)
        require(validation == {"status": "VALID", "objective": target}, "The exact construction fails original complete acceptance")
        attacks, adversary_cost = timed(adversaries, witness, target)
        row = {"id": cid, "question_sha256": q["question_sha256"], "instruction_sha256": q["instruction_sha256"],
               "status": "EXACT_ORDINARY_OPTIMUM_CONSTRUCTED_AND_INDEPENDENTLY_CHECKED", "derived_optimum": target,
               "complete_proof": proof, "witness_sha256": digest(wire(witness)), "witness_bytes": len(wire(witness)),
               "complete_construction": construction_cost, "independent_full_checker": validation_cost,
               "independent_full_check_result": validation, "local_adversaries": attacks, "local_adversary_cost": adversary_cost}
        if cid == "IMO-2023-P5-8":
            repeat, repeat_cost = timed(ninja_exhaustive, target)
            row["separate_exhaustive_recount"] = {**repeat, **repeat_cost}
        rows.append(row)
        witnesses.append({"id": cid, "construction": witness})
    return rows, witnesses


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for flag in ("cohort", "questions", "output", "witness-output"):
        cli.add_argument("--" + flag, type=Path, required=True)
    args = cli.parse_args()
    require(args.output.resolve() != args.witness_output.resolve() and not args.output.exists() and not args.witness_output.exists(),
            "Expected two new separate artifacts")
    rows, witnesses = run(args.cohort, args.questions)
    private = wire({"status": "D49_EXTREMAL_A_INDEPENDENT_CONSTRUCTIONS_LOCAL_ONLY", "cohort_sha256": COHORT_SHA, "rows": witnesses})
    report = wire({"status": "D49_EXTREMAL_A_QUESTION_ONLY_EXACT_CONTROLS_FROZEN_BEFORE_REFERENCE",
                   "cohort_sha256": COHORT_SHA, "question_projection_sha256": QUESTION_SHA,
                   "source_sha256": digest(Path(__file__).read_bytes()), "private_witnesses_sha256": digest(private),
                   "scope": "Question-derived exact controls and synthetic adversaries. No benchmark references, author checker code, or model trajectory fields opened.",
                   "cost_boundary": "CPU wall/thread times and named work for each separately executed constructor, independent checker and synthetic controls. Manual derivation and JSON I/O are outside these timings.",
                   "rows": rows})
    with args.witness_output.open("xb") as f:
        f.write(private)
    with args.output.open("xb") as f:
        f.write(report)
    print("D49 exact controls", len(rows), digest(report))
