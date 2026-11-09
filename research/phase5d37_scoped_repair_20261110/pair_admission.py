"""CPU calibration for the MathConstruct C2 family and separate edge restrictions."""

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
from itertools import combinations
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import warnings


ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "pair_admission_freeze.json"


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sum_upper_bound(n):
    """Compare the smallest possible endpoint sum and largest possible pair-sum sum."""
    return (2 * n - 1) // 5


def undirected(a, b):
    return (a, b) if a < b else (b, a)


@dataclass(frozen=True)
class PairTask:
    case_id: str
    setting: str
    n: int
    target: int
    forbidden: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        if type(self.n) is not int or self.n < 1 or type(self.target) is not int or not 0 <= self.target <= sum_upper_bound(self.n):
            raise ValueError("Invalid problem size or target")
        if type(self.forbidden) is not tuple:
            raise ValueError("Restrictions must be a frozen tuple")
        for pair in self.forbidden:
            if (type(pair) is not tuple or len(pair) != 2 or any(type(v) is not int for v in pair)
                    or not 1 <= pair[0] < pair[1] <= self.n or sum(pair) > self.n):
                raise ValueError("Invalid forbidden pair")
        if self.forbidden != tuple(sorted(set(self.forbidden))):
            raise ValueError("Restrictions must be sorted and unique")

    @property
    def scope_sha256(self):
        return digest(["distinct-sum-disjoint-pairs-v1", self.n, self.target, self.forbidden])


def legal_edges(n):
    return ((a, b) for a, b in combinations(range(1, n + 1), 2) if a + b <= n)


def build_tasks(freeze):
    tasks = [PairTask(f"official-{n}", "MATHCONSTRUCT_ORIGINAL", n, sum_upper_bound(n))
             for n in freeze["official_solver_comparison_n"]]
    for row in freeze["restricted_cpu_calibration"]:
        n, count, salt = row["n"], row["forbidden_count"], row["salt"]
        ranked = sorted(legal_edges(n), key=lambda p: hashlib.sha256(f"{salt}:{p[0]}:{p[1]}".encode("ascii")).digest())
        if not 0 < count <= len(ranked):
            raise ValueError("Frozen restriction count exceeds the legal edge universe")
        tasks.append(PairTask(f"restricted-{n}", "D37_FORBIDDEN_PAIR_CALIBRATION", n, sum_upper_bound(n),
                              tuple(sorted(ranked[:count]))))
    if len({task.case_id for task in tasks}) != len(tasks):
        raise ValueError("Repeated CPU calibration case IDs")
    return tasks


@dataclass(frozen=True)
class Verification:
    status: str
    reason: str
    scope_sha256: str
    pairs_examined: int
    checked_size: int | None = None
    witness_sha256: str | None = None
    proof_scope: str = "NONE"


def check_packing(task, candidate):
    """Exact point checker. The output includes no assertion about a partial candidate's extensibility."""
    scope = task.scope_sha256
    if type(candidate) not in (tuple, list):
        return Verification("INVALID", "packing_requires_list", scope, 0)
    if len(candidate) > task.target:
        return Verification("INVALID", "more_pairs_than_requested", scope, 0)
    forbidden = set(task.forbidden)
    endpoints, sums, normalized = set(), set(), []
    for index, pair in enumerate(candidate, 1):
        if type(pair) not in (tuple, list) or len(pair) != 2 or any(type(value) is not int for value in pair):
            return Verification("INVALID", "pair_requires_two_exact_integers", scope, index)
        a, b = pair
        if not 1 <= a <= task.n or not 1 <= b <= task.n:
            return Verification("INVALID", "endpoint_outside_original_domain", scope, index)
        if a == b or a in endpoints or b in endpoints:
            return Verification("INVALID", "endpoints_not_disjoint", scope, index)
        total = a + b
        if total > task.n:
            return Verification("INVALID", "pair_sum_exceeds_n", scope, index)
        if total in sums:
            return Verification("INVALID", "pair_sums_not_distinct", scope, index)
        edge = undirected(a, b)
        if edge in forbidden:
            return Verification("INVALID", "forbidden_undirected_pair", scope, index)
        endpoints.update(pair)
        sums.add(total)
        normalized.append(edge)
    size = len(normalized)
    signature = digest([scope, sorted(normalized)])
    if size < task.target:
        return Verification("FEASIBLE_PARTIAL", "target_size_not_reached", scope, size, size, signature,
                            "EXACT_FEASIBLE_LOWER_BOUND")
    proof = "FULL_OBJECTIVE" if size == sum_upper_bound(task.n) else "REQUESTED_THRESHOLD_ONLY"
    return Verification("FEASIBLE_TARGET", "verified_all_constraints", scope, size, size, signature, proof)


