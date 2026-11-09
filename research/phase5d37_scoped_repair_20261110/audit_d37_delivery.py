"""Verify phase receipts and decide whether a model repair pilot is admitted."""

import json
import subprocess

from freeze_scope_regressions import BASELINE, REPO, ROOT, sha
from pair_recount import recount
from rebuild_scope_inventory import write_once
from rook_cover import Board, brute_window_count, validate


def load(name):
    return json.loads((ROOT / name).read_bytes())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def check_rook_arm(board, record):
    candidate = record["candidate"]
    if candidate is None:
        require(not record["valid_first_feasible"], "Missing rook candidate is marked solved")
        return 0
    independent = validate(board, candidate)["valid"] and brute_window_count(board, candidate) == 0
    require(independent == record["valid_first_feasible"], "Rook result disagrees with independent validation")
    return 1


def check_rooks(rook):
    for file, digest in rook["runtime_sha256"].items():
        require(sha((ROOT / file).read_bytes()) == digest, "A timed rook source changed")
    verified = local_successes = same_hint_successes = 0
    author_seconds, direct_seconds, local_seconds = [], [], []
    for setting in ("official", "restricted_synthetic"):
        for row in rook[setting].values():
            spec = row["board"]
            board = Board(spec["n"], spec["k"], tuple(map(tuple, spec["pins"])), tuple(map(tuple, spec["forbidden"])))
            methods = row["methods"]
            verified += sum(check_rook_arm(board, record) for record in methods.values())
            if setting == "official":
                require(methods["author"]["valid_first_feasible"], "Official author control did not solve")
                author_seconds.append(row["author_and_checker_median_11_seconds"])
                continue
            direct = methods["cp_sat_cold"]
            require(direct["valid_first_feasible"] and methods["highs_milp_cold"]["valid_first_feasible"],
                    "Restricted rook instance has no verified strong direct solution")
            direct_seconds.append(direct["first_feasible_elapsed_seconds"])
            plant = row["offline_satisfiability_certificate"]["rooks"]
            require(validate(board, plant)["valid"] and brute_window_count(board, plant) == 0,
                    "Offline satisfiability witness is invalid")
            for repair in row["same_draft_repairs"].values():
                fixed, free = repair["fixed_scope_cp_sat"], repair["free_scope_same_hint_cp_sat"]
                verified += check_rook_arm(board, fixed) + check_rook_arm(board, free)
                require(fixed["valid_first_feasible"] and free["valid_first_feasible"], "Rook repair did not hit target")
                require(set(map(tuple, repair["preserved_rooks"])) <= set(map(tuple, fixed["candidate"])),
                        "Fixed solver modified a protected rook")
                local_successes += 1
                same_hint_successes += 1
                local_seconds.append(fixed["first_feasible_elapsed_seconds"])
    return {"official_author_target_hits": [len(author_seconds), len(rook["official"])],
            "restricted_both_direct_target_hits": [len(direct_seconds), len(rook["restricted_synthetic"])],
            "restricted_local_target_hits": [local_successes, 12], "restricted_same_hint_free_target_hits": [same_hint_successes, 12],
            "largest_official_author_median_seconds": max(author_seconds),
            "largest_restricted_direct_cp_sat_seconds": max(direct_seconds),
            "largest_restricted_local_cp_sat_seconds": max(local_seconds), "archived_method_candidates_rechecked": verified}


