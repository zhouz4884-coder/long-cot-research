"""CPU-only read audit of historical trajectory metadata and binomial bounds.

Never launches workers, loads a model, resumes a queue, or uses correctness labels
to select trajectories. Existing input files are opened read-only.
"""

import collections
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(r"D:\ACL")
OUT = Path(__file__).with_name("existing_trajectory_metadata_audit.json")
KEYWORD = re.compile(r"\bWait\b|\bActually\b|\bmistake\b|\bcorrection\b|\bincorrect\b|不对|更正|重新计算", re.I)


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def percentile(values, quantile):
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * quantile)] if ordered else None


def cdf(k, n, probability):
    return sum(math.comb(n, j) * probability ** j * (1 - probability) ** (n-j)
               for j in range(k + 1))


def upper95(k, n):
    if k == n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(90):
        mid = (lo + hi) / 2
        if cdf(k, n, mid) > 0.05:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main():
    groups = {
        "math500_bank": list((ROOT / "results/bank").glob("*traces*.jsonl")),
        "math500_online_full": list((ROOT / "results/online").glob("qwen3_4b*.jsonl")),
        "omni_boxed_pilot": list((ROOT / "experiments/radar20261013/results").glob("pilot_full*.jsonl")),
        "omni_native_pilot": list((ROOT / "experiments/radar20261013/results").glob("native_pilot*.jsonl")),
        "formal_development_snapshot": list((ROOT / "experiments/radar20261013/provenance/bank_snapshots/development_20261014_01").glob("shard*.jsonl")),
    }
    summaries = []
    for group, paths in groups.items():
        subgroup = collections.defaultdict(list)
        for path in sorted(paths):
            for row in read_rows(path):
                if group == "math500_online_full" and row.get("method") != "full":
                    continue
                key = str(row.get("nominal_budget", "all"))
                subgroup[key].append(row)
        source_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
        for budget, rows in sorted(subgroup.items()):
            lengths, times = [], []
            stopped, dtype, revisions = collections.Counter(), collections.Counter(), collections.Counter()
            capped = candidate_count = ids_retained = text_retained = token_count_mismatch = 0
            unique_ids = set()
            for row in rows:
                trace = row.get("full", {}).get("trace", {}) if "full" in row else row.get("trace", {})
                length = len(trace.get("ids", []))
                lengths.append(length)
                ids_retained += bool(trace.get("ids"))
                text_retained += bool(trace.get("text"))
                token_count_mismatch += trace.get("tokens", length) != length
                stopped[str(trace.get("stop_reason"))] += 1
                dtype[str(row.get("dtype", "not_in_row"))] += 1
                revisions[str(row.get("model_revision", "not_in_row"))] += 1
                unique_ids.add(row["problem_id"])
                capped += bool(row.get("length_censored", trace.get("length_censored", False)))
                candidate_count += bool(KEYWORD.search(trace.get("text", "")))
                if row.get("wall_ms") is not None:
                    times.append(row["wall_ms"] / 1000)
            summaries.append({
                "group": group, "nominal_budget": budget,
                "rows": len(rows), "unique_problem_ids_within_group": len(unique_ids),
                "token_ids_retained_rows": ids_retained, "text_retained_rows": text_retained,
                "token_count_vs_ids_mismatch_rows": token_count_mismatch,
                "trace_tokens": {"sum": sum(lengths), "min": min(lengths),
                                 "median_lower": percentile(lengths, .5),
                                 "p90_lower": percentile(lengths, .9), "max": max(lengths)},
                "capped_rows": capped, "stop_reasons": dict(stopped),
                "broad_keyword_candidate_rows_not_semantic_labels": candidate_count,
                "wall_seconds_sum_recorded": sum(times) if times else None,
                "dtype_values": dict(dtype), "model_revision_values": dict(revisions),
                "input_sha256": source_hashes,
            })
    test_ids = {r["problem_id"] for r in read_rows(ROOT / "data/test.jsonl")}
    online_ids = {r["problem_id"] for p in groups["math500_online_full"]
                  for r in read_rows(p) if r.get("method") == "full"}
    result = {
        "scope": "Read-only CPU metadata audit; no semantic correction labels, model use or queue changes.",
        "groups": summaries,
        "online_full_question_join": {"online_ids": len(online_ids),
                                       "data_test_exact_id_matches": len(test_ids & online_ids)},
        "counts_not_pooled": "Budgets, historical pools, methods and recovery copies are not independent samples.",
        "binomial_one_sided_95_upper": [
            {"events": k, "independent_questions": n, "upper": upper95(k, n)}
            for n, k in [(32, 0), (50, 0), (100, 0), (100, 1), (100, 2), (100, 4)]
        ],
        "P_count_below_5_for_n100_if_true_rate_5pct": cdf(4, 100, .05),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "summaries": len(summaries),
                      "online_question_join": result["online_full_question_join"],
                      "binomial_one_sided_95_upper": result["binomial_one_sided_95_upper"],
                      "P_count_below_5_at_true_5pct": result["P_count_below_5_for_n100_if_true_rate_5pct"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
