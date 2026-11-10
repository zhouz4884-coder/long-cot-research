"""Question-only independent exact controls for CMO parity and USAMO bricks."""
from collections import Counter
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from time import perf_counter_ns, process_time_ns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COHORT_SHA = "2ef60c97ae05c2b811f873457682c8be4a650fdd9556f26c332e1203b2671617"
PARITY_ID = "CMO-2018-P5-101"
BRICK_ID = "USAMO-2020-P2"


def digest(data):
    return sha256(data).hexdigest()


def wire(data):
    return (json.dumps(data, indent=2, allow_nan=False) + "\n").encode()


def measure(fn):
    t0, c0 = perf_counter_ns(), process_time_ns()
    data = fn()
    return data, {"wall_ns": perf_counter_ns() - t0, "process_cpu_ns": process_time_ns() - c0}


def candidate_status(status, **fields):
    return {"status": status, "authority": "CANDIDATE_ONLY", **fields}


def parity_margins(board):
    return ([sum(row) % 2 for row in board],
            [sum(col) % 2 for col in zip(*board)])


def min_weight_with_margins(rows, cols):
    n = len(rows)
    odd_rows = [i for i, bit in enumerate(rows) if bit]
    odd_cols = [j for j, bit in enumerate(cols) if bit]
    if (len(odd_rows) - len(odd_cols)) % 2:
        raise ValueError("Row and column totals have different parity")
    if len(odd_rows) < len(odd_cols):
        return [(j, i) for i, j in min_weight_with_margins(cols, rows)]
    # Match each odd column to a different odd row, then put remaining
    # odd rows in one column. The remaining number of rows is even.
    return list(zip(odd_rows, odd_cols)) + [(i, n - 1) for i in odd_rows[len(odd_cols):]]


def parity_analysis(board, n, *, claimed_upper=None):
    if type(board) not in (tuple, list) or len(board) != n or any(
        type(row) not in (tuple, list) or len(row) != n for row in board
    ):
        return candidate_status("FORMAT_ERROR", reason="GRID_SHAPE")
    for i, row in enumerate(board):
        for j, bit in enumerate(row):
            if type(bit) is not int or bit not in (0, 1):
                return candidate_status("CONFLICT", reason="NON_BINARY_CELL", support=[[i, j]],
                                        named_work={"cell_type_checks": n * i + j + 1})
    if not n % 2:
        return candidate_status("UNKNOWN", reason="UNSUPPORTED_EVEN_WIDTH")
    rows, cols = parity_margins(board)
    candidates = []
    for common in (0, 1):
        target = min_weight_with_margins([bit ^ common for bit in rows], [bit ^ common for bit in cols])
        candidates.append((len(target), common, target))
    odd, common, target = min(candidates)
    maximum_even = n * n - odd
    details = {"maximum_even_for_this_board": maximum_even, "final_odd_coordinates": target,
               "row_col_common_toggle_parity": common, "row_odd_count": sum(rows), "column_odd_count": sum(cols),
               "named_work": {"cell_type_checks": n * n, "parity_accumulation_terms": 2 * n * n,
                              "parity_margin_counts": 2 * n, "two_orbit_targets": 2}}
    if claimed_upper is not None and maximum_even > claimed_upper:
        return candidate_status("CONFLICT", reason="LEGAL_TOGGLE_ORBIT_EXCEEDS_CANDIDATE_BOUND",
                                claimed_upper=claimed_upper, **details)
    return candidate_status("COMPLETE_FEASIBLE", **details)


def parity_worst(n):
    if type(n) is not int or n < 1 or n % 2 == 0:
        raise ValueError("Expected a positive odd grid size")
    board = [[int(i < n - 1 and j == 0) for j in range(n)] for i in range(n)]
    return board, n * n - (n - 1)


