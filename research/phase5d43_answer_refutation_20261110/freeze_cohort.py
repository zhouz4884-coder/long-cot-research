"""Freeze D4.3 from provenance columns and prepare a separate label-blind view."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import pyarrow.parquet as pq


BASELINE = "e609dafe1cd44eaf03f5ff777c216294db95f2d9"
REVISION = "c34143c92856d9b90fdb9c808c7e66070dcab9a1"
MANIFEST_SHA256 = "f1b27b3528a8f6d8b23db46d394bade22067bdbae973d87f9bb5182746f86453"
MODEL_ID = "Qwen/Qwen3-8B"
MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
SALT = "long-cot-d43-aime-2009-2023-pilot-v1"
DRAWS = (0, 1, 2, 3)
SAMPLE_COUNT = 32
IDENTITY_COLUMNS = (
    "problem_id", "year", "part", "problem_number", "eval_index", "problem",
)
RECEIPT_COLUMNS = (
    "problem_id", "eval_index", "draw_index", "sample_id", "seed",
    "response_sha256", "model_id", "model_revision", "contract_sha256",
)
BLIND_COLUMNS = (
    *RECEIPT_COLUMNS, "problem", "response", "finish_reason", "stop_condition",
    "stop_token_id", "cap_hit", "input_tokens", "output_tokens", "effective_max_new_tokens",
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def question_digest(question: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", question)).strip().casefold()
    return digest(normalized.encode())


def cohort_key(problem_id: str) -> str:
    return digest(f"{SALT}\0{problem_id}".encode())


def write_exclusive(path: Path, value: dict) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)


def load_shards(source: Path) -> tuple[dict, dict]:
    raw = (source / "PUBLICATION_MANIFEST.json").read_bytes()
    if digest(raw) != MANIFEST_SHA256:
        raise ValueError("Pinned upstream manifest bytes differ")
    manifest = json.loads(raw)
    indexed = {row["path"]: row for row in manifest["files"]}
    shards = {}
    for draw in DRAWS:
        path = f"data/draw-{draw:02}.parquet"
        record = indexed[path]
        data = (source / path).read_bytes()
        if len(data) != record["size"] or digest(data) != record["sha256"]:
            raise ValueError(f"Pinned shard bytes differ: {path}")
        parquet = pq.ParquetFile(source / path)
        if parquet.metadata.num_rows != 480:
            raise ValueError(f"Unexpected row count: {path}")
        shards[draw] = parquet
    return manifest, shards


def read_projected(shard, columns: tuple[str, ...]) -> list[dict]:
    return shard.read(columns=list(columns)).to_pylist()


def lock_selection(source: Path, exclusions_path: Path) -> dict:
    manifest, shards = load_shards(source)
    exclusions_bytes = exclusions_path.read_bytes()
    exclusions = json.loads(exclusions_bytes)
    excluded_ids = set(exclusions["excluded_problem_ids"])
    excluded_questions = set(exclusions["normalized_question_sha256"])
    identities = read_projected(shards[0], IDENTITY_COLUMNS)
    if len({row["problem_id"] for row in identities}) != 480:
        raise ValueError("Pinned source does not contain one draw row per problem")
    cohort = []
    counts = {"source": len(identities), "outside_years": 0, "development_match": 0, "duplicate": 0}
    seen_questions = set()
    for row in sorted(identities, key=lambda row: (cohort_key(row["problem_id"]), row["problem_id"])):
        problem = row.pop("problem")
        pid = row["problem_id"]
        if pid != f'{row["year"]}-{row["part"]}-{row["problem_number"]}':
            raise ValueError(f"Unexpected canonical problem identity: {pid}")
        if not 2009 <= row["year"] <= 2023:
            counts["outside_years"] += 1
            continue
        qhash = question_digest(problem)
        if pid in excluded_ids or qhash in excluded_questions:
            counts["development_match"] += 1
            continue
        if qhash in seen_questions:
            counts["duplicate"] += 1
            continue
        seen_questions.add(qhash)
        cohort.append({**row, "normalized_question_sha256": qhash, "samples": []})
    if len(cohort) < SAMPLE_COUNT:
        raise ValueError("The approved source is too small for the frozen cohort")
    selected = {row["problem_id"]: row for row in cohort[:SAMPLE_COUNT]}
    for draw, shard in shards.items():
        rows = read_projected(shard, RECEIPT_COLUMNS)
        ids = {row["problem_id"]: row for row in rows}
        if len(ids) != 480 or set(ids) != {row["problem_id"] for row in identities}:
            raise ValueError(f"Missing or duplicate problem in draw {draw}")
        for pid, row in selected.items():
            sample = ids[pid]
            check_identity(row, sample, draw, manifest["contract_sha256"])
            row["samples"].append({key: sample[key] for key in (
                "draw_index", "sample_id", "seed", "response_sha256",
            )})
    if len({sample["sample_id"] for row in selected.values() for sample in row["samples"]}) != 128:
        raise ValueError("Selected sample IDs must be unique")
    return {
        "status": "FROZEN_FROM_IDENTITY_COLUMNS_WITHOUT_RESPONSES_OR_GOLD",
        "baseline_commit": BASELINE,
        "source_revision": REVISION,
        "publication_manifest_sha256": MANIFEST_SHA256,
        "contract_sha256": manifest["contract_sha256"],
        "model": {"id": MODEL_ID, "revision": MODEL_REVISION},
        "exclusions_sha256": digest(exclusions_bytes),
        "draws": DRAWS,
        "sampling_salt": SALT,
        "sampling_order": "ascending SHA-256 of salt + U+0000 + canonical problem ID",
        "exclusion_counts": counts,
        "eligible_unique": len(cohort),
        "selected": list(selected.values()),
    }


def check_identity(problem: dict, sample: dict, draw: int, contract: str) -> None:
    index = problem["eval_index"]
    if (
        sample["draw_index"] != draw or sample["eval_index"] != index
        or sample["seed"] != 1234 + 480 * draw + index
        or sample["model_id"] != MODEL_ID or sample["model_revision"] != MODEL_REVISION
        or sample["contract_sha256"] != contract
    ):
        raise ValueError(f"Run identity differs for {problem['problem_id']} draw {draw}")


def materialize(source: Path, freeze_path: Path) -> dict:
    raw = freeze_path.read_bytes()
    freeze = json.loads(raw)
    if freeze["status"] != "FROZEN_FROM_IDENTITY_COLUMNS_WITHOUT_RESPONSES_OR_GOLD":
        raise ValueError("Missing identity-only selection freeze")
    if freeze["source_revision"] != REVISION or freeze["draws"] != list(DRAWS):
        raise ValueError("Cohort source changed")
    manifest, shards = load_shards(source)
    selected = {row["problem_id"]: row for row in freeze["selected"]}
    if len(selected) != SAMPLE_COUNT:
        raise ValueError("Wrong frozen question count")
    blind = []
    for draw, shard in shards.items():
        for sample in read_projected(shard, BLIND_COLUMNS):
            pid = sample["problem_id"]
            if pid not in selected:
                continue
            problem = selected[pid]
            check_identity(problem, sample, draw, manifest["contract_sha256"])
            expected, = (row for row in problem["samples"] if row["draw_index"] == draw)
            if any(sample[key] != value for key, value in expected.items()):
                raise ValueError(f"Frozen sample changed: {pid}, draw {draw}")
            if question_digest(sample["problem"]) != problem["normalized_question_sha256"]:
                raise ValueError(f"Problem text changed: {pid}, draw {draw}")
            if digest(sample["response"].encode()) != expected["response_sha256"]:
                raise ValueError(f"Response integrity failed: {pid}, draw {draw}")
            blind.append(sample)
    if len(blind) != SAMPLE_COUNT * len(DRAWS):
        raise ValueError("Incomplete blind view")
    return {"cohort_freeze_sha256": digest(raw), "rows": blind}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "materialize"))
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--exclusions", type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--local-blind-output", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        if args.exclusions is None:
            parser.error("--exclusions is required")
        write_exclusive(args.freeze, lock_selection(args.sources, args.exclusions))
    else:
        if args.local_blind_output is None:
            parser.error("--local-blind-output is required")
        repo = Path(__file__).resolve().parents[2]
        if not args.local_blind_output.resolve().is_relative_to(repo / "outputs"):
            parser.error("Store raw trace material only in the local outputs folder")
        write_exclusive(args.local_blind_output, materialize(args.sources, args.freeze))


if __name__ == "__main__":
    main()
