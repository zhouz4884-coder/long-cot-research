"""Bounded CPU admission for official MathConstruct C3 and separate restrictions."""

from __future__ import annotations

import ast
from dataclasses import asdict
from hashlib import sha256
from itertools import combinations, permutations, product
import json
from pathlib import Path
import platform
import random
import statistics
from time import perf_counter
from types import SimpleNamespace
from urllib.request import urlopen

from rook_cover import (Board, as_rooks, brute_window_count, min_conflicts, planted_restrictions,
                        proposed_repair_scope, solve_cp_sat, solve_milp, structural, validate)


ROOT = Path(__file__).resolve().parent
COMMIT = "3e51d847547a6586237ae55b83131b0e31b8476d"
BASE = f"https://raw.githubusercontent.com/eth-sri/mathconstruct/{COMMIT}/"
AUTHORS_MODULE = "src/math_construct/problems/imo_shortlist/problem_2014_c3.py"
SOURCES = {
    AUTHORS_MODULE: "ad500f24c78d747560c0b0b5972139f43b9827d1d5e8fa5fa8a932e1f55715da",
    "src/math_construct/problems/templates.py": "46ff716aecd45ade4c2a5ed754e2b94eebf69596f5a8d099f6e7f71313ff4437",
    "LICENSE": "9ae5f2facea3d00158a6bd479c54d1bf24de9659b20a4f1a8464b0c343df09b8",
}
OFFICIAL = ((22, 5), (15, 4), (16, 4), (35, 6), (36, 6), (63, 8), (64, 8))
RESTRICTED = ((12, 4, 101, .20, 2), (15, 4, 102, .45, 3), (22, 5, 103, .20, 3),
              (22, 5, 104, .45, 4), (31, 6, 105, .30, 4), (34, 6, 106, .50, 5))
SOLVER_LIMIT = 4.0


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def author_reference():
    assets = {}
    manifest = {}
    for path, expected in SOURCES.items():
        with urlopen(BASE + path, timeout=15) as response:
            payload = response.read()
        if sha256(payload).hexdigest() != expected:
            raise ValueError(f"Author source hash mismatch: {path}")
        assets[path] = payload
        manifest[path] = {"url": BASE + path, "sha256": expected, "bytes": len(payload)}
    module = ast.parse(assets[AUTHORS_MODULE])
    generator, = (n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "get_solution")
    cls, = (n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "Problem2014C3")
    checker, = (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "check")
    namespace = {"CheckerTag": SimpleNamespace(CORRECT="CORRECT", INCORRECT_LENGTH="INCORRECT_LENGTH",
                                                INCORRECT_FORMAT="INCORRECT_FORMAT", INCORRECT_SOLUTION="INCORRECT_SOLUTION")}
    # Execute only the two reviewed functions from byte-verified author code.
    exec(compile(ast.Module(body=[generator, checker], type_ignores=[]), AUTHORS_MODULE, "exec"), namespace)
    return namespace["get_solution"], namespace["check"], manifest


def timed(board, method):
    start = perf_counter()
    candidate, detail = method()
    check_started = perf_counter()
    report = validate(board, candidate) if candidate is not None else None
    end = perf_counter()
    passed = report is not None and report["valid"]
    return {"method_elapsed_seconds": check_started - start, "independent_check_seconds": end - check_started,
            "wall_through_terminal_seconds": end - start, "first_feasible_elapsed_seconds": end - start if passed else None,
            "valid_first_feasible": passed, "candidate": candidate, "check": report, "method": detail}


