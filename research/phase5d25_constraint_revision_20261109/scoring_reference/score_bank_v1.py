"""Score only the complete, independently frozen raw generation bank."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from complete_answer import backend_status, score_final_answer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def safe_result(root, name):
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("Result path is outside the experiment")
    path = root / rel
    if not path.resolve(strict=True).is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Result path escapes the verified experiment")
    return path


def verify_raw(root, manifest):
    if manifest["status"] != "FROZEN_AFTER_GENERATION" or not manifest["records"]:
        raise ValueError("Scoring requires all planned generation outcomes")
    records, seen = [], set()
    for entry in manifest["records"]:
        key = entry["evaluation_partition"], entry["case_id"], entry["seed"], entry["arm"]
        if key in seen:
            raise ValueError("Duplicate scoring key")
        seen.add(key)
        path = safe_result(root, entry["path"])
        raw = path.read_bytes()
        if sha(raw) != entry["sha256"]:
            raise ValueError("Raw result changed after the scoring freeze")
        result = json.loads(raw)
        if result.get("status") != "COMPLETE" or type(result.get("EOS")) is not bool or type(result.get("think_closed")) is not bool:
            raise ValueError("A nonterminal or malformed model result cannot be graded")
        if result.get("case_id", entry["case_id"]) != entry["case_id"] or result.get("seed", entry["seed"]) != entry["seed"]:
            raise ValueError("Raw result case identity differs")
        records.append((entry, result))
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--scoring", type=Path, required=True)
    args = ap.parse_args()
    root, scoring = args.root.resolve(), args.scoring.resolve()
    if not scoring.is_relative_to(root) or (scoring / "SCORES.json").exists():
        raise ValueError("A separate, unused scoring folder is required")
    frozen_raw = (scoring / "GRADE_FREEZE.json").read_bytes()
    manifest = json.loads(frozen_raw)
    if sha(Path(__file__).read_bytes()) != manifest["grader_runner_sha256"]:
        raise ValueError("Scoring runner changed after freeze")
    complete_answer = Path(__file__).with_name("complete_answer.py")
    if sha(complete_answer.read_bytes()) != manifest["complete_answer_sha256"]:
        raise ValueError("Answer extraction source changed after freeze")
    backend = backend_status()
    if backend["status"] != "ok":
        raise ValueError(f"Frozen answer backend is not available: {backend}")
    records = verify_raw(root, manifest)
    opened = datetime.now(timezone.utc).isoformat()
    answer_raw = (scoring / "eval_only.jsonl").read_bytes()
    if sha(answer_raw) != manifest["eval_sha256"]:
        raise ValueError("Evaluation reference hash mismatch")
    answers = {row["case_id"]: row for row in map(json.loads, answer_raw.splitlines())}
    if set(answers) != {entry["case_id"] for entry, _ in records}:
        raise ValueError("Scored generation and evaluation references differ in membership")
    began = time.monotonic()

    def grade(row):
        entry, result = row
        gold = answers[entry["case_id"]]
        outcome = score_final_answer(result["final_response"], gold["gold"], answer_kind=gold["answer_kind"],
                                     eos=result["EOS"], think_closed=result["think_closed"])
        return {**entry, **outcome, "EOS": result["EOS"], "stop_reason": result["stop_reason"]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(grade, records))
    by_arm = defaultdict(list)
    for row in rows:
        by_arm[row["evaluation_partition"], row["arm"]].append(row)
    summaries = []
    for (partition, arm), group in sorted(by_arm.items()):
        unique = {row["case_id"] for row in group}
        summaries.append({"evaluation_partition": partition, "arm": arm, "trajectories": len(group), "distinct_problems": len(unique),
                          "correct": sum(row["grade"]["correct"] is True for row in group),
                          "unknown": sum(row["grade"]["correct"] is None for row in group),
                          "EOS": sum(row["EOS"] for row in group)})
    output = {"status": "COMPLETE", "freeze_sha256": sha(frozen_raw), "first_reference_read_utc": opened,
              "scoring_seconds": time.monotonic() - began, "bank": manifest["bank"],
              "backend": backend,
              "scope": "Whole-object answer extraction before semantic comparison. All matching raw cases remain in the denominator.",
              "summaries": summaries, "scores": rows}
    with (scoring / "SCORES.json").open("xb") as stream:
        stream.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": "COMPLETE", "summaries": summaries}, ensure_ascii=False))


if __name__ == "__main__":
    main()
