"""Exact rook-window validation and same-goal CPU construction baselines."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import product
from math import gcd
import random


@dataclass(frozen=True)
class Board:
    n: int
    k: int
    pins: tuple[tuple[int, int], ...] = ()
    forbidden: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        if type(self.n) is not int or type(self.k) is not int or not 2 <= self.k <= self.n:
            raise ValueError("Expected integer dimensions 2 <= k <= n")
        if any(len(cell) != 2 or any(type(v) is not int or not 1 <= v <= self.n for v in cell)
               for cell in (*self.pins, *self.forbidden)):
            raise ValueError("Restrictions require in-bounds integer coordinates")
        if len(self.pins) != len(dict(self.pins)) or len(self.pins) != len({c for _, c in self.pins}):
            raise ValueError("Pinned rooks conflict by row or column")
        if set(self.pins) & set(self.forbidden) or len(set(self.forbidden)) != len(self.forbidden):
            raise ValueError("Restrictions are inconsistent or repeated")

    def allowed_columns(self):
        by_row = dict(self.pins)
        by_column = {c: r for r, c in self.pins}
        blocked = set(self.forbidden)
        return tuple(tuple(c for c in range(1, self.n + 1)
                           if by_row.get(r, c) == c and by_column.get(c, r) == r and (r, c) not in blocked)
                     for r in range(1, self.n + 1))


def empty_windows(columns, k):
    """Return every uncovered window by scanning gaps in each k-row strip."""
    last_start = len(columns) - k + 1
    holes = []
    for top in range(last_start):
        before = 0
        for col in (*sorted(columns[top:top + k]), len(columns) + 1):
            holes.extend((top + 1, left) for left in range(before + 1, col - k + 1))
            before = col
    return holes


def validate(board, rooks):
    if not isinstance(rooks, (tuple, list)) or len(rooks) != board.n:
        return {"valid": False, "reason": "wrong_rook_count"}
    if any(not isinstance(cell, (tuple, list)) or len(cell) != 2 or
           any(type(v) is not int or not 1 <= v <= board.n for v in cell) for cell in rooks):
        return {"valid": False, "reason": "malformed_or_out_of_range"}
    row_map = dict(rooks)
    if len(row_map) != board.n or len(set(row_map.values())) != board.n:
        return {"valid": False, "reason": "row_or_column_collision"}
    missing = [(r, c) for r, c in board.pins if row_map[r] != c]
    blocked = [(r, c) for r, c in board.forbidden if row_map[r] == c]
    holes = empty_windows([row_map[r] for r in range(1, board.n + 1)], board.k)
    return {"valid": not (missing or blocked or holes), "reason": "checked_all_rules",
            "missing_pins": missing, "forbidden_rooks": blocked, "empty_windows": holes}


def brute_window_count(board, rooks):
    """Independent nested occupancy loop for well-formed candidates."""
    occupied = {tuple(cell) for cell in rooks}
    starts = range(1, board.n - board.k + 2)
    return sum(not any((r, c) in occupied for r in range(i, i + board.k)
                       for c in range(j, j + board.k)) for i, j in product(starts, repeat=2))


def as_rooks(columns):
    return [[r, c] for r, c in enumerate(columns, 1)]


def structural(board, author_seed):
    """Try all square symmetries of the author construction, then affine permutations."""
    n = board.n
    seen = set()
    allowed = tuple(map(set, board.allowed_columns()))

    def passes(columns):
        return all(c in a for c, a in zip(columns, allowed, strict=True)) and not empty_windows(columns, board.k)

    def dihedral():
        for transpose, flip_r, flip_c in product((False, True), repeat=3):
            rooks = []
            for r, c in author_seed:
                if transpose:
                    r, c = c, r
                rooks.append((n + 1 - r if flip_r else r, n + 1 - c if flip_c else c))
            yield tuple(c for _, c in sorted(rooks))

    def affine():
        for step in range(1, n):
            if gcd(step, n) == 1:
                for offset in range(n):
                    yield tuple((step * row + offset) % n + 1 for row in range(n))

    for family, candidates in (("author_dihedral", dihedral()), ("modular_affine", affine())):
        for columns in candidates:
            if columns not in seen:
                seen.add(columns)
                if passes(columns):
                    return as_rooks(columns), {"status": "FEASIBLE", "family": family, "candidate_tests": len(seen)}
    return None, {"status": "NO_CANDIDATE_FOUND", "candidate_tests": len(seen)}


def planted_restrictions(n, k, seed, density, pin_count, author_seed):
    """Freeze solvable synthetic restrictions before observing any baseline outcomes."""
    rng = random.Random(seed)
    columns = [c for _, c in sorted(author_seed)]
    accepted = 0
    for _ in range(1600):
        left, right = rng.sample(range(n), 2)
        columns[left], columns[right] = columns[right], columns[left]
        if empty_windows(columns, k):
            columns[left], columns[right] = columns[right], columns[left]
        else:
            accepted += 1
    pinned_rows = sorted(rng.sample(range(1, n + 1), pin_count))
    pins = tuple((r, columns[r - 1]) for r in pinned_rows)
    forbidden = tuple((r, c) for r, c in product(range(1, n + 1), repeat=2)
                      if c != columns[r - 1] and rng.random() < density)
    return Board(n, k, pins, forbidden), as_rooks(columns), accepted


def min_conflicts(board, *, seed=20261110, restarts=8, steps=180):
    """Start from random legal assignments, then repair uncovered windows with swaps."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    rng = random.Random(seed)
    n = board.n
    allowed = tuple(map(set, board.allowed_columns()))
    matching_attempts = swaps_considered = 0
    for _ in range(restarts):
        costs = np.array([[rng.random() if c in allowed[r] else 1e6 for c in range(1, n + 1)] for r in range(n)])
        rows, cols = linear_sum_assignment(costs)
        matching_attempts += 1
        if any(costs[r, c] >= 1e6 for r, c in zip(rows, cols, strict=True)):
            break
        columns = [int(c) + 1 for c in cols]
        tabu = deque(maxlen=12)
        for step in range(steps + 1):
            holes = empty_windows(columns, board.k)
            if not holes:
                return as_rooks(columns), {"status": "FEASIBLE", "matching_attempts": matching_attempts,
                                          "swaps_evaluated": swaps_considered}
            if step == steps:
                break
            top, left = rng.choice(holes)
            inner = set(range(top - 1, top + board.k - 1))
            outer = [r for r, c in enumerate(columns) if left <= c < left + board.k and r not in inner]
            moves = []
            for i, j in product(sorted(inner), outer):
                if columns[j] not in allowed[i] or columns[i] not in allowed[j]:
                    continue
                move = tuple(sorted((i, j)))
                columns[i], columns[j] = columns[j], columns[i]
                score = len(empty_windows(columns, board.k))
                columns[i], columns[j] = columns[j], columns[i]
                swaps_considered += 1
                if move not in tabu or score < len(holes):
                    moves.append((score, rng.random(), move))
            if not moves:
                break
            _, _, (i, j) = min(moves)
            columns[i], columns[j] = columns[j], columns[i]
            tabu.append((i, j))
    return None, {"status": "NO_CANDIDATE_FOUND", "matching_attempts": matching_attempts,
                  "swaps_evaluated": swaps_considered}