def independent_controls(author, authors_check):
    n, k = 5, 3
    board = Board(n, k)
    agree = 0
    for columns in permutations(range(1, n + 1)):
        candidate = as_rooks(columns)
        checked = validate(board, candidate)
        other = authors_check(SimpleNamespace(n=n, k=k), candidate)[0]
        if other != checked["valid"] or brute_window_count(board, candidate) != len(checked["empty_windows"]):
            raise ValueError("Checker mismatch with independent grid and author reference")
        agree += 1
    shape_board = Board(9, 3)
    legal = author(shape_board.n, shape_board.k)
    blocked = tuple(legal[0])
    pin_col = 1 + (legal[0][1] % shape_board.n)
    negatives = {
        "missing_rook": (shape_board, legal[:-1]),
        "duplicate_coordinate": (shape_board, [legal[1], *legal[1:]]),
        "duplicate_column": (shape_board, [[1, legal[1][1]], *legal[1:]]),
        "zero_based_coordinate": (shape_board, [[0, 1], *legal[1:]]),
        "float_coordinate": (shape_board, [[1.0, 1], *legal[1:]]),
        "boolean_coordinate": (shape_board, [[True, 1], *legal[1:]]),
        "identity_uncovered_window": (shape_board, as_rooks(range(1, shape_board.n + 1))),
        "forbidden_cell": (Board(9, 3, forbidden=(blocked,)), legal),
        "wrong_pin": (Board(9, 3, pins=((1, pin_col),)), legal),
    }
    output = {key: validate(b, candidate) for key, (b, candidate) in negatives.items()}
    if any(row["valid"] for row in output.values()) or not validate(shape_board, legal)["valid"]:
        raise ValueError("Negative or positive checker control failed")
    # Two rows can both use only column 1. This contradiction is independent of any solver outcome.
    impossible = Board(5, 3, forbidden=tuple(product((1, 2), range(2, 6))))
    cp = timed(impossible, lambda: solve_cp_sat(impossible, SOLVER_LIMIT))
    milp = timed(impossible, lambda: solve_milp(impossible, SOLVER_LIMIT))
    if any(row["candidate"] is not None or row["method"]["status"] != "INFEASIBLE" for row in (cp, milp)):
        raise ValueError("An exact solver did not reject the elementary Hall obstruction")
    return {"author_and_naive_checker_agreement": agree, "positive_pass": True, "negatives": output,
            "negative_hall_obstruction": {"board": asdict(impossible), "cp_sat": cp, "highs_milp": milp}}


def draft_pair(board, plant, seed):
    rng = random.Random(seed + 100_000)
    excluded = set(rng.sample(range(1, board.n + 1), 3))
    partial = [p for p in plant if p[0] not in excluded]
    pairs = list(combinations(range(board.n), 2))
    rng.shuffle(pairs)
    for i, j in pairs:
        mutated = [p.copy() for p in plant]
        mutated[i][1], mutated[j][1] = mutated[j][1], mutated[i][1]
        if not validate(board, mutated)["valid"]:
            return {"partial_three_missing_rows": partial, "invalid_one_swap": mutated}
    raise ValueError("Predeclared corruption rule did not expose a negative draft")


def board_methods(board, author, reference):
    methods = {
        "author": timed(board, lambda: (author(board.n, board.k), {"status": "AUTHOR_CONSTRUCTED"})),
        "dihedral_and_modular": timed(board, lambda: structural(board, reference)),
        "matching_min_conflicts": timed(board, lambda: min_conflicts(board)),
        "cp_sat_cold": timed(board, lambda: solve_cp_sat(board, SOLVER_LIMIT)),
        "highs_milp_cold": timed(board, lambda: solve_milp(board, SOLVER_LIMIT)),
    }
    for name in ("cp_sat_cold", "highs_milp_cold"):
        row = methods[name]
        if row["candidate"] is not None and not row["valid_first_feasible"]:
            raise ValueError(f"{name} returned a false feasible candidate")
    return methods