def run():
    subprocess.run(["git", "diff", "--exit-code", BASELINE, "--", "research/phase5d25_constraint_revision_20261109",
                    "research/phase5d35_witness_gated_revision_20261109", "research/phase5d36_progressive_witness_20261109"],
                   cwd=REPO, check=True)
    gate = load("D37_ADMISSION_GATE.json")
    scope = load("scope_replay_audit.json")
    require(scope["event_count"] == gate["source_audit"]["expected_point_events"] == 451 and
            scope["point_eligible_recall"] == [270, 270] and scope["point_false_authorization"] == [0, 181],
            "Frozen development scope frame is incomplete")
    require(all(row["scope_matches"] for row in scope["selected_real_regressions"]) and
            all(row["matches"] for row in scope["synthetic_challenge"]), "A known source-scope regression remains")
    independent = load("scope_independent_retest_results.json")
    initial = load("scope_independent_results.json")
    require(sha((ROOT / "scope_adapter.py").read_bytes()) == independent["retest_scope_adapter_sha256"] and
            sha((ROOT / "scope_independent_results.json").read_bytes()) == independent["first_result_sha256"] and
            not independent["retest_false_authority_ids"] and not independent["retest_positive_mismatch_ids"],
            "Independent source audit does not match its disclosed-set retest")
    terminal = load("terminal_format_audit.json")
    require(len(terminal["fresh_synthetic_rows"]) == 36 and terminal["additional_gpu_seconds"] == 0,
            "Terminal challenge count differs from freeze")
    pair = load("pair_admission_results.json")
    require(json.loads(json.dumps(recount())) == load("pair_admission_audit.json"), "Pair raw recount differs")
    all_pairs = pair["task_results"]
    restricted = [item for item in all_pairs if item["task"]["case_id"].startswith("restricted-")]
    require(len(all_pairs) == 12 and len(restricted) == 6 and all(
        row["methods"]["HiGHSFeasibility"]["target_hit_repeats"] == 3 for row in all_pairs),
        "Pair free solver did not return all frozen targets")
    pair_times = [trial["first_verified_target_seconds"] for row in all_pairs
                  for trial in row["methods"]["HiGHSFeasibility"]["trials"]]
    screen = gate["cpu_admission"]["first_screen_cpu_seconds"]
    require(all(t is not None and t <= screen for t in pair_times), "Pair direct screen requires further audit")
    rook = check_rooks(load("rook_admission_results.json"))
    require(rook["restricted_both_direct_target_hits"] == [6, 6] and rook["restricted_local_target_hits"] == [12, 12]
            and rook["largest_restricted_direct_cp_sat_seconds"] < screen and
            rook["largest_official_author_median_seconds"] < screen, "Rook direct screen requires further audit")
    names = ["D37_ADMISSION_GATE.json", "scope_event_inventory.json", "scope_regressions.json", "scope_review_labels.json",
             "scope_replay_audit.json", "scope_adapter.py", "scoped_obligation.py", "scope_independent_results.json",
             "scope_independent_retest_results.json", "terminal_format_audit.json", "terminal_challenge_freeze.json",
             "pair_admission_freeze.json", "pair_admission_results.json", "pair_admission_audit.json", "rook_admission_results.json"]
    report = {"status": "COMPLETE_CPU_ADMISSION_NO_GO", "baseline_commit": BASELINE,
              "scope": {"reconstructed_arms": 48, "reconstructed_events": 451, "point_eligible_recall": scope["point_eligible_recall"],
                        "point_false_authorization": scope["point_false_authorization"],
                        "independent_initial_false_authorization": [initial["counts"]["FALSE_AUTHORITY"], initial["expected_none"]],
                        "disclosed_retest_false_authorization": [len(independent["retest_false_authority_ids"]), initial["expected_none"]]},
              "terminal_synthetic_confusion": terminal["fresh_synthetic_confusion"],
              "pair": {"restricted_direct_target_hits": [6, 6], "restricted_local_target_hits": [sum(
                  row["methods"]["LocalExactFixed"]["target_hit_repeats"] == 3 for row in restricted), 6],
                       "largest_free_target_seconds": max(pair_times)},
              "rook": rook, "model_pilot_admitted": False, "new_model_tokens": 0, "new_gpu_seconds": 0,
              "independent_model_test_denominator": 0,
              "reason": "Both tested families have strong checked same-target CPU solutions inside the frozen short screen. No eligible whole-family model test was formed. The scope retest is a regression check, not a deployment safety estimate.",
              "evidence_sha256": {name: sha((ROOT / name).read_bytes()) for name in names}}
    write_once(ROOT / "D37_DELIVERY_AUDIT.json", report)
    return report


if __name__ == "__main__":
    data = run()
    print(json.dumps({k: v for k, v in data.items() if k != "evidence_sha256"}, indent=2))
