"""Freeze D3 audit checkpoints from the complete formal native bank."""

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
LEGACY = ROOT / "legacy"
for path in (LEGACY, ROOT.parent / "phase5d_scope_rebase_20261106", ROOT.parent / "phase5d2_quarantined_rebase_20261107"):
    if path.is_dir() and str(path) not in sys.path:
        sys.path.append(str(path))

from independent_audit import AuditRequest, digest
from natural_evidence import parse_expression
from native_d2_worker import MODEL_HASH, prompt_for, SAMPLING
from proposal_check import check_event, resolve_event_scope
from symbol_scope import apply_observed_step, scope_from_problem
from typed_math_events import canonical_json, extract_events


PROTOCOL_SHA256 = "7cfa11b0f2990e8ffbfd4e85a55671f616c2fba69db4802a8218bcfdb8248fda"
DATA_SHA256 = "fcb7720df07e82a1f8e8eb8993607f4451972e4c32a477c2afe0525ef3ad2507"
CODE_FILES = ("select_d3_events.py", "typed_math_events.py", "proposal_check.py", "symbol_scope.py", "independent_audit.py")
FORMAL_COUNT = 16
FORMAL_SEEDS = (20261109, 20261110)
MAX_PROBLEMS = 4
WITNESS_KINDS = frozenset({"SYMBOLIC_IDENTITY", "EQUATION_TRANSITION"})


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def bank_questions(root, visible=None):
    frozen_bytes = (root / "D3_DATA_FREEZE.json").read_bytes()
    if sha(frozen_bytes) != DATA_SHA256:
        raise ValueError("D3 data specification differs from the pre-output freeze")
    frozen = json.loads(frozen_bytes)
    spec = frozen["banks"]["bank"]
    if frozen["status"] != "FROZEN" or spec["count"] != FORMAL_COUNT or tuple(spec["seeds"]) != FORMAL_SEEDS:
        raise ValueError("Formal bank count or seeds changed")
    raw = (visible or root / "prepared_data/bank/visible.jsonl").read_bytes()
    if sha(raw) != spec["visible_sha256"]:
        raise ValueError("Visible question bank differs from the freeze")
    cases = [json.loads(line) for line in raw.splitlines()]
    if len(cases) != FORMAL_COUNT or [row["case_id"] for row in cases] != [row[0] for row in spec["selected_ids"]]:
        raise ValueError("Formal visible membership or ordering changed")
    return cases


def record_path(case_id, seed, worker):
    return f"bank/native_results/worker_{worker}/{case_id}_{seed}/result.json"


def verify_record(row, case, seed, tokenizer):
    prompt, generated = row["prompt_ids"], row["generated_ids"]
    if (row["case_id"], row["seed"], row["question_hash"]) != (case["case_id"], seed, case["problem_hash"]):
        raise ValueError("Native source does not match the frozen case")
    if (row["status"] != "COMPLETE" or row["sampling"] != SAMPLING or not generated
            or row["new_tokens"] != len(generated) or digest(prompt) != row["prompt_sha256"]
            or digest(generated) != row["generated_sha256"] or prompt != prompt_for(tokenizer, case["question"])):
        raise ValueError("Formal native source is incomplete or changed")
    stop = row["stop_reason"]
    if (stop not in ("EOS", "CONTEXT_CAP") or row["EOS"] != (stop == "EOS")
            or row["hit_context_cap"] != (stop == "CONTEXT_CAP")
            or len(prompt) + len(generated) > row["context_capacity"]
            or (stop == "CONTEXT_CAP" and len(prompt) + len(generated) != row["context_capacity"])):
        raise ValueError("Formal native source has an invalid termination record")
    eos_tags = [tokenizer.encode(tag, add_special_tokens=False) for tag in ("<|im_end|>", "<|endoftext|>")]
    if any(len(encoded) != 1 for encoded in eos_tags):
        raise ValueError("Native Qwen EOS tags are not atomic")
    eos = {encoded[0] for encoded in eos_tags}
    if any(token in eos for token in generated[:-1]) or (generated[-1] in eos) != (stop == "EOS"):
        raise ValueError("Formal native EOS record differs from the generated IDs")
    prefix = [{"stage": "native_prefill", "input_tokens": min(256, len(prompt) - start),
               "past_tokens": start, "position_start": start} for start in range(0, len(prompt), 256)]
    ledger = row["ledger"]
    if ledger[:len(prefix)] != prefix or len(ledger) != len(prefix) + len(generated) - 1:
        raise ValueError("Formal native forward ledger differs from the schedule")
    for start, item in enumerate(ledger[len(prefix):], len(prompt)):
        if item != {"stage": "native_decode", "input_tokens": 1, "past_tokens": start, "position_start": start}:
            raise ValueError("Formal native forward ledger differs from the schedule")


