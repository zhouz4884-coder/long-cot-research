"""Independently recount the derived whole-corpus ledger and failure families."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run():
    inventory_raw = (ROOT / "corpus_inventory.json").read_bytes()
    summary = json.loads((ROOT / "corpus_summary.json").read_bytes())
    digest = hashlib.sha256(inventory_raw).hexdigest()
    require(digest == summary["inventory_sha256"], "Corpus summary inventory hash differs")
    episodes = json.loads(inventory_raw)["episodes"]
    key = {(e["state_id"], e["model"], e["mode"]) for e in episodes}
    states = {e["state_id"] for e in episodes}
    targets = {e["target_id"] for e in episodes}
    require(len(key) == len(episodes) == 852 and len(states) == 142 and len(targets) == 141,
            "Published corpus denominator differs")
    steps = Counter(s["outcome"] for e in episodes for s in e["steps"])
    require(dict(steps) == summary["attempt_outcomes"] and sum(steps.values()) == 3499, "Attempt counts differ")
    errors = [(e, s) for e in episodes for s in e["steps"] if s["outcome"] == "ARCHIVED_LEAN_ERROR"]
    protected_errors = [(e, s) for e, s in errors if s["proved_target_prerequisites"]]
    protected_targets = {e["target_id"] for e, _ in protected_errors}
    require(len(protected_errors) == summary["errors_with_proved_ancestor"]["attempts"] == 851 and
            len(protected_targets) == summary["errors_with_proved_ancestor"]["targets"] == 85,
            "Protected error clusters differ")
    accepted = [e for e in episodes if e["author_rescan_pass"]]
    loop = [e for e in episodes if e["loop_time_outcome"] == "solved"]
    require(len(accepted) == 573 and len(loop) == 575 and len({e["target_id"] for e in accepted}) == 123,
            "Loop and author-rescan outcomes differ")
    failures = defaultdict(list)
    for episode in episodes:
        failures[episode["controlled_failure_family"]].append(episode)
    families = {}
    for name, rows in sorted(failures.items()):
        all_starts = {e["state_id"] for e in rows}
        any_accepted = {e["state_id"] for e in rows if e["author_rescan_pass"]}
        families[name] = {"controlled_starts": len(all_starts), "at_least_one_author_rescan_success": len(any_accepted),
                          "no_author_rescan_success_in_six_archived_episodes": len(all_starts - any_accepted)}
    observed_retained = [e for e in accepted if e["endpoint"]["release_necessity"].startswith("OBSERVED_")]
    used = [e for e in observed_retained if e["endpoint"]["release_necessity"] == "OBSERVED_ALL_PRIOR_DECLARATIONS_RETAINED_AND_USED"]
    require(len(observed_retained) == summary["observed_no_replacement_source"]["episodes"] == 127 and
            len(used) == summary["observed_no_replacement_and_actual_use"]["episodes"] == 118,
            "Retained prerequisite counts differ")
    report = {"status": "PASS", "scope": "Recount of pinned author telemetry ledger. Controlled start families are dataset construction labels. No causal diagnosis of model failure is inferred from them.",
              "inventory_sha256": digest, "controlled_starts": len(states), "independent_target_clusters": len(targets),
              "episodes": len(episodes), "step_records": sum(steps.values()),
              "steps_with_observed_action": sum(steps.values()) - steps["NO_OBSERVED_MODEL_ACTION"],
              "author_reported_verifier_calls": sum(e["author_verifier_calls"] for e in episodes),
              "loop_time_solved_episodes": len(loop), "author_rescan_accepted_episodes": len(accepted),
              "states_without_author_rescan_success": len(states - {e["state_id"] for e in accepted}),
              "target_clusters_without_author_rescan_success": len(targets - {e["target_id"] for e in accepted}),
              "protected_lean_errors": len(protected_errors), "protected_lean_error_target_clusters": len(protected_targets),
              "retained_source_episodes": len(observed_retained), "retained_and_used_episodes": len(used),
              "controlled_failure_families": families}
    output = ROOT / "D39_CORPUS_VALIDATION.json"
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    if output.exists():
        require(output.read_bytes() == raw, "Independent corpus validation changed on replay")
    else:
        output.write_bytes(raw)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
