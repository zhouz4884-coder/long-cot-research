"""Question-only exact controls for three D4.9 ComBench grid tasks."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import combinations, permutations
import json
from pathlib import Path
import platform
from time import perf_counter, process_time


COHORT_SHA256 = "2ef60c97ae05c2b811f873457682c8be4a650fdd9556f26c332e1203b2671617"
CASE_IDS = ("CB-76", "CB-46", "CB-99")
OPTIMA = {"CB-76": 3800, "CB-46": 13300, "CB-99": 44}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def require_grid(grid, size):
    if type(grid) is not list or len(grid) != size:
        raise ValueError("wrong number of rows")
    for row in grid:
        if type(row) is not list or len(row) != size or any(type(value) is not int for value in row):
            raise ValueError("wrong row length or non-integer cell")


def make_visibility(size):
    def pure(index):
        if index < 5:
            return 1
        if index < 10:
            return 2
        return 0

    return [
        [pure(i) + pure(j) if bool(pure(i)) != bool(pure(j)) else 0 for j in range(size)]
        for i in range(size)
    ]


def check_visibility(grid, size):
    require_grid(grid, size)
    row_counts = [Counter(row) for row in grid]
    column_counts = [Counter(column) for column in zip(*grid, strict=True)]
    counts = Counter()
    failures = []
    for i, row in enumerate(grid):
        for j, color in enumerate(row):
            if color not in (0, 1, 2):
                raise ValueError("invalid piece color")
            counts[color] += 1
            if color == 0:
                continue
            other = 3 - color
            visible = row_counts[i][other] + column_counts[j][other]
            if visible != 5:
                failures.append((i, j, visible))
    return {
        "valid": not failures,
        "objective": counts[1] + counts[2],
        "work": {"cell_tallies": 2 * size * size, "cell_visits": size * size, "piece_constraints_checked": counts[1] + counts[2]},
        "first_conflict": failures[0] if failures else None,
        "conflicts": len(failures),
    }


def local_visibility(known, size, cell):
    """Refute a committed piece only if five opposites is already impossible."""
    color = known.get(cell)
    if color not in (1, 2):
        return None
    i, j = cell
    line = [(i, k) for k in range(size) if k != j] + [(k, j) for k in range(size) if k != i]
    opposite = [position for position in line if known.get(position) == 3 - color]
    if len(opposite) > 5:
        return {"reason": "excess", "support": [cell, *opposite[:6]]}
    committed_nonopposite = [position for position in line if position in known and known[position] != 3 - color]
    if len(line) - len(committed_nonopposite) < 5:
        needed = len(line) - 4
        return {"reason": "insufficient_capacity", "support": [cell, *committed_nonopposite[:needed]]}
    return None


def make_rank_grid(size):
    return [[size * ((i + j) % size) + i + 1 for j in range(size)] for i in range(size)]


def rectangle_counted(a, b, c, d):
    return max(a, d) < min(b, c) or max(b, c) < min(a, d)


def check_rank_grid(grid, size):
    require_grid(grid, size)
    ranks = [value for row in grid for value in row]
    if set(ranks) != set(range(1, size * size + 1)):
        return {"valid": False, "objective": None, "work": {"ranks_checked": len(ranks), "rectangles_checked": 0}}
    value = checked = 0
    for i, k in combinations(range(size), 2):
        for j, l in combinations(range(size), 2):
            value += rectangle_counted(grid[i][j], grid[i][l], grid[k][j], grid[k][l])
            checked += 1
    return {"valid": True, "objective": value, "work": {"ranks_checked": len(ranks), "rectangles_checked": checked}}


def rank_corner_identity(grid):
    size = len(grid)
    value = 0
    for i, row in enumerate(grid):
        for j, entry in enumerate(row):
            a = sum(other < entry for other in row)
            b = sum(grid[k][j] < entry for k in range(size))
            value += a * b
    base = (size * (size - 1) // 2) ** 2
    return value - base, size * sum(k * k for k in range(size)) - base


def primal_edges(size):
    for i in range(size):
        for j in range(size):
            if i + 1 < size:
                yield (i, j), (i + 1, j)
            if j + 1 < size:
                yield (i, j), (i, j + 1)


def label_sticks(size, merges):
    parents = {(i, j): (i, j) for i in range(size) for j in range(size)}

    def root(cell):
        while parents[cell] != cell:
            cell = parents[cell]
        return cell

    for first, second in merges:
        parents[root(second)] = root(first)
    labels = {}
    return [[labels.setdefault(root((i, j)), len(labels) + 1) for j in range(size)] for i in range(size)]


def dual_edge(left, right):
    """Primal adjacency shared by two adjacent 2x2 squares indexed at top left."""
    i, j = left
    k, l = right
    if i == k and abs(j - l) == 1:
        col = max(j, l)
        return (i, col), (i + 1, col)
    if j == l and abs(i - k) == 1:
        row = max(i, k)
        return (row, j), (row, j + 1)
    raise ValueError("non-adjacent dual vertices")


def make_sticks(size):
    last = size - 1
    merges = [((i, j), (i, j + 1)) for i in (0, last) for j in range(last)]
    merges += [((i, j), (i + 1, j)) for j in (0, last) for i in range(1, last - 1)]
    # Pair the inner dual squares horizontally, then pair the remaining column vertically.
    merges += [dual_edge((i, j), (i, j + 1)) for i in range(1, last - 1) for j in range(1, last - 2, 2)]
    if (last - 2) % 2:
        merges += [dual_edge((i, last - 2), (i + 1, last - 2)) for i in range(1, last - 2, 2)]
    return label_sticks(size, merges), len(merges)


def check_sticks(grid, size):
    require_grid(grid, size)
    positions = defaultdict(list)
    for i, row in enumerate(grid):
        for j, label in enumerate(row):
            positions[label].append((i, j))
    labels = len(positions)
    if set(positions) != set(range(1, labels + 1)):
        return {"valid": False, "objective": None, "reason": "label range", "work": {"cell_visits": size * size, "adjacencies_checked": 0}}
    malformed = []
    for label, cells in positions.items():
        rows, cols = zip(*cells, strict=True)
        height = max(rows) - min(rows) + 1
        width = max(cols) - min(cols) + 1
        if min(height, width) != 1 or height * width != len(cells):
            malformed.append(label)
    contacts = Counter()
    checks = 0
    for (i, j), (k, l) in primal_edges(size):
        checks += 1
        first, second = grid[i][j], grid[k][l]
        if first != second:
            contacts[tuple(sorted((first, second)))] += 1
    repeated = [pair for pair, multiplicity in contacts.items() if multiplicity > 1]
    return {
        "valid": not malformed and not repeated,
        "objective": labels,
        "work": {"cell_visits": size * size, "adjacencies_checked": checks, "sticks_checked": labels},
        "contact_edges": sum(contacts.values()),
        "malformed_labels": malformed,
        "repeated_contact_pairs": repeated,
    }


def local_stick_conflict(square):
    """The original 2x2 rule. None means a cell is still unknown."""
    edges = ((0, 1), (0, 2), (1, 3), (2, 3))
    known_merges = [edge for edge in edges if square[edge[0]] is not None and square[edge[0]] == square[edge[1]]]
    if len(known_merges) < 2:
        return None
    return {"reason": "two_merges_in_square", "support": sorted(set(known_merges[0] + known_merges[1]))}


def exact_dual_matching(size):
    """Independent ordinary full algorithm using bipartite augmenting paths."""
    graph = defaultdict(list)
    edge_to_primal = {}
    for index, (first, second) in enumerate(primal_edges(size)):
        i, j = first
        k, l = second
        square_coordinates = ((i, j - 1), (i, j)) if j == l else ((i - 1, j), (i, j))
        squares = [(r, c) for r, c in square_coordinates if 0 <= r < size - 1 and 0 <= c < size - 1]
        if len(squares) == 2:
            even, odd = sorted(squares, key=lambda cell: sum(cell) % 2)
        elif sum(squares[0]) % 2 == 0:
            even, odd = squares[0], (size, index)
        else:
            even, odd = (size, index), squares[0]
        graph[even].append(odd)
        edge_to_primal[even, odd] = first, second
    match = {}
    inspected = 0

    def augment(even, visited):
        nonlocal inspected
        for odd in graph[even]:
            inspected += 1
            if odd in visited:
                continue
            visited.add(odd)
            if odd not in match or augment(match[odd], visited):
                match[odd] = even
                return True
        return False

    for even in graph:
        augment(even, set())
    merges = [edge_to_primal[even, odd] for odd, even in match.items()]
    work = {"left_vertices": len(graph), "edges_built": len(edge_to_primal), "edge_inspections": inspected, "maximum_merges": len(merges)}
    return label_sticks(size, merges), work


def check_full(case_id, grid):
    if case_id == "CB-76":
        return check_visibility(grid, 200)
    if case_id == "CB-46":
        return check_rank_grid(grid, 20)
    if case_id == "CB-99":
        return check_sticks(grid, 10)
    raise ValueError("unrecognized task")


def measured(fn, *args):
    wall, cpu = perf_counter(), process_time()
    value = fn(*args)
    return value, {"wall_seconds": perf_counter() - wall, "cpu_seconds": process_time() - cpu}


def run_controls(grid_76, grid_46, grid_99):
    broken_visibility = [row[:] for row in grid_76]
    broken_visibility[5][10] = 0
    assert not check_visibility(broken_visibility, 200)["valid"]
    six = {(0, 0): 1} | {(0, i): 2 for i in range(1, 7)}
    excessive = local_visibility(six, 200, (0, 0))
    assert excessive == {"reason": "excess", "support": list(six)}
    assert local_visibility({(0, 0): 1}, 200, (0, 0)) is None
    full_empty_line = {(0, i): 0 for i in range(1, 200)} | {(i, 0): 0 for i in range(1, 200)}
    shortfall = local_visibility(full_empty_line | {(0, 0): 1}, 200, (0, 0))
    assert shortfall["reason"] == "insufficient_capacity" and len(shortfall["support"]) == 395

    assert not rectangle_counted(1, 2, 3, 4)
    assert rectangle_counted(1, 3, 4, 2)
    duplicates = [row[:] for row in grid_46]
    duplicates[0][1] = duplicates[0][0]
    assert not check_rank_grid(duplicates, 20)["valid"]
    row_major = [list(range(i * 20 + 1, (i + 1) * 20 + 1)) for i in range(20)]
    rank_feasible_not_optimal = check_rank_grid(row_major, 20)
    assert rank_feasible_not_optimal["valid"] and rank_feasible_not_optimal["objective"] == 0
    two_by_two = 0
    for values in permutations(range(1, 5)):
        grid = [list(values[:2]), list(values[2:])]
        objective, upper = rank_corner_identity(grid)
        assert objective == check_rank_grid(grid, 2)["objective"] <= upper
        two_by_two += 1

    assert local_stick_conflict((1, 1, 1, None)) == {"reason": "two_merges_in_square", "support": [0, 1, 2]}
    assert local_stick_conflict((1, 1, 2, 2)) == {"reason": "two_merges_in_square", "support": [0, 1, 2, 3]}
    assert local_stick_conflict((1, None, 2, None)) is None
    assert not check_sticks([[1, 1], [2, 2]], 2)["valid"]
    assert not check_sticks([[1, 1], [1, 2]], 2)["valid"]
    stick_feasible_not_optimal = check_sticks([[10 * i + j + 1 for j in range(10)] for i in range(10)], 10)
    assert stick_feasible_not_optimal["valid"] and stick_feasible_not_optimal["objective"] == 100
    assert check_sticks(grid_99, 10)["valid"]
    edges = list(primal_edges(3))
    exhaustive_stick_checks = 0
    for mask in range(1 << len(edges)):
        merges = [edge for bit, edge in enumerate(edges) if mask & (1 << bit)]
        grid = label_sticks(3, merges)
        clean = all(
            local_stick_conflict((grid[i][j], grid[i][j + 1], grid[i + 1][j], grid[i + 1][j + 1])) is None
            for i in range(2) for j in range(2)
        )
        assert clean == check_sticks(grid, 3)["valid"]
        exhaustive_stick_checks += 1
    return {
        "visibility": {"excess": excessive, "shortfall_support_size": len(shortfall["support"]), "unknown_not_rejected": True, "mutated_full_board_rejected": True},
        "rank": {"named_rectangle_both_directions": True, "duplicate_rank_rejected": True, "feasible_suboptimal_objective": rank_feasible_not_optimal["objective"], "all_rank_permutations_2x2_checked": two_by_two},
        "sticks": {"bend_and_parallel_double_contact_rejected": True, "unknown_not_rejected": True, "feasible_suboptimal_objective": stick_feasible_not_optimal["objective"], "all_merge_subsets_3x3_checked": exhaustive_stick_checks},
    }


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--local-witnesses", required=True, type=Path)
    args = parser.parse_args()

    def load_cohort():
        path = Path(__file__).with_name("D49_COHORT_FREEZE.json")
        contents = path.read_bytes()
        if sha256(contents).hexdigest() != COHORT_SHA256:
            raise ValueError("unexpected cohort identity")
        cohort = json.loads(contents)
        rows = {row["cb_id"]: row for row in cohort["rows"] if row["cb_id"] in CASE_IDS}
        if set(rows) != set(CASE_IDS):
            raise ValueError("expected all three exact case IDs")
        return cohort, rows

    (cohort, sources), intake_cost = measured(load_cohort)
    grid_76, cost_76 = measured(make_visibility, 200)
    grid_46, cost_46 = measured(make_rank_grid, 20)
    (grid_99, merge_count), cost_99 = measured(make_sticks, 10)
    (corner_value, corner_bound), rank_identity_cost = measured(rank_corner_identity, grid_46)
    assert corner_value == corner_bound == OPTIMA["CB-46"]
    (matching_grid, matching_work), matching_cost = measured(exact_dual_matching, 10)
    matching_check, matching_check_cost = measured(check_sticks, matching_grid, 10)
    assert matching_check["valid"] and matching_check["objective"] == OPTIMA["CB-99"]
    assert merge_count == matching_work["maximum_merges"] == 56
    witnesses = dict(zip(CASE_IDS, (grid_76, grid_46, grid_99), strict=True))
    construction_costs = dict(zip(CASE_IDS, (cost_76, cost_46, cost_99), strict=True))
    construction_work = {
        "CB-76": {"cell_values_written": 40000},
        "CB-46": {"cell_values_written": 400},
        "CB-99": {"cell_values_written": 100, "merge_edges": merge_count},
    }
    bounds = {
        "CB-76": {"direction": "MAX", "bound": 3800, "nonmixed_side_count_cases": {"both_at_least_ten": 3800, "exactly_one_below_ten": 3710, "both_below_ten": 3600}},
        "CB-46": {"direction": "MAX", "bound": corner_bound, "corner_upper_bound": 49400, "one_corner_per_rectangle": 36100},
        "CB-99": {"direction": "MIN", "bound": 44, "dual_squares": 81, "dual_boundary_squares": 32, "merge_upper_bound": (81 + 32) // 2},
    }
    rows = []
    for case_id, grid in witnesses.items():
        verified, verify_cost = measured(check_full, case_id, grid)
        assert verified["valid"] and verified["objective"] == bounds[case_id]["bound"] == OPTIMA[case_id]
        source = sources[case_id]
        rows.append({
            "id": source["id"], "cb_id": case_id, "question_sha256": source["question_sha256"],
            "instruction_sha256": source["instruction_sha256"], "witness_sha256": digest(grid),
            "bound_certificate": bounds[case_id], "independent_full_check": verified,
            "construction_work": construction_work[case_id],
            "construction_cost": construction_costs[case_id], "full_check_cost": verify_cost,
        })
    controls, control_cost = measured(run_controls, grid_76, grid_46, grid_99)
    write_new(args.local_witnesses, {"witnesses": witnesses, "independent_matching_witness": matching_grid})
    result = {
        "status": "QUESTION_ONLY_OPTIMUM_BOUND_AND_WITNESS_MATCH_3_OF_3",
        "frozen_cohort_sha256": COHORT_SHA256,
        "question_only_projection_sha256": cohort["pool_sha256"],
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Question-only ordinary deterministic controls. Author verifier, reference construction, model output and official objective values were unopened. Attainment plus a mathematical bound is recorded separately from local feasibility.",
        "witness_hash_convention": "Compact UTF-8 JSON of integer matrix; sort_keys enabled and no ASCII escaping needed.",
        "local_witness_file_sha256": sha256(args.local_witnesses.read_bytes()).hexdigest(),
        "hardware_runtime": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
        "cost_scope": "Single Python process, no GPU or solver dependency. Timings omit interpreter startup and analyst derivation. Python process CPU clock has coarse granularity on some Windows calls. Report the exact operation counts together with timings.",
        "intake_cost": intake_cost,
        "rows": rows,
        "crosschecks": {
            "CB-46": {"corner_identity_value": corner_value, "row_column_comparisons": 2 * 20**3, "cost": rank_identity_cost},
            "CB-99": {"independent_maximum_bipartite_matching": matching_work, "witness_sha256": digest(matching_grid), "independent_full_check": matching_check, "matching_cost": matching_cost, "full_check_cost": matching_check_cost},
        },
        "adversarial_controls": controls,
        "adversarial_control_cost": control_cost,
    }
    write_new(args.receipt, result)


if __name__ == "__main__":
    main()
