"""Frozen observed-state E15 feedback trial under the native Qwen3 schedule."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
D35 = ROOT / "legacy" if (ROOT / "legacy").is_dir() else ROOT.parent / "phase5d35_witness_gated_revision_20261109"
sys.path.append(str(D35))

from development_worker import (D1, NativeEngine, capture_snapshot, id_sha, load_runtime,
                                prompt_for, reference_runtime, restore_snapshot, verify_inputs, work, write)
from candidate_archive import ObservedPrefix, observe
from candidate_ratchet import ProgressiveWitness
from complete_answer import _rational
from complete_answer_v2 import extract_final_answer
from goal_claim_detector import comparison_supports, target_id_for
from native_snapshot import advance_native, replay_schedule
from witness_contract import DIGITS, compile_contract


ARMS = ("NativeContinue", "NeutralReminder", "ClaimOnly", "NumericWitness", "VerifiedWitness",
        "ProgressiveWitness", "EveryStepAudit", "InvalidWitnessControl")
INTERACTIVE = {"ProgressiveWitness", "EveryStepAudit"}
CHECKPOINTS = {"early": (316, 19902), "late": (464, 24532)}
MAX_RECOGNIZED_DIGITS = 16
CLAIM = re.compile(
    r"\b(?:(?:the\s+)?(?:current\s+|global\s+)?(?:largest|greatest|maximum)\s+"
    r"(?:(?:valid|fibbish)\s+){0,2}(?:number|candidate|value)\s*(?:is|=)|"
    r"(?:the\s+)?(?:[a-z0-9]+-digit\s+)?(?:candidate|number)\s*(?:is|=))\s*"
    r"(?:\\\(|\$|`|\*\*)?\s*(?P<forward>[1-9][0-9]{0,15})(?![0-9,])(?=\s|[.;$`*\\]|$)"
    r"|(?<![\d,])(?P<reverse>[1-9][0-9]{0,15})(?![\d,])\s*(?:\$|`|\*\*)?\s+"
    r"(?:is\s+(?:a\s+)?(?:valid(?:\s+fibbish)?\s+number|valid\b|fibbish\b|the\s+(?:maximum|greatest|largest)\b)"
    r"|satisfies\s+the\s+(?:original\s+)?(?:fibbish|digit)\b)", re.I,
)
NEGATED = re.compile(r"\b(?:if|suppose|assume|maybe|whether|could|would|try|might|not)\b", re.I)
EXTREMUM = re.compile(r"\b(?:largest|greatest|maximum)\b", re.I)
EXACT_INTEGER = re.compile(rf"(?<![0-9A-Za-z_,./+−-])[1-9][0-9]{{0,{MAX_RECOGNIZED_DIGITS - 1}}}(?![0-9A-Za-z_,/+−-]|\.\d)")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(engine, ids, *, special=True):
    return engine.tokenizer.decode(list(ids), skip_special_tokens=not special)


def source_prefix(engine, identity, packet, generated, trajectory):
    return ObservedPrefix.from_tokens(
        generated, lambda ids: decode(engine, ids), prompt_ids=packet["prompt_ids"],
        tokenizer_sha256=identity.tokenizer_sha256, trajectory_id=trajectory,
        question_sha256=sha(packet["question"].encode()),
    )


def candidate(prefix, contract, span, value, *, role, source=None, maximum=False):
    kind = "MAXIMALITY_CLAIM" if maximum else "FEASIBLE_CANDIDATE"
    return observe(prefix, contract_id=contract.contract_id, target_id=target_id_for(contract),
                   goal_claim_type=kind, role=role, source=span if source is None else source,
                   fields={"value": span}, value=value,
                   claim={"kind": "MAX", "value": value} if maximum else None)


def observed_plan(prefix, contract):
    """Choose the first actually observed false literal comparison, without a global claim."""
    supports = [row for row in comparison_supports(prefix, contract)
                if row.relation == "<" and row.left > row.right]
    if not supports:
        raise ValueError("Selected prefix has no source-bound false literal comparison")
    return min(supports, key=lambda row: row.source_span.token_span)


def read_budget(freeze):
    return {"point_budget": freeze["primary_point_budget"],
            "work_budget": freeze["arithmetic_work_budget"], "feedback_budget": freeze["feedback_budget"]}


def cues(left, right):
    opening = "\n\nReview the current search for the maximum. "
    closing = " Continue solving the original problem, justify the greatest valid value, and give the final boxed answer.\n\n"
    neutral = "Check whether a larger valid candidate exists."
    claim = f"The prior comparison does not establish {right} as greatest."
    numeric = f"Exact numerical comparison gives {left} > {right}. This comparison alone does not check feasibility."
    verified = f"A point check confirms {left} satisfies the original digit rule, and {left} > {right}. It is a feasible lower bound."
    content = {"NeutralReminder": neutral, "ClaimOnly": claim, "NumericWitness": numeric,
               "VerifiedWitness": verified, "ProgressiveWitness": verified, "EveryStepAudit": verified,
               "InvalidWitnessControl": neutral}
    return {"NativeContinue": "", **{arm: opening + text + closing for arm, text in content.items()}}


def seed_controller(prefix, contract, support, budgets, mode):
    controller = ProgressiveWitness(contract, prefix, mode=mode, **budgets)
    operands = []
    for span, value in ((support.right_span.char_span, support.right), (support.left_span.char_span, support.left)):
        item = candidate(prefix, contract, span, value, role="observed_comparison_operand")
        decision = controller.admit(prefix, item, feedback=False)
        if decision.receipt is None or decision.receipt.status != "CERTIFIED_FEASIBLE":
            raise ValueError("Required point-check could not certify the observed operand")
        operands.append(decision.as_dict())
    return controller, operands


def reject_invalid_control(prefix, contract, support):
    """Try to replace an actual candidate field before model exposure, then fail closed."""
    forged = 10112357  # Preregistered falsified control, not an observation or a Gold answer.
    try:
        candidate(prefix, contract, support.left_span.char_span, forged, role="observed_comparison_operand")
    except ValueError:
        return {"status": "REJECTED_UNBOUND_OBSERVATION", "candidate": forged,
                "attempted_source": support.left_span.as_dict(), "exposed_to_model": False,
                "fallback": "identical NeutralReminder cue and paired RNG"}
    raise ValueError("Invalid witness matched a different numeric observation")


def paragraph_matches(text):
    for match in CLAIM.finditer(text):
        prelude = re.split(r"[.!?\n]", text[max(0, match.start() - 90):match.start()])[-1]
        trailing = text[match.end():match.end() + 35]
        if NEGATED.search(prelude) or re.match(r"\s+(?:possible\s+)?(?:digits?|bits?|length)\b", trailing, re.I):
            continue
        role = "explicit_candidate_commitment"
        maximum = bool(EXTREMUM.search(match[0]))
        yield match.span(), match.span("forward" if match["forward"] else "reverse"), maximum, role


def authored_candidates(engine, prefix, contract, start, end, matches):
    previous = decode(engine, prefix.generated_ids[:start])
    visible = decode(engine, prefix.generated_ids[start:end])
    if not prefix.text.startswith(previous + visible):
        return ()
    result = []
    for source, field, maximum, role in matches:
        offset = len(previous)
        value = int(visible[slice(*field)])
        field = (field[0] + offset, field[1] + offset)
        source = (source[0] + offset, source[1] + offset)
        try:
            result.append(candidate(prefix, contract, field, value, source=source, role=role, maximum=maximum))
        except ValueError:
            continue
    return result


def terminal_candidate(engine, prefix, contract, final_start, final_response):
    selection = extract_final_answer(final_response, "scalar")
    if selection.get("status") != "ok" or len(selection.get("components", ())) != 1:
        return None, selection
    value = _rational(selection["components"][0])
    if value is None or value.denominator != 1 or value <= 0 or not selection.get("selected_span"):
        return None, selection
    before = decode(engine, prefix.generated_ids[:final_start])
    if not prefix.text.startswith(before + final_response):
        return None, selection
    start, end = (len(before) + offset for offset in selection["selected_span"])
    digits = [m for m in EXACT_INTEGER.finditer(prefix.text, start, end) if int(m[0]) == value]
    if len(digits) != 1:
        return None, selection
    try:
        item = candidate(prefix, contract, digits[0].span(), int(value), source=(start, end),
                         role="explicit_maximum_answer", maximum=True)
    except ValueError:
        item = None
    return item, selection


def replay_diagnostics(engine, cache, logits, packet):
    started = time.monotonic()
    expected = len(packet["prompt_ids"]) + len(packet["generated_ids"])
    layers = engine.kv_fingerprints(cache)
    if int(cache.get_seq_length()) != expected or any(
            pair["shape"][-2] != expected for layer in layers for pair in layer["kv"]):
        raise ValueError("Prefix and full KV positions differ")
    logit_raw = logits.detach().float().cpu().contiguous().numpy().tobytes()
    return {"observed_prefix_sha256": packet["observed_prefix_sha256"], "cache_sequence_length": expected,
            "next_logits_sha256_fp32": sha(logit_raw), "next_logits_numel": logits.numel(), "kv_layers": layers,
            "diagnostic_wall_seconds": time.monotonic() - started,
            "qualification": "Measured replay state; historical D3 did not export per-checkpoint KV/logit bytes."}


def restore_before_close(engine, state, resume, stage):
    """Retain the paid RNG stream while removing the rejected final drafting suffix."""
    start = time.monotonic()
    end, position, logits = resume
    rng_before = sha(bytes(state.rng.get_state().cpu().tolist()))
    engine.stage = stage
    if callable(getattr(state.cache, "crop", None)):
        state.cache.crop(position)
        method = "native_dynamic_cache_crop"
    else:
        state.cache, logits = replay_schedule(engine, state.prompt_ids, state.generated_ids[:end])
        method = "paid_singleton_replay"
    if int(state.cache.get_seq_length()) != position:
        raise ValueError("Terminal repair restore position mismatch")
    del state.generated_ids[end:]
    state.next_logits = logits
    state.cache_position = position
    state.thinking_open = True
    state.stop_reason = "RUNNING"
    engine.sync()
    return {"method": method, "restored_generated_tokens": end, "cache_position": position,
            "restored_prefix_sha256": id_sha(list(state.prompt_ids) + state.generated_ids),
            "wall_seconds": time.monotonic() - start, "rng_policy": "keep_paid_post_draft_rng",
            "post_draft_rng_before_restore_sha256": rng_before,
            "rng_after_restore_sha256": sha(bytes(state.rng.get_state().cpu().tolist()))}


def feedback_paragraph(obligation):
    return "\n\n" + obligation.message.strip() + "\n\n"


def run_arm(engine, identity, ref, snapshot, packet, contract, support, seed_id, arm, cue, budgets,
            repair_attempts, folder, shared_work):
    began = time.monotonic()
    ledger_start = len(engine.ledger)
    state = restore_snapshot(engine, snapshot, identity=identity)
    trajectory = f"d36_{packet['checkpoint_step']}_{seed_id}_{arm}"
    mode = "every_step" if arm == "EveryStepAudit" else "event"
    interactive = arm in INTERACTIVE
    controller = None
    setup = []
    invalid = None
    setup_start = time.monotonic()
    if interactive or arm in {"VerifiedWitness", "InvalidWitnessControl"}:
        initial = source_prefix(engine, identity, packet, state.generated_ids, trajectory)
        if arm == "InvalidWitnessControl":
            invalid = reject_invalid_control(initial, contract, support)
        else:
            controller, setup = seed_controller(initial, contract, support, budgets, mode)
    setup_seconds = time.monotonic() - setup_start
    forced = []

    def inject(message, phase):
        at = len(state.generated_ids)
        row = ref.append_checked_text(engine, state, message, arm + "_" + phase)
        forced.append({**row, "phase": phase, "start_generated": at, "end_generated": len(state.generated_ids)})
        return row["status"] == "APPENDED"

    if cue and not inject(cue, "initial_cue"):
        raise ValueError("Frozen initial cue did not fit")
    start = len(state.generated_ids)
    next_progress = start + 256
    sampled = 0
    events = []
    rejected = []
    restores = []
    held = False
    incumbent = support.left
    resume = None
    parser_seconds = 0.0
    skipped_nonimproving = 0
    while True:
        engine.stage = arm + "_decode"
        while state.stop_reason == "RUNNING":
            pre_token = ((len(state.generated_ids), state.cache_position, state.next_logits)
                         if interactive and state.thinking_open else None)
            token = advance_native(engine, state)
            sampled += 1
            if token == engine.close_ids[0] and pre_token is not None:
                resume = pre_token
            if sampled + len(snapshot.generated_ids) >= next_progress:
                write(folder / (arm + "_progress.json"), {"status": "GENERATING", "arm": arm,
                      "generated_tokens": len(state.generated_ids), "sampled_paid_tokens": sampled,
                      "elapsed_seconds": time.monotonic() - began})
                next_progress += 256
            if not interactive or state.stop_reason != "RUNNING" or not state.thinking_open:
                continue
            parse_started = time.monotonic()
            if decode(engine, state.generated_ids[-8:]).endswith("\n\n"):
                end = len(state.generated_ids)
                matches = tuple(paragraph_matches(decode(engine, state.generated_ids[start:end])))
                if matches:
                    prefix = source_prefix(engine, identity, packet, state.generated_ids, trajectory)
                    for item in authored_candidates(engine, prefix, contract, start, end, matches):
                        if (mode == "event" and item.value <= incumbent
                                and item.goal_claim_type != "MAXIMALITY_CLAIM"):
                            skipped_nonimproving += 1
                            continue
                        decision = controller.admit(prefix, item, authored_span=(start, end))
                        events.append({"phase": "thinking", "candidate": item.as_dict(), "decision": decision.as_dict()})
                        if decision.receipt is not None and decision.receipt.status == "CERTIFIED_FEASIBLE":
                            incumbent = max(incumbent, item.value)
                        if decision.obligation is not None:
                            if inject(feedback_paragraph(decision.obligation), "event_feedback"):
                                engine.stage = arm + "_decode"
                                break  # Re-extract on the next authored paragraph under the new prefix.
                start = len(state.generated_ids)
            parser_seconds += time.monotonic() - parse_started
        result = ref.state_result(engine, state)
        terminal_decision = None
        selection = None
        if interactive and result["EOS"] and result["think_closed"] and resume is not None:
            parse_started = time.monotonic()
            prefix = source_prefix(engine, identity, packet, state.generated_ids, trajectory)
            item, selection = terminal_candidate(engine, prefix, contract, resume[0] + 1, result["final_response"])
            parser_seconds += time.monotonic() - parse_started
            if item is not None:
                terminal_decision = controller.admit(prefix, item, terminal=True,
                                                     authored_span=(resume[0] + 1, len(state.generated_ids)))
                events.append({"phase": "final", "candidate": item.as_dict(), "decision": terminal_decision.as_dict()})
        if terminal_decision is None or not terminal_decision.veto:
            break
        obligation = terminal_decision.obligation
        if len(restores) >= repair_attempts or obligation is None:
            held = True
            break
        repair_message = feedback_paragraph(obligation)
        # Do not truncate a paid draft if there is no capacity to resume with the repair.
        if resume[1] + len(engine.tokenizer.encode(repair_message, add_special_tokens=False)) >= engine.capacity:
            held = True
            break
        rejected.append({"stop_reason": state.stop_reason, "generated_sha256": result["generated_sha256"],
                         "final_response": result["final_response"], "discarded_sampled_ids": state.generated_ids[resume[0]:],
                         "draft_start": resume[0], "draft_end": len(state.generated_ids), "paid_samples_so_far": sampled})
        restores.append(restore_before_close(engine, state, resume, arm + "_repair_replay"))
        if not inject(repair_message, "terminal_feedback"):
            raise ValueError("A checked terminal repair failed to enter the restored state")
        start = len(state.generated_ids)
        resume = None
    engine.sync()
    paid = engine.ledger[ledger_start:]
    final_response = result["final_response"] if not held else None
    delivery = "WITHHELD_CERTIFIED_VETO" if held else "NATIVE_MODEL_DRAFT"
    return {**result, "arm": arm, "case_id": packet["case_id"], "checkpoint_step": packet["checkpoint_step"],
            "replicate": seed_id, "retained_observed_tokens": len(snapshot.generated_ids),
            "initial_cue": cue, "forced_feedback": forced, "sampled_continuation_tokens": sampled,
            "teacher_forced_tokens": sum(row["tokens"] for row in forced), "rejected_drafts": rejected,
            "terminal_restores": restores, "terminal_selection": selection, "final_delivery": delivery,
            "delivered_final_response": final_response, "certified_optimality": False,
            "invalid_witness_control": invalid, "initial_point_receipts": setup, "point_audit_events": events,
            "controller": controller.report() if controller is not None else None,
            "verifier_setup_seconds": setup_seconds,
            "authored_candidate_scan_seconds_including_feedback": parser_seconds,
            "nonimproving_thinking_candidates_skipped_before_tool": skipped_nonimproving,
            "restore_copy_cost": asdict(state.restore_cost), "paid_work_after_cut": work(paid),
            "ledger_after_cut": paid, "shared_replay_equivalent": shared_work,
            "elapsed_seconds": time.monotonic() - began}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", choices=CHECKPOINTS, required=True)
    parser.add_argument("--replicate")
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    args = parser.parse_args()
    verify_inputs(args.root, f"d36_{args.checkpoint}_runtime_freeze.json")
    packet = json.loads((args.root / "prepared" / f"{args.checkpoint}_checkpoint.json").read_bytes())
    freeze = json.loads((args.root / "D36_EXPERIMENT_FREEZE.json").read_bytes())
    if tuple(freeze["arms"]) != ARMS or freeze["terminal_repair_attempts"] != 1:
        raise ValueError("Frozen arm set or repair allowance disagrees with the runner")
    replicas = [row for row in freeze["replicates"] if args.replicate is None or row["id"] == args.replicate]
    if not replicas or len({row["id"] for row in replicas}) != len(replicas):
        raise ValueError("Continuation RNG seed is absent or ambiguous")
    if (packet["checkpoint_step"], len(packet["generated_ids"])) != CHECKPOINTS[args.checkpoint]:
        raise ValueError("Unexpected frozen early/late checkpoint")
    model, tokenizer, device, metadata = load_runtime(D1, args.model, args.gpu)
    engine = NativeEngine(model, tokenizer, device)
    ref = reference_runtime()
    identity = ref.execution_identity(D1, engine, metadata)
    packet_ids = packet["generated_ids"]
    if (prompt_for(tokenizer, packet["question"]) != packet["prompt_ids"]
            or id_sha(packet["prompt_ids"] + packet_ids) != packet["observed_prefix_sha256"]
            or packet["boundary_offsets"][-1] != len(packet_ids)
            or not decode(engine, packet_ids[-8:]).endswith("\n\n")):
        raise ValueError("Invalid observed native packet or open-thought paragraph boundary")
    contract = compile_contract(packet["question"])
    if contract is None or contract.template_id != DIGITS:
        raise ValueError("No trusted E15 local feasibility predicate")
    support = observed_plan(source_prefix(engine, identity, packet, packet_ids, "frozen_plan"), contract)
    prompts = cues(support.left, support.right)
    cue_ids = {arm: tokenizer.encode(text, add_special_tokens=False) for arm, text in prompts.items()}
    if not cue_ids["VerifiedWitness"] == cue_ids["ProgressiveWitness"] == cue_ids["EveryStepAudit"]:
        raise ValueError("Matched evidence arm cues differ")
    rng_bytes = base64.b64decode(packet["rng_state_base64"], validate=True)
    rng_state = engine.torch.tensor(list(rng_bytes), dtype=engine.torch.uint8)
    folder = args.root / "gpu_results" / (args.checkpoint if args.replicate is None else f"{args.checkpoint}_{args.replicate}")
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / "manifest.json", metadata)
    began = time.monotonic()
    engine.torch.cuda.reset_peak_memory_stats(device)
    with engine.torch.inference_mode():
        engine.stage = "shared_observed_prefix_replay"
        cache, logits = engine.prefill(packet["prompt_ids"])
        for index, token in enumerate(packet_ids, 1):
            cache, logits = engine.forward([token], cache)
            if index % 512 == 0:
                write(folder / "replay_progress.json", {"retained": index, "target": len(packet_ids)})
        engine.sync()
        replay = {"wall_seconds": time.monotonic() - began, "work": work(engine.ledger)}
        diagnostics = replay_diagnostics(engine, cache, logits, packet)
        write(folder / "SOURCE_BOUND_PLAN.json", {"status": "READY", "observed_comparison": asdict(support),
              "question_sha256": contract.question_sha256, "contract_id": contract.contract_id,
              "checkpoint_step": packet["checkpoint_step"], "historical_rng_sha256": sha(rng_bytes),
              "initial_cues": prompts, "initial_cue_token_ids": cue_ids,
              "shared_replay": replay, "replay_state_diagnostics": diagnostics,
              "point_budget": read_budget(freeze), "arms": ARMS,
              "no_original_future_gold_or_solver": True})
        historical_rng = engine.rng(state=rng_state.clone())
        shared_snapshot = capture_snapshot(engine, identity=identity, prompt_ids=packet["prompt_ids"],
                                           generated_ids=packet_ids, cache=cache, next_logits=logits,
                                           rng=historical_rng, thinking_open=True,
                                           checkpoint_id=f"d36_{args.checkpoint}_shared")
        del cache, logits
        summaries = []
        for row in replicas:
            seed_id = row["id"]
            replica_folder = folder / seed_id
            replica_folder.mkdir()
            rng = engine.rng(state=rng_state.clone()) if row["seed"] is None else engine.rng(seed=row["seed"])
            snapshot = replace(shared_snapshot, _rng_state=rng.get_state(), checkpoint_id=f"d36_{args.checkpoint}_{seed_id}")
            write(replica_folder / "snapshot.json", {**snapshot.metadata(), "rng_sha256": sha(bytes(rng.get_state().cpu().tolist())),
                  "continuation_seed": row["seed"], "snapshot_copy_cost_shared_once": asdict(snapshot.copy_cost)})
            for arm in ARMS:
                arm_row = run_arm(engine, identity, ref, snapshot, packet, contract, support, seed_id, arm, prompts[arm],
                                  read_budget(freeze), freeze["terminal_repair_attempts"], replica_folder, replay)
                write(replica_folder / (arm + ".json"), arm_row)
                summaries.append({key: arm_row[key] for key in ("arm", "replicate", "stop_reason", "final_delivery",
                                  "sampled_continuation_tokens", "teacher_forced_tokens", "elapsed_seconds")})
                write(folder / "arm_progress.json", {"status": "GENERATING", "completed": summaries,
                      "total": len(replicas) * len(ARMS)})
            del snapshot
        del shared_snapshot
    write(folder / "actual_forward_ledger.json", engine.ledger)
    write(folder / "summary.json", {"status": "COMPLETE", "checkpoint": args.checkpoint, "arms": summaries,
          "actual_shared_replay": replay, "actual_paid_work": work(engine.ledger),
          "elapsed_seconds": time.monotonic() - began, "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(device)})


if __name__ == "__main__":
    main()