def parity_exhaustive_control():
    n = 3
    presses = []
    for i, j in product(range(n), repeat=2):
        presses.append(sum(1 << (r * n + c) for r, c in product(range(n), repeat=2) if r == i or c == j))
    image = {0}
    for generator in presses:
        image |= {x ^ generator for x in tuple(image)}
    worst = n * n
    for state in range(1 << (n * n)):
        board = [[(state >> (r * n + c)) & 1 for c in range(n)] for r in range(n)]
        exact_min_odd = min((state ^ mask).bit_count() for mask in image)
        result = parity_analysis(board, n)
        if result["maximum_even_for_this_board"] != n * n - exact_min_odd:
            raise AssertionError("Orbit reduction differs from original press generators")
        worst = min(worst, result["maximum_even_for_this_board"])
    return {"width": n, "states": 1 << (n * n), "reachable_masks": len(image), "worst_max_even": worst,
            "named_work": {"orbit_state_distance_checks": (1 << (n * n)) * len(image)}}


PERP = ((1, 2), (0, 2), (0, 1))


def brick_layer_key(brick, dimension):
    axis, u, v = brick
    d0, _ = PERP[axis]
    return (axis, dimension, u if dimension == d0 else v)


def brick_candidates(n):
    return tuple(product(range(3), range(n), range(n)))


def verify_bricks(bricks, n, *, complete=True):
    used, layers, work = set(), {}, Counter()
    for row in bricks:
        work["brick_domain_checks"] += 1
        if (type(row) not in (tuple, list) or len(row) != 3 or any(type(x) is not int for x in row)
                or not 0 <= row[0] < 3 or not all(0 <= x < n for x in row[1:])):
            return candidate_status("CONFLICT", reason="INVALID_BRICK", named_work=dict(work))
        brick = tuple(row)
        if brick in used:
            return candidate_status("CONFLICT", reason="DUPLICATE_BRICK", support=[brick], named_work=dict(work))
        axis = brick[0]
        for dim in PERP[axis]:
            work["overlap_layer_checks"] += 1
            key = brick_layer_key(brick, dim)
            other = layers.get((3 - axis - dim, dim, key[2]))
            if other is not None:
                return candidate_status("CONFLICT", reason="PERPENDICULAR_INTERIOR_OVERLAP",
                                        support=[other, brick], named_work=dict(work))
            layers[key] = brick
        used.add(brick)
    if not complete:
        return candidate_status("UNKNOWN", reason="PARTIAL_NO_PROVEN_CONFLICT", named_work=dict(work))
    if not used:
        return candidate_status("CONFLICT", reason="EMPTY_CONSTRUCTION", named_work=dict(work))
    for brick in sorted(used):
        axis = brick[0]
        for index, dim in enumerate(PERP[axis], 1):
            for step in (-1, 1):
                work["long_face_checks"] += 1
                position = brick[index] + step
                if not 0 <= position < n:
                    continue
                parallel = list(brick)
                parallel[index] = position
                other_layer = (3 - axis - dim, dim, position)
                if tuple(parallel) not in used and other_layer not in layers:
                    return candidate_status("CONFLICT", reason="UNSUPPORTED_LONG_FACE",
                                            brick=brick, direction=[dim, step],
                                            required_absence_scope={"parallel": parallel, "competing_layer": other_layer},
                                            named_work=dict(work))
    return candidate_status("COMPLETE_FEASIBLE", brick_count=len(used), named_work=dict(work))


def verify_bricks_voxels(bricks, n):
    """Independent unit-voxel geometry, without using the layer predicates."""
    occ = {}
    work = Counter()
    for i, (axis, u, v) in enumerate(bricks):
        d0, d1 = PERP[axis]
        for coord in range(n):
            cell = [0, 0, 0]
            cell[axis], cell[d0], cell[d1] = coord, u, v
            cell = tuple(cell)
            work["voxel_insertions"] += 1
            if cell in occ:
                return False, dict(work)
            occ[cell] = (i, axis)
    if not occ:
        return False, dict(work)
    supported = set()
    for cell, (i, axis) in occ.items():
        for dim in PERP[axis]:
            for step in (-1, 1):
                other = list(cell)
                other[dim] += step
                work["voxel_face_checks"] += 1
                neighbor = occ.get(tuple(other))
                if not 0 <= other[dim] < n or (neighbor is not None and neighbor[1] != dim):
                    supported.add((i, dim, step))
    return len(supported) == len(bricks) * 4, dict(work)


