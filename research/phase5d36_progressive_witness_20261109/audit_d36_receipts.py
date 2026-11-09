"""Replay D3.6 v2 source, arithmetic, and control receipts after generation closes."""

from dataclasses import asdict, replace
import hashlib
import json
from math import isfinite
from types import SimpleNamespace

from wcpr_worker import (INTERACTIVE, authored_candidates, candidate, cues, feedback_paragraph,
                         id_sha, observed_plan, paragraph_matches, reject_invalid_control,
                         source_prefix, terminal_candidate)
from audit_dev_checkpoints import TOKENIZER, make_tokenizer
from goal_claim_detector import target_id_for
from progress_state import PointReceipt, ProgressState, canonical
from search_obligation import make_obligation
from witness_contract import DIGITS, check_candidate, compile_contract


def _require(ok, error):
    if not ok:
        raise ValueError(error)


def _equal(observed, expected, label):
    _require(canonical(observed) == canonical(expected), f"D3.6 v2 receipt differs at {label}")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class _ReplayPolicy:
    """Recompute v2 policy without the controller, query wrapper, or event trigger."""

    def __init__(self, contract, freeze, mode):
        self.contract = contract
        self.point_budget = freeze["primary_point_budget"]
        self.work_budget = freeze["arithmetic_work_budget"]
        self.feedback_budget = freeze["feedback_budget"]
        self.mode = mode
        self.state = ProgressState(contract.contract_id, target_id_for(contract), contract.question_sha256, "MAX")
        self.calls = self.ops = self.feedback = 0
        self.first = {}
        self.seen = set()
        self.decisions = []

    @property
    def incumbent(self):
        return self.state.incumbent.objective if self.state.incumbent else None

    def decision(self, item, *, terminal=False, feedback=True):
        point = item.value
        previous = self.first.get(point)
        remaining = self.work_budget - self.ops
        calls = ops = 0
        if previous:
            math, status, remaining = previous.math, previous.status, previous.check_budget
        elif self.calls == self.point_budget or not remaining:
            math = {"status": "UNKNOWN", "reason": "common_point_or_work_budget_exhausted"}
            status = "UNKNOWN"
        else:
            math = check_candidate(self.contract, point, budget=remaining)
            calls, ops = 1, math["paid_check_count"]
            scope_ok = math["proof_scope"] == "FULL_ORIGINAL_CONSTRAINTS" and math["certificate_sha256"]
            status = {"FEASIBLE_ONLY": "CERTIFIED_FEASIBLE", "INVALID_CANDIDATE": "CERTIFIED_INFEASIBLE"}.get(
                math["status"], "UNKNOWN") if scope_ok else "UNKNOWN"
        self.calls += calls
        self.ops += ops
        receipt = PointReceipt(item.contract_id, item.target_id, item.question_sha256, item.trajectory_id,
                               item.tokenizer_sha256, item.observed_prefix_sha256, item.observed_count,
                               item.candidate_id, item.source_span.token_span, item.source_span.token_sha256,
                               point, status, remaining, calls, ops, previous.receipt_sha256 if previous else None,
                               canonical(math))
        if previous is None and status != "UNKNOWN":
            self.first[point] = receipt

        if status == "UNKNOWN":
            action = "NATIVE_CONTINUE"
        elif status == "CERTIFIED_INFEASIBLE":
            action = "REPAIR_INFEASIBLE"
        elif self.incumbent is None or point > self.incumbent:
            action = "UPDATE_BOUND"
            self.state = replace(self.state, incumbent=receipt)
        else:
            action = "KEEP_BOUND" if point == self.incumbent else "BLOCK_REGRESSION"

        veto = terminal and action in {"BLOCK_REGRESSION", "REPAIR_INFEASIBLE"}
        allowed = veto if terminal else action in {"UPDATE_BOUND", "REPAIR_INFEASIBLE"} or (
            self.mode == "every_step" and action in {"KEEP_BOUND", "BLOCK_REGRESSION"})
        key = (action, item.candidate_id if self.mode == "every_step" else point, self.incumbent, terminal)
        obligation = None
        if feedback and allowed and self.feedback < self.feedback_budget and key not in self.seen:
            self.seen.add(key)
            self.feedback += 1
            obligation = make_obligation(self.state, action, receipt)
        decision = {"action": action, "receipt": receipt.as_dict(), "veto": veto, "certified_answer": None,
                    "terminal": terminal, "obligation": obligation.as_dict() if obligation else None}
        self.decisions.append(decision)
        return decision, obligation

    def check_summary(self, summary):
        expected = {"state": self.state.as_dict(), "point_budget": self.point_budget, "work_budget": self.work_budget,
                    "point_calls": self.calls, "paid_operations": self.ops, "bound_proof_operations": 0,
                    "mode": self.mode, "feedback_budget": self.feedback_budget, "feedback_emitted": self.feedback,
                    "events": self.decisions}
        for key, value in expected.items():
            _equal(summary[key], value, f"controller.{key}")
        seconds = summary["point_check_seconds"]
        _require(type(seconds) in (float, int) and isfinite(seconds) and seconds >= 0, "Invalid point wall time")


