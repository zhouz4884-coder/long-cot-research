"""Same-observed-state D2 generation, with no access to evaluation answers."""

import argparse
import base64
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from native_d2_worker import load_runtime, SAMPLING, verify_inputs
from native_engine import NativeEngine, digest_ids
from native_worker import write
from native_snapshot import (ExecutionIdentity, NativeState, advance_native,
                             capture_snapshot, replay_schedule, restore_snapshot)
from natural_evidence import check_relation
from proposal_check import check_proposal
from reflection_fork import generate_reflection, resolve_reflection


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_identity(root, engine, metadata):
    assets = metadata["model_files"]
    tokenizer_assets = [row for row in assets["files"]
                        if row["name"].startswith(("tokenizer", "vocab", "merges", "special_tokens", "added_tokens", "chat_template"))]
    if not tokenizer_assets:
        raise ValueError("Tokenizer asset identity is missing")
    return ExecutionIdentity(
        model_sha256=assets["manifest_sha256"],
        tokenizer_sha256=hashlib.sha256(json.dumps(tokenizer_assets, sort_keys=True).encode()).hexdigest(),
        engine_sha256=file_hash(root / "native_engine.py"),
        backend=metadata["backend"], dtype=metadata["dtype"], device=str(engine.device),
        runtime=json.dumps({key: metadata[key] for key in ("gpu", "torch", "transformers")}, sort_keys=True),
        sampling_config=SAMPLING,
    )


def cost(ledger):
    return {"forward_calls": len(ledger),
            "forward_input_tokens": sum(row["input_tokens"] for row in ledger),
            "attention_pairs": sum(row["input_tokens"] * row["past_tokens"] +
                                   row["input_tokens"] * (row["input_tokens"] + 1) // 2
                                   for row in ledger)}


