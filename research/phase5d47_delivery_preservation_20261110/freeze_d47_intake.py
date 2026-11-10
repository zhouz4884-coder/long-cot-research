"""Freeze a question-only D4.7 cohort and project only its blind archive rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns, thread_time_ns

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D46 = HERE.parent / "phase5d46_point_infeasibility_20261110"
sys.path.insert(0, str(D46))
from freeze_d46_intake import (
    BLIND_COLUMNS, DRAWS, METADATA, MODEL_PARAMETERS, check_identity, digest, load,
    project, question_digest, sha, verified_shards, write_exclusive,
)


def check_prior():
    baseline = load(HERE / "D47_BASELINE_FREEZE.json")
    for name, expected in baseline["d46_evidence_sha256"].items():
        path = D46 / name
        original = subprocess.check_output(
            ["git", "show", f'{baseline["baseline_commit"]}:{path.relative_to(ROOT).as_posix()}'], cwd=ROOT,
        )
        if digest(original) != expected or sha(path) != expected:
            raise ValueError(f"D4.6 freeze changed: {name}")
    return baseline


def freeze(old, new, local, output):
    from d47_problem_specs import PROBLEMS

    wall, cpu = perf_counter_ns(), thread_time_ns()
    baseline = check_prior()
    manifest, paths, assets = verified_shards(old, new)
    scope_path = HERE / "D47_QUESTION_SCOPE_AUDIT.json"
    scope = load(scope_path)
    audited = {row["case_id"]: row for row in scope["rows"]}
    ids = sorted(PROBLEMS)
    if set(audited) != set(ids) or not 8 <= len(ids) <= 12:
        raise ValueError("Reviewed case scope requires 8–12 independent cases")
    fields = ("problem_id", "problem", "eval_index", "rendered_prompt_sha256", "source_record_sha256")
    source = {row["problem_id"]: row for row in project(paths[0], fields, ids)}
    if set(source) != set(ids):
        raise ValueError("Missing original question projection")
    rows, visible = {}, []
    for cid in ids:
        item, spec, review = source[cid], PROBLEMS[cid], audited[cid]
        q = item["problem"]
        direct, normalized = digest(q.encode()), question_digest(q)
        if (direct, normalized, spec["direction"]) != (
            review["exact_question_sha256"], review["normalized_question_sha256"], review["direction"],
        ):
            raise ValueError(f"Question scope changed: {cid}")
        rows[cid] = {"case_id": cid, "question_sha256": direct, "normalized_question_sha256": normalized,
                     "eval_index": item["eval_index"], "source_record_sha256": item["source_record_sha256"],
                     "rendered_prompt_sha256": item["rendered_prompt_sha256"], "draws": [], **spec}
        visible.append({"case_id": cid, "question": q, "question_sha256": direct, **spec})
    for draw, path in paths.items():
        records = project(path, METADATA, ids)
        if len(records) != len(ids) or {row["problem_id"] for row in records} != set(ids):
            raise ValueError(f"Different denominator in draw {draw}")
        for sample in records:
            case = rows[sample["problem_id"]]
            check_identity(case, sample, draw, manifest["contract_sha256"])
            if json.loads(sample["generation_parameters_json"]) != MODEL_PARAMETERS or any(
                sample[k] != case[k] for k in ("rendered_prompt_sha256", "source_record_sha256")
            ):
                raise ValueError("Original question, prompt or generation identity changed")
            case["draws"].append({k: sample[k] for k in ("draw_index", "sample_id", "seed", "response_sha256")})
    write_exclusive(local, {"status": "D47_QUESTION_ONLY_WITHOUT_TRACES_OR_LABELS", "rows": visible})
    result = {
        "status": "D47_QUESTION_IDENTITIES_FROZEN_BEFORE_TRACE_OR_GOLD",
        "baseline_commit": baseline["baseline_commit"], "source_revision": scope["source"]["revision"],
        "upstream_manifest_sha256": sha(old / "PUBLICATION_MANIFEST.json"),
        "generation_contract_sha256": manifest["contract_sha256"], "source_shards": assets,
        "scope_audit_sha256": sha(scope_path), "observation_rules_sha256": sha(HERE / "D47_OBSERVATION_RULES.json"),
        "parent_observation_rules_sha256": sha(D46 / "D46_OBSERVATION_RULES.json"),
        "problem_specs_sha256": sha(HERE / "d47_problem_specs.py"),
        "point_domain_sha256": sha(HERE / "d47_point_domains.py"),
        "question_only_sha256": sha(local), "selected_question_count": len(ids),
        "planned_draw_count": len(DRAWS), "planned_trace_count": len(ids)*len(DRAWS),
        "rows": [rows[cid] for cid in ids], "intake_wall_ns": perf_counter_ns()-wall, "intake_cpu_ns": thread_time_ns()-cpu,
    }
    write_exclusive(output, result)
    return result


def materialize(old, new, cohort_path, output):
    cohort = load(cohort_path)
    manifest, paths, assets = verified_shards(old, new)
    if assets != cohort["source_shards"] or cohort["planned_trace_count"] != cohort["selected_question_count"] * len(DRAWS):
        raise ValueError("Blind trace projection changed from question-only freeze")
    selected = {row["case_id"]: row for row in cohort["rows"]}
    rows = []
    for draw, path in paths.items():
        samples = project(path, BLIND_COLUMNS, list(selected))
        if len(samples) != len(selected) or {r["problem_id"] for r in samples} != set(selected):
            raise ValueError("Missing or repeated fixed draw identity")
        for sample in samples:
            item = selected[sample["problem_id"]]
            check_identity(item, sample, draw, manifest["contract_sha256"])
            record, = (r for r in item["draws"] if r["draw_index"] == draw)
            if any(sample[k] != v for k, v in record.items()):
                raise ValueError("Different draw identity")
            if digest(sample["problem"].encode()) != item["question_sha256"] or digest(sample["response"].encode()) != sample["response_sha256"]:
                raise ValueError("Raw question or generated response changed")
            if (sample["input_tokens"] + sample["effective_max_new_tokens"] != 32768
                    or not 0 <= sample["output_tokens"] <= sample["effective_max_new_tokens"]
                    or (sample["cap_hit"] and sample["output_tokens"] != sample["effective_max_new_tokens"])):
                raise ValueError("Full source tokens disagree with archive limits")
            rows.append(sample)
    result = {"cohort_freeze_sha256": sha(cohort_path), "draws": list(DRAWS), "rows": rows}
    write_exclusive(output, result)
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("freeze", "materialize"))
    for name in ("old-source", "new-source", "freeze", "local"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    if not args.local.resolve().is_relative_to(ROOT / "outputs"):
        cli.error("Raw wording and archive text stay under outputs")
    if args.mode == "freeze":
        result = freeze(args.old_source, args.new_source, args.local, args.freeze)
        print(result["status"], result["planned_trace_count"], sha(args.freeze))
    else:
        result = materialize(args.old_source, args.new_source, args.freeze, args.local)
        print("D47_BLIND_ARCHIVE_PROJECTION", len(result["rows"]), sha(args.local))


if __name__ == "__main__":
    main()
