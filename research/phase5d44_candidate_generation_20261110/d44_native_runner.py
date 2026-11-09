"""Pinned Qwen3-4B native-state smoke or four-arm trial; no answer access."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import sys
from time import perf_counter


HERE = Path(__file__).resolve().parent
LEGACY = HERE / "legacy"
D2 = HERE.parent / "phase5d2_quarantined_rebase_20261107"
D1 = HERE.parent / "phase5d_scope_rebase_20261106"
if LEGACY.is_dir():
    sys.path.insert(0, str(LEGACY))
else:
    sys.path.extend((str(D2), str(D1)))

from native_d2_worker import SAMPLING, load_runtime, prompt_for, verify_inputs
from native_engine import NativeEngine, digest_ids
from native_snapshot import ExecutionIdentity, NativeState, advance_native, capture_snapshot, replay_schedule, replay_snapshot, restore_snapshot


ARMS = ("NativeContinue", "GenericReminder", "TypedObligation", "IndependentRestart")
FLOOR = 256
STRIDE = 64
PARITY_TOKENS = 12
GENERIC_BASES = (
    "Review.",
    "Recheck your work and continue.",
    "Recheck the reasoning so far. Continue solving the original question and verify the final result.",
)
GENERIC_CLAUSES = (
    "Check the assumptions you have used.",
    "Go over the important steps in order.",
    "Verify the calculations and transformations.",
    "Return to a step if its justification is unclear.",
    "Check whether the conclusion follows from the work.",
    "Make sure the final response addresses the original request.",
    "Continue until you can state the result clearly.",
)
MAX_NEUTRAL_PADDING = 8
CONTROL_MARKERS = ("<|", "<think>", "</think>")
VISIBLE_KEYS = {"case_id", "question", "problem_kind", "seed", "restart_seed", "question_sha256", "obligation"}
OBLIGATION_KEYS = {"kind", "args", "cue", "question_sha256", "proof_sha256", "review_sha256", "scope_patterns"}
TRUSTED_SMOKE_CUE = (
    "Before reporting a final integer in this test, check whether the written addition uses both original addends."
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def progress(path, arm, state):
    # The file is only a live diagnostic. Terminal artifacts are write-once.
    staged = path.with_suffix(".pending")
    staged.write_text(json.dumps({"arm": arm, "generated_tokens": len(state.generated_ids),
                                  "cache_position": state.cache_position, "stop_reason": state.stop_reason}) + "\n")
    staged.replace(path)


def identity_for(engine, metadata):
    assets = metadata["model_files"]
    tokenizer_assets = [item for item in assets["files"] if item["name"].startswith(
        ("tokenizer", "vocab", "merges", "special_tokens", "added_tokens", "chat_template"))]
    if not tokenizer_assets:
        raise ValueError("No tokenizer identity assets")
    source = LEGACY if LEGACY.is_dir() else D1
    return ExecutionIdentity(assets["manifest_sha256"], sha(json.dumps(tokenizer_assets, sort_keys=True).encode()),
                             sha((source / "native_engine.py").read_bytes()), metadata["backend"], metadata["dtype"],
                             str(engine.device), json.dumps({key: metadata[key] for key in ("gpu", "torch", "transformers")},
                                                            sort_keys=True), SAMPLING)


def validate_cases(data):
    if type(data) is not dict or set(data) != {"cases"} or type(data["cases"]) is not list or not data["cases"]:
        raise ValueError("Input must contain only a nonempty visible cases list")
    names = set()
    for case in data["cases"]:
        if type(case) is not dict or set(case) != VISIBLE_KEYS:
            raise ValueError("Unexpected visible-case field")
        case_id = case["case_id"]
        if (type(case_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", case_id)
                or case_id in names):
            raise ValueError("Invalid or repeated case identity")
        names.add(case_id)
        q = case["question"]
        if type(q) is not str or not q.strip() or sha(q.encode()) != case["question_sha256"]:
            raise ValueError("Visible question bytes differ from the freeze")
        if case["problem_kind"] not in ("EXTREMUM", "FIRST_EVENT", "SCOPE_CONTROL"):
            raise ValueError("Unexpected frozen problem kind")
        if case["obligation"] is not None and (
                type(case["obligation"]) is not dict or set(case["obligation"]) != OBLIGATION_KEYS
                or case["obligation"]["question_sha256"] != case["question_sha256"]):
            raise ValueError("Reviewed obligation fields or question binding differ")
        if case["problem_kind"] == "SCOPE_CONTROL" and case["obligation"] is not None:
            raise ValueError("A scope-control row cannot authorize a trigger")
        a, b = case["seed"], case["restart_seed"]
        if any(type(x) is not int or not 0 <= x < (1 << 63) for x in (a, b)) or a == b:
            raise ValueError("Expected distinct frozen native and restart seeds")
    return data["cases"]


def work(ledger):
    return {"forward_calls": len(ledger), "forward_input_tokens": sum(row["input_tokens"] for row in ledger),
            "attention_pairs": sum(row["input_tokens"] * row["past_tokens"] +
                                   row["input_tokens"] * (row["input_tokens"] + 1) // 2 for row in ledger)}


def channel_open(engine, ids):
    for token in reversed(ids):
        if token in engine.open_ids:
            return True
        if token in engine.close_ids:
            return False
    return False


def decode(engine, ids):
    return engine.tokenizer.decode(list(ids), skip_special_tokens=False)


def open_thought(engine, state):
    if not state.thinking_open:
        raise ValueError("Only a live thinking prefix may be inspected")
    generated = state.generated_ids
    start = next((i + 1 for i in range(len(generated) - 1, -1, -1) if generated[i] in engine.open_ids), 0)
    return decode(engine, generated[start:])


def encode_plain(engine, text):
    if type(text) is not str or not text.strip() or len(text) > 4096 or any(mark in text for mark in CONTROL_MARKERS):
        raise ValueError("Expected bounded plain text without role/think delimiters")
    ids = engine.tokenizer.encode("\n\n" + text.strip() + "\n\n", add_special_tokens=False)
    controls = set(engine.tokenizer.all_special_ids) | engine.eos | set(engine.open_ids + engine.close_ids)
    if not ids or any(token in controls for token in ids):
        raise ValueError("Bridge would inject a control token")
    return list(ids)


def choose_generic(engine, typed_budget):
    """Find the longest deterministic fluent generic variant that fits the typed bridge."""
    best, shortest = None, None
    for base_index, base in enumerate(GENERIC_BASES):
        for count in range(len(GENERIC_CLAUSES) + 1):
            for indices in combinations(range(len(GENERIC_CLAUSES)), count):
                text = " ".join((base, *(GENERIC_CLAUSES[i] for i in indices)))
                ids = encode_plain(engine, text)
                variant = {"base_index": base_index, "clause_indices": list(indices), "unpadded_text": text}
                if shortest is None or len(ids) < len(shortest[0]):
                    shortest = (ids, variant)
                if len(ids) <= typed_budget and (best is None or len(ids) > len(best[0])):
                    best = (ids, variant)
    return best if best is not None else shortest


def matched_bridges(engine, cue):
    """Use matched fluent text with a small exact whitespace residual, without retokenization."""
    typed = encode_plain(engine, cue)
    generic, variant = choose_generic(engine, len(typed))
    padding = engine.tokenizer.encode(" ", add_special_tokens=False)
    controls = set(engine.tokenizer.all_special_ids) | engine.eos | set(engine.open_ids + engine.close_ids)
    if len(padding) != 1 or padding[0] in controls or decode(engine, padding) != " ":
        raise ValueError("Pinned tokenizer lacks an exact neutral padding token")
    target = max(len(generic), len(typed))
    result = {}
    for arm, unpadded in (("GenericReminder", generic), ("TypedObligation", typed)):
        count = target - len(unpadded)
        if count > MAX_NEUTRAL_PADDING:
            raise ValueError("Frozen cue cannot be matched with a small neutral padding residual")
        actual = unpadded + padding * count
        text = decode(engine, actual)
        if text != decode(engine, unpadded) + " " * count or any(mark in text for mark in CONTROL_MARKERS):
            raise ValueError("Padding is not neutral under the actual decoded bridge")
        result[arm] = {"token_ids": actual, "text": text, "padding_tokens": count, "padding_token_id": padding[0],
                       "unpadded_tokens": len(unpadded), "forced_tokens": target}
    result["GenericReminder"]["fluent_variant"] = variant
    return result


def prefill(engine, prompt, seed, identity, stage):
    engine.stage = stage
    cache, logits = engine.prefill(prompt)
    return NativeState(tuple(prompt), [], cache, logits, engine.rng(seed=seed), len(prompt),
                       channel_open(engine, prompt), "RUNNING", identity)


def emit_to_end(engine, state, stage, path, observe=None):
    engine.stage = stage
    while state.stop_reason == "RUNNING":
        token = advance_native(engine, state)
        if observe is not None:
            observe(state, token)
        if len(state.generated_ids) % 1024 == 0:
            progress(path, stage, state)
    engine.sync()


def make_snapshot(engine, state, checkpoint_id):
    return capture_snapshot(engine, identity=state.identity, prompt_ids=state.prompt_ids, generated_ids=state.generated_ids,
                            cache=state.cache, next_logits=state.next_logits, rng=state.rng, thinking_open=True,
                            checkpoint_id=checkpoint_id)


def save_checkpoint(snapshot, folder):
    vector = snapshot._next_logits.detach().float().cpu().contiguous().numpy().astype("<f4", copy=False).tobytes()
    with (folder / "checkpoint_logits.f32le").open("xb") as stream:
        stream.write(vector)
    rng = bytes(snapshot._rng_state.detach().cpu().tolist())
    return {"metadata": snapshot.metadata(), "position": snapshot.cache_position,
            "observed_generated_count": len(snapshot.generated_ids), "observed_prefix_sha256": snapshot.prefix_sha256,
            "rng_sha256": sha(rng), "rng_state_base64": base64.b64encode(rng).decode(),
            "full_next_logits": {"path": "checkpoint_logits.f32le", "dtype": "little_endian_float32", "sha256": sha(vector),
                                 "numel": snapshot._next_logits.numel()}, "copy_cost": asdict(snapshot.copy_cost)}


def inject(engine, state, bridge, arm):
    if not state.thinking_open or state.stop_reason != "RUNNING" or state.cache_position + bridge["forced_tokens"] >= engine.capacity:
        raise ValueError("No eligible open-thinking checkpoint capacity for the matched bridge")
    engine.stage = arm + ":bridge"
    for token in bridge["token_ids"]:
        state.cache, state.next_logits = engine.forward([token], state.cache)
        state.generated_ids.append(token)
        state.cache_position += 1


def terminal(engine, state):
    ids = list(state.generated_ids)
    close = [i for i, token in enumerate(ids) if token in engine.close_ids]
    final_ids = ids[close[-1] + 1:] if close else []
    return {"prompt_ids": list(state.prompt_ids), "generated_ids": ids, "generated_sha256": digest_ids(ids),
            "text": decode(engine, ids), "final_response": engine.tokenizer.decode(final_ids, skip_special_tokens=True),
            "stop_reason": state.stop_reason, "EOS": state.stop_reason == "EOS", "hit_context_cap": state.stop_reason == "CONTEXT_CAP",
            "think_closed": bool(close) and not state.thinking_open, "context_capacity": engine.capacity,
            "final_cache_position": state.cache_position}


def short_probe(engine, state, count, stage):
    engine.stage = stage
    first = len(state.generated_ids)
    while state.stop_reason == "RUNNING" and len(state.generated_ids) - first < count:
        advance_native(engine, state)
    engine.sync()
    return state.generated_ids[first:]


def parity_check(engine, snapshot, identity, actual_ids):
    began = perf_counter()
    start = len(engine.ledger)
    state = restore_snapshot(engine, snapshot, identity=identity)
    logits = bool(engine.torch.equal(state.next_logits, snapshot._next_logits))
    rng = bool(engine.torch.equal(state.rng.get_state(), snapshot._rng_state))
    expected = actual_ids[len(snapshot.generated_ids):len(snapshot.generated_ids) + PARITY_TOKENS]
    observed = short_probe(engine, state, len(expected), "ParityRestore:decode")
    return {"status": "PASS" if logits and rng and observed == expected and bool(expected) else "FAIL",
            "snapshot_logits_exact": logits, "snapshot_rng_exact": rng, "observed": observed, "expected_from_native": expected,
            "restore_cost": asdict(state.restore_cost), "paid_work": work(engine.ledger[start:]),
            "elapsed_seconds": perf_counter() - began}


def run_case(engine, identity, case, folder, detect):
    began = perf_counter()
    folder.mkdir(exist_ok=False)
    engine.ledger = []
    engine.torch.cuda.reset_peak_memory_stats(engine.device)
    prompt = prompt_for(engine.tokenizer, case["question"])
    native = prefill(engine, prompt, case["seed"], identity, "NativeContinue:prefill")
    snapshot = bridges = trigger = None
    trigger_seconds = 0.0
    polling_seconds = 0.0
    eligible_polls = 0
    inspections = 0

    def observe(state, token):
        nonlocal snapshot, bridges, trigger, trigger_seconds, inspections, polling_seconds, eligible_polls
        count = len(state.generated_ids)
        if (trigger is not None or case["obligation"] is None or count < FLOOR or state.stop_reason != "RUNNING"
                or not state.thinking_open):
            return
        poll_start = perf_counter()
        eligible_polls += 1
        if count % STRIDE and "}" not in decode(engine, [token]):
            polling_seconds += perf_counter() - poll_start
            return
        start = perf_counter()
        inspections += 1
        detected = detect(case, open_thought(engine, state))
        trigger_seconds += perf_counter() - start
        polling_seconds += perf_counter() - poll_start
        if detected is None:
            return
        if type(detected) is not dict or type(detected.get("cue")) is not str:
            raise ValueError("Trigger result lacks a plain-text cue")
        bridges = matched_bridges(engine, detected["cue"])
        fit = state.cache_position + bridges["TypedObligation"]["forced_tokens"] < engine.capacity
        trigger = {"detection": detected, "checkpoint_generated_tokens": count,
                   "observation_reason": "CADENCE" if count % STRIDE == 0 else "OBSERVED_BRACE_TOKEN",
                   "status": "TRIGGERED" if fit else "MATCHED_BRIDGE_NO_CONTEXT"}
        if fit:
            snapshot = make_snapshot(engine, state, case["case_id"] + "_first_observed_obligation")
            trigger["checkpoint"] = save_checkpoint(snapshot, folder)

    emit_to_end(engine, native, "NativeContinue:decode", folder / "native_progress.json", observe)
    native_result = terminal(engine, native)
    native_cost = work(engine.ledger)
    native_seconds = perf_counter() - began
    del native
    parity = parity_check(engine, snapshot, identity, native_result["generated_ids"]) if snapshot else {"status": "NOT_TRIGGERED"}
    arms = {"NativeContinue": {**native_result, "elapsed_seconds": native_seconds, "paid_work": native_cost,
                               "sampled_continuation_tokens": len(native_result["generated_ids"]), "teacher_forced_tokens": 0}}
    if trigger is None:
        trigger = {"status": "NO_REVIEWED_OBLIGATION" if case["obligation"] is None else
                   "EARLY_BEFORE_CHECKPOINT" if len(native_result["generated_ids"]) < FLOOR else "NO_ELIGIBLE_TRIGGER"}
    for arm in ("GenericReminder", "TypedObligation"):
        if snapshot is None or parity["status"] != "PASS":
            reason = "RESTORE_PARITY_FAILED" if snapshot else trigger["status"]
            arms[arm] = {**native_result, "mode": "REUSED_NATIVE_NO_ACTION", "reuse_reason": reason, "elapsed_seconds": 0,
                         "paid_work": work([]), "sampled_continuation_tokens": 0, "teacher_forced_tokens": 0}
            continue
        start, offset = perf_counter(), len(engine.ledger)
        state = restore_snapshot(engine, snapshot, identity=identity)
        inject(engine, state, bridges[arm], arm)
        before = len(state.generated_ids)
        emit_to_end(engine, state, arm + ":decode", folder / (arm + "_progress.json"))
        arms[arm] = {**terminal(engine, state), "mode": "TRIGGERED", "bridge": bridges[arm],
                     "sampled_continuation_tokens": len(state.generated_ids) - before,
                     "teacher_forced_tokens": bridges[arm]["forced_tokens"], "restore_cost": asdict(state.restore_cost),
                     "paid_work": work(engine.ledger[offset:]), "elapsed_seconds": perf_counter() - start}
        del state
    del snapshot
    start, offset = perf_counter(), len(engine.ledger)
    restart = prefill(engine, prompt, case["restart_seed"], identity, "IndependentRestart:prefill")
    emit_to_end(engine, restart, "IndependentRestart:decode", folder / "restart_progress.json")
    arms["IndependentRestart"] = {**terminal(engine, restart), "mode": "FRESH_PROMPT_AND_FROZEN_SEED",
                                  "sampled_continuation_tokens": len(restart.generated_ids), "teacher_forced_tokens": 0,
                                  "paid_work": work(engine.ledger[offset:]), "elapsed_seconds": perf_counter() - start}
    del restart
    result = {"case_id": case["case_id"], "question_sha256": case["question_sha256"], "seed": case["seed"],
              "restart_seed": case["restart_seed"], "trigger": trigger, "detector_calls": inspections,
              "detector_wall_seconds": trigger_seconds, "detector_eligible_token_polls": eligible_polls,
              "detector_total_polling_wall_seconds": polling_seconds, "restore_parity": parity, "arm_order": ARMS,
              "arms": arms, "actual_paid_work": work(engine.ledger), "paid_forward_ledger": engine.ledger,
              "elapsed_seconds": perf_counter() - began,
              "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(engine.device),
              "peak_reserved_bytes": engine.torch.cuda.max_memory_reserved(engine.device)}
    write(folder / "result.json", result)
    return {"case_id": case["case_id"], "trigger_status": trigger["status"], "parity": parity["status"],
            "terminal_by_arm": {name: arm["stop_reason"] for name, arm in arms.items()}, "elapsed_seconds": result["elapsed_seconds"]}


def probe_smoke_bridges(engine, snapshot, identity):
    bridges = matched_bridges(engine, TRUSTED_SMOKE_CUE)
    rows = {}
    for arm, bridge in bridges.items():
        engine.sync()
        started = perf_counter()
        state = restore_snapshot(engine, snapshot, identity=identity)
        same_logits = bool(engine.torch.equal(state.next_logits, snapshot._next_logits))
        same_rng = bool(engine.torch.equal(state.rng.get_state(), snapshot._rng_state))
        start = len(engine.ledger)
        inject(engine, state, bridge, arm)
        forced_work = work(engine.ledger[start:])
        count = bridge["forced_tokens"]
        expected_work = {
            "forward_calls": count,
            "forward_input_tokens": count,
            "attention_pairs": count * snapshot.cache_position + count * (count + 1) // 2,
        }
        start = len(engine.ledger)
        ids = short_probe(engine, state, PARITY_TOKENS, arm + ":bridge_smoke_probe")
        engine.sync()
        rows[arm] = {
            "status": "PASS" if same_logits and same_rng and forced_work == expected_work and len(ids) == PARITY_TOKENS else "FAIL",
            "same_start_logits": same_logits, "same_start_rng": same_rng, "bridge": bridge,
            "forced_work": forced_work, "expected_forced_work": expected_work,
            "probe_ids": ids, "probe_work": work(engine.ledger[start:]), "elapsed_seconds": perf_counter() - started,
        }
        del state
    return rows


def smoke(engine, identity, packet, output, bridge_smoke):
    began = perf_counter()
    engine.ledger = []
    engine.torch.cuda.reset_peak_memory_stats(engine.device)
    if packet is None:
        question = "Compute 7 + 5."
        prompt = prompt_for(engine.tokenizer, question)
        ids = ([] if channel_open(engine, prompt) else engine.open_ids) + engine.tokenizer.encode(
            "\nI will check the arithmetic.\n\n", add_special_tokens=False)
        rng = engine.rng(seed=20261110)
        scope = "TRUSTED_SMALL_FORCED_BOUNDARY_NOT_HISTORICAL_PREFIX"
    else:
        prompt, ids = packet["prompt_ids"], packet["generated_ids"]
        if (prompt_for(engine.tokenizer, packet["question"]) != prompt
                or digest_ids(prompt + ids) != packet["observed_prefix_sha256"]):
            raise ValueError("Historical observed packet identity differs")
        raw = base64.b64decode(packet["rng_state_base64"], validate=True)
        rng = engine.rng(state=engine.torch.tensor(list(raw), dtype=engine.torch.uint8))
        scope = "HISTORICAL_OBSERVED_PREFIX"
    if not channel_open(engine, prompt + ids) or len(prompt) + len(ids) + PARITY_TOKENS >= engine.capacity:
        raise ValueError("Smoke boundary must preserve a live open thinking state")
    engine.stage = "Smoke:observed_replay"
    cache, logits = replay_schedule(engine, prompt, ids)
    original = NativeState(tuple(prompt), list(ids), cache, logits, rng, len(prompt) + len(ids), True, "RUNNING", identity)
    del cache, logits, rng
    snapshot = make_snapshot(engine, original, "d44_smoke_boundary")
    checkpoint = save_checkpoint(snapshot, output)
    expected = short_probe(engine, original, PARITY_TOKENS, "Smoke:direct_probe")
    del original
    restored = parity_check(engine, snapshot, identity, list(ids) + expected)
    engine.stage = "Smoke:independent_replay"
    cold = replay_snapshot(engine, snapshot, identity=identity)
    same_logits = bool(engine.torch.equal(cold.next_logits, snapshot._next_logits))
    same_rng = bool(engine.torch.equal(cold.rng.get_state(), snapshot._rng_state))
    cold_ids = short_probe(engine, cold, len(expected), "Smoke:independent_probe")
    del cold
    bridges = probe_smoke_bridges(engine, snapshot, identity) if bridge_smoke else None
    passed = restored["status"] == "PASS" and same_logits and same_rng and cold_ids == expected
    if bridges is not None:
        passed = passed and all(row["status"] == "PASS" for row in bridges.values())
        passed = passed and len({row["bridge"]["forced_tokens"] for row in bridges.values()}) == 1
    return {"status": "PASS" if passed else "FAIL", "scope": scope, "probe_only_not_quality_generation": True,
            "checkpoint": checkpoint, "prompt_ids": prompt, "observed_ids": ids,
            "original_probe_ids": expected, "restore_parity": restored,
            "independent_replay": {"same_logits": same_logits, "same_rng": same_rng, "probe_ids": cold_ids},
            "matched_bridge_probe": bridges,
            "paid_work": work(engine.ledger), "paid_forward_ledger": engine.ledger, "elapsed_seconds": perf_counter() - began,
            "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(engine.device),
            "peak_reserved_bytes": engine.torch.cuda.max_memory_reserved(engine.device)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--mode", choices=("smoke", "main"), required=True)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--input", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--model", required=True)
    cli.add_argument("--gpu", required=True)
    cli.add_argument("--bridge-smoke", action="store_true")
    args = cli.parse_args()
    if args.bridge_smoke and args.mode != "smoke":
        cli.error("A bridge smoke is only available in smoke mode")
    root = args.root.resolve()
    if root != HERE:
        cli.error("Runtime root must be the staged runner directory")
    output = (root / args.output).resolve()
    if output == root or not output.is_relative_to(root) or output.exists():
        cli.error("Output must be a new path within the authorized runtime root")
    freeze_name = f"d44_{args.mode}_runtime_freeze.json"
    freeze = json.loads((root / freeze_name).read_bytes())
    paths = {item["path"] for item in freeze["files"]}
    if any(Path(p).is_absolute() or not (root / p).resolve().is_relative_to(root) for p in paths):
        raise ValueError("Unsafe runtime freeze entry")
    required = {"d44_native_runner.py", *["legacy/" + name for name in (
        "native_d2_worker.py", "native_engine.py", "native_snapshot.py", "native_worker.py", "observations.py", "p0_base_frozen.py",
    )]}
    if args.mode == "main":
        required.add("obligation_trigger.py")
    if not required <= paths:
        raise ValueError("Runtime freeze lacks a required executable source")
    verify_inputs(root, freeze_name)
    if args.input is not None:
        source = (root / args.input).resolve()
        if not source.is_relative_to(root) or source.relative_to(root).as_posix() not in paths:
            raise ValueError("Input is not inside the pinned runtime freeze")
        data = json.loads(source.read_bytes())
    else:
        data = None
    cases = validate_cases(data) if args.mode == "main" else None
    if args.mode == "main":
        case_ids = [case["case_id"] for case in cases]
        if (freeze["case_ids"] != case_ids or freeze["shard_packet_sha256"] != sha(source.read_bytes())
                or freeze["worker"] not in (0, 1)
                or not re.fullmatch(r"[a-f0-9]{64}", freeze["full_packet_sha256"])):
            raise ValueError("Main worker shard differs from its frozen ordered packet identity")
    legacy = root / "legacy"
    if not legacy.is_dir():
        raise ValueError("A staged GPU run requires the frozen native legacy modules")
    began = perf_counter()
    model, tokenizer, device, metadata = load_runtime(legacy, args.model, args.gpu)
    engine = NativeEngine(model, tokenizer, device)
    identity = identity_for(engine, metadata)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {**metadata, "mode": args.mode, "execution_identity": identity.as_dict(),
                "runtime_freeze_sha256": sha((root / freeze_name).read_bytes()),
                "model_load_wall_seconds": perf_counter() - began}
    if args.mode == "main":
        manifest.update({key: freeze[key] for key in ("case_ids", "shard_packet_sha256", "worker", "full_packet_sha256")})
    else:
        manifest["bridge_smoke"] = args.bridge_smoke
    write(output / "manifest.json", manifest)
    with engine.torch.inference_mode():
        if args.mode == "smoke":
            summary = smoke(engine, identity, data, output, args.bridge_smoke)
        else:
            from obligation_trigger import detect

            results = [run_case(engine, identity, case, output / case["case_id"], detect) for case in cases]
            summary = {"status": "COMPLETE" if all(row["parity"] != "FAIL" for row in results) else "PARITY_FAILURE_RETAINED",
                       "cases": results, "elapsed_including_model_load_seconds": perf_counter() - began}
    write(output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "mode": args.mode}), flush=True)
    raise SystemExit(0 if summary["status"] in {"PASS", "COMPLETE"} else 1)


if __name__ == "__main__":
    main()
