"""Read-only evidence recount for the completed D2 coverage wave."""

from collections import Counter, defaultdict
import hashlib
import json
from math import fsum, isclose
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def token_sha(ids):
    return sha(json.dumps(ids, separators=(",", ":")).encode("utf-8"))


def need(condition, detail):
    if not condition:
        raise ValueError(detail)


def verify_manifest(manifest):
    hashes = {}
    for item in manifest["files"]:
        name = item["path"]
        permitted = name.startswith("native_results/") or name.startswith("logs/coverage_") or name == "coverage_launcher.json"
        path = (ROOT / name).resolve()
        need(permitted and path.is_relative_to(ROOT) and name not in hashes, f"Unexpected retrieval entry {name}")
        payload = path.read_bytes()
        actual = sha(payload)
        need(len(payload) == item["bytes"] and actual == item["sha256"], f"Retrieved bytes differ for {name}")
        hashes[name] = actual
    return hashes


def result_work(result):
    prompt = result["prompt_ids"]
    generated = result["generated_ids"]
    need(token_sha(prompt) == result["prompt_sha256"], "Prompt token hash mismatch")
    need(token_sha(generated) == result["generated_sha256"], "Generated token hash mismatch")
    need(len(generated) == result["new_tokens"] and result["status"] == "COMPLETE", "Terminal metadata differs")
    need(result["EOS"] != result["hit_context_cap"], "Coverage result lacks an exclusive terminal condition")
    need(result["stop_reason"] == ("EOS" if result["EOS"] else "CONTEXT_CAP"), "Stop reason disagrees with flags")
    cursor = 0
    by_stage = Counter()
    attention = 0
    for row in result["ledger"]:
        width = row["input_tokens"]
        need(type(width) is int and width > 0 and row["past_tokens"] == row["position_start"] == cursor,
             "Noncontiguous coverage forward ledger")
        stage = row["stage"]
        if cursor < len(prompt):
            need(stage == "native_prefill" and width == min(256, len(prompt) - cursor), "Unexpected prefill schedule")
        else:
            need(stage == "native_decode" and width == 1, "Unexpected decode schedule")
        by_stage[stage] += width
        attention += width * cursor + width * (width + 1) // 2
        cursor += width
    need(by_stage["native_prefill"] == len(prompt), "Prefill token total differs")
    need(by_stage["native_decode"] == len(generated) - 1, "D1 unforwarded terminal token convention differs")
    return {"prompt_tokens": len(prompt), "generated_tokens": len(generated), "forward_calls": len(result["ledger"]),
            "forward_input_tokens": cursor, "prefill_forward_input_tokens": by_stage["native_prefill"],
            "decode_forward_input_tokens": by_stage["native_decode"], "causal_attention_token_pairs": attention}


def verify_selected(entry, source, relative, result_sha):
    need(entry["source_result"] == relative and entry["source_result_sha256"] == result_sha, "Selected source file identity differs")
    end = entry["generated_count"]
    need(type(end) is int and 0 < end <= len(source["generated_ids"]), "Selected observed prefix length is invalid")
    digest = token_sha(source["prompt_ids"] + source["generated_ids"][:end])
    need(entry["observed_prefix_sha256"] == digest, "Selected observed prefix token hash differs")
    matched_step = [step for step in source["steps"] if step["step"] == entry["step"] and step["end"] == end]
    matched_event = [event for event in source["events"] if event["step"] == entry["step"] and event["end"] == end and event["thinking_open"]]
    need(len(matched_step) == len(matched_event) == 1, "Selected checkpoint lacks an observed live step")
    return {"case_id": entry["case_id"], "seed": entry["seed"], "step": entry["step"], "source_result": relative,
            "source_result_sha256": result_sha, "generated_count": end, "observed_prefix_sha256": digest,
            "recorded_step_boundary": matched_step[0]["boundary"], "role_certified_at_selection": entry["role_certified"]}


