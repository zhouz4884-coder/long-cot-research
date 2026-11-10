"""Verify the two paid Qwen runs and summarize the fixed controlled holdout."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAB = ROOT / "outputs/d50_lab_runtime_20261110"
ARMS = ("uniform", "U", "A", "T")
MODES = ("raw_sgd", "matched_norm")
ROLES = ("E", "W", "C")


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def collect(stage):
    folder = LAB / stage
    result, result_sha = read(folder / "result.json")
    checked, retrieval_sha = read(folder / "retrieval_receipt.json")
    require(result_sha == checked["result_sha256"] and not checked["live"], "Result is unverified or still writing")
    paid = result["paid_work"]
    counts = Counter(x["kind"] for x in paid["rows"])
    tokens = sum(x.get("input_tokens", 0) for x in paid["rows"])
    require(counts == {"FORWARD": paid["forward_calls"], "BACKWARD": paid["backward_calls"]}
            and tokens == paid["forward_input_tokens"], "Paid work recount differs")
    stages = defaultdict(Counter)
    for row in paid["rows"]:
        block = row["stage"].split(":", 1)[0]
        stages[block][row["kind"]] += 1
        stages[block]["forward_input_tokens"] += row.get("input_tokens", 0)
    meta = {"raw_result_sha256": result_sha, "retrieval_receipt_sha256": retrieval_sha,
            "runner_source_sha256": result["runner_source_sha256"],
            "parameter_base_sha256": result["parameter_base_sha256"],
            "parameter_final_sha256": result["parameter_final_sha256"],
            "paid_work": {k: v for k, v in paid.items() if k != "rows"},
            "counts_by_stage": {k: dict(v) for k, v in sorted(stages.items())},
            "model_and_adapter_load_wall_ns": result["runtime"]["model_and_adapter_load_wall_ns"],
            "diagnostic_elapsed_wall_ns": result["elapsed_wall_ns"],
            "peak_allocated_bytes": result["peak_allocated_bytes"], "peak_reserved_bytes": result["peak_reserved_bytes"],
            "bitwise_restore_count": result["bitwise_restore_count"]}
    return result, meta


def main():
    dev, dev_meta = collect("d50_dev_fp32_v1")
    actual, run_meta = collect("d50_control_fp32_v1")
    gate, gate_sha = read(HERE / "D50_CONTROLLED_GATE_RESULT.json")
    launch, launch_sha = read(HERE / "D50_CONTROLLED_GPU_LAUNCH_FREEZE.json")
    require(gate["runner_result_sha256"] == run_meta["raw_result_sha256"]
            and actual["input_sha256"] == launch["main_input_sha256"]
            and actual["separate_holdout_sha256"] == launch["holdout_input_sha256"]
            and dev["runner_source_sha256"] == actual["runner_source_sha256"] == launch["runner_sha256"]
            and dev["parameter_base_sha256"] == dev["parameter_final_sha256"]
            == actual["parameter_base_sha256"] == actual["parameter_final_sha256"]
            and dev["settings"] == actual["settings"] == launch["settings"], "Scope, parameters or frozen launch differ")
    require(dev["status"] == actual["status"] == "COMPLETE"
            and gate["status"] == "NO_GO_CONTROLLED_GATE"
            and gate["problem_counts_by_role"] == {"E": 4, "W": 4, "C": 4}, "Study status or denominator differs")
    roles = {role: [r for r in gate["rows"] if r["role"] == role] for role in ROLES}
    residuals = {mode: {arm: {role: {
        field: actual["branches"][arm][mode]["by_role"][role][field]
        for field in ("delta_loss", "linear_delta_loss", "residual")
    } for role in ROLES} for arm in ARMS} for mode in MODES}
    results = {}
    for mode in MODES:
        results[mode] = {
            "mean_margin_change_nats_per_target_token": {r: {a: mean(
                x["modes"][mode]["delta"][a]["nats_per_target_token"] for x in rows)
                for a in ARMS} for r, rows in roles.items()},
            "paired_margin_sign_changes": {r: {a: sum(
                (x["initial"]["sequence_nats"] > 0) != (x["modes"][mode]["after"][a]["sequence_nats"] > 0)
                for x in rows) for a in ARMS} for r, rows in roles.items()},
            "actual_update_norms": {a: actual["branches"][a][mode]["actual_update_norm"] for a in ARMS},
            "linear_loss_check_by_arm_and_role_in_sequence_nats": residuals[mode],
        }
    summary = {
        "status": "D50_TWO_REAL_QWEN_RUNS_COMPLETE_CONTROLLED_GATE_NO_GO",
        "control_gate_sha256": gate_sha, "control_launch_freeze_sha256": launch_sha,
        "dev": dev_meta, "controlled": run_meta,
        "sum_forward_calls": sum(x["paid_work"]["forward_calls"] for x in (dev_meta, run_meta)),
        "sum_backward_calls": sum(x["paid_work"]["backward_calls"] for x in (dev_meta, run_meta)),
        "sum_forward_input_tokens": sum(x["paid_work"]["forward_input_tokens"] for x in (dev_meta, run_meta)),
        "sum_load_plus_diagnostic_wall_ns": sum(x["model_and_adapter_load_wall_ns"] + x["diagnostic_elapsed_wall_ns"]
                                                for x in (dev_meta, run_meta)),
        "checkpoint": "Qwen3-4B", "runtime": actual["runtime"],
        "reference_gram": actual["reference_gram"], "reference_cosine": actual["reference_cosine"],
        "reference_probe_stability": {a: {k: v[k] for k in ("probe_cosine", "probe_relative_l2", "status")}
                                      for a, v in actual["reference_anchors"].items()},
        "weight_summary": {a: actual["branches"][a]["weight_summary"] for a in ARMS},
        "train_teacher_tokens": actual["train_support_count"],
        "max_observed_initial_spread_nats_per_target_token": max(x["observed_initial_spread"] for x in gate["rows"]),
        "base_positive_margin_by_role": {r: sum(x["initial"]["sequence_nats"] > 0 for x in rows)
                                         for r, rows in roles.items()},
        "metrics": results, "joint_e_wins": gate["joint_e_wins"], "absolute_wc_harms": gate["absolute_wc_harms"],
        "scope": "Controlled paired teacher-forced margins, no free-generation final accuracy or natural update. "
                 "GPU load and diagnostic walls are measured. Host staging and source preparation are separate.",
    }
    raw = (json.dumps(summary, indent=2, allow_nan=False) + "\n").encode()
    with (HERE / "D50_CONTROLLED_GPU_SUMMARY.json").open("xb") as stream:
        stream.write(raw)
    print(sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