def _append_receipt(tokenizer, forced, generated, start, text, phase, prompt_length, capacity):
    ids = tokenizer.encode(text, add_special_tokens=False)
    applied = prompt_length + start + len(ids) < capacity
    end = start + len(ids) if applied else start
    details = {"text": text, "token_ids": ids, "text_sha256": _sha(text.encode())} if applied else {}
    record = {"status": "APPENDED" if applied else "INSUFFICIENT_CONTEXT", "tokens": end - start, "phase": phase,
              "start_generated": start, "end_generated": end, **details}
    _equal(next(forced, None), record, f"forced {phase} at {start}")
    if applied:
        _equal(generated[start:end], ids, f"measured forced IDs at {start}")
    return end


def _check_event(events, item, phase, decision, authored_start, authored_end):
    spans = (item.source_span, *item.field_spans.values())
    _require(all(authored_start <= span.token_start < span.token_end <= authored_end for span in spans),
             "Event contains evidence outside the sampled source segment")
    _equal(next(events, None), {"phase": phase, "candidate": item.as_dict(), "decision": decision},
           f"{phase} event at prefix {item.observed_count}")


def audit_receipt_row(row, packet, contract, tokenizer, tokenizer_sha256, freeze, support):
    """Audit a closed arm. No generation, scoring reference, or mutable verifier is opened."""
    arm, replica, step = row["arm"], row["replicate"], packet["checkpoint_step"]
    initial = packet["generated_ids"]
    final = row["generated_ids"]
    _require(row["status"] == "COMPLETE" and final[:len(initial)] == initial, "Arm is open or changes the frozen prefix")
    _equal(row["prompt_ids"], packet["prompt_ids"], "arm prompt")
    _equal(row["generated_sha256"], id_sha(final), "last attempt digest")
    prompt_length, capacity = len(packet["prompt_ids"]), row["context_capacity"]
    trajectory = f"d36_{step}_{replica}_{arm}"
    engine = SimpleNamespace(tokenizer=tokenizer)
    identity = SimpleNamespace(tokenizer_sha256=tokenizer_sha256)

    def prefix(ids):
        return source_prefix(engine, identity, packet, ids, trajectory)

    close_id, = tokenizer.encode("</think>", add_special_tokens=False)
    forced = iter(row["forced_feedback"])
    events = iter(row["point_audit_events"])
    drafts, restores = row["rejected_drafts"], row["terminal_restores"]
    _require(len(drafts) == len(restores) <= freeze["terminal_repair_attempts"] == 1, "Invalid terminal attempt count")
    if drafts:
        draft, restore = drafts[0], restores[0]
        cut = draft["draft_start"]
        _require(len(initial) < cut <= len(final), "Rejected draft has an invalid rewind cut")
        original = final[:cut] + draft["discarded_sampled_ids"]
        _equal(draft["draft_end"], len(original), "rejected draft length")
        _equal(draft["generated_sha256"], id_sha(original), "rejected draft digest")
        _equal(restore["restored_generated_tokens"], cut, "terminal restore cut")
        _equal(restore["cache_position"], prompt_length + cut, "terminal restore cache position")
        _equal(restore["restored_prefix_sha256"], id_sha(packet["prompt_ids"] + final[:cut]), "terminal restore source")
        _equal(restore["rng_after_restore_sha256"], restore["post_draft_rng_before_restore_sha256"], "terminal restore RNG")
    else:
        original = final

    expected_cue = cues(support.left, support.right)[arm]
    _equal(row["initial_cue"], expected_cue, "initial cue text")
    cursor = len(initial)
    if expected_cue:
        cursor = _append_receipt(tokenizer, forced, original, cursor, expected_cue, "initial_cue", prompt_length, capacity)
        _require(cursor > len(initial), "Frozen cue could not be applied")
    invalid = reject_invalid_control(prefix(initial), contract, support) if arm == "InvalidWitnessControl" else None
    _equal(row["invalid_witness_control"], invalid, "invalid witness source control")
    policy = None
    setup = []
    if arm in INTERACTIVE or arm == "VerifiedWitness":
        mode = "every_step" if arm == "EveryStepAudit" else "event"
        policy = _ReplayPolicy(contract, freeze, mode)
        for span, value in ((support.right_span, support.right), (support.left_span, support.left)):
            item = candidate(prefix(initial), contract, span.char_span, value, role="observed_comparison_operand")
            decision, _ = policy.decision(item, feedback=False)
            _require(decision["receipt"]["status"] == "CERTIFIED_FEASIBLE", "Initial point did not certify")
            setup.append(decision)
    _equal(row["initial_point_receipts"], setup, "two observed point checks")

    selection = None
    skipped = 0
    withheld = False
    forced_applied = cursor - len(initial)
    final_text = ""
    for attempt, ids in enumerate((original, final) if drafts else (final,)):
        closed = [index for index, token in enumerate(ids) if token == close_id]
        eos = bool(drafts and not attempt) or row["EOS"]
        cut = closed[-1] if closed else None
        final_text = tokenizer.decode(ids[cut + 1:], skip_special_tokens=True) if cut is not None else ""
        terminal_decision = obligation = selection = None
        if arm in INTERACTIVE:
            limit = cut if cut is not None else len(ids) - 1
            end = cursor + 1
            while end <= limit:
                if tokenizer.decode(ids[max(0, end - 8):end], skip_special_tokens=False).endswith("\n\n"):
                    text = tokenizer.decode(ids[cursor:end], skip_special_tokens=False)
                    matches = tuple(paragraph_matches(text))
                    if matches:
                        for item in authored_candidates(engine, prefix(ids[:end]), contract, cursor, end, matches):
                            if policy.mode == "event" and item.value <= policy.incumbent and item.goal_claim_type != "MAXIMALITY_CLAIM":
                                skipped += 1
                                continue
                            decision, note = policy.decision(item)
                            _check_event(events, item, "thinking", decision, cursor, end)
                            if note:
                                after = _append_receipt(tokenizer, forced, ids, end, feedback_paragraph(note),
                                                        "event_feedback", prompt_length, capacity)
                                if after > end:
                                    forced_applied += after - end
                                    end = after
                                    break
                    cursor = end
                end += 1
            if eos and cut is not None:
                item, selection = terminal_candidate(engine, prefix(ids), contract, cut + 1, final_text)
                if item:
                    terminal_decision, obligation = policy.decision(item, terminal=True)
                    _check_event(events, item, "final", terminal_decision, cut + 1, len(ids))
        can_repair = bool(terminal_decision and terminal_decision["veto"] and obligation and not attempt and
                          prompt_length + cut + len(tokenizer.encode(feedback_paragraph(obligation), add_special_tokens=False)) < capacity)
        if drafts and not attempt:
            _require(can_repair and draft["stop_reason"] == "EOS", "Rejected draft has no legal paid repair")
            _equal(draft["draft_start"], cut, "rejected draft close token")
            _equal(draft["final_response"], final_text, "rejected final text")
            _equal(draft["paid_samples_so_far"], len(ids) - len(initial) - forced_applied, "samples before repair")
            cursor = _append_receipt(tokenizer, forced, final, cut, feedback_paragraph(obligation),
                                     "terminal_feedback", prompt_length, capacity)
            forced_applied += cursor - cut
        else:
            _require(not can_repair, "Runtime withheld a terminal for which a legal repair was available")
            withheld = bool(terminal_decision and terminal_decision["veto"])

    _equal(next(events, None), None, "unexplained point audit events")
    _equal(next(forced, None), None, "unexplained forced feedback")
    _equal(row["terminal_selection"], selection, "last terminal selection")
    _equal(row["final_response"], final_text, "last final response from token IDs")
    _equal(row["final_delivery"], "WITHHELD_CERTIFIED_VETO" if withheld else "NATIVE_MODEL_DRAFT", "terminal policy")
    _equal(row["delivered_final_response"], None if withheld else final_text, "delivered terminal text")
    _equal(row["certified_optimality"], False, "point-only certificate scope")
    _equal(row["teacher_forced_tokens"], forced_applied, "actually forced tokens")
    _equal(row["nonimproving_thinking_candidates_skipped_before_tool"], skipped, "before-tool filtering")
    if policy:
        policy.check_summary(row["controller"])
    else:
        _equal(row["controller"], None, "inactive controller")
    return {"replicate": replica, "arm": arm, "point_events_verified": len(policy.decisions) if policy else 0,
            "paid_point_calls": policy.calls if policy else 0, "paid_math_operations": policy.ops if policy else 0,
            "feedback_obligations": policy.feedback if policy else 0, "forced_tokens": forced_applied,
            "feedback_applied": sum(record["status"] == "APPENDED" and record["phase"] != "initial_cue"
                                    for record in row["forced_feedback"]),
            "rejected_drafts_reconstructed": len(drafts), "terminal_withheld": withheld}