def complete_bank(root, tokenizer):
    retrieval_path = root / "BANK_RETRIEVAL.json"
    retrieval = read(retrieval_path)
    workers = retrieval["launcher"]["workers"]
    if (retrieval["status"] != "COMPLETE" or retrieval["mode"] != "bank"
            or retrieval["launcher"]["status"] != "FINISHED" or {row["worker"] for row in workers} != {0, 1}
            or len(workers) != 2 or any(row["exit_code"] != 0 for row in workers)):
        raise ValueError("Selection requires both formal workers to finish successfully")
    receipts = {row["path"]: row["sha256"] for row in retrieval["files"]}
    metadata = {}
    for worker in workers:
        index = worker["worker"]
        relative = f"bank/native_results/worker_{index}/manifest.json"
        raw = (root / relative).read_bytes()
        if sha(raw) != receipts.get(relative):
            raise ValueError("Formal worker manifest differs from its retrieval receipt")
        manifest = json.loads(raw)
        if (manifest["worker"] != index or manifest["gpu"] != worker["gpu"] or manifest["dtype"] != "FP16"
                or manifest["backend"] != "sdpa" or manifest["scientific_new_token_cap"] is not None
                or manifest["model_files"]["manifest_sha256"] != MODEL_HASH or manifest["sampling"] != SAMPLING
                or manifest["transformers"] != "4.55.2" or manifest["torch"].split("+")[0] != "2.8.0"):
            raise ValueError("Formal worker execution identity changed")
        metadata[index] = manifest
    cases = bank_questions(root)
    tasks = [(case, seed, (case_index + seed_index) % 2)
             for case_index, case in enumerate(cases) for seed_index, seed in enumerate(FORMAL_SEEDS)]
    expected_paths = {record_path(case["case_id"], seed, worker) for case, seed, worker in tasks}
    local_paths = {path.relative_to(root).as_posix() for path in (root / "bank/native_results").glob("worker_*/*/result.json")}
    if local_paths != expected_paths or {path for path in receipts if path.endswith("/result.json")} != expected_paths:
        raise ValueError("Complete formal bank and retrieval receipt disagree")
    for case, seed, worker in tasks:
        relative = record_path(case["case_id"], seed, worker)
        raw = (root / relative).read_bytes()
        if sha(raw) != receipts[relative]:
            raise ValueError("Formal source differs from its retrieval receipt")
        row = json.loads(raw)
        verify_record(row, case, seed, tokenizer)
        if row["context_capacity"] != metadata[worker]["context_capacity"]:
            raise ValueError("Formal source context capacity differs from its worker manifest")
        yield case, worker, relative, receipts[relative], row


def replay_steps(row, question, tokenizer, through_step=None):
    """Rebuild the scopes and events using only each already observed prefix."""
    scope = scope_from_problem(row["prompt_ids"], question, tokenizer, parse_expression)
    history = []
    previous_end = 0
    generated = row["generated_ids"]
    for index, step in enumerate(row["steps"]):
        if through_step is not None and index > through_step:
            return
        start, end = step["start"], step["end"]
        if step["step"] != index or not previous_end <= start < end <= len(generated):
            raise ValueError("Native step provenance is not ordered")
        if tokenizer.decode(generated[start:end], skip_special_tokens=False) != step["text"]:
            raise ValueError("Native step text differs from its recorded tokens")
        predecessor = scope
        scope = apply_observed_step(scope.advance_prefix(generated[:end]), step, tokenizer, parse_expression)
        events = extract_events(step, observed_prefix_sha256=scope.observed_prefix_sha256, prior_steps=history[-16:])
        yield step, scope, predecessor, events
        previous_end = end
        history.append(step)


