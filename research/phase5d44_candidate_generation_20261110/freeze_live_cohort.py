"""Choose eight independent AIME problems using question-only scope predicates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
sys.path.insert(0, str(D43))
from freeze_cohort import digest, question_digest, write_exclusive


SALT = "long-cot-d44-native-constraint-pilot-v1"
DRAW0_SHA256 = "5da6ef58914d22c60659e7e21266f4530021993014d8af6cebe1a640d137c787"
FIRST_EVENT = re.compile(r"\b(?:first time|earliest time|first (?:meet|occur|happen|return|reach))\b", re.I)
EXTREMUM = re.compile(
    r"\b(?:find|determine|what is|compute|give)\b[^.!?]{0,220}"
    r"\b(?:maximum|minimum|largest|smallest|greatest|least)\b",
    re.I,
)


def key(pid: str, label: str) -> str:
    return digest(f"{SALT}\0{label}\0{pid}".encode())


def classify(row: dict) -> tuple[str, str] | None:
    q, number = row["problem"], row["problem_number"]
    if 4 <= number <= 14 and FIRST_EVENT.search(q):
        return "FIRST_EVENT", "first-event"
    tail = " ".join(re.split(r"[.!?]\s+", q)[-2:])
    if 5 <= number <= 13 and EXTREMUM.search(tail):
        return "EXTREMUM", "extremum-medium" if number <= 9 else "extremum-late"
    return None


def freeze(shard: Path) -> tuple[dict, list[dict]]:
    if digest(shard.read_bytes()) != DRAW0_SHA256:
        raise ValueError("Question-only source is not the pinned draw-00 shard")
    old_bytes = (D43 / "D43_COHORT_FREEZE.json").read_bytes()
    exclusion_bytes = (D43 / "D43_DEVELOPMENT_EXCLUSIONS.json").read_bytes()
    old, exclusions = json.loads(old_bytes), json.loads(exclusion_bytes)
    ids = set(exclusions["excluded_problem_ids"]) | {row["problem_id"] for row in old["selected"]}
    hashes = set(exclusions["normalized_question_sha256"]) | {
        row["normalized_question_sha256"] for row in old["selected"]
    }
    columns = ("problem_id", "year", "part", "problem_number", "problem", "has_asy", "source_record_sha256")
    rows = pq.ParquetFile(shard).read(columns=list(columns)).to_pylist()
    strata = {"first-event": [], "extremum-medium": [], "extremum-late": []}
    seen = set()
    for row in sorted(rows, key=lambda row: key(row["problem_id"], "order")):
        pid, q = row["problem_id"], row["problem"]
        normalized = question_digest(q)
        if (
            pid in ids or normalized in hashes or normalized in seen
            or not 2009 <= row["year"] <= 2023 or row["has_asy"]
        ):
            continue
        scope = classify(row)
        if scope is None:
            continue
        kind, stratum = scope
        seen.add(normalized)
        strata[stratum].append({
            "case_id": pid, "question": q, "problem_kind": kind, "stratum": stratum,
            "year": row["year"], "part": row["part"], "problem_number": row["problem_number"],
            "question_sha256": digest(q.encode()), "normalized_question_sha256": normalized,
            "source_record_sha256": row["source_record_sha256"],
            "seed": int(key(pid, "native")[:8], 16), "restart_seed": int(key(pid, "restart")[:8], 16),
        })
    quotas = {"first-event": 2, "extremum-medium": 3, "extremum-late": 3}
    if any(len(strata[name]) < count for name, count in quotas.items()):
        raise ValueError("Not enough disjoint questions for the frozen shape quotas")
    visible = [row for name, count in quotas.items() for row in strata[name][:count]]
    order = sorted(visible, key=lambda row: key(row["case_id"], "run-order"))
    return {
        "status": "LIVE_PILOT_COHORT_FROZEN_WITHOUT_RESPONSES_OR_GOLD",
        "cohort_selection_code_sha256": digest(Path(__file__).read_bytes()),
        "source_revision": old["source_revision"], "question_source_shard_sha256": DRAW0_SHA256,
        "old_cohort_sha256": digest(old_bytes), "old_exclusions_sha256": digest(exclusion_bytes),
        "sampling_salt": SALT, "quotas": quotas,
        "eligible_counts": {name: len(value) for name, value in strata.items()},
        "rows": [{key: value for key, value in row.items() if key != "question"} for row in order],
    }, order


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--shard", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--local-visible", type=Path, required=True)
    args = cli.parse_args()
    if not args.local_visible.resolve().is_relative_to(HERE.parents[1] / "outputs"):
        cli.error("The question-only text projection must stay under local outputs")
    if args.output.exists() or args.local_visible.exists():
        cli.error("Refuse to replace a frozen cohort or visible projection")
    report, rows = freeze(args.shard)
    write_exclusive(args.local_visible, {"rows": rows})
    report["visible_sha256"] = digest(args.local_visible.read_bytes())
    write_exclusive(args.output, report)
    print(report["status"], report["eligible_counts"])


if __name__ == "__main__":
    main()
