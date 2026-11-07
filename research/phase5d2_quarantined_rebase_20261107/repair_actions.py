"""Conditional native repair arms from one already observed checkpoint."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import sys

from dual_frontier_rebase import bind_observed_thinking, plan_rebase, replay_rebase, _closed_paragraph
from natural_ledger import build_natural_ledger, make_observed_relations, relation_sha256, support
from natural_evidence import relations
from native_snapshot import NativeState, replay_schedule, restore_snapshot, validate_snapshot


ARMS = ("GenericRewind", "RebaseNoCarry", "RebaseCarry", "FullRestart", "SameEvidenceCompactBridge")
RESAMPLING_SEEDS = tuple(range(20261109, 20261117))


def _write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _helpers(provided):
    if provided is not None:
        return provided
    from paired_d2_worker import append_checked_text, finish, state_result, cost
    return SimpleNamespace(append_checked_text=append_checked_text, finish=finish, state_result=state_result, cost=cost)


def _observed_inputs(engine, snapshot, selected, baseline):
    end = selected["generated_count"]
    if (baseline["case_id"] != selected["case_id"] or baseline["seed"] != selected["seed"]
            or tuple(baseline["prompt_ids"]) != snapshot.prompt_ids or tuple(baseline["generated_ids"][:end]) != snapshot.generated_ids
            or snapshot.prefix_sha256 != selected["observed_prefix_sha256"] or end != len(snapshot.generated_ids)):
        raise ValueError("Selected checkpoint source differs from its snapshot")
    steps = []
    parsed = []
    boundaries = [0]
    rejected_boundaries = []
    for step in baseline["steps"]:
        if step["end"] > end:
            continue
        if not 0 <= step["start"] < step["end"] <= end:
            raise ValueError("An observed step has invalid generated-token offsets")
        text = engine.tokenizer.decode(list(snapshot.generated_ids[step["start"]:step["end"]]), skip_special_tokens=False)
        if text != step["text"]:
            raise ValueError("Observed step text and exact source tokens differ")
        steps.append(step)
        if text.endswith("\n\n"):
            observed_text = engine.tokenizer.decode(list(snapshot.generated_ids[:step["end"]]), skip_special_tokens=False)
            if _closed_paragraph(observed_text):
                boundaries.append(step["end"])
            else:
                rejected_boundaries.append(step["end"])
        for item in relations(step):
            parsed.append({**item, "observed_prefix_sha256": snapshot.prefix_sha256})
    step = next((item for item in steps if item["step"] == selected["step"]), None)
    if step is None or step["end"] != end or not step["text"].endswith("\n\n"):
        raise ValueError("Selected event lacks its observed complete paragraph")
    candidate = selected.get("relation")
    if not isinstance(candidate, dict):
        return steps, parsed, boundaries, None, step, rejected_boundaries
    candidate = {**candidate, "observed_prefix_sha256": snapshot.prefix_sha256}
    if not any(relation_sha256(item) == relation_sha256(candidate) for item in parsed):
        raise ValueError("Selected relation differs from observed-prefix extraction")
    return steps, parsed, boundaries, candidate, step, rejected_boundaries


def _prefix_work(baseline, position, cost):
    rows = []
    cursor = 0
    for row in baseline.get("ledger", ()):
        if row["past_tokens"] != cursor or row.get("position_start", cursor) != cursor:
            raise ValueError("Original prefix ledger is not a contiguous native stream")
        end = cursor + row["input_tokens"]
        if end > position:
            break
        rows.append(row)
        cursor = end
        if cursor == position:
            break
    return {"available": cursor == position, "cache_position": position, "recorded_position": cursor,
            "work": cost(rows) if cursor == position else None, "wall_seconds": None,
            "wall_scope": "Original stream has no per-prefix wall measurement; its paid forward work is separate."}


def _evidence(build, candidate, carry_plan):
    proof = build.ledger.proofs[build.metadata["candidate_proof_id"]]
    claim = build.ledger.claims[proof.conclusion]
    payload = {"observed_equality": candidate["surface"], "generated_token_span": candidate["token_span"],
               "literal_expression": proof.expression, "exact_expression_value": str(support.exact(proof.expression)),
               "stated_rhs_value": str(claim.value), "effect": "Withdraw this arithmetic proof occurrence.",
               "role_review_receipt_sha256": build.metadata["role_certificate_sha256"],
               "checker_certificate": asdict(build.challenge.certificate)}
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", r"\u003c").replace(">", r"\u003e")
    bad = "\n\nChecked arithmetic evidence for the already observed step.\n" + encoded + "\nContinue solving the original problem.\n\n"
    return bad, carry_plan.bridge_text, payload


def _fresh_state(engine, snapshot, identity, kept, *, seed=None):
    cache, logits = replay_schedule(engine, snapshot.prompt_ids, snapshot.generated_ids[:kept])
    rng = engine.rng(state=snapshot._rng_state.clone()) if seed is None else engine.rng(seed=seed)
    return NativeState(snapshot.prompt_ids, list(snapshot.generated_ids[:kept]), cache, logits, rng,
                       len(snapshot.prompt_ids) + kept, True, "RUNNING", identity)


def _record_result(engine, state, helper, arm, selected, began, first_forward, common, prefix_work, kept, injected, **extra):
    result = {**helper.state_result(engine, state), "case_id": selected["case_id"], "seed": selected["seed"], "arm": arm,
              "elapsed_seconds": time.monotonic() - began, "postcheckpoint_paid_work": helper.cost(engine.ledger[first_forward:]),
              "postcheckpoint_ledger": engine.ledger[first_forward:], "common_observed_prefix": prefix_work,
              "retained_observed_generated_tokens": kept, "discarded_observed_generated_tokens": selected["generated_count"] - kept,
              "teacher_forced_evidence_tokens": sum(item["tokens"] for item in injected),
              "evidence_injections": injected, "common_evidence": common,
              "hot_restore_cost": None if state.restore_cost is None else asdict(state.restore_cost), **extra}
    if prefix_work["available"]:
        result["full_paid_forward_work_with_common_prefix"] = {
            key: prefix_work["work"][key] + result["postcheckpoint_paid_work"][key]
            for key in result["postcheckpoint_paid_work"]}
    return result


def _append(helper, engine, state, text, stage):
    if not text:
        return {"status": "EMPTY", "tokens": 0}
    result = helper.append_checked_text(engine, state, text, stage)
    if result["status"] != "APPENDED":
        raise RuntimeError("A READY repair could not fit its checked evidence")
    return result


def _selector():
    try:
        import d0_answer_extract
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase5d_scope_rebase_20261106"))
        import d0_answer_extract
    expected = "e64ef21c1b9e90ad8ecb41b0ce5058307248d33668b91fbfa3ece4e98b69d37d"
    if hashlib.sha256(Path(d0_answer_extract.__file__).read_bytes()).hexdigest() != expected:
        raise ValueError("Frozen LastBox selection source differs")
    return d0_answer_extract


def plurality(replicas):
    """Frozen LastBox surface fingerprints with earliest-occurrence tie break."""
    selector = _selector()
    groups = {}
    for index, result in enumerate(replicas):
        if result.get("EOS") is not True:
            result["plurality_extraction"] = {"status": "unknown", "reason": "replica_did_not_reach_EOS"}
            continue
        extraction = selector.extract_policy(result["final_response"], "LastBox")
        result["plurality_extraction"] = extraction
        if extraction["status"] != "ok":
            continue
        key = selector.fingerprint(extraction["surface"])
        groups.setdefault(key, []).append(index)
    if not groups:
        return None
    return min(groups.values(), key=lambda indices: (-len(indices), indices[0]))[0]


def _bracket(replicas, target):
    total = 0.0
    below = None
    above = None
    completed = 0
    for index, replica in enumerate(replicas):
        total += replica["elapsed_seconds"]
        if replica.get("EOS") is not True:
            continue
        completed += 1
        point = {"replicas": index + 1, "completed_EOS_replicas": completed, "cumulative_seconds": total}
        if total <= target:
            below = point
        if total > target and above is None:
            above = point
    return {"target_postcheckpoint_seconds": target, "below": below, "above": above,
            "bracketed": below is not None and above is not None,
            "status": "BRACKETED" if below is not None and above is not None else
                      "NO_COMPLETED_BELOW_TARGET" if above is not None else "REPLICA_GUARD_BEFORE_UPPER",
            "actual_completed_replica_seconds": total}


def run_repair_experiment(engine, snapshot, identity, selected, baseline, role_certificate, folder, *, helpers=None):
    folder = Path(folder)
    output = folder / "repair"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob("*.json")):
        raise ValueError("Repair folder already has records; preserve the earlier attempt")
    started = time.monotonic()
    case = {"case_id": selected["case_id"], "seed": selected["seed"]}
    _, parsed, boundaries, candidate, step, rejected = _observed_inputs(engine, snapshot, selected, baseline)
    boundary_diagnostics = {"accepted_paragraph_offsets": boundaries, "rejected_paragraph_offsets": rejected,
                            "rejected_paragraph_count": len(rejected)}
    if candidate is None:
        result = {"status": "NOT_ELIGIBLE", **case, "reason": "Selected event has no literal relation", "arms": [],
                  "source_boundaries": boundary_diagnostics}
        _write(output / "REPAIR_STATUS.json", result)
        return result
    source = make_observed_relations(snapshot.prompt_ids, snapshot.generated_ids, boundaries, parsed)
    build = build_natural_ledger(source, len(snapshot.generated_ids), candidate, role_certificate)
    if build.challenge is None:
        result = {"status": "NOT_ELIGIBLE", **case, "reason": build.status, "metadata": build.metadata, "arms": [],
                  "source_boundaries": boundary_diagnostics}
        _write(output / "REPAIR_STATUS.json", result)
        return result
    observed = bind_observed_thinking(build.ledger, engine.tokenizer, snapshot_id=snapshot.checkpoint_id,
                                      source_version=identity.sha256, prompt_ids=snapshot.prompt_ids,
                                      generated_ids=snapshot.generated_ids, boundary_offsets=boundaries)
    carry_plan = plan_rebase(build.ledger, build.challenge, observed, carry=True)
    no_carry_plan = plan_rebase(build.ledger, build.challenge, observed, carry=False)
    if carry_plan.status != "READY" or no_carry_plan.status != "READY":
        result = {"status": "NOT_ELIGIBLE", **case, "reason": carry_plan.status, "arms": [],
                  "source_boundaries": boundary_diagnostics}
        _write(output / "REPAIR_STATUS.json", result)
        return result
    helper = _helpers(helpers)
    validate_snapshot(engine, snapshot, identity=identity)
    bad_text, carry_text, evidence = _evidence(build, candidate, carry_plan)
    opening = observed.complete_boundaries[0]
    generic_cut = max(offset for offset in observed.complete_boundaries if offset <= step["start"])
    prefix_work = _prefix_work(baseline, snapshot.cache_position, helper.cost)
    prefix_work["snapshot_capture_cost"] = asdict(snapshot.copy_cost)
    prefix_work["execution_identity_sha256"] = identity.sha256
    common = {"checked_bad_equality": evidence, "bad_text_sha256": hashlib.sha256(bad_text.encode()).hexdigest(),
              "carry_packet_sha256": hashlib.sha256(carry_text.encode()).hexdigest(),
              "carried_claim_ids": list(carry_plan.carried_claims), "carry_packet_empty": not bool(carry_text),
              "carry_fact_provenance": [asdict(fact) for fact in carry_plan.carry_witness],
              "shared_preparation_seconds": time.monotonic() - started,
              "role_review_timing": "Pre-Gold review receipt exists before this timed executor; its review cost is external.",
              "NoCarry_policy": "The feature ablation omits the carry packet; strong baselines receive it."}
    summaries = []
    generation_prefixes = {}
    with engine.torch.inference_mode():
        for arm in ARMS:
            began = time.monotonic()
            first_forward = len(engine.ledger)
            injected = []
            if arm in ("RebaseNoCarry", "RebaseCarry"):
                plan = carry_plan if arm == "RebaseCarry" else no_carry_plan
                rebuilt = replay_rebase(engine, plan, build.ledger, observed, snapshot_id=snapshot.checkpoint_id,
                                         source_version=identity.sha256, current_prefix_ids=snapshot.prefix_ids)
                kept = plan.cut_token
                state = NativeState(snapshot.prompt_ids, list(rebuilt.prefix_ids[len(snapshot.prompt_ids):]), rebuilt.cache,
                                    rebuilt.next_logits, engine.rng(state=snapshot._rng_state.clone()), len(rebuilt.prefix_ids),
                                    True, "RUNNING", identity)
                injected.append({"status": "APPENDED" if rebuilt.appended_bridge_tokens else "EMPTY",
                                 "tokens": rebuilt.appended_bridge_tokens, "text": plan.bridge_text})
            elif arm == "SameEvidenceCompactBridge":
                kept = len(snapshot.generated_ids)
                state = restore_snapshot(engine, snapshot, identity=identity)
                injected.append(_append(helper, engine, state, carry_text, arm + "_carry"))
            else:
                kept = generic_cut if arm == "GenericRewind" else opening
                engine.stage = arm + "_schedule_replay"
                state = _fresh_state(engine, snapshot, identity, kept)
                injected.append(_append(helper, engine, state, carry_text, arm + "_carry"))
            injected.append(_append(helper, engine, state, bad_text, arm + "_checked_evidence"))
            generation_prefix = support.digest(tuple(state.prompt_ids) + tuple(state.generated_ids))
            generation_prefixes[arm] = generation_prefix
            continuation = helper.finish(engine, state, output, arm)
            engine.sync()
            result = _record_result(engine, state, helper, arm, selected, began, first_forward, common, prefix_work, kept,
                                    injected, continuation=continuation, RNG_policy="checkpoint post-observation RNG state",
                                    carry_serialized=arm != "RebaseNoCarry" and bool(carry_text),
                                    generation_start_prefix_sha256=generation_prefix)
            path = output / (arm + ".json")
            _write(path, result)
            summaries.append({"arm": arm, "path": path.relative_to(folder).as_posix(), "EOS": result["EOS"],
                              "elapsed_seconds": result["elapsed_seconds"], "paid_work": result["postcheckpoint_paid_work"]})
            del state
        target = max(item["elapsed_seconds"] for item in summaries)
        replicas = []
        for index, seed in enumerate(RESAMPLING_SEEDS, 1):
            began = time.monotonic()
            first_forward = len(engine.ledger)
            engine.stage = "Resampling_schedule_replay"
            state = _fresh_state(engine, snapshot, identity, opening, seed=seed)
            injected = [_append(helper, engine, state, carry_text, "Resampling_carry"),
                        _append(helper, engine, state, bad_text, "Resampling_checked_evidence")]
            continuation = helper.finish(engine, state, output, f"resampling_replica_{index:02}")
            engine.sync()
            replica = _record_result(engine, state, helper, "ResamplingReplica", selected, began, first_forward, common,
                                     prefix_work, opening, injected, continuation=continuation, replica_index=index,
                                     sampling_seed=seed, RNG_policy="fixed independent native resampling seed")
            replicas.append(replica)
            _write(output / f"resampling_replica_{index:02}.json", replica)
            del state
            if replica["EOS"] and sum(item["elapsed_seconds"] for item in replicas) > target:
                break
    selected_replica = plurality(replicas)
    for index, replica in enumerate(replicas, 1):
        _write(output / f"resampling_replica_{index:02}.json", replica)
    bracket = _bracket(replicas, target)
    for side in ("below", "above"):
        point = bracket[side]
        if point is None:
            continue
        count = point["replicas"]
        choice = plurality(replicas[:count])
        point["chosen_replica_index"] = None if choice is None else choice + 1
        point["selection_status"] = "ABSTAINED" if choice is None else "SELECTED"
        point["final_response"] = "" if choice is None else replicas[choice]["final_response"]
        point["cumulative_paid_work"] = helper.cost([row for item in replicas[:count] for row in item["postcheckpoint_ledger"]])
    if selected_replica is None:
        chosen = {"status": "COMPLETE", **case, "arm": "Resampling", "EOS": False, "think_closed": False,
                  "final_response": "", "generated_ids": [], "prompt_ids": list(snapshot.prompt_ids),
                  "stop_reason": "PLURALITY_ABSTAINED", "new_tokens": 0, "hit_context_cap": False,
                  "context_capacity": engine.capacity}
    else:
        chosen = {**replicas[selected_replica], "arm": "Resampling"}
    chosen.update(selection_policy="Plurality of frozen LastBox fingerprints, earliest tie, no Gold",
                  chosen_replica_index=None if selected_replica is None else selected_replica + 1,
                  resampling_bracket=bracket, replica_count=len(replicas), technical_replica_guard=len(RESAMPLING_SEEDS),
                  elapsed_seconds=sum(item["elapsed_seconds"] for item in replicas),
                  postcheckpoint_paid_work=helper.cost([row for item in replicas for row in item["postcheckpoint_ledger"]]),
                  postcheckpoint_ledger=[row for item in replicas for row in item["postcheckpoint_ledger"]],
                  teacher_forced_evidence_tokens=sum(item["teacher_forced_evidence_tokens"] for item in replicas),
                  completed_EOS_replicas=sum(item["EOS"] for item in replicas),
                  cost_matched_bracket_available=bracket["bracketed"])
    if prefix_work["available"]:
        chosen["full_paid_forward_work_with_common_prefix"] = {
            key: prefix_work["work"][key] + chosen["postcheckpoint_paid_work"][key]
            for key in chosen["postcheckpoint_paid_work"]}
    _write(output / "Resampling.json", chosen)
    summaries.append({"arm": "Resampling", "path": "repair/Resampling.json", "EOS": chosen["EOS"],
                      "elapsed_seconds": chosen["elapsed_seconds"], "paid_work": chosen["postcheckpoint_paid_work"]})
    result = {"status": "COMPLETE", **case, "arms": summaries, "resampling": bracket,
              "common_evidence": common, "common_prefix_work": prefix_work,
              "semantic_lost_support": sorted(carry_plan.lost_support),
              "invalidated_proof_token_spans": carry_plan.invalidated_text_spans,
              "source_boundaries": boundary_diagnostics,
              "rebase_cut_generated_token": carry_plan.cut_token, "generic_cut_generated_token": generic_cut,
              "cut_equality": generic_cut == carry_plan.cut_token,
              "generation_start_prefixes": generation_prefixes,
              "GenericRewind_RebaseCarry_prefix_equal": generation_prefixes["GenericRewind"] == generation_prefixes["RebaseCarry"],
              "NoCarry_Carry_prefix_equal": generation_prefixes["RebaseNoCarry"] == generation_prefixes["RebaseCarry"],
              "elapsed_seconds": time.monotonic() - started,
              "scope": "Conditional same-observed-prefix repair after pre-Gold role review."}
    _write(output / "REPAIR_STATUS.json", result)
    return result