def recount_relations(seed_slots, runs, hashes):
    counts, unknowns = Counter(), Counter()
    by_seed = {seed: [] for seed in seed_slots}
    relation_ids = {}
    role_ready = 0
    rebase_ready = 0
    for line in (ROOT / "COVERAGE_RELATIONS.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["case_id"], row["seed"])
        need(key in runs, "Relation belongs to an unknown trajectory")
        need(row["source_result"] == runs[key]["result_path"] and row["source_result_sha256"] == hashes.get(row["source_result"]),
             "Relation has an unbound source result")
        relation_id = row["relation_id"]
        need(relation_id not in relation_ids, "Duplicate relation identity")
        relation_ids[relation_id] = row
        checked = row["check_result"]
        counts[checked["status"]] += 1
        role_ready += row["role_certified"]
        rebase_ready += row["rebase_eligible"]
        if checked["status"] == "UNKNOWN":
            unknowns[checked["reason"]] += 1
        relation = row["relation"]
        closed_arithmetic = relation.get("certificate_type") == "ARITHMETIC_EQ" and relation.get("variables") == []
        if closed_arithmetic and checked["status"] == "INVALID_JUSTIFICATION":
            need(row["literal_checkable"] and checked["truth"] is False, "False literal metadata is internally inconsistent")
            by_seed[row["seed"]].append({key: row[key] for key in
                ("case_id", "seed", "step", "equation_index", "relation_id", "live_paragraph_checkpoint",
                 "actionable_role_candidate", "role_certified", "rebase_eligible")})
    groups = {}
    for seed, rows in by_seed.items():
        ids = sorted({row["case_id"] for row in rows})
        groups[str(seed)] = {"false_literal_rows": len(rows), "affected_distinct_problems": len(ids), "case_ids": ids,
                             "planned_problems_at_seed": sum(run_seed == seed for _, run_seed in runs)}
    false_rows = [row for rows in by_seed.values() for row in rows]
    false_summary = {"rows": len(false_rows), "distinct_problems": len({row["case_id"] for row in false_rows}),
                     "seeded_trajectories": len({(row["case_id"], row["seed"]) for row in false_rows}),
                     "by_seed": groups, "row_metadata": false_rows}
    return counts, unknowns, false_summary, relation_ids, role_ready, rebase_ready


def main():
    manifest = load("COVERAGE_RETRIEVAL_MANIFEST.json")
    hashes = verify_manifest(manifest)
    data = load("DATA_MANIFEST.json")
    protocol = load("COVERAGE_PROTOCOL.json")
    seeds = tuple(data["seed_slots"])
    need(data["questions"] == protocol["questions"] == 24 and seeds == tuple(protocol["seeds"]) and len(set(seeds)) == 2,
         "Data and protocol disagree on 24×2")
    expected = {(f"D2_{index:02}", seed) for index in range(1, 25) for seed in seeds}
    pair_selection = load("PAIR_SELECTION.json")
    selected = pair_selection["selected"]
    selection_map = {(row["case_id"], row["seed"]): row for row in selected}
    need(pair_selection["status"] == "FROZEN" and len(selection_map) == len(selected) == len({row["case_id"] for row in selected}),
         "Selection identity is not frozen and unique")
    runs = {}
    selected_sources = []
    for relative, digest in sorted(hashes.items()):
        if not relative.endswith("/result.json"):
            continue
        result = load(relative)
        key = (result["case_id"], result["seed"])
        need(key in expected and key not in runs, "Unexpected or duplicate trajectory")
        worker = (int(key[0].split("_")[-1]) - 1 + seeds.index(key[1])) % 2
        need(relative == f"native_results/worker_{worker}/{key[0]}_{key[1]}/result.json", "Worker or raw result identity differs")
        runs[key] = {"result_path": relative, "result_sha256": digest, "worker": worker, **result_work(result),
                     "elapsed_seconds": result["elapsed_seconds"], "EOS": result["EOS"], "think_closed": result["think_closed"],
                     "context_cap": result["hit_context_cap"], "recorded_steps": len(result["steps"]), "event_steps": len(result["events"])}
        if key in selection_map:
            selected_sources.append(verify_selected(selection_map[key], result, relative, digest))
    need(set(runs) == expected and len(selected_sources) == len(selected), "Coverage or selected source is incomplete")
    for worker in (0, 1):
        summary = load(f"native_results/worker_{worker}/summary.json")
        expected_worker = {key for key, row in runs.items() if row["worker"] == worker}
        keys = {(row["case_id"], row["seed"]) for row in summary["cases"]}
        need(summary["status"] == "COMPLETE" and summary["completed"] == len(keys) == len(summary["cases"]) == 24
             and keys == expected_worker, "Worker summary is incomplete")
        for item in summary["cases"]:
            row = runs[(item["case_id"], item["seed"])]
            need(item["EOS"] == row["EOS"] and item["new_tokens"] == row["generated_tokens"] and item["elapsed_seconds"] == row["elapsed_seconds"],
                 "Worker summary and raw terminal metadata disagree")
    summed = {key: sum(row[key] for row in runs.values()) for key in
              ("prompt_tokens", "generated_tokens", "forward_calls", "forward_input_tokens", "prefill_forward_input_tokens",
               "decode_forward_input_tokens", "causal_attention_token_pairs", "EOS", "context_cap", "think_closed", "recorded_steps", "event_steps")}
    launch = load("coverage_launcher.json")
    need(launch["status"] == "FINISHED" and len(launch["workers"]) == 2 and all(row["exit_code"] == 0 for row in launch["workers"]),
         "Coverage launch has an incomplete worker")
    gpu_seconds = fsum(row["elapsed_seconds"] for row in launch["workers"])
    run_seconds = fsum(row["elapsed_seconds"] for row in runs.values())
    checker, unknowns, false_literals, relation_ids, role_ready, rebase_ready = recount_relations(seeds, runs, hashes)
    audit = load("COVERAGE_AUDIT.json")
    need(audit["integrity_status"] == "PASS" and audit["retrieval_manifest_sha256"] == sha((ROOT / "COVERAGE_RETRIEVAL_MANIFEST.json").read_bytes()),
         "Primary audit references a different retrieval")
    need(dict(checker) == audit["checker_status_counts"] and dict(unknowns) == audit["unknown_reason_counts"], "Relation recount differs")
    for key in ("EOS", "context_cap", "generated_tokens", "forward_calls", "forward_input_tokens", "event_steps"):
        need(summed[key] == audit["counts"][key], f"Raw aggregate differs for {key}")
    need(summed["recorded_steps"] == audit["counts"]["complete_steps"] and isclose(gpu_seconds, audit["observed_GPU_seconds_from_launcher"], abs_tol=1e-7),
         "Step count or GPU seconds differ")
    need(false_literals["rows"] == audit["counts"]["invalid_literal_relations"], "False literal recount differs")
    for selected_row in selected:
        if selected_row["relation_id"] is not None:
            rel = relation_ids[selected_row["relation_id"]]
            for key in ("case_id", "seed", "step", "source_result_sha256", "generated_count", "observed_prefix_sha256"):
                need(selected_row[key] == rel[key], "Selected relation provenance differs")
    report = {"status": "PASS", "date": "2026-11-07", "distinct_problems": 24, "seeded_trajectories": len(runs),
              "seed_slots": list(seeds), "verified_retrieval_members": len(hashes), "selected_sources_verified": selected_sources,
              "counts": summed, "GPU_seconds_from_launcher": gpu_seconds, "GPU_minutes_from_launcher": gpu_seconds / 60,
              "parallel_launcher_wall_seconds": launch["elapsed_seconds"], "sum_raw_case_elapsed_seconds": run_seconds,
              "worker_elapsed_seconds": {str(row["worker"]): row["elapsed_seconds"] for row in launch["workers"]},
              "checker_status_counts": dict(checker), "unknown_reason_counts": dict(unknowns), "false_closed_literal_targets": false_literals,
              "role_certified_rows_at_coverage_freeze": role_ready, "rebase_eligible_rows_at_coverage_freeze": rebase_ready,
              "data_manifest_sha256": sha((ROOT / "DATA_MANIFEST.json").read_bytes()),
              "retrieval_manifest_sha256": sha((ROOT / "COVERAGE_RETRIEVAL_MANIFEST.json").read_bytes()),
              "coverage_audit_sha256": sha((ROOT / "COVERAGE_AUDIT.json").read_bytes()),
              "selection_sha256": sha((ROOT / "PAIR_SELECTION.json").read_bytes()),
              "relation_rows_sha256": sha((ROOT / "COVERAGE_RELATIONS.jsonl").read_bytes()),
              "scope": "Byte checks, terminal metadata, forward ledgers, selected prefix hashes and recorded literal checker outcomes. Role review and answer scoring are separate.",
              "run_metadata": [{"case_id": key[0], "seed": key[1], **value} for key, value in sorted(runs.items())]}
    path = ROOT / "INDEPENDENT_COVERAGE_RECOUNT.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("run_metadata", "false_closed_literal_targets", "selected_sources_verified")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
