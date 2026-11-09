"""Aggregate closed, audited E15 shards and evaluate the independent-admission gate."""

from collections import defaultdict
import json

from prepare_d36_checkpoints import FREEZE, ROOT, sha, write_once


def load(name):
    return json.loads((ROOT / name).read_bytes())


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def paired_results(groups, trial_arm, control_arm):
    rows = []
    for (checkpoint, replicate), group in groups.items():
        trial, control = group[trial_arm], group[control_arm]
        rows.append({"checkpoint": checkpoint, "replicate": replicate,
                     "correctness_delta": int(trial["correct"]) - int(control["correct"]),
                     "gpu_inputs_delta": trial["gpu_inputs_after_cut"] - control["gpu_inputs_after_cut"],
                     "attention_pairs_delta": trial["attention_pairs_after_cut"] - control["attention_pairs_after_cut"],
                     "seconds_after_cut_delta": trial["seconds_after_cut"] - control["seconds_after_cut"],
                     "trial_feedback_appended": trial["model_modified_by_feedback"],
                     "trial_terminal_vetoes": trial["terminal_vetoes"]})
    return {"pairs": rows, "rescues": sum(row["correctness_delta"] == 1 for row in rows),
            "harms": sum(row["correctness_delta"] == -1 for row in rows),
            "baseline_correct_denominator": sum(group[control_arm]["correct"] for group in groups.values()),
            "ties_correctness": sum(row["correctness_delta"] == 0 for row in rows)}


def run():
    freeze = json.loads(FREEZE.read_bytes())
    checkpoints = list(freeze["checkpoints"])
    audits = {checkpoint: load(f"{checkpoint.upper()}_GPU_AUDIT.json") for checkpoint in checkpoints}
    for key, row in audits.items():
        need(row["status"] == "PASS" and row["checkpoint"] == key, "Missing a validated E15 shard")
    groups = defaultdict(dict)
    by_arm = defaultdict(list)
    for checkpoint, audit in audits.items():
        for row in audit["model_arms"]:
            groups[checkpoint, row["replicate"]][row["arm"]] = row
            by_arm[row["arm"]].append(row)
    expected_groups = len(checkpoints) * len(freeze["replicates"])
    need(len(groups) == expected_groups and all(set(x) == set(freeze["arms"]) for x in groups.values()),
         "Incomplete E15 paired matrix")
    correct_gold = {checkpoint: int(audit["historical_reference_after_close"]) for checkpoint, audit in audits.items()}
    point = load("D36_POINT_BASELINES.json")
    tool_bests = {key: row["budgets"][str(freeze["primary_point_budget"])]["best_feasible"]
                  for key, row in point["checkpoints"].items()}
    tool_correct = {key: tool_bests[key] == correct_gold[key] for key in checkpoints}
    direct = load("D36_DIRECT_SOLVER_COMPARISON.json")
    direct_correct = all(direct["certificate"]["value"] == val for val in correct_gold.values())
    need(direct["status"] == "PASS" and direct_correct, "Unrestricted solver disagreement must be investigated")
    contrasts = {trial + "_vs_" + control: paired_results(groups, trial, control) for trial, control in (
        ("ClaimOnly", "NeutralReminder"), ("NumericWitness", "NeutralReminder"),
        ("VerifiedWitness", "NumericWitness"), ("ProgressiveWitness", "VerifiedWitness"),
        ("EveryStepAudit", "ProgressiveWitness"), ("ProgressiveWitness", "NativeContinue"),
    )}
    summary_by_arm = {}
    for arm, rows in by_arm.items():
        summary_by_arm[arm] = {"denominator": len(rows), "correct": sum(r["correct"] for r in rows),
                               "eos": sum(r["eos"] for r in rows), "technical_cap": sum(r["technical_cap"] for r in rows),
                               "paid_inputs_after_cut": sum(r["gpu_inputs_after_cut"] for r in rows),
                               "seconds_after_cut": sum(r["seconds_after_cut"] for r in rows),
                               "point_calls": sum(r["point_calls"] for r in rows), "point_ops": sum(r["point_ops"] for r in rows),
                               "vetoes": sum(r["terminal_vetoes"] for r in rows),
                               "feedback_appended": sum(r["model_modified_by_feedback"] for r in rows),
                               "new_valid_bounds": sum(r["new_valid_bounds_after_cue"] for r in rows),
                               "positive_bound_scope": "Feasibility only in E15 point-access experiments."}
    # The point-only tool sees the same frozen observation and has zero continuation model work.
    # Its candidate is evaluated by final-value correctness, independently of its proof scope.
    dominance = all(tool_correct.values()) and all(row["gpu_inputs_after_cut"] > 0 for row in by_arm["ProgressiveWitness"])
    gate = ("NOT_ADMITTED_STRONG_LOCAL_POINT_BASELINE_ALREADY_SOLVES_E15" if dominance
            else "REQUIRES_MANUAL_REPLICATED_NET_INCREMENT_AUDIT")
    references = [FREEZE.name, "D36_CPU_DIAGNOSIS_ZH.md", "D36_CROSS_PHASE_OBSERVATIONS.json",
                  "D36_CROSS_PHASE_SCORES.json", "D36_NUMERIC_CONTEXT_REVIEW.json", "D36_CLOCK_INTERVALS.json",
                  "D36_POINT_BASELINES.json", "D36_DIRECT_SOLVER_COMPARISON.json", "D36_SOURCE_REFERENCE.json"]
    references += [f"{key.upper()}_{suffix}.json" for key in checkpoints for suffix in ("GPU_AUDIT", "RETRIEVAL")]
    result = {"status": "COMPLETE_DEVELOPMENT_MATRIX", "problem_count": 1, "paired_checkpoint_seed_groups": len(groups),
              "paid_arm_count": sum(map(len, by_arm.values())), "arm_summary": summary_by_arm, "matched_contrasts": contrasts,
              "bounded_tools_only_k": freeze["primary_point_budget"], "tools_only_same_prefix_best_feasible": tool_bests,
              "tools_only_scalar_matches_reference": tool_correct, "tools_only_has_global_certificate": False,
              "unrestricted_solver_exact_and_correct": direct_correct,
              "independent_confirmation_gate": gate, "independent_new_problem_scores": 0,
              "clock_accounting": {key: row["clock_accounting"] for key, row in audits.items()},
              "evidence_sha256": {file: sha((ROOT / file).read_bytes()) for file in references}}
    write_once(ROOT / "D36_DELIVERY_AUDIT.json", result)
    return result


if __name__ == "__main__":
    data = run()
    print(json.dumps({key: data[key] for key in ("status", "arm_summary", "independent_confirmation_gate")}, indent=2))
