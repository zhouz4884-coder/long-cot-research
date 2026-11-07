"""Uniform frozen LastBox evaluation after blinded D2 generation is closed."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

from freeze_generation import collect_generation, safe_path

try:
    from d0_answer_extract import extract_policy
    from d0_math_grade import grade_selected
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase5d_scope_rebase_20261106"))
    from d0_answer_extract import extract_policy
    from d0_math_grade import grade_selected

import d0_answer_extract
import d0_math_grade

GRADING_SOURCES = {
    "extractor": (Path(d0_answer_extract.__file__), "e64ef21c1b9e90ad8ecb41b0ce5058307248d33668b91fbfa3ece4e98b69d37d"),
    "grader": (Path(d0_math_grade.__file__), "b6cd1b9f15d015204e54c445ab0f4f1d1bdc93775515ee4bfc8fdb41e5823980"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pre_gold_validate(root):
    root = Path(root).resolve()
    frozen = json.loads(safe_path(root, "GENERATION_FREEZE.json").read_text(encoding="utf-8"))
    if frozen["status"] != "FROZEN":
        raise ValueError("Generation bank must close before evaluation")
    current, loaded = collect_generation(root)
    if set(current) != set(frozen):
        raise ValueError("Generation manifest schema differs")
    for field in current:
        if field != "created_utc" and current[field] != frozen[field]:
            raise ValueError("Frozen generation field changed: " + field)
    return frozen, loaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / "D2_SCORES.json"
    if out.exists():
        raise ValueError("Scores already exist; preserve the frozen evaluation")
    frozen, loaded = pre_gold_validate(root)
    grading_sources = {}
    for name, (path, expected) in GRADING_SOURCES.items():
        if sha(path) != expected:
            raise ValueError("A frozen scoring implementation changed")
        grading_sources[name] = expected
    if importlib.metadata.version("math-verify") != "0.9.0":
        raise ValueError("The frozen math grading backend is unavailable")
    answers = safe_path(root, "d2_eval_only.jsonl")
    began = time.monotonic()
    first_answer_read = datetime.now(timezone.utc).isoformat()
    raw_answers = answers.read_bytes()
    if hashlib.sha256(raw_answers).hexdigest() != frozen["eval_expected_sha256"]:
        raise ValueError("Evaluation answer bytes differ")
    answer_rows = list(map(json.loads, raw_answers.splitlines()))
    gold = {case["case_id"]: case["gold"] for case in answer_rows}
    expected_ids = {record["case_id"] for record in frozen["records"] if record["bank"] == "all_natural"}
    if len(gold) != len(answer_rows) or set(gold) != expected_ids or any(value is None for value in gold.values()):
        raise ValueError("Evaluation answer membership differs")

    def score(record):
        result = loaded[record["path"]]
        selection = (extract_policy(result["final_response"], "LastBox")
                     if result["EOS"] and result["think_closed"] else {"status": "uncommitted"})
        graded = (grade_selected(selection, gold[record["case_id"]]) if selection["status"] == "ok"
                  else {"status": "not_delivered", "correct": False})
        return {**record, "selection": selection, "grade": graded, "EOS": result["EOS"],
                "stop_reason": result["stop_reason"], "visible_assistant_tokens": result["new_tokens"]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(score, frozen["records"]))
    groups = defaultdict(list)
    for row in rows:
        groups[(row["bank"], row["arm"])].append(row)
    summaries = []
    for (bank, arm), group in sorted(groups.items()):
        summaries.append({"bank": bank, "arm": arm, "trajectories": len(group),
                          "distinct_problems": len({row["case_id"] for row in group}),
                          "correct": sum(row["grade"].get("correct") is True for row in group),
                          "incorrect_or_undelivered": sum(row["grade"].get("correct") is False for row in group),
                          "grading_unknown": sum(row["grade"].get("correct") is None for row in group),
                          "EOS": sum(row["EOS"] for row in group)})
    output = {"status": "COMPLETE", "first_evaluation_answer_read_utc": first_answer_read,
              "generation_freeze_sha256": sha(root / "GENERATION_FREEZE.json"),
              "grading_source_sha256": grading_sources, "math_verify_version": "0.9.0",
              "eval_sha256": hashlib.sha256(raw_answers).hexdigest(), "scores": rows, "summaries": summaries,
              "wall_seconds": time.monotonic()-began,
              "scope": "48-run descriptive baseline and conditional event experiments kept in distinct banks. Two seeds of one problem are correlated. No Gold-best candidate selection."}
    with out.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
