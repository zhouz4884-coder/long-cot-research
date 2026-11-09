"""Gold-blind replay of typed extraction, bounded checking, and action eligibility."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D2 = ROOT.parent / "phase5d2_quarantined_rebase_20261107"
LEGACY = ROOT / "legacy" if (ROOT / "legacy").is_dir() else D2
sys.path.append(str(LEGACY))
RUNTIME = ROOT.parent / "p05_design_review_20261105" / "runtime4552"
if RUNTIME.is_dir():
    sys.path.insert(0, str(RUNTIME))

_CODE_FILES = ("symbol_scope.py", "typed_math_events.py", "proposal_check.py")
_START_CODE = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in _CODE_FILES}

from natural_evidence import parse_expression
from proposal_check import check_event
from symbol_scope import apply_observed_step, scope_from_problem
from typed_math_events import extract_events


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def read_lines(path):
    return list(map(json.loads, path.read_bytes().splitlines()))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def id_hash(ids):
    return sha(json.dumps(ids, separators=(",", ":")).encode())


def native_sources(bank, root):
    if bank == "d2":
        by_id = {row["case_id"]: row for row in read_lines(D2 / "d2_visible.jsonl")}
        for entry in read(D2 / "GENERATION_FREEZE.json")["records"]:
            if entry["bank"] != "all_natural":
                continue
            raw = (D2 / entry["path"]).read_bytes()
            if sha(raw) != entry["sha256"]:
                raise ValueError("Inherited raw trajectory changed")
            yield json.loads(raw), by_id[entry["case_id"]]["question"], entry["sha256"], entry["path"]
    else:
        by_id = {row["case_id"]: row for row in read_lines(ROOT / "prepared_data" / bank / "visible.jsonl")}
        paths = sorted((root / "native_results").glob("worker_*/*/result.json"))
        data = read(ROOT / "D3_DATA_FREEZE.json")["banks"][bank]
        if len(paths) != data["count"] * len(data["seeds"]):
            raise ValueError("A partial bank cannot be represented as complete")
        seen = set()
        for path in paths:
            raw = path.read_bytes()
            row = json.loads(raw)
            case = by_id[row["case_id"]]
            key = (row["case_id"], row["seed"])
            if key in seen or row["seed"] not in data["seeds"] or row["question_hash"] != case["problem_hash"]:
                raise ValueError("Bank membership or problem identity drifted")
            seen.add(key)
            yield row, case["question"], sha(raw), path.relative_to(ROOT).as_posix()


def scoped_step(scope, generated, step, tokenizer):
    if step["end"] > len(generated):
        raise ValueError("Observed step exceeds the native history")
    scope = scope.advance_prefix(generated[:step["end"]])
    return apply_observed_step(scope, step, tokenizer, parse_expression)


def analyze(source, question, digest, source_path, tokenizer, stream, inherited):
    prompt = source["prompt_ids"]
    generated = source["generated_ids"]
    if id_hash(prompt) != source["prompt_sha256"] or id_hash(generated) != source["generated_sha256"]:
        raise ValueError("Raw trajectory token hashes differ")
    scope = scope_from_problem(prompt, question, tokenizer, parse_expression)
    counts = Counter()
    kinds, reasons, statuses = Counter(), Counter(), Counter()
    history, matched = [], []
    for step in source["steps"]:
        counts["observed_steps"] += 1
        predecessor = scope if history else None
        scope = scoped_step(scope, generated, step, tokenizer)
        prefix = scope.observed_prefix_sha256
        events = extract_events(step, observed_prefix_sha256=prefix, prior_steps=history[-16:])
        if step.get("event_types") or events:
            counts["steps_with_lexical_or_typed_event"] += 1
        history.append(step)
        step_records = []
        for event in events:
            counts["extracted_objects"] += 1
            kinds[event.kind] += 1
            statement = event.statement
            if statement and event.kind != "UNSUPPORTED":
                counts["typed_objects_with_statement"] += 1
            resolution = None
            if event.variables:
                counts["symbolic_objects"] += 1
                resolution = scope.resolve_expression(event.variables, target_token_span=event.source.token_span,
                                                      target_char_span=event.source.char_span)
                if resolution.status == "BOUND":
                    counts["reliably_bound_symbolic_objects"] += 1
                    counts["scope_authority_" + resolution.authority.lower()] += 1
            else:
                counts["objects_without_free_variables"] += 1
            checked = check_event(event, scope=scope, predecessor_scope=predecessor)
            statuses[checked["status"]] += 1
            if checked["status"] == "UNKNOWN":
                reasons[checked["reason"]] += 1
            counts["actual_checker_executions"] += bool(checked.get("exact_checks"))
            counts["conclusive_math_results"] += checked["status"] != "UNKNOWN"
            counts["proved_false_without_action"] += checked.get("truth") is False and checked.get("action") == "NONE"
            counts["certificate_permits_action"] += checked.get("action") not in ("NONE", None)
            record = {"case_id": source["case_id"], "seed": source["seed"], "step": step["step"],
                      "source_result_sha256": digest, "event": event.as_dict(),
                      "symbol_scope_status": None if resolution is None else resolution.status,
                      "symbol_scope_reason": None if resolution is None else resolution.reason,
                      "symbol_scope_authority": None if resolution is None else resolution.authority,
                      "check": checked,
                      "executable_revision": False,
                      "revision_status": "requires_independent_role_and_live_plan" if checked.get("truth") is False else "no_adverse_proof_verified"}
            step_records.append(record)
            stream.write((json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode())
        for old in inherited.get(step["step"], ()):
            relation = old["relation"]
            match = next((r for r in step_records if r["event"]["normalized"] == relation["normalized"]
                          and r["event"]["source"]["char_span"] == relation["char_span_in_step"]), None)
            cutoff = scope.resolve_expression(relation["variables"], target_token_span=tuple(relation["token_span"]),
                                              target_char_span=tuple(relation["char_span_in_step"]))
            if prefix != old["observed_prefix_sha256"]:
                raise ValueError("Historical relation prefix hash was not reconstructed exactly")
            matched.append({"case_id": source["case_id"], "seed": source["seed"], "step": step["step"],
                            "surface": relation["surface"], "old_relation_id": old["relation_id"],
                            "scope_status": cutoff.status, "scope_reason": cutoff.reason,
                            "scope_authority": cutoff.authority,
                            "typed_kind": None if match is None else match["event"]["kind"],
                            "checker_status": None if match is None else match["check"]["status"],
                            "checker_reason": None if match is None else match["check"]["reason"]})
    counts["executable_revisions"] = 0
    return {"case_id": source["case_id"], "seed": source["seed"], "source_path": source_path,
            "source_sha256": digest, "native_stop_reason": source["stop_reason"], "new_tokens": source["new_tokens"],
            "seconds": source["elapsed_seconds"], "counts": dict(counts), "kinds": dict(kinds),
            "unknown_reasons": dict(reasons), "verdicts": dict(statuses)}, matched


def historical_sources(tokenizer):
    manifest_path = REPO / "research/next_design_20261105/P1_sampling_manifest.json"
    index = read(REPO / "research/phase5b_boundary_20261106/NATURAL_TRIAGE_INDEX.json")
    if sha(manifest_path.read_bytes()) != index["manifest_sha256"]:
        raise ValueError("Historical triage selection changed")
    manifest = read(manifest_path)
    pool = manifest["eligible_pool"]
    lines = {}
    for file, expected in pool["source_file_sha256"].items():
        raw = Path(file).read_bytes()
        if sha(raw) != expected:
            raise ValueError("Historical raw input changed")
        lines[file] = raw.splitlines(keepends=True)
    qraw = Path(pool["question_source_path"]).read_bytes()
    if sha(qraw) != pool["question_source_sha256"]:
        raise ValueError("Historical question file changed")
    questions = {row["problem_id"]: row["question"] for row in map(json.loads, qraw.splitlines())}
    targets = set(index["target_ranks"] + index["control_ranks"])
    for case in manifest["cases"]:
        rank = case["sample_rank_1based"]
        if rank not in targets:
            continue
        raw = lines[case["source_path"]][case["source_line_number_1based"] - 1]
        if sha(raw) != case["source_line_sha256_including_line_ending"]:
            raise ValueError("Historical selected trajectory changed")
        row = json.loads(raw)
        ids = row["trace"]["ids"]
        if id_hash(ids) != case["trace_ids_sha256_json_compact_utf8"]:
            raise ValueError("Historical sampled token IDs changed")
        question = questions[case["problem_id"]]
        prompt = tokenizer.apply_chat_template([{"role": "user", "content": question}], tokenize=True,
                                               add_generation_prompt=True, enable_thinking=True)
        if not isinstance(prompt, list):
            raise ValueError("Expected tokenizer IDs for question-only offline grounding")
        steps, start = [], 0
        open_id = tokenizer.encode("<think>", add_special_tokens=False)[0]
        close_id = tokenizer.encode("</think>", add_special_tokens=False)[0]
        for index_id, token in enumerate(ids, 1):
            if token == open_id:
                start = index_id
                continue
            if token == close_id:
                break
            if tokenizer.decode(ids[max(0, index_id - 8):index_id], skip_special_tokens=False).endswith("\n\n"):
                text = tokenizer.decode(ids[start:index_id], skip_special_tokens=False)
                if text.strip():
                    steps.append({"step": len(steps), "start": start, "end": index_id, "text": text,
                                  "boundary": "paragraph"})
                start = index_id
        yield {"case_id": f"B_{rank:03d}", "seed": row["seed"], "prompt_ids": prompt, "prompt_sha256": id_hash(prompt),
               "generated_ids": ids, "generated_sha256": id_hash(ids), "steps": steps,
               "stop_reason": row["trace"]["stop_reason"], "new_tokens": len(ids), "elapsed_seconds": row["trace"]["ms"] / 1000}, \
              question, sha(raw), f"{Path(case['source_path']).name}:{case['source_line_number_1based']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", choices=("d2", "phase5b", "precheck", "bank"), required=True)
    ap.add_argument("--tokenizer", type=Path, required=True)
    ap.add_argument("--raw-root", type=Path)
    ap.add_argument("--tag", choices=("final", "v2", "v3"), default="final")
    args = ap.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True, trust_remote_code=False)
    inherited = defaultdict(lambda: defaultdict(list))
    if args.bank == "d2":
        for row in read_lines(D2 / "COVERAGE_RELATIONS.jsonl"):
            if row["check_result"]["reason"] == "symbolic_scope_unbound":
                inherited[row["case_id"], row["seed"]][row["step"]].append(row)
    raw_root = args.raw_root or ROOT / args.bank
    sources = historical_sources(tokenizer) if args.bank == "phase5b" else native_sources(args.bank, raw_root)
    out = ROOT / "diagnostics" / (args.bank if args.tag == "final" else f"{args.bank}_{args.tag}")
    out.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    rows, matched = [], []
    with (out / "TYPED_EVENT_REPLAY.jsonl").open("wb") as stream:
        for source, question, sha256, path in sources:
            summary, comparisons = analyze(source, question, sha256, path, tokenizer, stream,
                                           inherited.get((source["case_id"], source["seed"]), {}))
            rows.append(summary)
            matched.extend(comparisons)
    if args.bank == "d2" and (len(rows) != 48 or len(matched) != 162):
        raise ValueError("D2 denominator or exact prefix matching differs")
    if _START_CODE != {name: sha((ROOT / name).read_bytes()) for name in _CODE_FILES}:
        raise ValueError("Source changed during audit execution")
    aggregate = {}
    for field in ("counts", "kinds", "unknown_reasons", "verdicts"):
        total = Counter()
        for row in rows:
            total.update(row[field])
        aggregate[field] = dict(total)
    report = {"status": "COMPLETE", "bank": args.bank, "trajectory_count": len(rows),
              "distinct_problem_count": len({row["case_id"] for row in rows}), "aggregate": aggregate,
              "original_scope_unbound": len(matched),
              "original_scope_replay_reasons": dict(Counter(row["scope_reason"] or row["scope_status"] for row in matched)),
              "original_typed_replay_verdicts": dict(Counter(row["checker_status"] or "unmatched_typed_surface" for row in matched)),
              "frozen_code_sha256": _START_CODE,
              "evaluation_answers_read": False, "additional_gpu_seconds": 0, "cpu_wall_seconds": time.monotonic() - began,
              "historical_boundary": "Outcome-selected Phase5-B development subset. Recorded token IDs; question grounding replayed with an offline template; no original native RNG/KV or action permission." if args.bank == "phase5b" else None,
              "scope": "Each checked object is bounded by its observed prefix. Offline mathematical results do not grant live revision without independent source role and a supported plan.",
              "rows": rows}
    write(out / "TYPED_COVERAGE.json", report)
    if matched:
        write(out / "ORIGINAL_162_RECOUNT.json", matched)
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows",)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
