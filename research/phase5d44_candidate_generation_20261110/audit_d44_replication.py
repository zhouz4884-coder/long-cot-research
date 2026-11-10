"""Independently verify D4.4 archival coverage and the live preregistration bindings."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(path: Path) -> str:
    return sha(path.read_bytes())


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def prior_assets(plan: dict) -> None:
    for key, path in (
        ("d43_cohort_sha256", D43 / "D43_COHORT_FREEZE.json"),
        ("d43_readout_sha256", D43 / "D43_MACHINE_READOUT_FREEZE.json"),
        ("d43_scored_historical_sha256", D43 / "D43_SCORED_RESULTS.json"),
        ("d43_extractor_sha256", D43 / "extract_candidates.py"),
    ):
        relative = path.relative_to(ROOT).as_posix()
        original = subprocess.check_output(["git", "show", f'{plan["baseline_commit"]}:{relative}'], cwd=ROOT)
        assert sha(original) == digest(path) == plan[key], relative


def load_labels(source: Path, plan: dict, receipt: dict, fresh: dict) -> dict[str, frozenset[int]]:
    assert digest(source / "PUBLICATION_MANIFEST.json") == plan["upstream_manifest_sha256"]
    assert set(p.name for p in (source / "data").glob("draw-*.parquet")) == {
        f"draw-{draw:02}.parquet" for draw in range(4, 8)
    }
    expected = {row["sample_id"]: row for row in fresh["rows"]}
    question_ids = {row["problem_id"] for row in expected.values()}
    reference = {row["problem_id"]: row for row in receipt["cohort_identity"]["rows"]}
    assert set(reference) == question_ids and len(question_ids) == 32 and len(expected) == 128
    accepted = {}
    for draw, asset in zip(range(4, 8), plan["replication_expected_shards"], strict=True):
        path = source / asset["path"]
        assert path.name == f"draw-{draw:02}.parquet"
        assert path.stat().st_size == asset["size"] and digest(path) == asset["sha256"]
        assert pq.ParquetFile(path).metadata.num_rows == 480
        columns = ["problem_id", "sample_id", "draw_index", "seed", "response_sha256", "model_id",
                   "model_revision", "contract_sha256", "input_tokens", "output_tokens",
                   "cap_hit", "finish_reason", "accepted_answer_integers"]
        records = pq.read_table(path, columns=columns,
                                filters=[("problem_id", "in", sorted(question_ids))]).to_pylist()
        assert len(records) == 32 and {row["problem_id"] for row in records} == question_ids
        for raw in records:
            pid, sid = raw["problem_id"], raw["sample_id"]
            sample = expected[sid]
            assert raw["seed"] == 1234 + 480 * draw + reference[pid]["eval_index"]
            assert raw["draw_index"] == draw and raw["model_id"] == receipt["model"]["id"]
            assert raw["model_revision"] == receipt["model"]["revision"]
            assert raw["contract_sha256"] == plan["upstream_generation_contract_sha256"]
            assert all(sample[key] == raw[key] for key in (
                "problem_id", "draw_index", "seed", "response_sha256", "input_tokens", "output_tokens",
            ))
            assert raw["cap_hit"] == (sample["termination"] == "LENGTH_CAP")
            assert (raw["finish_reason"] == "stop") == (sample["termination"] == "NATIVE_STOP")
            values = frozenset(raw["accepted_answer_integers"])
            assert values and all(type(v) is int and 0 <= v <= 999 for v in values)
            assert accepted.setdefault(pid, values) == values
    assert len(accepted) == 32
    return accepted


def summarize(rows: list[dict], labels: dict) -> dict:
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda item: item["draw_index"]):
        groups[row["problem_id"]].append(row)
    coverage, majority, first, states = set(), set(), {}, Counter()
    for pid, group in groups.items():
        values = []
        for row in group:
            if row["termination"] != "NATIVE_STOP":
                states["cap"] += 1
                continue
            value = row["final"]["value"]
            if value is None:
                states["native_missing"] += 1
                continue
            values.append(value)
            if value in labels[pid]:
                states["native_correct"] += 1
                coverage.add(pid)
                first.setdefault(pid, row["draw_index"])
            else:
                states["native_wrong"] += 1
        if values and Counter(values).most_common(1)[0][0] in labels[pid]:
            majority.add(pid)
    return {
        "coverage_ids": sorted(coverage), "majority_ids": sorted(majority), "first_correct": first,
        "terminal_counts": dict(states), "rows": len(rows),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
    }


def audit(source: Path) -> dict:
    files = {key: HERE / name for key, name in (
        ("acquisition", "D44_ACQUISITION_FREEZE.json"), ("source_receipt", "D44_SOURCE_RECEIPT.json"),
        ("readout", "D44_READOUT_FREEZE.json"), ("score", "D44_REPLICATION_RESULTS.json"),
        ("trigger_gate", "D44_ARCHIVE_TRIGGER_REPLAY_V2.json"),
        ("stage", "D44_LIVE_STAGE_FREEZE.json"), ("launch", "D44_GPU_MAIN_LAUNCH.json"),
    )}
    plan, receipt, fresh, scored, trigger, stage, launch = map(load, files.values())
    prior_assets(plan)
    for key in ("acquisition", "source_receipt", "readout"):
        assert scored["input_sha256"][key] == digest(files[key])
    assert fresh["acquisition_freeze_sha256"] == digest(files["acquisition"])
    assert fresh["source_receipt_sha256"] == digest(files["source_receipt"])
    assert fresh["status"] == "D44_NEW_DRAW_READOUTS_FROZEN_WITHOUT_GOLD"
    labels = load_labels(source, plan, receipt, fresh)
    old = load(D43 / "D43_MACHINE_READOUT_FREEZE.json")["rows"]
    blocks = {"historical": old, "replication": fresh["rows"], "merged": [*old, *fresh["rows"]]}
    independently_counted = {key: summarize(rows, labels) for key, rows in blocks.items()}
    for key, block in independently_counted.items():
        target = scored["blocks"][key]
        assert target["observed_draw_count"] == block["rows"]
        assert target["native_final_coverage"] == len(block["coverage_ids"])
        assert target["native_final_majority_correct"] == len(block["majority_ids"])
        assert target["observed_input_tokens"] == block["input_tokens"]
        assert target["observed_output_tokens"] == block["output_tokens"]
        recorded = scored["rows"]
        assert {r["problem_id"]: r[key]["earliest_correct_native_draw"] for r in recorded
                if r[key]["native_final_coverage"]} == block["first_correct"]
    misses = sorted(set(labels) - set(independently_counted["merged"]["coverage_ids"]))
    assert misses == sorted(scored["historical_misses"])
    assert trigger["independent_development_problems_triggered"] >= 2
    assert trigger["sources"]["trigger_sha256"] == digest(HERE / "obligation_trigger.py")
    assert launch["live_stage_freeze_sha256"] == digest(files["stage"])
    assert launch["live_runner_sha256"] == stage["live_runner_sha256"] == digest(HERE / "d44_native_runner.py")
    assert stage["scorer_sha256"] == digest(HERE / "score_live.py")
    return {
        "status": "ARCHIVE_RESULTS_AND_LIVE_LAUNCH_RECONCILED",
        "blocks": independently_counted, "persistent_missing_problem_ids": misses,
        "independent_archival_gate_questions": trigger["independent_development_problems_triggered"],
        "evidence_sha256": {key: digest(path) for key, path in files.items()},
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    report = audit(args.source)
    if args.output:
        with args.output.open("xb") as stream:
            stream.write((json.dumps(report, indent=2) + "\n").encode())
    print(report["status"], {key: len(block["coverage_ids"]) for key, block in report["blocks"].items()})


if __name__ == "__main__":
    main()