def allowed_positions(board, fixed=()):
    by_row = dict(fixed)
    return {(r, c) for r, cols in enumerate(board.allowed_columns(), 1) for c in cols
            if by_row.get(r, c) == c}


def constraints(board, positions):
    n, k = board.n, board.k
    for r in range(1, n + 1):
        yield tuple((r, c) for c in range(1, n + 1) if (r, c) in positions), True
    for c in range(1, n + 1):
        yield tuple((r, c) for r in range(1, n + 1) if (r, c) in positions), True
    for i, j in product(range(1, n - k + 2), repeat=2):
        yield tuple((r, c) for r, c in product(range(i, i + k), range(j, j + k)) if (r, c) in positions), False


def solve_cp_sat(board, limit, *, fixed=(), hint=()):
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    allowed = allowed_positions(board)
    known = set(board.pins) | {tuple(p) for p in fixed}
    fixed_rows, fixed_cols = {r for r, _ in known}, {c for _, c in known}
    if len(known) != len(fixed_rows) or len(known) != len(fixed_cols) or not known <= allowed:
        return None, {"status": "INFEASIBLE_FIXED_RESTRICTIONS", "variables": 0, "solver_wall_seconds": 0}
    free = {p for p in allowed if p[0] not in fixed_rows and p[1] not in fixed_cols}
    positions = known | free
    decisions = {p: model.new_bool_var(f"r{p[0]}c{p[1]}") for p in sorted(free)}
    posted = 0
    for subset, equality in constraints(board, positions):
        if any(p in known for p in subset):
            continue
        variables = [decisions[p] for p in subset]
        if equality:
            model.add_exactly_one(variables)
        else:
            model.add_bool_or(variables)
        posted += 1
    if hint:
        hint_by_row = dict(hint)
        for (r, c), variable in decisions.items():
            if r in hint_by_row:
                model.add_hint(variable, int(hint_by_row[r] == c))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 20261110
    solver.parameters.stop_after_first_solution = True
    solver.parameters.max_time_in_seconds = limit
    status = solver.solve(model)
    selected = known | {p for p, v in decisions.items() if solver.value(v)} if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    candidate = [[*p] for p in sorted(selected)] if selected is not None else None
    return candidate, {"status": solver.status_name(status), "branches": solver.num_branches,
                       "conflicts": solver.num_conflicts, "variables": len(decisions),
                       "fixed_rooks": len(known), "posted_constraints": posted, "solver_wall_seconds": solver.wall_time}