def brick_constructor(n):
    if type(n) is not int or n < 2 or n % 2:
        raise ValueError("Expected a positive even cube side at least two")
    even = range(0, n, 2)
    # Shared layer partitions: x even for Y and odd for Z, y even
    # for X and odd for Z, z even for X and odd for Y.
    return ([(0, i, i) for i in even] + [(1, i, i + 1) for i in even]
            + [(2, i + 1, i + 1) for i in even])


def brick_exact_solver(n, *, time_seconds, structural_bound=None):
    from ortools.sat.python import cp_model

    wall, cpu = perf_counter_ns(), process_time_ns()
    cp = cp_model.CpModel()
    bv = {brick: cp.NewBoolVar("b_" + "_".join(map(str, brick))) for brick in brick_candidates(n)}
    members = {}
    for brick, var in bv.items():
        for dim in PERP[brick[0]]:
            members.setdefault(brick_layer_key(brick, dim), []).append(var)
    lv = {key: cp.NewBoolVar("layer_" + "_".join(map(str, key))) for key in members}
    for key, values in members.items():
        cp.AddMaxEquality(lv[key], values)
    for dim in range(3):
        a0, a1 = PERP[dim]
        for x in range(n):
            cp.Add(lv[(a0, dim, x)] + lv[(a1, dim, x)] <= 1)
    for brick, var in bv.items():
        axis = brick[0]
        for index, dim in enumerate(PERP[axis], 1):
            for step in (-1, 1):
                position = brick[index] + step
                if not 0 <= position < n:
                    continue
                parallel = list(brick)
                parallel[index] = position
                cp.Add(var <= bv[tuple(parallel)] + lv[(3 - axis - dim, dim, position)])
    size = sum(bv.values())
    cp.Add(size >= (1 if structural_bound is None else structural_bound))
    cp.Minimize(size)
    init = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = time_seconds
    status, run = measure(lambda: solver.Solve(cp))
    witness = [brick for brick, var in bv.items() if solver.Value(var)] if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    return witness, {
        "width": n, "status": solver.StatusName(status), "initialization": init, "search": run,
        "time_envelope_seconds": time_seconds, "added_structural_lower_bound": structural_bound,
        "best_lower_bound": solver.BestObjectiveBound(), "objective": None if witness is None else len(witness),
        "branches": solver.NumBranches(), "conflicts": solver.NumConflicts(), "booleans": solver.NumBooleans(),
        "model_variables": len(cp.Proto().variables), "model_constraints": len(cp.Proto().constraints),
        "search_workers": 1, "seed": 0,
    }


def test_brick_geometry():
    n = 2
    candidates = brick_candidates(n)
    valid, minimum = 0, None
    for mask in range(1 << len(candidates)):
        pieces = [brick for index, brick in enumerate(candidates) if mask & (1 << index)]
        result = verify_bricks(pieces, n)
        independent, _ = verify_bricks_voxels(pieces, n)
        if (result["status"] == "COMPLETE_FEASIBLE") != independent:
            raise AssertionError("Brick layer checks disagree with independent geometry")
        if independent:
            valid += 1
            minimum = len(pieces) if minimum is None else min(minimum, len(pieces))
    if minimum != 3:
        raise AssertionError("Two-cube exact minimum disagrees")
    return {"width": n, "subsets_checked": 1 << len(candidates), "valid": valid, "minimum": minimum}


