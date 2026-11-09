"""Recount the committed D2 evidence without changing its scoring or protocol."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
D2 = ROOT.parent / "phase5d2_quarantined_rebase_20261107"
BASELINE = "6c3ac9ef28a10fd239238cbb70d07f47c7d72d46"
sys.path.insert(0, str(D2))
from natural_evidence import relations


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audits = ("COVERAGE_RETRIEVAL_MANIFEST.json", "PAIRING_RETRIEVAL_MANIFEST.json")
    raw_counts = {}
    for name in audits:
        files = read(D2 / name)["files"]
        for row in files:
            path = D2 / row["path"]
            if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
                raise ValueError(f"D2 frozen output changed: {path}")
        raw_counts[name] = len(files)
    read_paths = (
        "D2_CLOSEOUT_ZH.md", "D2_METHOD_AND_DECISIONS_ZH.md", "COVERAGE_AUDIT.json",
        "INVALID_LITERAL_FAILURE_MODES.json", "PAIR_SELECTION.json", "PAIRING_PROTOCOL.json",
        "natural_evidence.py", "proposal_check.py", "paired_d2_worker.py", "reflection_fork.py",
        "native_snapshot.py", "restricted_math_checker.py", "natural_ledger.py", "dual_frontier_rebase.py",
        "COVERAGE_RELATIONS.jsonl", "D2_SCORES.json", "GENERATION_FREEZE.json",
    )
    repo = ROOT.parents[1]
    sources = {}
    for name in read_paths:
        path = D2 / name
        previous = subprocess.check_output(["git", "show", f"{BASELINE}:{path.relative_to(repo).as_posix()}"], cwd=repo)
        if previous != path.read_bytes():
            raise ValueError(f"D2 committed input changed: {path}")
        sources[name] = sha(path)
    freeze = read(D2 / "GENERATION_FREEZE.json")
    baselines = {}
    for item in freeze["records"]:
        if item["bank"] == "all_natural":
            raw = read(D2 / item["path"])
            baselines[item["case_id"], item["seed"]] = raw
    extracted = [json.loads(line) for line in (D2 / "COVERAGE_RELATIONS.jsonl").read_bytes().splitlines()]
    unbound = []
    for row in extracted:
        if row["check_result"]["reason"] != "symbolic_scope_unbound":
            continue
        key = (row["case_id"], row["seed"])
        step = next(item for item in baselines[key]["steps"] if item["step"] == row["step"])
        old_relation = row["relation"]
        reextracted = [item for item in relations(step) if item.get("equation_index") == old_relation["equation_index"]
                       and item.get("char_span_in_step") == old_relation["char_span_in_step"]
                       and item.get("surface") == old_relation["surface"]]
        if len(reextracted) != 1 or reextracted[0]["reason"] != "symbolic_scope_unbound":
            raise ValueError("Inherited scope failure was not reproduced")
        unbound.append(key)
    selected = read(D2 / "PAIR_SELECTION.json")["selected"]
    arms = ("InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck")
    checks, identity = [], []
    for item in selected:
        case = f"{item['case_id']}_{item['seed']}"
        folder, = (D2 / "paired_results").glob(f"worker_*/{case}")
        records = [read(folder / f"{arm}.json") for arm in arms]
        identical = all(records[0][field] == record[field] for record in records[1:]
                        for field in ("audit_cue", "generated_ids", "prompt_ids"))
        if not identical or any(record["disposition"] != "UNKNOWN" for record in records):
            raise ValueError("Old three-arm fallback evidence differs")
        for record in records:
            checks.append({"case": case, "arm": record["arm"], "reason": record["proposal_check"]["parser"]["reason"],
                           "sampled_tokens": record["sampled_tokens_including_discarded"],
                           "cue_tokens": record["teacher_forced_audit_and_redirect_tokens"],
                           "elapsed": record["standalone_end_to_end_seconds"]})
        identity.append(read(folder / "IDENTITY_GATE.json")["status"])
    chosen = [baselines[item["case_id"], item["seed"]] for item in selected]
    native_tokens = sum(item["new_tokens"] for item in chosen)
    scoped = [row for row in checks if row["arm"] == "ScopedIsolatedCheck"]
    output = {"status": "PASS", "baseline_commit": BASELINE, "source_sha256": sources, "verified_receipts": raw_counts,
              "native_trajectories": len(baselines), "relations": len(extracted),
              "reproduced_symbolic_scope_unbound": len(unbound), "unbound_distinct_problems": len({x[0] for x in unbound}),
              "unbound_distinct_trajectories": len(set(unbound)),
              "proposal_reasons": dict(Counter(row["reason"] for row in checks)), "check_records": checks,
              "matching_three_arm_cases": len(selected), "identity_passes": identity.count("PASS"),
              "native_sampled_tokens": native_tokens, "scoped_sampled_tokens": sum(row["sampled_tokens"] for row in scoped),
              "scoped_cue_tokens": sum(row["cue_tokens"] for row in scoped),
              "native_seconds": sum(row["elapsed_seconds"] for row in chosen),
              "scoped_seconds": sum(row["elapsed"] for row in scoped),
              "interpretation": "Identical cue-conditioned generation plus a shared no-variable UNKNOWN path. Timing is a combined contrast; isolated RNG effects were not measured."}
    if (len(baselines), len(extracted), len(unbound), len(checks), identity.count("PASS")) != (48, 460, 162, 12, 4):
        raise ValueError("Unexpected D2 denominators")
    (ROOT / "INHERITED_D2_AUDIT.json").write_bytes((json.dumps(output, indent=2) + "\n").encode())
    print(json.dumps({k: v for k, v in output.items() if k not in ("source_sha256", "check_records")}, indent=2))


if __name__ == "__main__":
    main()