def solve_milp(board, limit):
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_array
    import warnings

    positions = allowed_positions(board)
    ordered = sorted(positions)
    index = {p: i for i, p in enumerate(ordered)}
    xrows, xcols, upper = [], [], []
    for row, (subset, equality) in enumerate(constraints(board, positions)):
        xrows.extend([row] * len(subset))
        xcols.extend(index[p] for p in subset)
        upper.append(1 if equality else np.inf)
    matrix = coo_array((np.ones(len(xrows)), (np.array(xrows, dtype=np.int32), np.array(xcols, dtype=np.int32))),
                       shape=(len(upper), len(ordered))).tocsc()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unrecognized options detected.*threads", category=RuntimeWarning)
        result = milp(np.zeros(len(ordered)), integrality=np.ones(len(ordered)), bounds=Bounds(0, 1),
                      constraints=LinearConstraint(matrix, 1, upper), options={"time_limit": limit, "threads": 1})
    candidate = [[*p] for p, v in zip(ordered, result.x, strict=True) if v > 0.5] if result.x is not None else None
    return candidate, {"status": ["FEASIBLE_ZERO_OBJECTIVE", "TIME_LIMIT_OR_NODE_LIMIT", "INFEASIBLE", "UNBOUNDED", "SOLVER_ERROR"][result.status],
                       "returned_primal": result.x is not None, "branches": getattr(result, "mip_node_count", None),
                       "variables": len(ordered), "message": result.message}


def proposed_repair_scope(board, draft):
    """Freeze unaffected assignments using only the presented draft and checker conflicts."""
    by_row = dict(draft)
    row_for_column = {c: r for r, c in draft}
    active = set(range(1, board.n + 1)) - by_row.keys()
    allowed = tuple(map(set, board.allowed_columns()))
    for r, c in draft:
        if c not in allowed[r - 1]:
            active.add(r)
    for r, c in board.pins:
        if by_row.get(r) != c and c in row_for_column:
            active.add(row_for_column[c])
    if len(draft) == board.n:
        diagnostics = validate(board, draft)
        for i, j in diagnostics.get("empty_windows", ())[:3]:
            active.update(range(i, i + board.k))
            active.update(row_for_column[c] for c in range(j, j + board.k))
    return sorted(active), [[r, c] for r, c in sorted(by_row.items()) if r not in active]
