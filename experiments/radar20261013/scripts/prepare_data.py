"""Freeze eligibility and question splits before any new model output exists."""
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from math_verify import ExprExtractionConfig, LatexExtractionConfig, parse
from sympy import Expr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reason_transition.core import normalize_math_surface, grade


def load(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]


def normalize_question(q):
    return re.sub(r"\s+", "", q).lower()


def words(q):
    return re.findall(r"[a-z0-9]+", q.lower())


def grams(q):
    t = words(q)
    return {tuple(t[i:i+5]) for i in range(max(0, len(t)-4))}


def main():
    data = ROOT / "data"
    source = load(data / "omni_source.jsonl")
    old = load(data / "excluded_math500.jsonl")
    old_keys = {normalize_question(r.get("question", r.get("problem"))) for r in old}
    old_grams = [grams(r.get("question", r.get("problem"))) for r in old]
    index = defaultdict(set)
    for i, g in enumerate(old_grams):
        for token in g:
            index[token].add(i)
    excluded, eligible, seen = [], [], set()
    for i, row in enumerate(source):
        q = row["problem"]
        key = normalize_question(q)
        why = None
        if key in old_keys:
            why = "exact_question_overlap_with_observed_math500"
        elif key in seen:
            why = "duplicate_question_in_omni"
        elif re.search(r"\b(prove|show that|demonstrate that)\b", q, re.I):
            why = "proof_or_mixed_proof_request"
        elif len(row["answer"]) > 256:
            why = "answer_longer_than_256_characters"
        if not why:
            g = grams(q)
            candidates = set.union(*(index[t] for t in g if t in index)) if any(t in index for t in g) else set()
            if any(len(g & old_grams[j]) / max(1, len(g | old_grams[j])) >= 0.85 for j in candidates):
                why = "near_question_overlap_jaccard_5gram_ge_0_85"
        if not why:
            try:
                gold = normalize_math_surface(row["answer"])
                target = parse(r"\boxed{" + gold + "}", extraction_config=(LatexExtractionConfig(), ExprExtractionConfig()), parsing_timeout=2)
                obj = target[0] if target else None
                if not isinstance(obj, Expr) or obj.free_symbols or obj.is_number is not True or obj.is_finite is not True:
                    why = "not_verified_finite_constant_scalar"
                elif grade(r"\boxed{" + row["answer"] + "}", row["answer"])["correct"] != 1:
                    why = "gold_self_verification_failed"
            except Exception as e:
                why = "gold_parse_exception_" + type(e).__name__
        seen.add(key)
        if why:
            excluded.append({"source_index": i, "reason": why, "question_sha256": hashlib.sha256(key.encode()).hexdigest()})
            continue
        domain = row["domain"][0].split(" -> ")[1] if row["domain"] else "Unknown"
        eligible.append({"problem_id": "omni/" + hashlib.sha256(q.encode()).hexdigest()[:20],
                         "source_index": i, "question": q, "gold": row["answer"], "subject": domain,
                         "difficulty": float(row["difficulty"]), "task": "math_scalar", "source": row["source"]})
    eligible.sort(key=lambda r: hashlib.sha256(("20261013:" + r["problem_id"]).encode()).hexdigest())
    n = len(eligible)
    # Fixed split allocation based only on eligible count; never on solver outcomes.
    pilot_n = min(100, max(40, n // 20))
    remaining = n - pilot_n
    sizes = {"development": int(0.20 * remaining), "selection": int(0.10 * remaining),
             "calibration": int(0.30 * remaining)}
    sizes["test"] = remaining - sum(sizes.values())
    splits = {k: [] for k in ["pilot", *sizes]}
    # Human previewed indices are always in pilot when eligible.
    preview = [r for r in eligible if r["source_index"] in [0,1,2]]
    pool = [r for r in eligible if r["source_index"] not in [0,1,2]]
    strata = defaultdict(list)
    for row in pool:
        strata[(row["subject"], int(row["difficulty"]) // 2)].append(row)
    rng = random.Random(20261013)
    for rows in strata.values():
        rng.shuffle(rows)

    def take_stratified(size):
        total = sum(map(len, strata.values()))
        ideal = {k: size * len(v) / total for k, v in strata.items()}
        quota = {k: math.floor(v) for k, v in ideal.items()}
        for key in sorted(ideal, key=lambda k: (-(ideal[k] - quota[k]), k))[:size - sum(quota.values())]:
            quota[key] += 1
        chosen = []
        for key, count in quota.items():
            chosen += strata[key][:count]
            del strata[key][:count]
        rng.shuffle(chosen)
        return chosen

    splits["pilot"] = preview + take_stratified(pilot_n - len(preview))
    for name, size in sizes.items():
        splits[name] = take_stratified(size)
    assert sum(map(len, splits.values())) == n
    assert len({r["problem_id"] for v in splits.values() for r in v}) == n
    assert not list((ROOT / "results").glob("**/*.jsonl")), "Cannot change a split after generation"
    for name, rows in splits.items():
        (data / (name + ".jsonl")).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (data / "eligibility_exclusions.json").write_text(json.dumps(excluded, indent=2), encoding="utf-8")
    manifest = {"seed": 20261013, "source_n": len(source), "eligible_n": n,
                "split_method": "subject x floor(difficulty/2) proportional largest remainder, seeded within-stratum shuffle; inspected source rows reserved for pilot",
                "coverage": n / len(source), "eligibility": "finite numeric scalar, gold self parse, no explicit proof request, no exact/near overlap with observed MATH500",
                "exclusion_counts": dict(Counter(r["reason"] for r in excluded)),
                "new_generation_records_at_freeze": 0,
                "exchangeability_scope": "The frozen eligible subset; not the full Omni-MATH benchmark or uncontaminated pretraining.",
                "splits": {name: {"n": len(rows), "ids": [r["problem_id"] for r in rows],
                                    "subject_counts": dict(Counter(r["subject"] for r in rows)),
                                    "sha256": hashlib.sha256((data / (name + ".jsonl")).read_bytes()).hexdigest()} for name, rows in splits.items()}}
    (ROOT / "provenance/data_freeze.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "splits"}, indent=2))
    print(json.dumps({k: len(v) for k, v in splits.items()}))


if __name__ == "__main__":
    main()