def write_once(path, value):
    raw = wire(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def main():
    import importlib.metadata

    raw = (HERE / "D49_COHORT_FREEZE.json").read_bytes()
    if digest(raw) != COHORT_SHA:
        raise ValueError("Frozen D49 cohort differs")
    cohort = {row["id"]: row for row in json.loads(raw)["rows"]}
    parity_audit, parity_audit_time = measure(parity_exhaustive_control)
    (parity_witness, parity_target), parity_construct_time = measure(lambda: parity_worst(101))
    parity_check, parity_check_time = measure(lambda: parity_analysis(parity_witness, 101))
    parity_bad = [r[:] for r in parity_witness]
    parity_bad[0][0] = 0
    parity_conflict, parity_conflict_time = measure(lambda: parity_analysis(parity_bad, 101, claimed_upper=parity_target))
    if parity_check["maximum_even_for_this_board"] != parity_target or parity_conflict["status"] != "CONFLICT":
        raise AssertionError("Parity controls differ")

    brick_audit, brick_audit_time = measure(test_brick_geometry)
    brick_witness, brick_construct_time = measure(lambda: brick_constructor(20))
    brick_check, brick_check_time = measure(lambda: verify_bricks(brick_witness, 20))
    (voxel, voxel_work), voxel_time = measure(lambda: verify_bricks_voxels(brick_witness, 20))
    if not voxel or brick_check["brick_count"] != 30:
        raise AssertionError("Structural witness does not meet proved minimum")
    exact_small, exact_small_receipt = brick_exact_solver(4, time_seconds=3)
    exact_main, exact_main_receipt = brick_exact_solver(20, time_seconds=8, structural_bound=30)
    for exact in (exact_small, exact_main):
        if exact is not None:
            width = 4 if exact is exact_small else 20
            if verify_bricks(exact, width)["status"] != "COMPLETE_FEASIBLE" or not verify_bricks_voxels(exact, width)[0]:
                raise AssertionError("Independent solver returned an invalid construction")
    bad, bad_time = measure(lambda: verify_bricks([(0, 0, 0), (1, 0, 0)], 20, complete=False))
    incomplete = verify_bricks(brick_witness[:1], 20, complete=False)
    if bad["reason"] != "PERPENDICULAR_INTERIOR_OVERLAP" or incomplete["status"] != "UNKNOWN":
        raise AssertionError("Partial and wrong-support controls differ")

    private_dir = ROOT / "outputs/d49_ordinary_root_20261110"
    private_dir.mkdir(parents=True, exist_ok=True)
    witness_hash = write_once(private_dir / "parity_brick_witnesses.json", {
        "cohort_sha256": COHORT_SHA, PARITY_ID: parity_witness, BRICK_ID: brick_witness,
        "independent_cp_sat_size20": exact_main,
    })
    result = {
        "status": "D49_QUESTION_ONLY_PARITY_AND_BRICK_CONTROLS_BEFORE_AUTHOR_REFERENCES",
        "cohort_sha256": COHORT_SHA, "source_sha256": digest(Path(__file__).read_bytes()),
        "private_witness_sha256": witness_hash, "ortools": importlib.metadata.version("ortools"),
        "cases": {
            PARITY_ID: {"question_sha256": cohort[PARITY_ID]["question_sha256"],
                        "complete_fixed_instance": {"value": parity_target, "construction": parity_construct_time,
                                                    "named_work": {"emitted_grid_cells": 101 * 101}},
                        "exact_witness_check": {**parity_check, "time": parity_check_time},
                        "exact_conflict": {**parity_conflict, "time": parity_conflict_time},
                        "independent_reduced_size_control": {**parity_audit, "time": parity_audit_time}},
            BRICK_ID: {"question_sha256": cohort[BRICK_ID]["question_sha256"],
                       "complete_fixed_instance": {"value": 30, "construction": brick_construct_time,
                                                   "named_work": {"emitted_bricks": 30}},
                       "exact_witness_check": {**brick_check, "time": brick_check_time},
                       "independent_voxel_validation": {"valid": voxel, "named_work": voxel_work, "time": voxel_time},
                       "exact_conflict": {**bad, "time": bad_time}, "clean_partial": incomplete,
                       "independent_small_exhaustion": {**brick_audit, "time": brick_audit_time},
                       "independent_cp_sat_small": exact_small_receipt,
                       "independent_cp_sat_fixed": exact_main_receipt},
        },
        "scope": "CPU proof and exact candidate check only. Witness checks carry no global authority. "
                 "The authored structural proof independently supplies the fixed-instance optimum. "
                 "Search envelopes are diagnostics and not model generation limits.",
    }
    print(write_once(HERE / "D49_ORDINARY_PARITY_BRICKS_PRE_REFERENCE.json", result))


if __name__ == "__main__":
    main()
