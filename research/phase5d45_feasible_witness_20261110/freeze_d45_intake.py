"""Freeze question-only D4.5 identities, then materialize a separate label-blind view."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns, thread_time_ns

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
D44 = HERE.parent / "phase5d44_candidate_generation_20261110"
sys.path.insert(0, str(D43))
from freeze_cohort import BLIND_COLUMNS, check_identity, digest, question_digest, write_exclusive
from d45_problem_specs import PROBLEMS


DRAWS = tuple(range(8))
MODEL_PARAMETERS = {"enable_thinking": True, "min_p": 0.0, "temperature": 0.6, "top_k": 20, "top_p": 0.95}
METADATA = ("problem_id", "eval_index", "draw_index", "sample_id", "seed", "response_sha256",
            "model_id", "model_revision", "contract_sha256", "generation_parameters_json",
            "rendered_prompt_sha256", "source_record_sha256")


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def sha(path: Path) -> str:
    return digest(path.read_bytes())


def check_prior() -> dict:
    record = load(HERE / "D45_BASELINE_FREEZE.json")
    for name, expected in record["d44_evidence_sha256"].items():
        path = D44 / name
        frozen = subprocess.check_output(
            ["git", "show", f'{record["baseline_commit"]}:{path.relative_to(ROOT).as_posix()}'], cwd=ROOT,
        )
        if digest(frozen) != expected or sha(path) != expected:
            raise ValueError(f"Prior D4.4 freeze changed: {name}")
    return record


def verified_shards(old: Path, new: Path) -> tuple[dict, dict[int, Path], list[dict]]:
    manifest = load(old / "PUBLICATION_MANIFEST.json")
    pinned = load(D44 / "D44_ACQUISITION_FREEZE.json")
    expected = pinned["upstream_manifest_sha256"]
    if sha(old / "PUBLICATION_MANIFEST.json") != expected or sha(new / "PUBLICATION_MANIFEST.json") != expected:
        raise ValueError("Archive publication manifest changed")
    assets = {row["path"]: row for row in manifest["files"]}
    paths, readback = {}, []
    for draw in DRAWS:
        name = f"data/draw-{draw:02}.parquet"
        asset = assets[name]
        path = (old if draw <= 3 else new) / name
        if path.stat().st_size != asset["size"] or sha(path) != asset["sha256"]:
            raise ValueError(f"Archive shard byte mismatch: {name}")
        if pq.ParquetFile(path).metadata.num_rows != 480:
            raise ValueError(f"Archive shard row mismatch: {name}")
        paths[draw] = path
        readback.append({**asset, "draw": draw})
    return manifest, paths, readback


def project(path: Path, fields: tuple[str, ...], ids: list[str]) -> list[dict]:
    return pq.read_table(path, columns=list(fields), filters=[("problem_id", "in", ids)]).to_pylist()


def freeze(old: Path, new: Path, local: Path, output: Path) -> dict:
    begin_wall, begin_cpu = perf_counter_ns(), thread_time_ns()
    baseline = check_prior()
    manifest, paths, assets = verified_shards(old, new)
    scope_path = HERE / "D45_QUESTION_SCOPE_AUDIT.json"
    scope = load(scope_path)
    proposed = {row["case_id"]: row for row in scope["nominated"]}
    if set(proposed) != set(PROBLEMS) or len(PROBLEMS) != 11:
        raise ValueError("Question-only selection did not freeze the reviewed eleven cases")
    ids = sorted(PROBLEMS)
    fields = ("problem_id", "problem", "eval_index", "rendered_prompt_sha256", "source_record_sha256")
    original = {row["problem_id"]: row for row in project(paths[0], fields, ids)}
    if set(original) != set(ids):
        raise ValueError("Missing original question projection")
    selected, visible = {}, []
    for cid in ids:
        row = original[cid]
        text = row["problem"]
        direct_sha = digest(text.encode())
        normalized_sha = question_digest(text)
        if (direct_sha, normalized_sha) != (
            proposed[cid]["exact_question_sha256"], proposed[cid]["normalized_question_sha256"],
        ):
            raise ValueError(f"Question wording differs from the question-only audit: {cid}")
        item = {
            "case_id": cid, "question_sha256": direct_sha, "normalized_question_sha256": normalized_sha,
            "eval_index": row["eval_index"], "rendered_prompt_sha256": row["rendered_prompt_sha256"],
            "source_record_sha256": row["source_record_sha256"], "draws": [], **PROBLEMS[cid],
        }
        selected[cid] = item
        visible.append({"case_id": cid, "question": text, "question_sha256": direct_sha, **PROBLEMS[cid]})
    for draw, path in paths.items():
        records = project(path, METADATA, ids)
        if len(records) != len(ids) or {row["problem_id"] for row in records} != set(ids):
            raise ValueError(f"Duplicate or absent source sample in draw {draw}")
        for sample in records:
            cid = sample["problem_id"]
            question = selected[cid]
            check_identity(question, sample, draw, manifest["contract_sha256"])
            if json.loads(sample["generation_parameters_json"]) != MODEL_PARAMETERS:
                raise ValueError("Source generation parameters changed")
            if any(sample[k] != question[k] for k in ("rendered_prompt_sha256", "source_record_sha256")):
                raise ValueError("Source problem identity changed across draws")
            question["draws"].append({k: sample[k] for k in ("draw_index", "sample_id", "seed", "response_sha256")})
    write_exclusive(local, {"status": "QUESTION_ONLY_NO_LABELS_OR_TRACE_CONTENT", "rows": visible})
    frozen = {
        "status": "D45_ELEVEN_QUESTION_IDENTITIES_FROZEN_BEFORE_TRACE_OR_GOLD",
        "baseline_commit": baseline["baseline_commit"], "source_revision": scope["source"]["revision"],
        "upstream_manifest_sha256": sha(old / "PUBLICATION_MANIFEST.json"),
        "generation_contract_sha256": manifest["contract_sha256"], "source_shards": assets,
        "scope_audit_sha256": sha(scope_path), "observation_rules_sha256": sha(HERE / "D45_OBSERVATION_RULES.json"),
        "problem_specs_sha256": sha(HERE / "d45_problem_specs.py"),
        "checker_sha256": sha(HERE / "d45_arithmetic_checker.py"),
        "question_only_sha256": sha(local), "selected_question_count": len(ids),
        "planned_draw_count": len(DRAWS), "planned_trace_count": len(ids) * len(DRAWS),
        "rows": [selected[cid] for cid in ids],
        "intake_wall_ns": perf_counter_ns() - begin_wall, "intake_cpu_ns": thread_time_ns() - begin_cpu,
    }
    write_exclusive(output, frozen)
    return frozen


def materialize(old: Path, new: Path, freeze_path: Path, output: Path) -> dict:
    cohort = load(freeze_path)
    manifest, paths, readback = verified_shards(old, new)
    if cohort["source_shards"] != readback or cohort["planned_trace_count"] != 88:
        raise ValueError("Blind projection differs from the frozen cohort")
    selected = {row["case_id"]: row for row in cohort["rows"]}
    ids = list(selected)
    rows = []
    for draw, path in paths.items():
        samples = project(path, BLIND_COLUMNS, ids)
        if len(samples) != len(ids) or {s["problem_id"] for s in samples} != set(ids):
            raise ValueError("Unexpected blind projection count")
        for sample in samples:
            question = selected[sample["problem_id"]]
            check_identity(question, sample, draw, manifest["contract_sha256"])
            frozen, = (r for r in question["draws"] if r["draw_index"] == draw)
            if any(sample[k] != v for k, v in frozen.items()):
                raise ValueError("Sample differs from the metadata-only freeze")
            if digest(sample["problem"].encode()) != question["question_sha256"]:
                raise ValueError("Question changed")
            if digest(sample["response"].encode()) != sample["response_sha256"]:
                raise ValueError("Source response bytes changed")
            if (sample["input_tokens"] + sample["effective_max_new_tokens"] != 32768
                    or not 0 <= sample["output_tokens"] <= sample["effective_max_new_tokens"]
                    or (sample["cap_hit"] and sample["output_tokens"] != sample["effective_max_new_tokens"])):
                raise ValueError("Source token budget metadata changed")
            rows.append(sample)
    record = {"cohort_freeze_sha256": sha(freeze_path), "draws": list(DRAWS), "rows": rows}
    write_exclusive(output, record)
    return record


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("freeze", "materialize"))
    for option in ("old-source", "new-source", "freeze", "local"):
        cli.add_argument("--" + option, type=Path, required=True)
    args = cli.parse_args()
    if not args.local.resolve().is_relative_to(ROOT / "outputs"):
        cli.error("Raw wording and generation content stay under outputs")
    if args.mode == "freeze":
        out = freeze(args.old_source, args.new_source, args.local, args.freeze)
        print(out["status"], out["planned_trace_count"])
    else:
        out = materialize(args.old_source, args.new_source, args.freeze, args.local)
        print("D45_LABEL_BLIND_TRACE_PROJECTION", len(out["rows"]), sha(args.local))


if __name__ == "__main__":
    main()
