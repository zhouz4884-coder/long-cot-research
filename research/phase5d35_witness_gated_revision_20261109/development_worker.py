"""Paid native development trials at frozen observed E12 and E15 boundaries."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
LEGACY = ROOT / "legacy"
D1 = LEGACY if LEGACY.is_dir() else ROOT.parent / "phase5d_scope_rebase_20261106"
D2 = LEGACY if LEGACY.is_dir() else ROOT.parent / "phase5d2_quarantined_rebase_20261107"
D3 = LEGACY if LEGACY.is_dir() else ROOT.parent / "phase5d25_constraint_revision_20261109"
for directory in (D1, D2, D3):
    sys.path.append(str(directory))

from bounded_witness_search import replay_search, search_witness
from candidate_archive import ObservedPrefix
from complete_answer_v2 import extract_final_answer
from dual_frontier_rebase import _closed_paragraph, _opener_offset
from independent_audit import work
from native_d2_worker import load_runtime, prompt_for, verify_inputs
from native_engine import NativeEngine
from native_snapshot import capture_snapshot, restore_snapshot
from native_worker import write
from prepare_checkpoints import id_sha
from witness_contract import compile_contract
from witness_verifier import OBSERVED, Witness, WitnessGate


SEARCH_BUDGET = 20_000


def reference_runtime():
    path = D2 / "paired_d2_worker.py"
    spec = importlib.util.spec_from_file_location("d35_frozen_native_reference", path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    return reference


def observed(packet, identity, tokenizer, generated):
    question_hash = hashlib.sha256(packet["question"].encode()).hexdigest()
    return ObservedPrefix.from_tokens(generated, lambda ids: tokenizer.decode(list(ids), skip_special_tokens=False),
                                     prompt_ids=packet["prompt_ids"], tokenizer_sha256=identity.tokenizer_sha256,
                                     trajectory_id=f"{packet['case_id']}_{packet['seed']}", question_sha256=question_hash)


def typed_gate(packet, engine, identity, generated):
    contract = compile_contract(packet["question"])
    if contract is None:
        raise ValueError("No faithful fixed contract for the staged original question")
    return WitnessGate(contract, observed(packet, identity, engine.tokenizer, generated))


def prior_exact(gate):
    for item in reversed(gate.records):
        if item.goal_claim_type not in ("EXACT_ANSWER", "FEASIBLE_CANDIDATE") or item.segment != "thinking":
            continue
        verdict = gate.verify(item.candidate_id)
        if verdict["status"] == "CERTIFIED_EXACT":
            return item, verdict
    raise ValueError("No actually observed candidate received a complete exact certificate")


def e15_plan(gate, packet, tokenizer):
    from goal_claim_detector import comparison_supports

    claims = [item for item in gate.records if item.goal_claim_type == "MAXIMALITY_CLAIM"]
    eligible = [item for item in gate.records if item.goal_claim_type in ("FEASIBLE_CANDIDATE", "EXACT_ANSWER")
                and type(item.value) is int]
    if not claims:
        raise ValueError("No observed global maximality claim at the native checkpoint")
    incumbent = claims[-1]
    witness = verdict = None
    for candidate in sorted(eligible, key=lambda x: (-x.value, x.source_span.token_start)):
        if candidate.value <= incumbent.value:
            break
        checked = gate.verify(incumbent.candidate_id, Witness(OBSERVED, candidate.candidate_id))
        if checked["action"] == "RETRACT_EXTREMUM_ONLY":
            witness, verdict = candidate, checked
            break
    if witness is None:
        raise ValueError("No admissible prior dominance witness")
    prompt, ids = packet["prompt_ids"], packet["generated_ids"]
    opener = _opener_offset(tokenizer, prompt, ids)
    boundaries = [opener, *[offset for offset in packet["boundary_offsets"]
                   if offset > opener and _closed_paragraph(tokenizer.decode(ids[:offset], skip_special_tokens=False))]]
    if boundaries[-1] != len(ids):
        raise ValueError("Staged snapshot does not end at a safe native paragraph")
    invalidated = [item.source_span.token_start for item in claims if item.value == incumbent.value]
    refuted_comparisons = []
    for comparison in comparison_supports(gate.prefix, gate.contract):
        # A syntactically bound numerical justification is retired only if its
        # actual asserted ordering is false for this same checked witness pair.
        if (comparison.left == witness.value and comparison.right == incumbent.value
                and comparison.relation == "<" and not comparison.left < comparison.right):
            invalidated.append(comparison.source_span.token_start)
            refuted_comparisons.append(asdict(comparison))
    generic_cut = max(offset for offset in boundaries if offset <= incumbent.source_span.token_start)
    scope_cut = max(offset for offset in boundaries if offset <= min(invalidated))
    if scope_cut > generic_cut:
        raise ValueError("The checked invalidation frontier lies past the generic rewind")
    common = (f"\n\nA candidate already observed in the reasoning, {witness.value}, satisfies the original digit rule "
              f"and is greater than {incumbent.value}. This refutes the claim that {incumbent.value} is greatest. "
              f"Treat {witness.value} only as a feasible lower bound. Continue solving the original problem, "
              "justify the greatest value and provide the final boxed answer.\n\n")
    return {"incumbent": incumbent.value, "witness": witness.value, "verdict": verdict,
            "incumbent_id": incumbent.candidate_id, "witness_id": witness.candidate_id,
            "generic_cut": generic_cut, "scope_cut": scope_cut, "observed_tokens": len(ids),
            "scope_cut_discards_witness_source": scope_cut < witness.source_span.token_end,
            "semantic_frontier": [item.candidate_id for item in claims if item.value == incumbent.value],
            "text_frontier_offsets": sorted(set(invalidated)), "refuted_comparisons": refuted_comparisons,
            "shared_witness_message": common, "carry_scope": "feasible lower bound only"}


def audit_tool_baseline(gate, folder, arm):
    began = time.perf_counter()
    receipt = search_witness(gate.contract, budget=SEARCH_BUDGET, purpose="SOLVE")
    replay_ok = replay_search(gate.contract, receipt)
    value = receipt.get("certified_value") if replay_ok and receipt.get("status") == "CERTIFIED_EXACT" else None
    write(folder / f"{arm}.json", {"status": "COMPLETE", "arm": arm, "delivery_mode": "direct_tool",
          "delivered_value": value, "final_response": None if value is None else f"\\boxed{{{value}}}",
          "native_generation_used": False, "natural_EOS": None, "search": receipt,
          "independent_search_replay_passed": replay_ok, "wall_seconds_including_replay": time.perf_counter() - began,
          "tool_budget": SEARCH_BUDGET, "paid_work": work([])})


def run_arm(engine, identity, ref, packet, rng_state, cache, logits, arm, cut, message, folder, replay):
    begin = time.monotonic()
    before = len(engine.ledger)
    ids = packet["generated_ids"][:cut]
    rng = engine.rng(state=rng_state.clone())
    snap = capture_snapshot(engine, identity=identity, prompt_ids=packet["prompt_ids"], generated_ids=ids,
                            cache=cache, next_logits=logits, rng=rng, thinking_open=True,
                            checkpoint_id=f"d35_{packet['case_id']}_{arm}")
    clone_cost = asdict(snap.copy_cost)
    branch = restore_snapshot(engine, snap, identity=identity)
    restore_cost = asdict(branch.restore_cost)
    del snap
    forced = 0
    if message:
        appended = ref.append_checked_text(engine, branch, message, arm + "_bridge")
        if appended["status"] != "APPENDED":
            raise ValueError("Checked witness bridge did not enter the actual branch")
        forced = appended["tokens"]
    stopped = ref.finish(engine, branch, folder, arm)
    row = {**ref.state_result(engine, branch), "arm": arm, "seed": packet["seed"],
           "case_id": packet["case_id"], "delivery_mode": "natural_native", "retained_observed_tokens": cut,
           "discarded_frozen_history_tokens": len(packet["generated_ids"]) - cut,
           "teacher_forced_bridge_tokens": forced, "sampled_continuation_tokens": stopped["continuation_tokens"],
           "snapshot_copy_cost": clone_cost, "restore_copy_cost": restore_cost, "elapsed_seconds": time.monotonic() - begin,
           "sequential_shared_replay_through_cut": replay, "paid_work_after_cut": work(engine.ledger[before:]),
           "ledger_after_cut": engine.ledger[before:]}
    write(folder / f"{arm}.json", row)
    del branch
    return row


def e12_delivery(gate, original, engine, identity, packet, folder, old_candidate, exact):
    started = time.perf_counter()
    ids = original["generated_ids"]
    close_positions = [i for i, token in enumerate(ids) if token == engine.close_ids[0]]
    thought_text = engine.tokenizer.decode(ids[:close_positions[-1]], skip_special_tokens=True) if close_positions else ""
    selected = extract_final_answer(thought_text, "scalar")
    write(folder / "LastThoughtAnswer.json", {"status": "COMPLETE", "arm": "LastThoughtAnswer",
          "delivery_mode": "last_thought_readout", "selection": selected,
          "final_response": f"\\boxed{{{selected['components'][0]}}}" if selected["status"] == "ok" else None,
          "native_thought_source_arm": "NativeContinue", "source_cost_through_think_close_recorded_in_native": True,
          "source_cost_through_think_close": work(original["ledger_after_cut"][:max(0, close_positions[-1] + 1 - len(packet["generated_ids"]))]) if close_positions else None,
          "wall_seconds": time.perf_counter() - started, "paid_work_after_source": work([])})
    audit_tool_baseline(gate, folder, "DirectVerifier")
    began = time.perf_counter()
    extended = typed_gate(packet, engine, identity, ids)
    revision = next((item for item in reversed(extended.records) if item.goal_claim_type == "FINAL_ANSWER_REVISION"), None)
    candidate = next((item for item in extended.records if item.segment == "thinking"
                      and item.value == old_candidate.value and item.assignments == old_candidate.assignments
                      and item.source_span.token_end <= len(packet["generated_ids"])), None)
    result = extended.verify(revision.candidate_id, Witness(OBSERVED, candidate.candidate_id)) if revision and candidate else None
    veto = bool(original["EOS"] and result and result["action"] == "VETO_DRAFT_AND_DELIVER_CERTIFIED"
                and result["released_value"] == exact["released_value"])
    write(folder / "WitnessGatedCommit.json", {"status": "COMPLETE", "arm": "WitnessGatedCommit",
          "delivery_mode": "verified_tool_commit_after_native_EOS" if veto else "unchanged_native_draft",
          "final_response": f"\\boxed{{{result['released_value']}}}" if veto else original["final_response"],
          "native_draft_arm": "NativeContinue", "native_draft_EOS": original["EOS"],
          "rejected_draft_tokens": len(ids) - close_positions[-1] - 1 if veto and close_positions else 0,
          "verification": result, "paid_native_draft_work": original["paid_work_after_cut"],
          "wall_seconds_after_draft": time.perf_counter() - began, "paid_work_after_draft": work([])})


def run_case(engine, identity, ref, packet, label, folder):
    prompt, ids = packet["prompt_ids"], packet["generated_ids"]
    if prompt_for(engine.tokenizer, packet["question"]) != prompt or id_sha(prompt + ids) != packet["observed_prefix_sha256"]:
        raise ValueError("The staged question or native token prefix is stale")
    began = time.monotonic()
    gate = typed_gate(packet, engine, identity, ids)
    count = len(ids)
    if label == "e12":
        old_candidate, exact = prior_exact(gate)
        value = exact["released_value"]
        cue = (f"\n\nAn exact verifier checked the previously observed candidate under every original sequence condition. "
               f"The requested term is uniquely {value}. When writing the final answer, preserve that result and "
               "do not rederive it with different parameters. Use a boxed answer.\n\n")
        plan = {"prior_certificate": exact, "shared_verified_message": cue}
        arms = [(count, "NativeContinue", ""), (count, "SameEvidencePrompt", cue)]
    else:
        plan = e15_plan(gate, packet, engine.tokenizer)
        cue = plan["shared_witness_message"]
        arms = [(plan["scope_cut"], "SCOPE-RebaseCarry", cue), (plan["generic_cut"], "GenericRewind", cue),
                (count, "NativeContinue", ""), (count, "WitnessOnlyPrompt", cue)]
        audit_tool_baseline(gate, folder, "BoundedSearch")
    write(folder / "SOURCE_BOUND_PLAN.json", {"status": "READY", "plan": plan, "observed_records": len(gate.records),
                                               "extract_seconds": gate.extract_seconds, "planning_seconds": time.monotonic() - began})
    rng_state = engine.torch.tensor(list(base64.b64decode(packet["rng_state_base64"], validate=True)), dtype=engine.torch.uint8)
    engine.stage = "shared_teacher_forced_prefix"
    replay_seconds = 0.0
    replay_ledger = []
    current, cache, logits = 0, None, None
    original = None
    summary = []
    for cut, arm, message in arms:
        engine.stage = "shared_teacher_forced_prefix"
        engine.sync()
        start = time.monotonic()
        offset = len(engine.ledger)
        if cache is None:
            cache, logits = engine.prefill(prompt)
        for i in range(current, cut):
            cache, logits = engine.forward([ids[i]], cache)
            if (i + 1) % 512 == 0:
                write(folder / "replay_progress.json", {"retained": i + 1, "next_arm": arm, "target": cut})
        engine.sync()
        replay_seconds += time.monotonic() - start
        replay_ledger.extend(engine.ledger[offset:])
        current = cut
        row = run_arm(engine, identity, ref, packet, rng_state, cache, logits, arm, cut, message, folder,
                      {"work": work(replay_ledger), "wall_seconds": replay_seconds})
        if arm == "NativeContinue":
            original = row
        summary.append({name: row[name] for name in ("arm", "stop_reason", "sampled_continuation_tokens", "elapsed_seconds")})
    del cache, logits
    if label == "e12":
        e12_delivery(gate, original, engine, identity, packet, folder, old_candidate, exact)
    return {"status": "COMPLETE", "case_id": packet["case_id"], "mode": label, "arms": summary,
            "standalone_replay_equivalents_are_not_rebilled": True, "actual_shared_replay_work": work(replay_ledger),
            "actual_shared_replay_seconds": replay_seconds, "actual_paid_work": work(engine.ledger),
            "elapsed_seconds": time.monotonic() - began}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case", choices=("e12", "e15"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    args = parser.parse_args()
    verify_inputs(args.root, f"{args.case}_runtime_freeze.json")
    packet = json.loads((args.root / "prepared" / f"{args.case}_checkpoint.json").read_bytes())
    model, tokenizer, device, metadata = load_runtime(D1, args.model, args.gpu)
    engine = NativeEngine(model, tokenizer, device)
    reference = reference_runtime()
    identity = reference.execution_identity(D1, engine, metadata)
    folder = args.root / "gpu_results" / args.case
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / "manifest.json", metadata)
    engine.torch.cuda.reset_peak_memory_stats(device)
    with engine.torch.inference_mode():
        result = run_case(engine, identity, reference, packet, args.case, folder)
    result["peak_allocated_bytes"] = engine.torch.cuda.max_memory_allocated(device)
    write(folder / "actual_forward_ledger.json", engine.ledger)
    write(folder / "summary.json", result)


if __name__ == "__main__":
    main()