def published_recipe(task):
    """Residue construction transcribed from the pinned author generator, with integer arithmetic."""
    residue = task.n % 5
    size = sum_upper_bound(task.n)
    half = (size - 1) // 2 if residue in (0, 3, 4) else size // 2
    large = list(reversed(range(2 * half + 2, 3 * half + 2)))
    large += list(reversed(range(3 * half + 2, 4 * half + 3)))
    small = list(range(2, 2 * half + 2, 2)) + list(range(1, 2 * half + 2, 2))
    if residue in (1, 2):
        large, small = large[:-1], small[:-1]
    if residue == 1:
        large = [value - 1 for value in large]
    pairs = tuple(undirected(large[i], small[i]) for i in range(task.target))
    return pairs, {"residue_class": residue, "formula_pairs_emitted": len(pairs)}


def two_pair_switch(task, trial_limit):
    """Repair the public construction using deterministic, strictly improving pair exchanges."""
    pairs, _ = published_recipe(task)
    blocked = set(task.forbidden)
    base = replace(task, forbidden=())
    start = check_packing(base, pairs)
    base_checks, base_pair_visits = 1, start.pairs_examined
    if start.status != "FEASIBLE_TARGET":
        raise ValueError("Public construction failed under the unmodified C2 constraints")
    initial = sum(pair in blocked for pair in pairs)
    count, trials = initial, 0
    trace = []
    while count and trials < trial_limit:
        replacement = None
        for i, (a, b) in enumerate(pairs):
            if (a, b) not in blocked:
                continue
            for j, (c, d) in enumerate(pairs):
                if j == i:
                    continue
                for one, two in (((a, c), (b, d)), ((a, d), (b, c))):
                    if trials >= trial_limit:
                        break
                    trials += 1
                    one, two = undirected(*one), undirected(*two)
                    remainder = count - 1 - int((c, d) in blocked) + int(one in blocked) + int(two in blocked)
                    if remainder >= count:
                        continue
                    candidate = list(pairs)
                    candidate[i], candidate[j] = one, two
                    verdict = check_packing(base, candidate)
                    base_checks += 1
                    base_pair_visits += verdict.pairs_examined
                    if verdict.status == "FEASIBLE_TARGET":
                        replacement = tuple(candidate)
                        trace.append({"replaced": [pairs[i], pairs[j]], "inserted": [one, two],
                                      "forbidden_before": count, "forbidden_after": remainder})
                        count = remainder
                        break
                if replacement or trials >= trial_limit:
                    break
            if replacement or trials >= trial_limit:
                break
        if not replacement:
            break
        pairs = replacement
    return pairs, {"initial_forbidden": initial, "remaining_forbidden": count, "switch_proposals": trials,
                   "trial_limit": trial_limit, "unrestricted_candidate_checks": base_checks,
                   "unrestricted_pairs_examined": base_pair_visits, "accepted_switches": trace}


