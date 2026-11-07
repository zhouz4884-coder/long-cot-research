"""Offline coverage, literal-check and fixed-pairing audit over observed records."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import natural_evidence
from observations import Observer


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
POLICY_SHA256 = "0bfc35436adec250b61035a9bbfa34fc762feb83fa582c9c5c1c4d256d7adc55"
DECISIVE = frozenset(("VERIFIED", "INVALID_JUSTIFICATION", "REFUTED_CLAIM"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def digest_ids(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.name == "PAIR_SELECTION.json" and path.exists():
        previous = read_json(path)
        if previous.get("status") == "FROZEN" and path.read_bytes() != raw:
            raise ValueError("A frozen pair selection would change")
    temp = path.with_name(path.name + ".audit.tmp")
    temp.write_bytes(raw)
    temp.replace(path)


def write_rows(path, rows):
    raw = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(raw, encoding="utf-8")


def frozen_source(root, name):
    path = root / name
    if path.exists():
        return path
    if name == "p0_base_frozen.py":
        return PROJECT / "research/direction_selection_20261105/real_model_p0.py"
    return PROJECT / "research/phase5d_scope_rebase_20261106" / name


def candidate_key(row):
    return (row["priority"], row["case_id"], row["seed"], row["step"], row["equation_index"])


def select_pairs(candidates, limit):
    """Category priority then frozen lexical ties, with one event per problem."""
    selected, excluded, seen = [], [], set()
    for row in sorted(candidates, key=candidate_key):
        if row["case_id"] in seen:
            excluded.append({"candidate_id": row["candidate_id"], "reason": "same_problem_already_selected"})
        elif len(selected) >= limit:
            excluded.append({"candidate_id": row["candidate_id"], "reason": "distinct_problem_limit"})
        else:
            selected.append(row)
            seen.add(row["case_id"])
    return selected, excluded


class SavedByteState:
    def __init__(self, encoded):
        self.raw = base64.b64decode(encoded, validate=True)

    def cpu(self):
        return self

    def tolist(self):
        return list(self.raw)


def replay_observer(row, tokenizer, open_id, close_id, eos_ids):
    """Re-decode event boundaries while checking recorded RNG bytes by identity."""
    observer = Observer()
    prompt, generated = row["prompt_ids"], row["generated_ids"]
    event_by_end = {event["end"]: event for event in row["events"] if event["thinking_open"]}

    class SavedRNG:
        current_end = None

        def get_state(self):
            return SavedByteState(event_by_end[self.current_end]["rng_state_base64"])

    rng = SavedRNG()
    engine = type("DecodeOnlyEngine", (), {"tokenizer": tokenizer})()
    thinking = open_id in prompt
    if thinking:
        observer.open(0)
    for end, token in enumerate(generated, 1):
        if token == open_id:
            thinking = True
            observer.open(end)
        elif token == close_id:
            observer.complete(engine, prompt, generated, end - 1, rng, open_thinking=False, boundary="think_close")
            observer.step_start = None
            thinking = False
        if token in eos_ids or len(prompt) + end >= row["context_capacity"]:
            break
        if thinking and tokenizer.decode(generated[max(0, end - 8):end], skip_special_tokens=False).endswith("\n\n"):
            rng.current_end = end
            observer.complete(engine, prompt, generated, end, rng, open_thinking=True, boundary="paragraph")
    return observer


def candidate_record(row, relative, event, relation, check, priority):
    end = event["end"]
    prefix_hash = digest_ids(row["prompt_ids"] + row["generated_ids"][:end])
    candidate = {
        "case_id": row["case_id"], "seed": row["seed"], "step": event["step"],
        "equation_index": relation.get("equation_index", 0) if relation is not None else -1,
        "generated_count": end, "observed_prefix_sha256": prefix_hash,
        "source_result": relative, "source_result_sha256": row["source_result_sha256"],
        "event": event, "relation": relation, "check_result": check,
        "priority": priority, "source_decode_validation": row["source_decode_validation"],
        "role_certified": False, "role_review_status": "PENDING_INDEPENDENT_PRE_GOLD_REVIEW",
        "rebase_eligible": False,
        "isolation_generation_requires": "Validate the observed paragraph with the real model tokenizer before generation",
    }
    candidate["candidate_id"] = digest({key: candidate[key] for key in (
        "case_id", "seed", "step", "equation_index", "observed_prefix_sha256", "relation",
    )})
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if sha(root / "PAIRING_PROTOCOL.json") != POLICY_SHA256:
        raise ValueError("Pairing policy differs from the declared pre-inspection policy")
    policy = read_json(root / "PAIRING_PROTOCOL.json")
    protocol = read_json(root / "COVERAGE_PROTOCOL.json")
    data = read_json(root / "DATA_MANIFEST.json")
    retrieval = read_json(root / "COVERAGE_RETRIEVAL_MANIFEST.json")
    retrieved_files = {entry["path"]: entry for entry in retrieval["files"]}
    launcher = read_json(root / "coverage_launcher.json")
    complete_launcher = launcher["status"] == "FINISHED"
    if not complete_launcher and not args.allow_partial:
        raise RuntimeError("Collection is running. Pass --allow-partial for coverage without final selection")
    # Bind offline extraction before opening any generated body.
    analysis_binding = {
        "pairing_protocol_sha256": POLICY_SHA256,
        "auditor_sha256": sha(Path(__file__)),
        "natural_evidence_sha256": sha(root / "natural_evidence.py"),
        "checker_sha256": sha(root / "restricted_math_checker.py"),
    }
    binding_path = root / "COVERAGE_ANALYSIS_FREEZE.json"
    if binding_path.exists() and read_json(binding_path) != analysis_binding:
        raise ValueError("Offline analysis source differs from its first inspection binding")
    if not binding_path.exists():
        write_json(binding_path, analysis_binding)
    checks = []

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    check("retrieved_launcher_bytes", sha(root / "coverage_launcher.json") == retrieved_files["coverage_launcher.json"]["sha256"])
    for entry in read_json(root / "coverage_freeze.json")["files"]:
        check("source_" + entry["path"], sha(frozen_source(root, entry["path"])) == entry["sha256"])
    visible = [json.loads(line) for line in (root / "d2_visible.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    check("visible_bytes", sha(root / "d2_visible.jsonl") == data["visible_sha256"])
    check("24_distinct_question_ids", len(visible) == data["questions"] == 24 and len({c["case_id"] for c in visible}) == 24)
    expected = {(case["case_id"], seed): (case, (index + seed_index) % 2)
                for index, case in enumerate(visible) for seed_index, seed in enumerate(protocol["seeds"])}
    check("48_seeded_tasks", len(expected) == 48)
    tokenizer = None
    if args.tokenizer:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        sys.path.insert(0, str(PROJECT / "research/p05_design_review_20261105/runtime4552"))
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True, trust_remote_code=False)
    trajectory_rows, relation_rows, event_rows, candidates, exclusions = [], [], [], [], []
    statuses, unknown_reasons = Counter(), Counter()
    parsed_tasks, decisive_tasks, event_tasks = set(), set(), set()
    live_decisive_tasks, literal_tasks, scope_bound_tasks = set(), set(), set()
    result_files = []
    for relative in sorted(name for name in retrieved_files if name.endswith("/result.json")):
        path = root / relative
        check("retrieved_" + relative, sha(path) == retrieved_files[relative]["sha256"])
        row = read_json(path)
        key = row["case_id"], row["seed"]
        check("expected_" + relative, key in expected)
        case, worker = expected[key]
        check("unique_" + relative, key not in {tuple(r["task_key"]) for r in trajectory_rows})
        check("worker_" + relative, path.parent.parent.name == f"worker_{worker}")
        check("completed_" + relative, row["status"] == "COMPLETE")
        manifest = read_json(path.parent.parent / "manifest.json")
        manifest_relative = (path.parent.parent / "manifest.json").relative_to(root).as_posix()
        check("retrieved_manifest_" + relative, sha(root / manifest_relative) == retrieved_files[manifest_relative]["sha256"])
        assets = manifest["model_files"]
        aggregate = hashlib.sha256(json.dumps(assets["files"], sort_keys=True).encode()).hexdigest()
        check("model_" + relative, aggregate == assets["manifest_sha256"] == protocol["model_manifest"])
        check("runtime_" + relative, manifest["torch"] == "2.8.0+cu128" and manifest["transformers"] == "4.55.2"
              and manifest["dtype"] == "FP16" and manifest["backend"] == "sdpa" and manifest["scientific_new_token_cap"] is None)
        if tokenizer is not None:
            asset_by = {r["name"]: r for r in assets["files"]}
            for name in ("tokenizer.json", "tokenizer_config.json", "generation_config.json"):
                local = args.tokenizer / name
                if local.exists():
                    check("tokenizer_" + relative + name, sha(local) == asset_by[name]["sha256"])
        generated, prompt = row["generated_ids"], row["prompt_ids"]
        check("capacity_" + relative, bool(prompt) and bool(generated) and row["context_capacity"] == manifest["context_capacity"]
              and len(prompt) + len(generated) <= row["context_capacity"])
        check("IDs_" + relative, len(generated) == row["new_tokens"] and digest_ids(generated) == row["generated_sha256"]
              and digest_ids(prompt) == row["prompt_sha256"] and row["question_hash"] == case["problem_hash"])
        eos = {151643, 151645}
        generation_config = args.tokenizer / "generation_config.json" if args.tokenizer else None
        if generation_config is not None and generation_config.exists():
            eos_value = read_json(generation_config)["eos_token_id"]
            eos = set(eos_value if isinstance(eos_value, list) else [eos_value])
        check("termination_" + relative, (row["EOS"] and row["stop_reason"] == "EOS" and generated[-1] in eos and not row["hit_context_cap"])
              or (row["hit_context_cap"] and row["stop_reason"] == "CONTEXT_CAP" and not row["EOS"]
                  and len(prompt) + len(generated) == row["context_capacity"]))
        check("first_EOS_" + relative, all(token not in eos for token in generated[:-1]))
        expected_ledger = []
        for start in range(0, len(prompt), 256):
            expected_ledger.append({"stage": "native_prefill", "input_tokens": min(256, len(prompt) - start), "past_tokens": start, "position_start": start})
        for index in range(len(generated) - 1):
            past = len(prompt) + index
            expected_ledger.append({"stage": "native_decode", "input_tokens": 1, "past_tokens": past, "position_start": past})
        check("ledger_" + relative, row["ledger"] == expected_ledger)
        check("sampling_" + relative, row["sampling"] == {"temperature": .6, "top_p": .95, "top_k": 20, "min_p": 0, "batch": 1})
        row["source_result_sha256"] = sha(path)
        row["source_decode_validation"] = "NOT_RUN"
        if tokenizer is not None:
            messages = [{"role": "user", "content": case["question"] +
                         "\nPlease reason step by step, and put your final answer within \\boxed{}."}]
            native_prompt = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=True)
            closed_prompt = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
            check("native_prompt_" + relative, prompt == native_prompt and native_prompt != closed_prompt)
            text = tokenizer.decode(generated, skip_special_tokens=False)
            check("text_" + relative, text == row["text"])
            op = tokenizer.encode("<think>", add_special_tokens=False)[0]
            cl = tokenizer.encode("</think>", add_special_tokens=False)[0]
            replayed = replay_observer(row, tokenizer, op, cl, eos)
            check("observer_steps_" + relative, replayed.steps == row["steps"])
            check("observer_events_" + relative, replayed.events == row["events"])
            check("observer_checkpoints_" + relative, replayed.checkpoints == row["checkpoints"])
            row["source_decode_validation"] = "PASS"
        events_by_step = {event["step"]: event for event in row["events"]}
        if row["events"]:
            event_tasks.add(key)
        for event in row["events"]:
            check("event_step_" + relative + str(event["step"]), 0 <= event["step"] < len(row["steps"]))
            observed_step = row["steps"][event["step"]]
            check("event_span_" + relative + str(event["step"]), event["start"] == observed_step["start"]
                  and event["end"] == observed_step["end"] and event["types"] == observed_step["event_types"])
            if event["thinking_open"]:
                state = base64.b64decode(event["rng_state_base64"], validate=True)
                check("RNG_" + relative + str(event["step"]), bool(state))
            event_rows.append({"case_id": row["case_id"], "seed": row["seed"], "source_result": relative,
                               "source_result_sha256": row["source_result_sha256"], "event": event})
        for step in row["steps"]:
            check("span_" + relative + str(step["step"]), 0 <= step["start"] < step["end"] <= len(generated))
            event = events_by_step.get(step["step"])
            live = event is not None and event["thinking_open"] and step["boundary"] == "paragraph" and "rng_state_base64" in event
            prefix_sha = digest_ids(prompt + generated[:step["end"]])
            for ordinal, extracted in enumerate(natural_evidence.relations(step)):
                relation = {**extracted, "observed_prefix_sha256": prefix_sha}
                outcome = natural_evidence.check_relation(relation)
                statuses[outcome["status"]] += 1
                if outcome["status"] == "UNKNOWN":
                    unknown_reasons[outcome["reason"]] += 1
                parsed = relation["status"] == "parsed"
                decisive = outcome["status"] in DECISIVE
                closed_literal = parsed and not relation.get("variables") and relation.get("certificate_type") == "ARITHMETIC_EQ"
                if parsed:
                    parsed_tasks.add(key)
                if decisive:
                    decisive_tasks.add(key)
                if closed_literal:
                    literal_tasks.add(key)
                if parsed and relation.get("variables"):
                    scope_bound_tasks.add(key)
                if decisive and live:
                    live_decisive_tasks.add(key)
                record = {
                    "case_id": row["case_id"], "seed": row["seed"], "step": step["step"],
                    "equation_index": relation.get("equation_index", ordinal),
                    "source_result": relative, "source_result_sha256": row["source_result_sha256"],
                    "observed_prefix_sha256": prefix_sha, "generated_count": step["end"],
                    "relation": relation, "check_result": outcome, "literal_checkable": closed_literal,
                    "decisive": decisive, "live_paragraph_checkpoint": live,
                    "actionable_role_candidate": bool(relation.get("actionable_role_candidate")),
                    "role_certified": False, "rebase_eligible": False,
                }
                record["relation_id"] = digest({k: record[k] for k in ("case_id", "seed", "step", "equation_index", "relation")})
                relation_rows.append(record)
                if not live:
                    exclusions.append({"relation_id": record["relation_id"], "reason": "no_live_observed_paragraph_checkpoint"})
                elif not decisive:
                    exclusions.append({"relation_id": record["relation_id"], "reason": "checker_not_decisive", "checker_reason": outcome.get("reason")})
                else:
                    priority = 0 if outcome["status"] == "INVALID_JUSTIFICATION" and closed_literal and relation.get("actionable_role_candidate") else 1
                    candidate = candidate_record(row, relative, event, relation, outcome, priority)
                    candidate["relation_id"] = record["relation_id"]
                    candidates.append(candidate)
            if live and "reflection_cue" in event["types"]:
                candidates.append(candidate_record(row, relative, event, None, None, 2))
        trajectory_rows.append({"task_key": list(key), "case_id": row["case_id"], "seed": row["seed"],
            "source_result": relative, "source_result_sha256": row["source_result_sha256"],
            "EOS": row["EOS"], "context_cap": row["hit_context_cap"], "think_closed": row["think_closed"],
            "new_tokens": row["new_tokens"], "steps": len(row["steps"]), "event_steps": len(row["events"]),
            "source_decode_validation": row["source_decode_validation"],
            "forward_calls": len(expected_ledger), "forward_input_tokens": sum(r["input_tokens"] for r in expected_ledger)})
        result_files.append({"path": relative, "sha256": row["source_result_sha256"]})
    observed_keys = {tuple(r["task_key"]) for r in trajectory_rows}
    missing = sorted(set(expected) - observed_keys)
    final = complete_launcher and not missing
    selected, selection_excluded = select_pairs(candidates, policy["max_distinct_problem_ids"]) if final else ([], [])
    selection = {
        "status": "FROZEN" if final else "PARTIAL_NO_FINAL_SELECTION", "policy_sha256": POLICY_SHA256,
        "analysis_binding": analysis_binding, "planned_problems": 24, "planned_trajectories": 48,
        "completed_trajectories": len(trajectory_rows), "selected": selected,
        "selection_exclusions": selection_excluded,
        "source_decode_validation": "PASS" if tokenizer is not None else "NOT_RUN",
        "repair_role_review": "All role_certified flags remain false until two pre-Gold observed-prefix reviews agree",
    }
    write_json(root / "PAIR_SELECTION.json", selection)
    counts = {
        "planned_problems": 24, "planned_seeded_trajectories": 48,
        "completed_trajectories": len(trajectory_rows), "missing_trajectories": len(missing),
        "observed_problem_ids": len({r["case_id"] for r in trajectory_rows}),
        "complete_steps": sum(r["steps"] for r in trajectory_rows),
        "event_steps": sum(r["event_steps"] for r in trajectory_rows),
        "trajectories_with_events": len(event_tasks), "trajectories_with_parsed_relation": len(parsed_tasks),
        "trajectories_with_literal_checkable_relation": len(literal_tasks),
        "trajectories_with_scope_bound_symbolic_relation": len(scope_bound_tasks),
        "trajectories_with_decisive_relation": len(decisive_tasks),
        "trajectories_with_live_decisive_relation": len(live_decisive_tasks),
        "extracted_relations": len(relation_rows),
        "literal_checkable_relations": sum(r["literal_checkable"] for r in relation_rows),
        "scope_bound_symbolic_relations": sum(r["relation"]["status"] == "parsed" and bool(r["relation"].get("variables")) for r in relation_rows),
        "decisive_relations": sum(r["decisive"] for r in relation_rows),
        "decisive_literal_relations": sum(r["decisive"] and r["literal_checkable"] for r in relation_rows),
        "invalid_literal_relations": sum(r["check_result"]["status"] == "INVALID_JUSTIFICATION" and r["literal_checkable"] for r in relation_rows),
        "lexical_invalid_actionable_candidates": sum(r["check_result"]["status"] == "INVALID_JUSTIFICATION" and r["literal_checkable"] and r["actionable_role_candidate"] for r in relation_rows),
        "role_certified_actionable_errors": 0, "rebase_eligible_events": 0,
        "eligible_pair_candidates": len(candidates), "selected_distinct_problem_ids": len(selected),
        "EOS": sum(r["EOS"] for r in trajectory_rows), "context_cap": sum(r["context_cap"] for r in trajectory_rows),
        "generated_tokens": sum(r["new_tokens"] for r in trajectory_rows),
        "forward_calls": sum(r["forward_calls"] for r in trajectory_rows),
        "forward_input_tokens": sum(r["forward_input_tokens"] for r in trajectory_rows),
    }
    ratios = {
        "observed_event_trajectory_fraction_of_planned48": len(event_tasks) / 48,
        "parsed_given_observed_event": len(parsed_tasks) / len(event_tasks) if event_tasks else None,
        "decisive_given_parsed": len(decisive_tasks) / len(parsed_tasks) if parsed_tasks else None,
        "observed_decisive_trajectory_fraction_of_planned48": len(decisive_tasks) / 48,
        "scope": "Literal/explicit-scope checking coverage. Partial counts are confirmed observed-window lower bounds; role/actionability has separate reviews.",
    }
    check("coverage_chain_consistent", parsed_tasks <= event_tasks and decisive_tasks <= parsed_tasks)
    check("result_bytes_unchanged", all(sha(root / r["path"]) == r["sha256"] for r in result_files))
    report = {
        "status": "COMPLETE" if final else "PARTIAL", "integrity_status": "PASS",
        "policy_sha256": POLICY_SHA256, "analysis_binding": analysis_binding, "checks_passed": len(checks),
        "retrieval_manifest_sha256": sha(root / "COVERAGE_RETRIEVAL_MANIFEST.json"),
        "counts": counts, "checker_status_counts": dict(statuses), "unknown_reason_counts": dict(unknown_reasons),
        "coverage_ratios": ratios, "missing_task_keys": [list(k) for k in missing],
        "trajectories": trajectory_rows, "worker_processes": launcher.get("workers", []),
        "process_observation": retrieval.get("process_observation"),
        "observed_GPU_seconds_from_launcher": sum(w.get("elapsed_seconds", 0) for w in launcher.get("workers", [])),
        "source_decode_validation": "PASS" if tokenizer is not None else "NOT_RUN",
        "exclusions": exclusions,
        "scope": "No Gold, answer accuracy or false-accept/reject rates evaluated. Literal truth and proof-role actionability are separate.",
    }
    write_rows(root / "COVERAGE_RELATIONS.jsonl", relation_rows)
    write_rows(root / "COVERAGE_EVENT_CHECKPOINTS.jsonl", event_rows)
    write_json(root / "COVERAGE_AUDIT.json", report)
    text = ["# D2自然覆盖审计", "", "本次状态为 " + report["status"] + "。完整性检查通过。", "",
            "24问题、48种子轨迹的计划分母保留。已完成轨迹、事件、关系和可执行字面检查分列。", "",
            "```json", json.dumps(counts, ensure_ascii=False, indent=2), "```", "",
            "字面关系的真/假不自动认证其在推导中的作用。所有role_certified保持false，正式修复需要两份独立前缀审查。", "",
            "源码解码复核为 " + report["source_decode_validation"] + "。配对执行前需真实tokenizer验证完整段落。", "",
            "收集未全部完成时只报部分覆盖，最终配对选择为空。选择完成后按冻结优先层和字典序，每问题最多一事件。", "",
            "逐关系见COVERAGE_RELATIONS.jsonl，所有排除见COVERAGE_AUDIT.json，配对输入见PAIR_SELECTION.json。"]
    (root / "COVERAGE_AUDIT_ZH.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": counts, "checker_status_counts": dict(statuses),
                      "worker_processes": report["worker_processes"], "source_decode_validation": report["source_decode_validation"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
