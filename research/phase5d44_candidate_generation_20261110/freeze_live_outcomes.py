"""Freeze exact completed GPU artifacts before opening live-pilot labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def freeze(lab: Path) -> dict:
    launch_path = HERE / "D44_GPU_MAIN_LAUNCH.json"
    stage_path = HERE / "D44_LIVE_STAGE_FREEZE.json"
    rules_path = HERE / "D44_LIVE_RULE_FREEZE.json"
    inputs_path = HERE / "D44_LIVE_INPUT_FREEZE_V2.json"
    cohort_path = HERE / "D44_LIVE_COHORT_FREEZE.json"
    scorer_path = HERE / "score_live.py"
    launch, stage, inputs = map(load, (launch_path, stage_path, inputs_path))
    root = lab / "main_raw_results"
    retrieval_path = root / "retrieval_receipt.json"
    retrieval = load(retrieval_path)
    if (
        retrieval["status"] != "BOTH_TERMINAL_WORKERS_RETRIEVED_WITHOUT_LABELS"
        or launch["live_stage_freeze_sha256"] != sha(stage_path)
        or launch["full_packet_sha256"] != stage["full_packet_sha256"]
        or stage["live_inputs_sha256"] != sha(inputs_path) or stage["rule_sha256"] != sha(rules_path)
        or stage["scorer_sha256"] != sha(scorer_path)
        or inputs["cohort_freeze_sha256"] != sha(cohort_path)
        or launch["private_process_receipt_sha256"] != retrieval["private_launch_receipt_sha256"]
    ):
        raise ValueError("Retrieval, launch and preregistration identities disagree")
    if len(retrieval["workers"]) != 2:
        raise ValueError("Expected both workers to complete")
    workers = []
    all_ids = []
    for index, record in enumerate(retrieval["workers"]):
        folder = root / f"worker_{index}"
        manifest, summary = load(folder / "manifest.json"), load(folder / "summary.json")
        bound = stage["workers"][index]
        if (
            record["worker"] != index or manifest["worker"] != index
            or record["terminal_status"] != "COMPLETE" or summary["status"] != "COMPLETE"
            or record["runtime_freeze_sha256"] != bound["runtime_freeze_sha256"]
            or record["packet_sha256"] != bound["staged_packet_sha256"]
            or manifest["runtime_freeze_sha256"] != bound["runtime_freeze_sha256"]
            or manifest["shard_packet_sha256"] != bound["staged_packet_sha256"]
            or manifest["full_packet_sha256"] != stage["full_packet_sha256"]
            or record["manifest_sha256"] != sha(folder / "manifest.json")
            or record["summary_sha256"] != sha(folder / "summary.json")
            or [item["case_id"] for item in record["cases"]] != bound["case_ids"]
            or manifest["case_ids"] != bound["case_ids"]
            or [item["case_id"] for item in summary["cases"]] != bound["case_ids"]
        ):
            raise ValueError(f"Worker {index} did not complete its exact staged cases")
        for item in record["cases"]:
            case_id = item["case_id"]
            case_folder = folder / case_id
            if sha(case_folder / "result.json") != item["result_sha256"]:
                raise ValueError(f"Raw outcome bytes changed for {case_id}")
            if "checkpoint_logits_sha256" in item and sha(
                case_folder / "checkpoint_logits.f32le"
            ) != item["checkpoint_logits_sha256"]:
                raise ValueError(f"Raw checkpoint bytes changed for {case_id}")
            all_ids.append(case_id)
        workers.append({key: record[key] for key in (
            "worker", "runtime_freeze_sha256", "packet_sha256", "manifest_sha256", "summary_sha256", "cases",
        )})
    if sorted(all_ids) != sorted(row["case_id"] for row in inputs["rows"]) or len(set(all_ids)) != 8:
        raise ValueError("Worker outcome denominator differs from the original live cohort")
    smoke = lab / "smoke_v2" / "raw_results" / "summary.json"
    safe_smoke = load(HERE / "D44_NATIVE_SMOKE_SAFE_SUMMARY.json")
    if load(smoke)["status"] != "PASS" or sha(smoke) != safe_smoke["v2_exact_replay_and_bridge"]["raw_summary_sha256"]:
        raise ValueError("Real matched-bridge smoke source differs")
    return {
        "status": "TWO_COMPLETE_WORKER_OUTCOMES_FROZEN_BEFORE_GOLD",
        "rule_freeze_sha256": sha(rules_path), "cohort_freeze_sha256": sha(cohort_path),
        "input_freeze_sha256": sha(inputs_path), "live_stage_freeze_sha256": sha(stage_path),
        "launch_sha256": sha(launch_path), "raw_retrieval_receipt_sha256": sha(retrieval_path),
        "smoke_sha256": sha(smoke), "independent_questions": len(all_ids), "workers": workers,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lab", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    report = freeze(args.lab)
    with args.output.open("xb") as stream:
        stream.write((json.dumps(report, indent=2) + "\n").encode())
    print(report["status"], sha(args.output))


if __name__ == "__main__":
    main()