def live_rng(row, step, tokenizer):
    record = next((event for event in row["events"] if event["step"] == step["step"]), None)
    if (record is None or record.get("thinking_open") is not True or step.get("boundary") != "paragraph"
            or not step["text"].endswith("\n\n")):
        return None
    if (record["start"], record["end"], record["types"]) != (step["start"], step["end"], step["event_types"]):
        raise ValueError("Live native observer event differs from the step")
    rng = base64.b64decode(record["rng_state_base64"], validate=True)
    if not rng or len(rng) > 65536:
        raise ValueError("Invalid live RNG state length")
    tags = [tokenizer.encode(tag, add_special_tokens=False) for tag in ("<think>", "</think>")]
    if any(len(encoded) != 1 for encoded in tags):
        raise ValueError("Unsupported native thinking boundary")
    open_id, close_id = (encoded[0] for encoded in tags)
    active = False
    for token in row["prompt_ids"] + row["generated_ids"][:step["end"]]:
        if token == open_id:
            active = True
        elif token == close_id:
            active = False
    if not active or step["end"] >= len(row["generated_ids"]):
        raise ValueError("Selected event is not an active native continuation")
    return sha(rng)


def scope_binding(event, scope, predecessor):
    if event.kind not in WITNESS_KINDS or not event.variables or not event.statement:
        return None, "not_a_typed_symbolic_witness_target"
    resolution = resolve_event_scope(event, scope)
    if resolution.status != "BOUND":
        return None, resolution.reason or "scope_unbound"
    checked = check_event(event, scope=scope, predecessor_scope=predecessor)
    binding = checked["binding"]
    if (binding is None or not checked["exact_checks"]
            or binding["scope_provenance"]["authority"] not in ("PROBLEM", "CONDITIONAL")):
        return None, checked["reason"]
    return {key: binding[key] for key in ("scope", "premises", "scope_provenance")}, None


def audit_requests(event, binding):
    """Only the scoped arm receives the domain and premise packet."""
    prefix = event.source.observed_prefix_sha256
    target = canonical_json(event.statement)
    variables = tuple(sorted(binding["scope"]["domains"]))
    scoped_packet = canonical_json({"domains": binding["scope"]["domains"],
                                    "premises": [row["predicate"] for row in binding["premises"]]})
    return {
        "UnscopedIndependent": AuditRequest(prefix, event.event_id, event.kind, target, (), variables),
        "ScopedIndependent": AuditRequest(prefix, event.event_id, event.kind, target, (scoped_packet,), variables),
    }


def choose(candidates):
    def order(row):
        source = row["event"]["source"]
        return (row["case_id"], row["seed"], row["step"], tuple(source["token_span"]),
                tuple(source["char_span"]), row["event_id"])

    selected, excluded, seen = [], Counter(), set()
    for row in sorted(candidates, key=order):
        if row["case_id"] in seen:
            excluded["same_problem_already_selected"] += 1
        elif len(selected) == MAX_PROBLEMS:
            excluded["four_distinct_problem_limit"] += 1
        else:
            selected.append(row)
            seen.add(row["case_id"])
    return selected, excluded