def local_repair_fixture(task, freeze):
    salt = freeze["local_repair_source"]["selection_salt"]
    public, _ = published_recipe(task)
    blocked = sorted(set(public) & set(task.forbidden))
    legal = sorted(set(public) - set(blocked), key=lambda p: hashlib.sha256(
        f"{salt}:{task.case_id}:{p[0]}:{p[1]}".encode("ascii")).digest())
    fixed = tuple(legal[:max(0, task.target - max(2, task.target // 3))])
    if not fixed:
        raise ValueError("Frozen local fixture lacks a preserved pair")
    defect = blocked[0] if blocked else fixed[0]
    draft = (*fixed, defect)
    preserved, invalid = check_packing(task, fixed), check_packing(task, draft)
    expected_reason = "forbidden_undirected_pair" if blocked else "endpoints_not_disjoint"
    if preserved.status != "FEASIBLE_PARTIAL" or invalid.reason != expected_reason:
        raise ValueError("Local repair fixture failed scope controls")
    return {"preserved_pairs": fixed, "invalid_draft": draft,
            "preserved_verification": asdict(preserved), "invalid_verification": asdict(invalid),
            "source_fixture_sha256": digest([task.scope_sha256, fixed, draft])}


def highs_first_target(task, freeze, backend, *, fixed=()):
    np, bounds, linear, milp, sparse = backend
    started = perf_counter()
    if fixed and check_packing(task, fixed).status != "FEASIBLE_PARTIAL":
        raise ValueError("Fixed local support must be independently verified and incomplete")
    forbidden = set(task.forbidden)
    used_endpoints = {v for pair in fixed for v in pair}
    used_sums = {sum(pair) for pair in fixed}
    edges = [(a, b) for a, b in legal_edges(task.n)
             if (a, b) not in forbidden and a not in used_endpoints and b not in used_endpoints and a + b not in used_sums]
    needed = task.target - len(fixed)
    if needed == 0:
        return (), {"solver_status": "TRIVIAL_EMPTY_TARGET", "binary_variables": len(edges)}
    if not edges:
        return None, {"solver_status": "NO_ALLOWED_EDGES", "binary_variables": 0}
    rows, cols = [], []
    target_row = 2 * task.n
    for index, (a, b) in enumerate(edges):
        rows.extend([a - 1, b - 1, task.n + a + b - 1, target_row])
        cols.extend([index] * 4)
    incidence = sparse((np.ones(len(rows)), (rows, cols)), shape=(target_row + 1, len(edges))).tocsc()
    lower = np.zeros(target_row + 1)
    upper = np.ones(target_row + 1)
    lower[-1] = upper[-1] = needed
    build_seconds = perf_counter() - started
    begin_solve = perf_counter()
    with warnings.catch_warnings(record=True) as notes:
        warnings.simplefilter("always", RuntimeWarning)
        result = milp(np.zeros(len(edges)), integrality=np.ones(len(edges)), bounds=bounds(0, 1),
                      constraints=linear(incidence, lower, upper),
                      options={"time_limit": freeze["highs_time_limit_seconds"], "threads": freeze["highs_threads"]})
    solve_seconds = perf_counter() - begin_solve
    proposal = (*fixed, *(edge for edge, value in zip(edges, result.x, strict=True) if value > .5)) if result.x is not None else None
    return proposal, {"solver_status": int(result.status), "solver_message": result.message,
                      "mip_nodes": int(result.mip_node_count) if result.get("mip_node_count") is not None else None,
                      "binary_variables": len(edges), "linear_rows": target_row + 1, "linear_nonzeros": len(rows),
                      "preserved_pair_count": len(fixed), "remaining_target": needed,
                      "model_build_seconds": build_seconds, "solver_seconds": solve_seconds,
                      "warnings": [str(note.message) for note in notes]}


def local_exact_repair(task, fixture, freeze, backend):
    rejected = check_packing(task, fixture["invalid_draft"])
    if rejected.status != "INVALID":
        raise ValueError("Local repair expects a genuinely invalid shared draft")
    candidate, details = highs_first_target(task, freeze, backend, fixed=fixture["preserved_pairs"])
    return candidate, {**details, "source_fixture_sha256": fixture["source_fixture_sha256"],
                       "checked_draft_reason": rejected.reason, "checked_draft_pairs_examined": rejected.pairs_examined}


def run_controls():
    task = PairTask("shape-control", "CPU_NEGATIVE_CONTROL", 15, 3)
    sample = ((1, 4), (2, 5), (3, 6))
    restricted = replace(task, forbidden=((1, 4),))
    controls = (
        ("clean_target", task, sample, "verified_all_constraints"),
        ("underfilled_is_partial", task, sample[:2], "target_size_not_reached"),
        ("oversized", task, sample + ((8, 7),), "more_pairs_than_requested"),
        ("repeated_endpoint", task, ((1, 4), (2, 5), (3, 5)), "endpoints_not_disjoint"),
        ("self_pair", task, ((1, 1),), "endpoints_not_disjoint"),
        ("duplicate_sum", task, ((1, 6), (2, 5), (3, 7)), "pair_sums_not_distinct"),
        ("sum_too_large", task, ((1, 4), (2, 5), (6, 11)), "pair_sum_exceeds_n"),
        ("bad_endpoint", task, ((0, 4),), "endpoint_outside_original_domain"),
        ("arity", task, ((1, 4, 5),), "pair_requires_two_exact_integers"),
        ("boolean", task, ((True, 4),), "pair_requires_two_exact_integers"),
        ("float", task, ((1.0, 4),), "pair_requires_two_exact_integers"),
        ("new_scope", restricted, sample, "forbidden_undirected_pair"),
        ("reversed_forbidden", restricted, ((4, 1), *sample[1:]), "forbidden_undirected_pair"),
    )
    rows = []
    for label, view, proposal, expected in controls:
        checked = check_packing(view, proposal)
        if checked.reason != expected:
            raise ValueError(f"Calibration control failed: {label}")
        rows.append({"name": label, "expected_reason": expected, "verification": asdict(checked)})
    reversed_sample = tuple((b, a) for a, b in reversed(sample))
    a, b = check_packing(task, sample), check_packing(task, reversed_sample)
    if a.witness_sha256 != b.witness_sha256 or a.scope_sha256 == restricted.scope_sha256:
        raise ValueError("Canonical witness or restriction scope identity failed")
    rows.append({"name": "canonical_undirected_witness_scope", "witness_sha256": a.witness_sha256,
                 "base_scope_sha256": a.scope_sha256, "restricted_scope_sha256": restricted.scope_sha256})
    return rows


def run_one(task, solve, *, fixed=()):
    began = perf_counter()
    candidate, details = solve()
    proposal_seconds = perf_counter() - began
    checked = check_packing(task, candidate) if candidate is not None else None
    if fixed and candidate is not None and not set(fixed) <= {undirected(*pair) for pair in candidate}:
        raise ValueError("Local repair changed a protected pair")
    elapsed = perf_counter() - began
    accepted = checked is not None and checked.status == "FEASIBLE_TARGET"
    return {"status": "VERIFIED_TARGET" if accepted else "NO_VERIFIED_TARGET", "candidate": candidate,
            "verification": asdict(checked) if checked else None, "proposal_seconds": proposal_seconds,
            "candidate_check_seconds": elapsed - proposal_seconds, "total_attempt_seconds": elapsed,
            "first_verified_target_seconds": elapsed if accepted else None, "details": details}


def run(freeze):
    controls = run_controls()
    audit_start = perf_counter()
    official = []
    lo, hi = freeze["official_author_recipe_range"]
    for n in range(lo, hi + 1):
        task = PairTask(f"author-support-{n}", "MATHCONSTRUCT_ORIGINAL", n, sum_upper_bound(n))
        checked = check_packing(task, published_recipe(task)[0])
        if checked.proof_scope != "FULL_OBJECTIVE":
            raise ValueError(f"Pinned source recipe failed independent verification at n={n}")
        official.append({"n": n, "target": task.target, "verified_witness_sha256": checked.witness_sha256})
    official_seconds = perf_counter() - audit_start

    began_import = perf_counter()
    import numpy as np
    import scipy
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix
    import_seconds = perf_counter() - began_import
    backend = np, Bounds, LinearConstraint, milp, coo_matrix
    tasks = build_tasks(freeze)
    results = []
    for task in tasks:
        fixture = local_repair_fixture(task, freeze)
        fixed = fixture["preserved_pairs"]
        methods = {
            "PublishedRecipe": lambda: published_recipe(task),
            "TwoPairSwitch": lambda: two_pair_switch(task, freeze["structural_switch_trial_limit"]),
            "HiGHSFeasibility": lambda: highs_first_target(task, freeze, backend),
            "LocalExactFixed": lambda: local_exact_repair(task, fixture, freeze, backend),
        }
        if list(methods) != freeze["methods"]:
            raise ValueError("Unfrozen solver set")
        grouped = {}
        for name, solve in methods.items():
            trials = [run_one(task, solve, fixed=fixed if name == "LocalExactFixed" else ())
                      for _ in range(freeze["repeat_count"])]
            valid_costs = [trial["first_verified_target_seconds"] for trial in trials if trial["status"] == "VERIFIED_TARGET"]
            grouped[name] = {"target_hit_repeats": len(valid_costs), "attempts": len(trials),
                             "median_first_verified_target_seconds": median(valid_costs) if valid_costs else None,
                             "trials": trials}
        results.append({"task": asdict(task), "constraint_scope_sha256": task.scope_sha256,
                        "certified_upper_bound": sum_upper_bound(task.n), "local_repair_fixture": fixture, "methods": grouped})
    return {"status": "COMPLETE_CPU_CALIBRATION", "python": sys.version, "scipy": scipy.__version__, "numpy": np.__version__,
            "cold_backend_import_seconds": import_seconds, "source_file_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "freeze_sha256": hashlib.sha256(FREEZE.read_bytes()).hexdigest(), "controls": controls,
            "official_author_recipe_audit": {"checked": len(official), "valid": len(official),
                                             "elapsed_seconds": official_seconds, "rows": official},
            "task_results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists. Use a new file for each timed observation.")
    result = run(json.loads(FREEZE.read_bytes()))
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
    for row in result["task_results"]:
        short = {method: (data["target_hit_repeats"], data["median_first_verified_target_seconds"])
                 for method, data in row["methods"].items()}
        print(row["task"]["case_id"], json.dumps(short))


if __name__ == "__main__":
    main()