def audit_receipts(packet, plan, arms, freeze, manifest):
    """Verify complete raw rows independently before opening the scoring reference."""
    tokenizer = make_tokenizer()
    tokenizer_assets = [row for row in manifest["model_files"]["files"] if row["name"].startswith(
        ("tokenizer", "vocab", "merges", "special_tokens", "added_tokens", "chat_template"))]
    _require(bool(tokenizer_assets), "Runtime tokenizer identity is absent")
    for asset in tokenizer_assets:
        _equal(_sha((TOKENIZER / asset["name"]).read_bytes()), asset["sha256"], f"tokenizer asset {asset['name']}")
    tokenizer_sha256 = _sha(json.dumps(tokenizer_assets, sort_keys=True).encode())
    contract = compile_contract(packet["question"])
    _require(contract is not None and contract.template_id == DIGITS, "No frozen E15 executable predicate")
    identity, engine = SimpleNamespace(tokenizer_sha256=tokenizer_sha256), SimpleNamespace(tokenizer=tokenizer)
    support = observed_plan(source_prefix(engine, identity, packet, packet["generated_ids"], "frozen_plan"), contract)
    _equal(plan["observed_comparison"], asdict(support), "frozen source comparison")
    _equal(plan["contract_id"], contract.contract_id, "frozen source contract")
    _require(all(row["context_capacity"] == manifest["context_capacity"] for row in arms.values()),
             "An arm reports a different context capacity from the runtime manifest")
    rows = [audit_receipt_row(row, packet, contract, tokenizer, tokenizer_sha256, freeze, support) for row in arms.values()]
    return {"status": "PASS", "runtime_tokenizer_sha256": tokenizer_sha256, "rows_verified": len(rows),
            "scope": "Replay frozen lexical adapter, independently reconstruct point/status/cost/action and feedback; no model generation or scoring reference.",
            "point_events_verified": sum(row["point_events_verified"] for row in rows),
            "rejected_drafts_reconstructed": sum(row["rejected_drafts_reconstructed"] for row in rows), "rows": rows}