def repair_methods(board, draft):
    active, preserved = proposed_repair_scope(board, draft)

    def local():
        recomputed, fixed = proposed_repair_scope(board, draft)
        if (recomputed, fixed) != (active, preserved):
            raise ValueError("Repair scope is unstable under identical input")
        return solve_cp_sat(board, SOLVER_LIMIT, fixed=fixed, hint=draft)

    local_result = timed(board, local)
    global_result = timed(board, lambda: solve_cp_sat(board, SOLVER_LIMIT, hint=draft))
    if local_result["candidate"] is not None and (not local_result["valid_first_feasible"] or
            not {tuple(r) for r in preserved} <= {tuple(r) for r in local_result["candidate"]}):
        raise ValueError("Local exact solver violated its original rules or preserved assignments")
    if global_result["candidate"] is not None and not global_result["valid_first_feasible"]:
        raise ValueError("Global hinted solver returned a false feasible candidate")
    return {"draft": draft, "draft_sha256": digest(draft), "initial_check": validate(board, draft),
            "active_rows": active, "preserved_rooks": preserved,
            "fixed_scope_cp_sat": local_result, "free_scope_same_hint_cp_sat": global_result}


def run():
    import numpy
    import ortools
    import scipy
    import ortools.sat.python.cp_model  # Warm solver imports outside method timings.
    import scipy.optimize

    author, authors_check, manifest = author_reference()
    output = {"status": "COMPLETE_CPU_DEVELOPMENT_ONLY", "source_commit": COMMIT, "source_artifacts": manifest,
              "runtime_sha256": {name: sha256((ROOT / name).read_bytes()).hexdigest()
                                 for name in ("rook_admission.py", "rook_cover.py")},
              "environment": {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor(),
                              "numpy": numpy.__version__, "ortools": ortools.__version__, "scipy": scipy.__version__},
              "scope": "Single-worker CPU first-feasible time from frozen input through independent exact check; imports and source transfer excluded.",
              "cpu_solver_limit_seconds_each": SOLVER_LIMIT, "min_conflicts_bounds": {"restart_limit": 8, "swap_steps_per_restart": 180},
              "check_controls": independent_controls(author, authors_check),
              "official": {}, "restricted_synthetic": {}}
    for n, k in OFFICIAL:
        key = f"n{n}_k{k}"
        board = Board(n, k)
        reference = author(n, k)
        if not (authors_check(SimpleNamespace(n=n, k=k), reference)[0] and validate(board, reference)["valid"]):
            raise ValueError("Official author case does not agree with both checkers")
        methods = board_methods(board, author, reference)
        timings = [timed(board, lambda: (author(n, k), {}))["first_feasible_elapsed_seconds"] for _ in range(11)]
        output["official"][key] = {"board": asdict(board), "origin": "original" if (n, k) == OFFICIAL[0] else "author_explicit_parameters",
                                   "author_and_checker_median_11_seconds": statistics.median(timings), "methods": methods}
        print("official", key, {k: r["method"]["status"] for k, r in methods.items()}, flush=True)
    for n, k, seed, density, pin_count in RESTRICTED:
        key = f"n{n}_k{k}_seed{seed}"
        reference = author(n, k)
        board, plant, swaps = planted_restrictions(n, k, seed, density, pin_count, reference)
        certificate = validate(board, plant)
        if not certificate["valid"] or brute_window_count(board, plant) != 0:
            raise ValueError("Restricted board is not independently satisfiable")
        methods = board_methods(board, author, reference)
        drafts = {name: repair_methods(board, draft) for name, draft in draft_pair(board, plant, seed).items()}
        output["restricted_synthetic"][key] = {"board": asdict(board), "generation_seed": seed,
                                                "nominal_forbidden_probability": density, "accepted_plant_swaps": swaps,
                                                "offline_satisfiability_certificate": {"rooks": plant, "sha256": digest(plant), "check": certificate},
                                                "methods": methods, "same_draft_repairs": drafts}
        print("restricted", key, {k: (r["method"]["status"], r["valid_first_feasible"]) for k, r in methods.items()},
              {k: (r["fixed_scope_cp_sat"]["method"]["status"], r["free_scope_same_hint_cp_sat"]["method"]["status"]) for k, r in drafts.items()}, flush=True)
    destination = ROOT / "rook_admission_results.json"
    destination.write_bytes((json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())
    return output


if __name__ == "__main__":
    run()
