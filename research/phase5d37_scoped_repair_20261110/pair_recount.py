"""Recount frozen candidate evidence and prove small fixed-scope no-extension cases."""

from dataclasses import asdict
import hashlib
from itertools import combinations
import json
from math import comb
from statistics import median

from pair_admission import FREEZE, ROOT, build_tasks, check_packing, digest, local_repair_fixture, run_controls


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def same(left, right, reason):
    need(digest(left) == digest(right), reason)


def residual_edges(task, fixed):
    occupied = {v for edge in fixed for v in edge}
    sums = {sum(edge) for edge in fixed}
    unused = [v for v in range(1, task.n + 1) if v not in occupied]
    return [(a, b) for a, b in combinations(unused, 2)
            if a + b <= task.n and a + b not in sums and (a, b) not in task.forbidden]


def exhaustive_fixed_extension(task, fixed):
    residual = residual_edges(task, fixed)
    remaining = task.target - len(fixed)
    trials = comb(len(residual), remaining)
    need(trials <= 50_000, "No exact negative receipt beyond the fixed enumeration budget")
    feasible = 0
    repeated_endpoint = 0
    repeated_sum = 0
    for group in combinations(residual, remaining):
        if len({v for edge in group for v in edge}) != 2 * remaining:
            repeated_endpoint += 1
        elif len({sum(edge) for edge in group}) != remaining:
            repeated_sum += 1
        else:
            feasible += 1
    need(repeated_endpoint + repeated_sum + feasible == trials, "Enumeration ledger is not complete")
    vertices = sorted({v for edge in residual for v in edge})
    cover = next((points for size in range(remaining) for points in combinations(vertices, size)
                  if all(a in points or b in points for a, b in residual)), None)
    return {"scope": "exact selected support only", "fixed": fixed, "remaining_pairs_required": remaining,
            "residual_legal_edges": residual, "enumerated_combinations": trials,
            "excluded_repeated_endpoint": repeated_endpoint, "excluded_repeated_sum": repeated_sum,
            "feasible_extensions": feasible, "residual_vertex_cover_smaller_than_target": cover}


def one_release_diagnostic(task, fixed):
    """Find an exactly checked single-release witness, outside the timed comparison."""
    examined = []
    for released in fixed:
        retained = tuple(edge for edge in fixed if edge != released)
        edges = residual_edges(task, retained)
        remaining = task.target - len(retained)
        maximum_trials = comb(len(edges), remaining)
        if maximum_trials > 50_000:
            continue
        for count, subset in enumerate(combinations(edges, remaining), 1):
            if len({v for edge in subset for v in edge}) != 2 * remaining:
                continue
            if len({sum(edge) for edge in subset}) != remaining:
                continue
            witness = (*retained, *subset)
            verified = check_packing(task, witness)
            need(verified.proof_scope == "FULL_OBJECTIVE", "Single-release witness violates original constraints")
            return {"scope": "post-timing one-protected-pair release control", "released": released,
                    "preserved_pair_count": len(retained), "residual_edges": len(edges),
                    "combinations_until_first_verified": count, "earlier_failed_releases": examined,
                    "witness": witness, "verification": asdict(verified)}
        examined.append({"released": released, "residual_edges": len(edges), "combinations_checked": maximum_trials})
    return None


def recount():
    freeze_raw = FREEZE.read_bytes()
    freeze = json.loads(freeze_raw)
    result_path = ROOT / "pair_admission_results.json"
    result_raw = result_path.read_bytes()
    result = json.loads(result_raw)
    need(result["status"] == "COMPLETE_CPU_CALIBRATION", "Missing closed CPU calibration")
    need(result["freeze_sha256"] == hashlib.sha256(freeze_raw).hexdigest(), "Protocol differs from timed run")
    need(result["source_file_sha256"] == hashlib.sha256((ROOT / "pair_admission.py").read_bytes()).hexdigest(),
         "Source differs from timed run")
    same(result["controls"], run_controls(), "Checker controls differ")
    attempts = witnesses = verified = 0
    local_no_extension = []
    for task, row in zip(build_tasks(freeze), result["task_results"], strict=True):
        same(asdict(task), row["task"], "Task differs from frozen case")
        fixture = local_repair_fixture(task, freeze)
        same(fixture, row["local_repair_fixture"], "Local repair fixture changed")
        fixed = fixture["preserved_pairs"]
        methods = row["methods"]
        same(list(methods), freeze["methods"], "Method membership differs")
        for name, record in methods.items():
            runs = record["trials"]
            need(len(runs) == record["attempts"] == freeze["repeat_count"], "Missing or extra timed attempt")
            hits = []
            for attempt in runs:
                attempts += 1
                candidate = attempt["candidate"]
                if candidate is not None:
                    witnesses += 1
                    observed = check_packing(task, candidate)
                    same(asdict(observed), attempt["verification"], "Candidate verification changed")
                    if name == "LocalExactFixed":
                        need(set(fixed) <= {tuple(sorted(edge)) for edge in candidate}, "Local method changed fixed support")
                    hit = observed.status == "FEASIBLE_TARGET"
                else:
                    need(attempt["verification"] is None, "Absent candidate claims proof")
                    hit = False
                need(hit == (attempt["status"] == "VERIFIED_TARGET"), "Hit differs from checked witness")
                if hit:
                    verified += 1
                    need(attempt["first_verified_target_seconds"] == attempt["total_attempt_seconds"] > 0,
                         "Success has no paid first-target time")
                    hits.append(attempt["first_verified_target_seconds"])
                else:
                    need(attempt["first_verified_target_seconds"] is None, "Failure claims a target time")
            same(len(hits), record["target_hit_repeats"], "Repeat hit count differs")
            same(median(hits) if hits else None, record["median_first_verified_target_seconds"], "Median differs")
        local = methods["LocalExactFixed"]
        if not local["target_hit_repeats"] and all(run["details"]["solver_status"] == 2 for run in local["trials"]):
            proof = exhaustive_fixed_extension(task, fixed)
            need(proof["feasible_extensions"] == 0, "Independent exact local enumeration disagrees with HiGHS")
            local_no_extension.append({"case_id": task.case_id, "constraint_scope_sha256": task.scope_sha256,
                                       "free_global_target_verified": methods["HiGHSFeasibility"]["target_hit_repeats"] > 0,
                                       **proof, "single_release_diagnostic": one_release_diagnostic(task, fixed)})
    return {"status": "PASS", "results_sha256": hashlib.sha256(result_raw).hexdigest(),
            "timed_attempts_recounted": attempts, "candidate_objects_rechecked": witnesses,
            "verified_target_witnesses": verified, "fixed_scope_no_extension": local_no_extension}


if __name__ == "__main__":
    print(json.dumps(recount(), ensure_ascii=False, indent=2))
