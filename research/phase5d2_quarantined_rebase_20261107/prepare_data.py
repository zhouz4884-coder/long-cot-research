"""Freeze MATH test questions by external metadata and a stable content ID."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
REVISION = "21a5633873b6a120296cce3e2df9d5550074f4a3"
SOURCE = "https://huggingface.co/datasets/EleutherAI/hendrycks_math/resolve/" + REVISION
SALT = "ACL-D2-MATH-test-v1-20261107"
STRATA = {
    "algebra": {2: 2, 3: 2, 4: 2, 5: 1},
    "intermediate_algebra": {3: 1, 4: 2, 5: 3},
    "number_theory": {2: 1, 3: 1, 4: 2, 5: 2},
    "counting_and_probability": {2: 1, 3: 1, 4: 1, 5: 2},
}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def stem(text):
    # Ignore formatting differences common to the published copies.
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"\\(?:left|right|displaystyle)\b", "", value)
    return re.sub(r"[\s$]", "", value)


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode()


def freeze(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Frozen bytes differ at {path}")
    else:
        path.write_bytes(raw)


def last_box(text):
    boxes = []
    for match in re.finditer(r"\\(?:boxed|fbox)\s*\{", text):
        depth = 1
        for end in range(match.end(), len(text)):
            if text[end] == "{" and (end == 0 or text[end-1] != "\\"):
                depth += 1
            elif text[end] == "}" and (end == 0 or text[end-1] != "\\"):
                depth -= 1
                if depth == 0:
                    boxes.append(text[match.end():end])
                    break
    return boxes[-1] if boxes else None


def main():
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    excluded = set()
    sources = {}
    old_paths = [
        REPO / "data/math500_source.jsonl",
        REPO / "research/phase5d_scope_rebase_20261106/native_visible.jsonl",
    ]
    old_paths.extend(REPO.glob("experiments/radar20261013/data/**/development.jsonl"))
    old_paths.extend(REPO.glob("experiments/radar20261013/data/**/pilot.jsonl"))
    old_paths.extend(REPO.glob("experiments/radar20261013/data/**/selection.jsonl"))
    old_paths.extend(REPO.glob("experiments/radar20261013/data/**/test.jsonl"))
    old_paths.extend(REPO.glob("experiments/radar20261013/data/**/calibration.jsonl"))
    for path in sorted(set(old_paths)):
        raw = path.read_bytes()
        sources[path.relative_to(REPO).as_posix()] = sha(raw)
        for line in raw.splitlines():
            if line.strip():
                row = json.loads(line)
                question = row.get("problem") or row.get("question")
                if isinstance(question, str):
                    excluded.add(stem(question))

    visible, evaluation, shards = [], [], []
    for subject, quotas in STRATA.items():
        relative = f"{subject}/test-00000-of-00001.parquet"
        path = args.cache / f"{subject}.parquet"
        if not path.exists():
            with urllib.request.urlopen(f"{SOURCE}/{relative}", timeout=90) as response:
                path.write_bytes(response.read())
        rows = pq.read_table(path).to_pylist()
        shards.append({"file": relative, "sha256": sha(path.read_bytes()), "rows": len(rows)})
        for level, quota in quotas.items():
            ranked = []
            for index, row in enumerate(rows):
                question = row["problem"]
                canonical = stem(question)
                if row["level"] != f"Level {level}" or canonical in excluded or "[asy]" in question.casefold():
                    continue
                identifier = sha(canonical.encode())
                ranked.append((sha(f"{SALT}\0{subject}\0{level}\0{identifier}".encode()), index, identifier))
            chosen = 0
            for rank, index, identifier in sorted(ranked):
                row = rows[index]
                canonical = stem(row["problem"])
                if canonical in excluded:
                    continue
                excluded.add(canonical)
                case_id = f"D2_{len(visible)+1:02}"
                visible.append({"case_id": case_id, "question": row["problem"], "problem_hash": identifier,
                                "subject": subject, "level": level, "source_row_0": index, "selection_rank": rank})
                evaluation.append({"case_id": case_id, "gold": last_box(row["solution"]), "solution": row["solution"]})
                chosen += 1
                if chosen == quota:
                    break
            if chosen != quota:
                raise ValueError(f"Insufficient unique rows for {subject} level {level}")
    assert len(visible) == len(evaluation) == 24
    visible_bytes, evaluation_bytes = jsonl(visible), jsonl(evaluation)
    freeze(ROOT / "d2_visible.jsonl", visible_bytes)
    freeze(ROOT / "d2_eval_only.jsonl", evaluation_bytes)
    manifest = {"dataset": "EleutherAI/hendrycks_math", "split": "test", "revision": REVISION,
                "selection_salt": SALT, "strata": STRATA, "shards": shards, "excluded_sources": sources,
                "exclude_asy": True, "normalized_stem_overlap": 0, "questions": len(visible),
                "seed_slots": [20261107, 20261108], "visible_sha256": sha(visible_bytes),
                "eval_sha256": sha(evaluation_bytes), "missing_gold_boxes": sum(x["gold"] is None for x in evaluation)}
    freeze(ROOT / "DATA_MANIFEST.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({key: manifest[key] for key in ("questions", "visible_sha256", "missing_gold_boxes", "revision")}))


if __name__ == "__main__":
    main()