def append_checked_text(engine, state, text, stage):
    if state.stop_reason != "RUNNING" or not state.thinking_open:
        raise ValueError("A bridge requires a live thinking state")
    if any(marker in text for marker in ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>")):
        raise ValueError("A bridge contains a role or thinking boundary")
    ids = engine.tokenizer.encode(text, add_special_tokens=False)
    if any(token in engine.eos or token in engine.open_ids + engine.close_ids for token in ids):
        raise ValueError("A bridge contains a control token")
    if state.cache_position + len(ids) >= engine.capacity:
        return {"status": "INSUFFICIENT_CONTEXT", "tokens": 0}
    engine.stage = stage
    for token in ids:
        state.cache, state.next_logits = engine.forward([token], state.cache)
        state.generated_ids.append(token)
        state.cache_position += 1
    return {"status": "APPENDED", "tokens": len(ids), "text": text,
            "token_ids": ids, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


def finish(engine, state, folder, arm):
    began = time.monotonic()
    first = len(state.generated_ids)
    engine.stage = arm + "_decode"
    while state.stop_reason == "RUNNING":
        advance_native(engine, state)
        if len(state.generated_ids) % 256 == 0:
            write(folder / (arm + "_progress.json"), {
                "status": "GENERATING", "arm": arm, "tokens": len(state.generated_ids),
                "elapsed_seconds": time.monotonic() - began,
            })
    engine.sync()
    return {"continuation_tokens": len(state.generated_ids) - first,
            "continuation_seconds": time.monotonic() - began}


def state_result(engine, state):
    positions = [i for i, token in enumerate(state.generated_ids) if token == engine.close_ids[0]]
    final = state.generated_ids[positions[-1] + 1:] if positions else []
    return {"status": "COMPLETE", "prompt_ids": list(state.prompt_ids),
            "prompt_sha256": digest_ids(list(state.prompt_ids)),
            "generated_ids": state.generated_ids, "generated_sha256": digest_ids(state.generated_ids),
            "text": engine.tokenizer.decode(state.generated_ids, skip_special_tokens=False),
            "final_response": engine.tokenizer.decode(final, skip_special_tokens=True),
            "new_tokens": len(state.generated_ids), "stop_reason": state.stop_reason,
            "EOS": state.stop_reason == "EOS", "hit_context_cap": state.stop_reason == "CONTEXT_CAP",
            "think_closed": bool(positions) and not state.thinking_open,
            "context_capacity": engine.capacity}


def checkpoint(engine, identity, baseline, selected):
    end = selected["generated_count"]
    event = next(event for event in baseline["events"]
                 if event["step"] == selected["step"] and event["end"] == end and event["thinking_open"])
    prompt, generated = baseline["prompt_ids"], baseline["generated_ids"][:end]
    if digest_ids(prompt + generated) != selected["observed_prefix_sha256"]:
        raise ValueError("Selected checkpoint source changed")
    step = next(step for step in baseline["steps"] if step["step"] == selected["step"])
    if not (0 <= step["start"] < step["end"] == end <= len(baseline["generated_ids"])):
        raise ValueError("Selected event does not match its complete observed step span")
    decoded = engine.tokenizer.decode(generated[step["start"]:step["end"]], skip_special_tokens=False)
    if decoded != step["text"] or not decoded.endswith("\n\n"):
        raise ValueError("Selected source is not the observed complete paragraph")
    rng_bytes = base64.b64decode(event["rng_state_base64"], validate=True)
    rng_state = engine.torch.tensor(list(rng_bytes), dtype=engine.torch.uint8)
    rng = engine.rng(state=rng_state)
    engine.stage = "checkpoint_schedule_replay"
    cache, logits = replay_schedule(engine, prompt, generated)
    snapshot = capture_snapshot(engine, identity=identity, prompt_ids=prompt, generated_ids=generated,
                                cache=cache, next_logits=logits, rng=rng, thinking_open=True,
                                checkpoint_id=f"{baseline['case_id']}_{baseline['seed']}_{selected['step']}")
    del cache, logits
    return snapshot


def regenerate_checkpoint(engine, identity, baseline, selected):
    """Pay for native prefix production in each standalone check arm."""
    prompt = baseline["prompt_ids"]
    expected = baseline["generated_ids"][:selected["generated_count"]]
    rng = engine.rng(seed=baseline["seed"])
    engine.stage = "standalone_native_prefill"
    cache, logits = engine.prefill(prompt)
    generated = []
    engine.stage = "standalone_native_prefix"
    for expected_token in expected:
        token = engine.sample(logits, rng)
        if token != expected_token:
            raise ValueError("Standalone prefix regeneration diverged from the selected native source")
        generated.append(token)
        cache, logits = engine.forward([token], cache)
    event = next(event for event in baseline["events"] if event["step"] == selected["step"])
    expected_rng = base64.b64decode(event["rng_state_base64"], validate=True)
    if bytes(rng.get_state().cpu().tolist()) != expected_rng:
        raise ValueError("Regenerated RNG differs from the selected native checkpoint")
    return capture_snapshot(engine, identity=identity, prompt_ids=prompt, generated_ids=generated,
                            cache=cache, next_logits=logits, rng=rng, thinking_open=True,
                            checkpoint_id=f"{baseline['case_id']}_{baseline['seed']}_{selected['step']}")


def identity_pair(engine, snapshot, identity, baseline, folder):
    """Compare a direct branch with UNKNOWN transfer through their full EOS."""
    began = time.monotonic()
    ledger_start = len(engine.ledger)
    direct = restore_snapshot(engine, snapshot, identity=identity)
    original_fingerprint = engine.kv_fingerprints(snapshot._cache)
    original_rng = snapshot._rng_state.clone()
    original_logits = snapshot._next_logits.clone()
    proposal = generate_reflection(engine, snapshot, identity=identity, max_proposal_tokens=192)
    resolution = resolve_reflection(engine, snapshot, proposal, identity=identity, disposition="UNKNOWN")
    shadow = resolution.state
    prefix_length = len(snapshot.generated_ids)
    engine.stage = "NativeContinue_decode"
    for _ in proposal.token_ids:
        if direct.stop_reason != "RUNNING":
            break
        advance_native(engine, direct)
    proposal_equal = direct.generated_ids == shadow.generated_ids
    comparisons = 0
    max_logit_difference = 0.0
    all_rng_equal = True
    token_equal = proposal_equal
    paired_seconds = {"NativeContinue": 0.0, "UnknownIdentity": 0.0}
    while direct.stop_reason == "RUNNING" and shadow.stop_reason == "RUNNING":
        difference = float((direct.next_logits - shadow.next_logits).abs().max())
        max_logit_difference = max(max_logit_difference, difference)
        comparisons += 1
        all_rng_equal = all_rng_equal and bool(engine.torch.equal(direct.rng.get_state(), shadow.rng.get_state()))
        started = time.monotonic()
        engine.stage = "NativeContinue_decode"
        left = advance_native(engine, direct)
        engine.sync()
        paired_seconds["NativeContinue"] += time.monotonic() - started
        started = time.monotonic()
        engine.stage = "UnknownIdentity_decode"
        right = advance_native(engine, shadow)
        engine.sync()
        paired_seconds["UnknownIdentity"] += time.monotonic() - started
        token_equal = token_equal and left == right
        if len(direct.generated_ids) % 256 == 0:
            write(folder / "identity_progress.json", {"status": "GENERATING", "tokens": len(direct.generated_ids),
                                                       "token_equal": token_equal, "max_logit_difference": max_logit_difference})
    # A failure remains fully observable. Each branch still reaches its own native end.
    finish(engine, direct, folder, "NativeContinue")
    finish(engine, shadow, folder, "UnknownIdentity")
    original_unchanged = (original_fingerprint == engine.kv_fingerprints(snapshot._cache)
                          and bool(engine.torch.equal(original_rng, snapshot._rng_state))
                          and bool(engine.torch.equal(original_logits, snapshot._next_logits)))
    terminal_rng_equal = bool(engine.torch.equal(direct.rng.get_state(), shadow.rng.get_state()))
    diagnostics = {"proposal_tokens": len(proposal.token_ids), "proposal_boundary": proposal.stop_reason,
                   "proposal_prefix_equal": proposal_equal, "logit_comparisons_after_proposal": comparisons,
                   "maximum_logit_difference": max_logit_difference, "RNG_equal_at_compared_steps": all_rng_equal,
                   "terminal_RNG_equal": terminal_rng_equal,
                   "sampled_tokens_equal": token_equal and direct.generated_ids == shadow.generated_ids,
                   "same_terminal_status": direct.stop_reason == shadow.stop_reason,
                   "original_snapshot_unmodified": original_unchanged,
                   "matches_recorded_native_full_ids": direct.generated_ids == baseline["generated_ids"],
                   "compared_continuation_tokens": len(direct.generated_ids) - prefix_length,
                   "proposal_cost": asdict(proposal.cost), "direct_restore_cost": asdict(direct.restore_cost),
                   "lockstep_decode_seconds": paired_seconds, "joint_wall_seconds": time.monotonic() - began,
                   "joint_paid_work": cost(engine.ledger[ledger_start:]),
                   "limits": "logits compared at proposal merge and subsequent live steps; proposal internal logits not recorded"}
    for arm, state in (("NativeContinue", direct), ("UnknownIdentity", shadow)):
        write(folder / (arm + ".json"), {**state_result(engine, state), "arm": arm,
                                         "case_id": baseline["case_id"], "seed": baseline["seed"],
                                         "identity_diagnostics": diagnostics})
    write(folder / "UNKNOWN_IDENTITY.json", diagnostics)
    return diagnostics


def audit_cue(relation):
    if relation is None:
        return "\nAudit the last reasoning step briefly, then continue solving the original problem.\n"
    text = ("\nAudit only this observed literal equality as written: " + relation["surface"] +
            ". Its truth does not certify the original problem or answer. ")
    if relation["variables"]:
        text += ("If proposing a counterexample, output exactly one JSON object with one assignment field "
                 "containing every variable " + json.dumps(relation["variables"]) +
                 ", using integers or rational objects {\"op\":\"rat\",\"num\":integer,\"den\":nonzero_integer}. ")
    return text + "After that audit, continue solving the original problem.\n"


def run_check_arm(engine, snapshot, identity, selected, arm, folder):
    began = time.monotonic()
    first = len(engine.ledger)
    state = restore_snapshot(engine, snapshot, identity=identity)
    relation = selected.get("relation")
    injected = append_checked_text(engine, state, audit_cue(relation), arm + "_audit_cue")
    audit_snapshot = capture_snapshot(engine, identity=identity, prompt_ids=state.prompt_ids,
                                     generated_ids=state.generated_ids, cache=state.cache,
                                     next_logits=state.next_logits, rng=state.rng, thinking_open=True,
                                     checkpoint_id=snapshot.checkpoint_id + "_audit")
    del state
    proposal = generate_reflection(engine, audit_snapshot, identity=identity, max_proposal_tokens=192)
    proposal_info = {"text": proposal.text, "token_ids": list(proposal.token_ids),
                     "stop_reason": proposal.stop_reason, "cost": asdict(proposal.cost)}
    unscoped = arm == "UnscopedIsolatedCheck"
    checked = (check_proposal(relation, proposal.text, unscoped=unscoped) if relation is not None else
               {"status": "UNKNOWN", "reason": "no_registered_relation"})
    disposition = "UNKNOWN"
    if arm != "InContextCheck" and checked["status"] == "INVALID_COUNTEREXAMPLE":
        disposition = "REJECT"
    elif arm != "InContextCheck" and checked["status"] in ("INVALID_JUSTIFICATION", "REFUTED_CLAIM"):
        disposition = "ACCEPT"
    consumed_rng = proposal._shadow.rng.get_state().clone()
    resolution = resolve_reflection(engine, audit_snapshot, proposal, identity=identity, disposition=disposition)
    state = resolution.state
    redirect = None
    if disposition == "REJECT":
        state.rng.set_state(consumed_rng)
        reason = checked.get("checker_result", {}).get("reason", "invalid candidate")
        redirect = append_checked_text(engine, state,
            "\nThe bounded checker rejected that proposed counterexample for the registered equality. "
            "Checked reason: " + reason + ". This certifies neither the old answer nor the whole proof. "
            "Continue solving the original problem.\n", arm + "_checked_redirect")
    continuation = finish(engine, state, folder, arm)
    result = {**state_result(engine, state), "arm": arm, "audit_cue": injected,
              "case_id": selected["case_id"], "seed": selected["seed"], "event_step": selected["step"],
              "proposal": proposal_info, "proposal_check": checked, "disposition": disposition,
              "discarded_proposal_tokens": resolution.discarded_proposal_tokens,
              "rollback_copy_cost": None if resolution.rollback_copy_cost is None else asdict(resolution.rollback_copy_cost),
              "RNG_after_rejection": "post-proposal consumed RNG" if disposition == "REJECT" else "adopted shadow RNG",
              "redirect": redirect, "continuation": continuation,
              "sampled_tokens_including_discarded": len(snapshot.generated_ids) + len(proposal_info["token_ids"]) + continuation["continuation_tokens"],
              "teacher_forced_audit_and_redirect_tokens": injected["tokens"] + (redirect["tokens"] if redirect else 0),
              "visible_assistant_tokens": len(state.generated_ids),
              "elapsed_seconds": time.monotonic() - began, "paid_work": cost(engine.ledger[first:]),
              "ledger": engine.ledger[first:]}
    write(folder / (arm + ".json"), result)
    return {"arm": arm, "EOS": result["EOS"], "tokens": result["new_tokens"],
            "disposition": disposition, "paid_work": result["paid_work"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--worker", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    root = args.root
    verify_inputs(root, "pairing_freeze.json")
    selection = json.loads((root / "PAIR_SELECTION.json").read_text(encoding="utf-8"))
    if selection["status"] != "FROZEN":
        raise ValueError("All collection runs and source selection must be frozen first")
    role_reviews = json.loads((root / "ROLE_REVIEWS.json").read_text(encoding="utf-8"))
    if role_reviews["selection_sha256"] != file_hash(root / "PAIR_SELECTION.json"):
        raise ValueError("Role reviews do not bind the frozen event selection")
    model, tokenizer, device, metadata = load_runtime(root, args.model, args.gpu)
    out = root / "paired_results" / f"worker_{args.worker}"
    out.mkdir(parents=True, exist_ok=True)
    write(out / "manifest.json", metadata)
    summaries = []
    for selected in selection["selected"]:
        source_worker = 0 if "/worker_0/" in selected["source_result"] else 1
        if source_worker != args.worker:
            continue
        folder = out / f"{selected['case_id']}_{selected['seed']}"
        folder.mkdir(exist_ok=True)
        source = root / selected["source_result"]
        if file_hash(source) != selected["source_result_sha256"]:
            raise ValueError("Collection result mutated after event selection")
        baseline = json.loads(source.read_text(encoding="utf-8"))
        engine = NativeEngine(model, tokenizer, device)
        identity = execution_identity(root, engine, metadata)
        model_device = engine.device
        engine.torch.cuda.reset_peak_memory_stats(model_device)
        began = time.monotonic()
        with engine.torch.inference_mode():
            snapshot = checkpoint(engine, identity, baseline, selected)
            write(folder / "checkpoint.json", {**snapshot.metadata(), "copy_cost": asdict(snapshot.copy_cost),
                                               "setup_paid_work": cost(engine.ledger),
                                               "setup_seconds": time.monotonic()-began,
                                               "execution": identity.as_dict()})
            identity_result = identity_pair(engine, snapshot, identity, baseline, folder)
            identity_pass = (identity_result["sampled_tokens_equal"] and identity_result["same_terminal_status"]
                             and identity_result["original_snapshot_unmodified"] and identity_result["terminal_RNG_equal"]
                             and identity_result["RNG_equal_at_compared_steps"]
                             and identity_result["maximum_logit_difference"] == 0
                             and identity_result["matches_recorded_native_full_ids"])
            write(folder / "IDENTITY_GATE.json", {"status": "PASS" if identity_pass else "FAIL",
                                                    "criteria": identity_result})
            if not identity_pass:
                raise RuntimeError("UNKNOWN identity gate failed before intervention generation")
            identity_peak = engine.torch.cuda.max_memory_allocated(model_device)
            review = next(review for review in role_reviews["reviews"]
                          if (review["case_id"], review["seed"], review["event_step"]) ==
                          (selected["case_id"], selected["seed"], selected["step"]))
            from repair_actions import run_repair_experiment
            engine.torch.cuda.reset_peak_memory_stats(model_device)
            repair_result = run_repair_experiment(engine, snapshot, identity, selected, baseline,
                                                  review.get("role_certificate"), folder)
            repair_peak = engine.torch.cuda.max_memory_allocated(model_device)
            del snapshot
            arms = []
            for arm in ("InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck"):
                engine.torch.cuda.reset_peak_memory_stats(model_device)
                arm_started = time.monotonic()
                arm_first_forward = len(engine.ledger)
                native_source = regenerate_checkpoint(engine, identity, baseline, selected)
                result = run_check_arm(engine, native_source, identity, selected, arm, folder)
                engine.sync()
                path = folder / (arm + ".json")
                complete = json.loads(path.read_text(encoding="utf-8"))
                complete.update(standalone_end_to_end_seconds=time.monotonic() - arm_started,
                                standalone_paid_work=cost(engine.ledger[arm_first_forward:]),
                                standalone_ledger=engine.ledger[arm_first_forward:],
                                native_prefix_capture_cost=asdict(native_source.copy_cost),
                                peak_allocated_bytes=engine.torch.cuda.max_memory_allocated(model_device),
                                standalone_scope="native prefix sampled from original seed, capture, audit and full EOS")
                write(path, complete)
                result.update(standalone_end_to_end_seconds=complete["standalone_end_to_end_seconds"],
                              standalone_paid_work=complete["standalone_paid_work"],
                              peak_allocated_bytes=complete["peak_allocated_bytes"])
                arms.append(result)
                del native_source
            write(folder / "all_paid_forwards.json", engine.ledger)
        summary = {"case_id": selected["case_id"], "seed": selected["seed"], "identity": identity_result,
                   "arms": arms, "repair": repair_result,
                   "identity_joint_peak_allocated_bytes": identity_peak,
                   "repair_peak_allocated_bytes": repair_peak,
                   "peak_allocated_bytes": max(identity_peak, repair_peak, *(arm["peak_allocated_bytes"] for arm in arms)),
                   "elapsed_seconds": time.monotonic()-began, "all_paid_work": cost(engine.ledger)}
        write(folder / "summary.json", summary)
        summaries.append(summary)
        write(out / "progress.json", {"status": "RUNNING", "completed": len(summaries), "cases": summaries})
        del engine
    write(out / "summary.json", {"status": "COMPLETE", "completed": len(summaries), "cases": summaries})


if __name__ == "__main__":
    main()
