"""Explore old, fully observed results; never fit or certify a new policy here.

Replays select a previously generated terminal answer. Their runtime is a
reference-run cost proxy, not the measured latency of a veto-and-resume policy.
The original model outputs, scores, predictors and release are read-only.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import beta, rankdata


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def auc(labels, scores):
    y = np.asarray(labels, dtype=int)
    p = np.asarray(scores, dtype=float)
    pos = int(y.sum())
    neg = len(y) - pos
    if not pos or not neg:
        return None
    return float((rankdata(p)[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def upper(harms, n, alpha=0.05):
    return float(beta.ppf(1 - alpha, harms + 1, n - harms)) if harms < n else 1.0


def bins(cases, score, outcome, edges):
    result = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        subset = [c for c in cases if lo <= c[score] < hi or (hi == 1 and c[score] == 1)]
        result.append({"lo": lo, "hi": hi, "n": len(subset),
                       "mean_score": float(np.mean([c[score] for c in subset])) if subset else None,
                       "observed_rate": float(np.mean([c[outcome] for c in subset])) if subset else None})
    return result


def decision_fields(row):
    d = row["decisions"][-1] if row["decisions"] else {}
    p = d.get("detail", {})
    costs = p.get("predicted_extra_tokens", {})
    values = p.get("values", {})
    full_net = p.get("full_fix", 0) - p.get("full_harm", 0)
    step_net = p.get("step_fix", 0) - p.get("step_harm", 0)
    margin = row["policy_spec"].get("margin", 0)
    return {"last_action": d.get("action"), "last_offset": d.get("offset"),
            "last_kind": d.get("kind"), "p_stop": p.get("stop_correct"),
            "p_full_fix": p.get("full_fix"), "p_full_harm": p.get("full_harm"),
            "p_full_correct": p.get("full_correct"), "raw_full_net": full_net,
            "raw_step_net": step_net, "stop_margin": margin,
            "predicted_full_extra_tokens": costs.get("FULL"),
            "full_cost_penalty": row["policy_spec"].get("cost_lambda", 0) * costs.get("FULL", 0),
            "penalized_full_value": values.get("FULL"),
            "cost_veto": max(full_net, step_net) > margin,
            "readout_entropy": p.get("readout_probe", {}).get("entropy")}


def describe_model(methods, questions):
    full, ctrl = methods["full"], methods["transition"]
    ids = sorted(set(full) & set(ctrl))
    cases = []
    for pid in ids:
        a, b = full[pid], ctrl[pid]
        q = questions[pid]
        harm = int(a["correct"] == 1 and b["correct"] == 0)
        benefit = int(a["correct"] == 0 and b["correct"] == 1)
        fields = decision_fields(b)
        cases.append({"problem_id": pid, "subject": q["subject"], "level": q["level"],
                      "harm": harm, "benefit": benefit, "full_correct": a["correct"],
                      "controller_correct": b["correct"], **fields,
                      "full_tokens": a["total_tokens"], "controller_tokens": b["total_tokens"],
                      "full_think_tokens": a["think_tokens"], "controller_think_tokens": b["think_tokens"],
                      "full_censored": a["length_censored"],
                      "controller_parse_status": b["grade"]["parse_status"],
                      "reference_wall_s": a["wall_ms"] / 1000,
                      "controller_wall_s": b["wall_ms"] / 1000,
                      "paired_wall_difference_s": (a["wall_ms"] - b["wall_ms"]) / 1000,
                      "reference_remaining_think_tokens": a["think_tokens"] - b["think_tokens"],
                      "question": q["question"], "gold": q["gold"],
                      "full_answer": a["answer"]["text"], "controller_answer": b["answer"]["text"],
                      "controller_last_thought": b["trace"]["text"][-800:],
                      "full_last_thought": a["trace"]["text"][-800:],
                      "error_category": "parse_failure" if b["grade"]["parse_status"] != "ok"
                                        else "answer_value_mismatch_unattributed" if harm
                                        else "not_harmful",
                      "causal_mechanism": "unknown"})
    stopped = [c for c in cases if c["last_action"] == "STOP"]
    ref_tokens = sum(full[k]["total_tokens"] for k in ids)
    ref_wall = sum(full[k]["wall_ms"] for k in ids)
    rules = {
        "old_frozen_policy": lambda c: False,
        "veto_p_stop_below_0_5": lambda c: c["p_stop"] < 0.5,
        "veto_p_stop_below_0_9": lambda c: c["p_stop"] < 0.9,
        "veto_p_stop_below_0_95": lambda c: c["p_stop"] < 0.95,
        "veto_cost_overrode_raw_gain": lambda c: c["cost_veto"],
        "veto_p_stop_below_0_9_or_cost_override": lambda c: c["p_stop"] < 0.9 or c["cost_veto"],
        "veto_full_fix_above_0_05": lambda c: c["p_full_fix"] > 0.05,
        "veto_full_fix_above_0_02": lambda c: c["p_full_fix"] > 0.02,
        "veto_full_fix_above_0_01": lambda c: c["p_full_fix"] > 0.01,
        "oracle_veto_all_actual_harms_NOT_DEPLOYABLE": lambda c: bool(c["harm"]),
        "veto_every_stop": lambda c: True,
    }
    replays = []
    for name, veto in rules.items():
        vetoed = [c for c in stopped if veto(c)]
        veto_ids = {c["problem_id"] for c in vetoed}
        selected = {k: full[k] if k in veto_ids else ctrl[k] for k in ids}
        harms = sum(full[k]["correct"] == 1 and selected[k]["correct"] == 0 for k in ids)
        fixes = sum(full[k]["correct"] == 0 and selected[k]["correct"] == 1 for k in ids)
        replays.append({"name": name, "n": len(ids), "vetoed_original_stops": len(vetoed),
                        "blocked_observed_harms": sum(c["harm"] for c in vetoed),
                        "lost_observed_benefits": sum(c["benefit"] for c in vetoed),
                        "retained_original_stops": len(stopped) - len(vetoed),
                        "logged_selected_correct": sum(r["correct"] for r in selected.values()),
                        "logged_selected_accuracy": sum(r["correct"] for r in selected.values()) / len(ids),
                        "logged_accuracy_delta": (fixes - harms) / len(ids),
                        "logged_harms": int(harms), "logged_benefits": int(fixes),
                        "reference_run_token_saving_proxy": 1 - sum(r["total_tokens"] for r in selected.values()) / ref_tokens,
                        "reference_run_wall_saving_proxy": 1 - sum(r["wall_ms"] for r in selected.values()) / ref_wall,
                        "latency_measured_for_new_policy": False,
                        "new_blind_test_result": False})
    coherence = [abs(c["p_full_correct"] - c["p_stop"] - (c["p_full_fix"] - c["p_full_harm"])) for c in stopped]
    result = {"n": len(ids), "actual_harms": sum(c["harm"] for c in cases),
              "actual_benefits": sum(c["benefit"] for c in cases), "terminal_stop_n": len(stopped),
              "risk_label_orientation": "STOP harm versus FULL equals old full_fix, NOT old full_harm",
              "auc_selected_terminal_STOP": {
                  "p_full_fix_for_harm": auc([c["harm"] for c in stopped], [c["p_full_fix"] for c in stopped]),
                  "one_minus_p_stop_for_harm": auc([c["harm"] for c in stopped], [1 - c["p_stop"] for c in stopped])},
              "stop_correctness_reliability": bins(stopped, "p_stop", "controller_correct", [0, 0.5, 0.9, 0.95, 1]),
              "relative_harm_reliability": bins(stopped, "p_full_fix", "harm", [0, 0.01, 0.02, 0.05, 0.1, 0.2, 1]),
              "independent_head_coherence": {
                  "identity_gap_mean_abs": float(np.mean(coherence)) if coherence else None,
                  "identity_gap_max_abs": max(coherence, default=None),
                  "full_fix_gt_one_minus_p_stop": sum(c["p_full_fix"] > 1 - c["p_stop"] for c in stopped),
                  "full_harm_gt_p_stop": sum(c["p_full_harm"] > c["p_stop"] for c in stopped)},
              "timing_components_s": {
                  "mean_detector": float(np.mean([ctrl[k]["detector_ms"] / 1000 for k in ids])),
                  "mean_sample_feature_timer": float(np.mean([ctrl[k]["feature_gpu_ms"] / 1000 for k in ids])),
                  "mean_answer": float(np.mean([ctrl[k]["answer"]["ms"] / 1000 for k in ids])),
                  "mean_num_decisions": float(np.mean([len(ctrl[k]["decisions"]) for k in ids])),
                  "warning": "Detector includes probe calls; feature_gpu_ms is a wall timer, not CUDA kernel attribution. Components are not assumed disjoint."},
              "logged_terminal_veto_replays": replays}
    return result, cases


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--out", type=Path, default=Path("results/next_phase_20261013"))
    args = p.parse_args()
    root, out = args.root, args.out
    out.mkdir(parents=True, exist_ok=True)
    assert json.loads((root / "results/analysis/study_integrity.json").read_text())["passed"]
    paths = sorted((root / "results/online").glob("*.jsonl"))
    sources = paths + [root / "data/test.jsonl", root / "reason_transition/predictor.py"]
    hashes = {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    questions = {r["problem_id"]: r for r in read_jsonl(root / "data/test.jsonl")}
    models = defaultdict(lambda: defaultdict(dict))
    rows_n = 0
    for f in paths:
        for row in read_jsonl(f):
            rows_n += 1
            model = row["model_path"].split("/")[-1]
            assert row["problem_id"] not in models[model][row["method"]]
            models[model][row["method"]][row["problem_id"]] = row
    assert rows_n == 1648
    results, all_cases = {}, []
    for model, methods in sorted(models.items()):
        result, cases = describe_model(methods, questions)
        results[model] = result
        all_cases += [{"model": model, **c} for c in cases]
    assert results["Qwen3-4B"]["actual_harms"] == 25
    assert results["Qwen3-4B"]["actual_benefits"] == 4
    assert results["Qwen3-4B-Thinking-2507"]["actual_harms"] == 2
    risks = []
    for n in [50, 100, 299, 300, 400, 505, 1000]:
        for k in [1, 8]:
            for h in [0, 1, 2, 3, 5, 10]:
                risks.append({"n_independent_problems": n, "predeclared_candidate_count": k,
                              "observed_harms": h, "familywise_alpha": 0.05,
                              "harm_upper": upper(h, n, 0.05 / k),
                              "one_pp_certified": upper(h, n, 0.05 / k) <= 0.01})
    payload = {"created_for": "2026-10-13 user roadmap independent audit", "is_new_gpu_experiment": False,
               "is_policy_selection_or_certification": False, "source_records": rows_n,
               "source_sha256": hashes,
               "scope": "Exploratory diagnosis on already observed test questions; no final threshold is selected.",
               "replay_warning": "Veto replays replace the old terminal answer by saved FULL. They do not resume a GPU branch, test later decisions, or measure new runtime. Existing confidence estimates are not guarantees.",
               "models": results, "risk_sample_size_examples": risks,
               "zero_harm_minimum_n_single_policy_one_pp": math.ceil(math.log(0.05) / math.log(0.99)),
               "zero_harm_minimum_n_eight_policies_one_pp": math.ceil(math.log(0.05 / 8) / math.log(0.99))}
    (out / "ROADMAP_AUDIT.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "ALL_TERMINAL_CASES.json").write_text(json.dumps(all_cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    changed = [c for c in all_cases if c["harm"] or c["benefit"]]
    with (out / "STOP_REVERSAL_MATRIX.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(changed[0]))
        writer.writeheader()
        writer.writerows(changed)
    for f in sources:
        assert hashes[str(f.relative_to(root))] == hashlib.sha256(f.read_bytes()).hexdigest()
    print(json.dumps({"source_records": rows_n, "reversal_matrix_rows": len(changed),
                      "models": results, "all_source_hashes_unchanged": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
