"""Freeze a stratified, problem-disjoint 150/50/300 MATH-500 split."""
import collections
import hashlib
import json
from pathlib import Path
import random


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8",newline="\n")


def allocate(groups, target, total):
    counts = {k: int(len(v) * target / total) for k, v in groups.items()}
    order = sorted(groups, key=lambda k: (-(len(groups[k]) * target / total - counts[k]), k))
    for k in order[:target - sum(counts.values())]:
        counts[k] += 1
    return counts


def main():
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    rows = [json.loads(x) for x in (data / "math500_source.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len({r["unique_id"] for r in rows}) == 500
    rng = random.Random(20261008)
    groups = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r["unique_id"]):
        groups[(r["subject"], str(r["level"]))].append(r)
    for g in groups.values():
        rng.shuffle(g)
    n_eng = allocate(groups, 50, 500)
    n_dev = allocate(groups, 150, 500)
    splits = {"engineering": [], "development": [], "test": []}
    for k, g in sorted(groups.items()):
        splits["engineering"] += g[:n_eng[k]]
        splits["development"] += g[n_eng[k]:n_eng[k] + n_dev[k]]
        splits["test"] += g[n_eng[k] + n_dev[k]:]
    manifest = {"seed": 20261008, "method": "subject-level proportional largest remainder; seeded within-stratum shuffle", "splits": {}}
    for name, group in splits.items():
        rng.shuffle(group)
        normalized = [{"problem_id": r["unique_id"], "question": r["problem"], "gold": r["answer"], "subject": r["subject"], "level": r["level"], "task": "math"} for r in group]
        p = data / (name + ".jsonl")
        write_jsonl(p, normalized)
        manifest["splits"][name] = {"n": len(group), "ids": [r["unique_id"] for r in group], "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        if name == "engineering":
            write_jsonl(data / "math500_smoke.jsonl", normalized[:24])
    (data / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",newline="\n")
    print({k: v["n"] for k, v in manifest["splits"].items()})


if __name__ == "__main__":
    main()
