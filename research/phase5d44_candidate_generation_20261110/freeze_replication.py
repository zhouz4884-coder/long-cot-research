"""Apply the frozen D4.3 readout to a hash-bound, label-free D4.4 sample projection."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter_ns, thread_time_ns

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
sys.path.insert(0, str(D43))

from extract_candidates import AUTHOR_SCORER_SHA, extract_row, load_author_scorer
from freeze_cohort import BLIND_COLUMNS, check_identity, digest, question_digest, write_exclusive


GENERATION_COLUMNS = (
    "generation_parameters_json", "rendered_prompt_sha256", "source_record_sha256",
)


def verified_json(path: Path, expected: str) -> dict:
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError(f"Frozen bytes changed: {path.name}")
    return json.loads(raw)


def locked_sources(source: Path, plan: dict, receipt: dict) -> dict:
    if plan["replication_draws"] != [4, 5, 6, 7] or receipt["draws"] != [4, 5, 6, 7]:
        raise ValueError("Only draws 4–7 are authorized for this replication")
    manifest = verified_json(source / "PUBLICATION_MANIFEST.json", plan["upstream_manifest_sha256"])
    indexed = {row["path"]: row for row in manifest["files"]}
    if manifest["contract_sha256"] != plan["upstream_generation_contract_sha256"]:
        raise ValueError("Generation contract changed")
    checks = {row["path"]: row for row in receipt["shards"]}
    if receipt["source"]["revision"] != plan["source_revision"]:
        raise ValueError("Source revision changed")
    for row in plan["replication_expected_shards"]:
        name = row["path"]
        raw = (source / name).read_bytes()
        external = checks[name]
        if (
            indexed[name] != row or external["sha256"] != row["sha256"]
            or len(raw) != row["size"] or digest(raw) != row["sha256"]
            or pq.ParquetFile(source / name).metadata.num_rows != 480
        ):
            raise ValueError(f"Wrong pinned replication shard: {name}")
    return manifest


def project(source: Path, plan: dict, receipt: dict, cohort: dict, questions: dict) -> list[dict]:
    manifest = locked_sources(source, plan, receipt)
    cohort_rows = {row["problem_id"]: row for row in cohort["selected"]}
    sources = {row["problem_id"]: row for row in receipt["cohort_identity"]["rows"]}
    if set(sources) != set(cohort_rows) or set(questions) != set(cohort_rows) or len(sources) != 32:
        raise ValueError("Replication questions differ from the frozen D4.3 cohort")
    by_sample = {s["sample_id"]: s for row in sources.values() for s in row["samples"]}
    selected = []
    for draw in plan["replication_draws"]:
        shard = source / f"data/draw-{draw:02}.parquet"
        rows = pq.read_table(shard, columns=[*BLIND_COLUMNS, *GENERATION_COLUMNS],
                             filters=[("problem_id", "in", list(cohort_rows))]).to_pylist()
        if len(rows) != 32 or {row["problem_id"] for row in rows} != set(cohort_rows):
            raise ValueError(f"Wrong filtered replication cohort in draw {draw}")
        for sample in rows:
            pid = sample["problem_id"]
            prior = cohort_rows[pid]
            external = sources[pid]
            check_identity(prior, sample, draw, manifest["contract_sha256"])
            if (
                sample["problem"] != questions[pid]
                or question_digest(sample["problem"]) != prior["normalized_question_sha256"]
                or digest(sample["response"].encode()) != sample["response_sha256"]
                or json.loads(sample["generation_parameters_json"]) != receipt["generation_contract"]["parameters"]
                or sample["rendered_prompt_sha256"] != external["rendered_prompt_sha256"]
                or sample["source_record_sha256"] != external["source_record_sha256"]
                or sample["input_tokens"] + sample["effective_max_new_tokens"] != 32768
                or not 0 <= sample["output_tokens"] <= sample["effective_max_new_tokens"]
                or (sample["cap_hit"] and sample["output_tokens"] != sample["effective_max_new_tokens"])
            ):
                raise ValueError(f"Wrong question, response or generation metadata in {pid} draw {draw}")
            identity = by_sample[sample["sample_id"]]
            if any(sample[key] != value for key, value in identity.items()):
                raise ValueError(f"Replication sample differs from its identity receipt: {pid}")
            selected.append({key: sample[key] for key in BLIND_COLUMNS})
    if len(selected) != plan["replication_expected_rows"] or len({r["sample_id"] for r in selected}) != len(selected):
        raise ValueError("Wrong number of distinct replication samples")
    return selected


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "d43-source", "acquisition", "receipt", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--local-blind-output", type=Path, required=True)
    args = cli.parse_args()
    if not args.local_blind_output.resolve().is_relative_to(HERE.parents[1] / "outputs"):
        cli.error("The projection containing raw text must stay in the local outputs directory")
    if args.output.exists() or args.local_blind_output.exists():
        cli.error("Refuse to replace an existing freeze or blind projection")
    plan_bytes, receipt_bytes = args.acquisition.read_bytes(), args.receipt.read_bytes()
    plan, receipt = json.loads(plan_bytes), json.loads(receipt_bytes)
    cohort = verified_json(D43 / "D43_COHORT_FREEZE.json", plan["d43_cohort_sha256"])
    intake = json.loads((D43 / "D43_PILOT_INTAKE.json").read_bytes())
    question_only = verified_json(args.d43_source / "d43_question_only.json", intake["question_only_view_sha256"])
    questions = {row["problem_id"]: row["question"] for row in question_only["questions"]}
    if digest((D43 / "extract_candidates.py").read_bytes()) != plan["d43_extractor_sha256"]:
        raise ValueError("Frozen D.4.3 readout code changed")
    scorer = load_author_scorer(args.d43_source / "aime_scorer.py")
    started = perf_counter_ns()
    samples = project(args.source, plan, receipt, cohort, questions)
    materialization_wall = perf_counter_ns() - started
    write_exclusive(args.local_blind_output, {
        "cohort_freeze_sha256": plan["d43_cohort_sha256"], "draws": plan["replication_draws"], "rows": samples,
    })
    wall, cpu = perf_counter_ns(), thread_time_ns()
    rows = [extract_row(scorer, sample) for sample in samples]
    result = {
        "status": "D44_NEW_DRAW_READOUTS_FROZEN_WITHOUT_GOLD",
        "cohort_freeze_sha256": plan["d43_cohort_sha256"],
        "acquisition_freeze_sha256": digest(plan_bytes), "source_receipt_sha256": digest(receipt_bytes),
        "blind_input_sha256": digest(args.local_blind_output.read_bytes()),
        "extractor_sha256": plan["d43_extractor_sha256"], "author_parser_sha256": AUTHOR_SCORER_SHA,
        "intake_code_sha256": digest(Path(__file__).read_bytes()),
        "draws": plan["replication_draws"],
        "cost": {"materialization_wall_ns": materialization_wall, "wall_ns": perf_counter_ns() - wall,
                 "cpu_ns": thread_time_ns() - cpu},
        "termination_counts": dict(Counter(r["termination"] for r in rows)),
        "thinking_readout_counts": dict(Counter(r["thinking"]["status"] for r in rows)),
        "final_readout_counts": dict(Counter(r["final"]["status"] for r in rows)),
        "rows": rows,
    }
    write_exclusive(args.output, result)
    print(result["status"], result["termination_counts"], result["final_readout_counts"])


if __name__ == "__main__":
    main()