def select(root, tokenizer):
    if sha((root / "D3_PAIRING_PROTOCOL.json").read_bytes()) != PROTOCOL_SHA256:
        raise ValueError("D3 pairing protocol differs from the pre-output freeze")
    code = {name: sha((ROOT / name).read_bytes()) for name in CODE_FILES}
    candidates, exclusions = [], Counter()
    counts = Counter()
    for case, worker, path, source_hash, row in complete_bank(root, tokenizer):
        counts["completed_trajectories"] += 1
        for step, scope, predecessor, events in replay_steps(row, case["question"], tokenizer):
            counts["observed_steps"] += 1
            counts["typed_events"] += len(events)
            for event in events:
                if event.kind not in WITNESS_KINDS or not event.variables or not event.statement:
                    exclusions["not_a_typed_symbolic_witness_target"] += 1
                    continue
                counts["typed_symbolic_witness_targets"] += 1
                rng = live_rng(row, step, tokenizer)
                if rng is None:
                    exclusions["no_live_observed_rng"] += 1
                    continue
                counts["live_typed_symbolic_witness_targets"] += 1
                binding, reason = scope_binding(event, scope, predecessor)
                if binding is None:
                    exclusions[reason] += 1
                    continue
                try:
                    for request in audit_requests(event, binding).values():
                        request.render()
                except ValueError:
                    exclusions["audit_request_character_limit"] += 1
                    continue
                candidates.append({"case_id": case["case_id"], "seed": row["seed"], "worker": worker,
                                   "step": step["step"], "generated_count": step["end"],
                                   "observed_prefix_sha256": scope.observed_prefix_sha256,
                                   "source_result": path, "source_result_sha256": source_hash,
                                   "event_id": event.event_id, "event": event.as_dict(),
                                   "scope_binding_sha256": digest(binding), "rng_state_sha256": rng,
                                   "scope_authority": binding["scope_provenance"]["authority"],
                                   "selection_priority": 1, "role_certified": False, "repair_eligible": False})
    if counts["completed_trajectories"] != FORMAL_COUNT * len(FORMAL_SEEDS):
        raise ValueError("Selection requires all formal trajectories")
    if code != {name: sha((ROOT / name).read_bytes()) for name in CODE_FILES}:
        raise ValueError("Selection source changed during replay")
    selected, rank_exclusions = choose(candidates)
    exclusions.update(rank_exclusions)
    return {"status": "FROZEN", "quality_gate": "READY" if selected else "NO_ELIGIBLE_TARGET",
            "formal_problems": FORMAL_COUNT, "formal_trajectories": FORMAL_COUNT * len(FORMAL_SEEDS),
            "protocol_sha256": PROTOCOL_SHA256, "bank_retrieval_sha256": sha((root / "BANK_RETRIEVAL.json").read_bytes()),
            "data_freeze_sha256": DATA_SHA256, "selection_code_sha256": code,
            "native_worker_manifest_sha256": {str(index): sha((root / f"bank/native_results/worker_{index}/manifest.json").read_bytes())
                                               for index in (0, 1)},
            "counts": {**counts, "eligible_events": len(candidates), "eligible_distinct_problems": len({r["case_id"] for r in candidates})},
            "exclusions": dict(exclusions), "selected": selected,
            "repair_gate": "NO_INDEPENDENT_ROLE_AND_SUPPORTED_PLAN", "evaluation_answers_read": False}


def rebuild_selected(row, case, selected, tokenizer):
    verify_record(row, case, selected["seed"], tokenizer)
    for step, scope, predecessor, events in replay_steps(row, case["question"], tokenizer, selected["step"]):
        if step["step"] != selected["step"]:
            continue
        matches = [event for event in events if event.event_id == selected["event_id"]]
        if (len(matches) != 1 or matches[0].as_dict() != selected["event"]
                or scope.observed_prefix_sha256 != selected["observed_prefix_sha256"]
                or step["end"] != selected["generated_count"] or live_rng(row, step, tokenizer) != selected["rng_state_sha256"]):
            raise ValueError("Selected event or native checkpoint could not be reconstructed")
        event = matches[0]
        binding, _ = scope_binding(event, scope, predecessor)
        if binding is None or digest(binding) != selected["scope_binding_sha256"]:
            raise ValueError("Selected scope could not be reconstructed")
        return event, scope, predecessor, binding
    raise ValueError("Selected observed step is missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tokenizer", type=Path, required=True)
    args = parser.parse_args()
    runtime = ROOT.parent / "p05_design_review_20261105/runtime4552"
    if runtime.is_dir():
        sys.path.insert(0, str(runtime))
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True, trust_remote_code=False)
    root = args.root.resolve()
    result = select(root, tokenizer)
    path = root / "quality/D3_PAIR_SELECTION.json"
    raw = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Existing frozen D3 selection differs")
    else:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
    print(json.dumps({key: value for key, value in result.items() if key != "selected"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
