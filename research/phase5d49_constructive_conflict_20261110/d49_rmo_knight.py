"""Independent exact RMO-2018-P4 fixed-grid checker and ordinary constructions."""
from __future__ import annotations

import argparse
from collections import deque
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter_ns, process_time_ns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASE_ID = "RMO-2018-P4-81"
COHORT_SHA = "2ef60c97ae05c2b811f873457682c8be4a650fdd9556f26c332e1203b2671617"
N = 81
MOVES = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
PATCH_WIDTHS = (4, 6, 8, 10, 12, 16, 24)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def write_once(path, data):
    raw = (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def diagonal_triplets(n):
    for row in range(n - 2):
        for col in range(n - 2):
            yield ((row, col), (row + 1, col + 1), (row + 2, col + 2))
        for col in range(2, n):
            yield ((row, col), (row + 1, col - 1), (row + 2, col - 2))


def neighbors(cell, n):
    row, col = cell
    for dr, dc in MOVES:
        r, c = row + dr, col + dc
        if 0 <= r < n and 0 <= c < n:
            yield r, c


def _white_search(grid, n):
    start, goal = (n - 1, 0), (0, n - 1)
    if grid[start[0]][start[1]] or grid[goal[0]][goal[1]]:
        return None, {"white_bfs_status": "ENDPOINT_NOT_WHITE", "white_reachable_count": None,
                      "white_bfs_expanded": 0, "knight_edges_tested": 0}
    queue = deque([start])
    parent = {start: None}
    expanded = edges = 0
    while queue:
        cell = queue.popleft()
        expanded += 1
        if cell == goal:
            path = []
            while cell is not None:
                path.append(cell)
                cell = parent[cell]
            path.reverse()
            return path, {"white_bfs_status": "WHITE_PATH_FOUND", "white_reachable_count": None,
                          "white_bfs_expanded": expanded, "knight_edges_tested": edges}
        for r, c in neighbors(cell, n):
            edges += 1
            if grid[r][c] == 0 and (r, c) not in parent:
                parent[r, c] = cell
                queue.append((r, c))
    return None, {"white_bfs_status": "WHITE_COMPONENT_EXHAUSTED", "white_reachable_count": len(parent),
                  "white_bfs_expanded": expanded, "knight_edges_tested": edges}


def check_grid(grid, n=N):
    """Check both diagonal slopes and return an actual white path on failure."""
    if type(grid) is not list or len(grid) != n or any(type(row) is not list or len(row) != n for row in grid):
        return {"valid": False, "shape": "WRONG_DIMENSIONS", "cells_checked": 0}
    cells_checked = 0
    black_cells = 0
    for row in grid:
        for value in row:
            cells_checked += 1
            if type(value) is not int or value not in (0, 1):
                return {"valid": False, "shape": "NON_BINARY_CELL", "cells_checked": cells_checked}
            black_cells += value
    violations = triplets = 0
    first = None
    for triple in diagonal_triplets(n):
        triplets += 1
        black = [cell for cell in triple if grid[cell[0]][cell[1]] == 1]
        if len(black) > 1:
            violations += 1
            if first is None:
                first = {"triple": triple, "black_cells": black[:2]}
    endpoints = [grid[n - 1][0], grid[0][n - 1]]
    path, reachability = _white_search(grid, n)
    valid = not any(endpoints) and violations == 0 and path is None
    return {"valid": valid, "shape": "BINARY_SQUARE", "cells_checked": cells_checked,
            "black_cells": black_cells, "endpoints_black_flags": endpoints,
            "diagonal_triplets_checked": triplets, "diagonal_violations": violations,
            "first_diagonal_conflict": first, "white_knight_path": path, **reachability}


def check_timed(grid):
    began_wall, began_cpu = perf_counter_ns(), process_time_ns()
    result = check_grid(grid)
    return result, {"wall_ns": perf_counter_ns() - began_wall, "process_cpu_ns": process_time_ns() - began_cpu}


def _build_cut(n, width):
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    inside = {(r, c) for r in range(n - width, n) for c in range(width)}
    black = {cell: model.NewBoolVar(f"black_{cell[0]}_{cell[1]}") for cell in sorted(inside)}
    side = {cell: model.NewBoolVar(f"side_{cell[0]}_{cell[1]}") for cell in sorted(inside)}
    start, goal = (n - 1, 0), (0, n - 1)
    model.Add(black[start] == 0)
    model.Add(side[start] == 0)
    if goal in inside:
        model.Add(black[goal] == 0)
        model.Add(side[goal] == 1)
    # Reflection across the line between the two fixed corners preserves
    # the square envelope and interchanges the first two knight neighbors.
    first, second = (n - 3, 1), (n - 2, 2)
    model.Add(black[first] <= black[second])
    diagonal_constraints = 0
    for triple in diagonal_triplets(n):
        variables = [black[cell] for cell in triple if cell in inside]
        if len(variables) >= 2:
            model.AddAtMostOne(variables)
            diagonal_constraints += 1
    internal_edges = boundary_edges = 0
    for cell in sorted(inside):
        for other in neighbors(cell, n):
            if other not in inside:
                # Outside the construction envelope all cells are white on
                # the goal side. A white neighbor inside must be on that side.
                model.AddBoolOr([black[cell], side[cell]])
                boundary_edges += 1
            elif cell < other:
                model.AddBoolOr([black[cell], black[other], side[cell].Not(), side[other]])
                model.AddBoolOr([black[cell], black[other], side[cell], side[other].Not()])
                internal_edges += 1
    return model, black, {
        "variables": 2 * len(inside), "diagonal_constraints": diagonal_constraints,
        "internal_knight_edges": internal_edges, "boundary_knight_edges": boundary_edges,
        "constraint_count": len(model.Proto().constraints),
    }


def solve_attempt(width, seconds):
    from ortools.sat.python import cp_model

    wall, cpu = perf_counter_ns(), process_time_ns()
    model, black, shape = _build_cut(N, width)
    encoding = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = seconds
    wall, cpu = perf_counter_ns(), process_time_ns()
    status = solver.Solve(model)
    run = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    p = solver.ResponseProto()
    row = {
        "width": width, "search_domain": "ORIGINAL_FULL_BOARD" if width == N else "FIXED_CORNER_ENVELOPE",
        "solver_limit_seconds": seconds, "solver_status": solver.StatusName(status), "model": shape,
        "encoding_cost": encoding, "solver_cost": run, "solver_wall_seconds": solver.WallTime(),
        "solver_user_seconds": solver.UserTime(), "solver_branches": solver.NumBranches(),
        "solver_conflicts": solver.NumConflicts(), "solver_deterministic_time": p.deterministic_time,
    }
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return row, None
    wall, cpu = perf_counter_ns(), process_time_ns()
    grid = [[0] * N for _ in range(N)]
    for (r, c), value in black.items():
        grid[r][c] = solver.Value(value)
    row["materialize_cost"] = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    checked, check_cost = check_timed(grid)
    row["independent_check"] = checked
    row["independent_check_cost"] = check_cost
    require(checked["valid"], "Exact solver produced an invalid constructive witness")
    return row, grid


def build(cohort, receipt, payload, packages):
    require(not receipt.exists() and not payload.exists(), "Ordinary RMO receipts are immutable")
    require(payload.resolve().is_relative_to((ROOT / "outputs").resolve()), "Keep full witnesses local")
    raw = cohort.read_bytes()
    require(digest(raw) == COHORT_SHA, "Frozen cohort bytes differ")
    scope = [row for row in json.loads(raw)["rows"] if row["id"] == CASE_ID]
    require(len(scope) == 1, "RMO case must be uniquely frozen")
    wall, cpu = perf_counter_ns(), process_time_ns()
    sys.path.insert(0, str(packages))
    import ortools
    from ortools.sat.python import cp_model
    setup = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}

    all_white = [[0] * N for _ in range(N)]
    conflict = [[0] * N for _ in range(N)]
    conflict[0][0] = conflict[1][1] = 1
    neg_path, neg_path_cost = check_timed(all_white)
    neg_diagonal, neg_diagonal_cost = check_timed(conflict)
    require(not neg_path["valid"] and neg_path["white_knight_path"] is not None
            and not neg_diagonal["valid"] and neg_diagonal["first_diagonal_conflict"] is not None,
            "Negative controls did not bind actual conflicts")

    attempts, witnesses = [], []
    for width in PATCH_WIDTHS:
        result, witness = solve_attempt(width, 5)
        attempts.append(result)
        if witness is not None:
            witnesses.append({"route": "CORNER_ENVELOPE", "width": width, "grid": witness})
            break
    direct, witness = solve_attempt(N, 20)
    attempts.append(direct)
    if witness is not None:
        witnesses.append({"route": "UNRESTRICTED_FULL_BOARD", "width": N, "grid": witness})
    code_sha = digest(Path(__file__).read_bytes())
    private = {
        "status": "D49_PRIVATE_RMO_ORDINARY_WITNESSES", "case_id": CASE_ID, "cohort_sha256": COHORT_SHA,
        "question_sha256": scope[0]["question_sha256"], "instruction_sha256": scope[0]["instruction_sha256"],
        "ordinary_checker_code_sha256": code_sha, "witnesses": witnesses,
    }
    private_sha = write_once(payload, private)
    public = {
        "status": "D49_RMO_ORDINARY_CONTROL_COMPLETE",
        **{k: private[k] for k in ("case_id", "cohort_sha256", "question_sha256", "instruction_sha256",
                                   "ordinary_checker_code_sha256")},
        "found_routes": [row["route"] for row in witnesses], "private_witness_sha256": private_sha,
        "ordinary_solver": {"implementation": "OR-Tools CP-SAT", "version": ortools.__version__,
                            "threads": 1, "seed": 0, "entry_module": cp_model.__name__},
        "solver_setup_cost": setup,
        "proof_scope": "Black cells at most one per length-three diagonal segment in both slopes. "
                       "The endpoints are white on different cut sides, and adjacent white cells share a side. "
                       "The unrestricted model is equivalent to exact white knight disconnection. "
                       "Envelope failures are only restricted searches. Limits and UNKNOWN are retained.",
        "negative_controls": {"all_white": {"check": neg_path, "cost": neg_path_cost},
                              "diagonal_pair": {"check": neg_diagonal, "cost": neg_diagonal_cost}},
        "attempts": attempts,
        "boundary": "Question-only exact independent solver and checker. Author references and executable verifiers stayed closed.",
    }
    print("D49 RMO receipt", write_once(receipt, public),
          "routes", public["found_routes"], "statuses", [row["solver_status"] for row in attempts])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=HERE / "D49_COHORT_FREEZE.json")
    parser.add_argument("--receipt", type=Path, default=HERE / "D49_RMO_KNIGHT_ORDINARY.json")
    parser.add_argument("--payload", type=Path, default=ROOT / "outputs/d49_rmo_knight_20261110/ordinary_witnesses.json")
    parser.add_argument("--packages", type=Path, default=ROOT / "outputs/d37_rook_cp_sat_20261110")
    args = parser.parse_args()
    build(args.cohort, args.receipt, args.payload, args.packages)


if __name__ == "__main__":
    main()
