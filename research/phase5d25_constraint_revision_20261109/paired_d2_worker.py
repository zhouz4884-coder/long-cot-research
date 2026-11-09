"""Run the no-cue audit identity gate on D2 sources and controlled witnesses."""

import argparse
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
for directory in (D1, D2):
    sys.path.append(str(directory))

from independent_audit import AuditRequest, RevisionPermit, digest, handle_event, run_side_audit, work
from native_d2_worker import load_runtime, prompt_for, verify_inputs
from native_engine import NativeEngine
from native_snapshot import NativeState, advance_native, capture_snapshot, replay_schedule, restore_snapshot
from native_worker import write
from restricted_math_checker import make_request, replay_certificate, verify as math_verify


def reference_runtime():
    spec = importlib.util.spec_from_file_location("frozen_d2_pairing", D2 / "paired_d2_worker.py")
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    return reference


def fingerprint(engine, state):
    return engine.kv_fingerprints(state.cache)


def same_live_state(engine, a, b):
    if a.next_logits is None or b.next_logits is None:
        logits = a.next_logits is None and b.next_logits is None
    else:
        logits = bool(engine.torch.equal(a.next_logits, b.next_logits))
    return (a.prefix_ids == b.prefix_ids and a.stop_reason == b.stop_reason
            and a.thinking_open == b.thinking_open and a.cache_position == b.cache_position
            and logits and bool(engine.torch.equal(a.rng.get_state(), b.rng.get_state())))


def run_identity(engine, snapshot, identity, baseline, selected, folder, reference):
    began = time.monotonic()
    first = len(engine.ledger)
    initial_kv = engine.kv_fingerprints(snapshot._cache)
    initial_rng = snapshot._rng_state.clone()
    initial_logits = snapshot._next_logits.clone()
    direct = restore_snapshot(engine, snapshot, identity=identity)
    relation = selected.get("relation") or {"surface": "No standalone relation was registered"}
    request = AuditRequest(snapshot.prefix_sha256, snapshot.checkpoint_id, "D2_IDENTITY_CONTROL",
                           relation["surface"], variables=tuple(relation.get("variables", ())))

    def no_action(*_):
        return {"status": "UNKNOWN", "reason": "frozen_no_action_identity_control"}, None

    result = handle_event(engine, snapshot, identity=identity, study_seed=baseline["seed"],
                          detect=lambda *_: request, verify=no_action)
    engine.stage = "identity_direct_proposal"
    for _ in result.metadata["native_proposal_ids"]:
        if direct.stop_reason != "RUNNING":
            raise RuntimeError("Direct native proposal ended before the adopted proposal")
        advance_native(engine, direct)
    shadow = result.state
    merge_equal = same_live_state(engine, direct, shadow) and fingerprint(engine, direct) == fingerprint(engine, shadow)
    source_unchanged = (engine.kv_fingerprints(snapshot._cache) == initial_kv
                        and bool(engine.torch.equal(snapshot._rng_state, initial_rng))
                        and bool(engine.torch.equal(snapshot._next_logits, initial_logits)))
    compared = 0
    max_difference = 0.0
    rng_equal = True
    prefix = len(snapshot.generated_ids)
    sampled_equal = direct.generated_ids == shadow.generated_ids
    while direct.stop_reason == shadow.stop_reason == "RUNNING":
        max_difference = max(max_difference, float((direct.next_logits - shadow.next_logits).abs().max()))
        rng_equal = rng_equal and bool(engine.torch.equal(direct.rng.get_state(), shadow.rng.get_state()))
        engine.stage = "identity_direct_decode"
        direct_token = advance_native(engine, direct)
        engine.stage = "identity_adopted_decode"
        shadow_token = advance_native(engine, shadow)
        sampled_equal = sampled_equal and direct_token == shadow_token
        compared += 1
        if len(direct.generated_ids) % 256 == 0:
            write(folder / "progress.json", {"stage": "identity_decode", "tokens": len(direct.generated_ids),
                                             "equal": sampled_equal, "maximum_logit_difference": max_difference})
    reference.finish(engine, direct, folder, "NativeContinue")
    reference.finish(engine, shadow, folder, "UnknownIdentity")
    terminal_equal = same_live_state(engine, direct, shadow) and fingerprint(engine, direct) == fingerprint(engine, shadow)
    frozen_equal = direct.generated_ids == baseline["generated_ids"]
    passed = all((merge_equal, source_unchanged, terminal_equal, frozen_equal, sampled_equal, rng_equal,
                  max_difference == 0.0, direct.stop_reason == "EOS", result.metadata["decision"] == "ADOPT_NATIVE"))
    diagnostics = {"status": "PASS" if passed else "FAIL", "case_id": baseline["case_id"], "seed": baseline["seed"],
                   "checkpoint": snapshot.metadata(), "event": result.metadata,
                   "merge_token_kv_logits_rng_equal": merge_equal, "source_kv_logits_rng_unmodified": source_unchanged,
                   "terminal_token_kv_rng_eos_equal": terminal_equal, "matches_d2_full_generated_ids": frozen_equal,
                   "all_sampled_tokens_equal": sampled_equal, "all_compared_rng_equal": rng_equal,
                   "post_proposal_logit_comparisons": compared, "maximum_logit_difference": max_difference,
                   "matched_continuation_tokens": len(direct.generated_ids) - prefix if sampled_equal else None,
                   "diagnostic_work": work(engine.ledger[first:]), "wall_seconds": time.monotonic() - began}
    write(folder / "NativeContinue.json", reference.state_result(engine, direct))
    write(folder / "UnknownIdentity.json", reference.state_result(engine, shadow))
    write(folder / "IDENTITY_GATE.json", diagnostics)
    if not passed:
        raise RuntimeError("Independent audit broke exact UNKNOWN continuation")
    return diagnostics


def point_control(scope, value, prefix_sha256, span):
    target = {"id": "controlled_claim", "version": 0, "kind": "claim", "certificate_type": "POLYNOMIAL_IDENTITY",
              "scope": {"id": "controlled_scope", "version": 0, "coefficient_domain": "Q", "domains": {"x": scope}},
              "statement": {"lhs": {"op": "var", "name": "x"}, "rhs": 1}, "required_premises": [],
              "source_span": span, "observed_prefix_sha256": prefix_sha256}
    request = make_request(target, mode="counterexample", assignment={"x": value})
    checked = math_verify(request, target=target)
    if checked["certificate"] is None or not replay_certificate(checked["certificate"], request, target=target):
        raise ValueError("Controlled witness certificate failed independent replay")
    return {"target": target, "request": request, "checker_result": checked}


def run_controlled_action(engine, identity, folder, reference):
    """Use injected assertions/witnesses to exercise the actual controlled revision path."""
    began = time.monotonic()
    question = "For positive integers x, decide whether x=1 always holds. Give a short justification."
    prompt = prompt_for(engine.tokenizer, question)
    opener = [] if engine.open_ids[0] in prompt else engine.open_ids
    raw_claim = "For every positive integer x, x=1.\n\n"
    observed = opener + engine.tokenizer.encode(raw_claim, add_special_tokens=False)
    engine.stage = "controlled_checkpoint"
    cache, logits = replay_schedule(engine, prompt, observed)
    rng = engine.rng(seed=20261109)
    snapshot = capture_snapshot(engine, identity=identity, prompt_ids=prompt, generated_ids=observed,
                                cache=cache, next_logits=logits, rng=rng, thinking_open=True,
                                checkpoint_id="D25_controlled_symbolic_action")
    del cache, logits
    scoped_domain = {"kind": "integer", "lower": 0, "lower_closed": False}
    source_span = [len(opener), len(observed)]
    outside = point_control(scoped_domain, -1, snapshot.prefix_sha256, source_span)
    unscoped = point_control({"kind": "real"}, -1, snapshot.prefix_sha256, source_span)
    valid = point_control(scoped_domain, 2, snapshot.prefix_sha256, source_span)
    request_scoped = AuditRequest(snapshot.prefix_sha256, "controlled_claim", "COUNTEREXAMPLE", "x=1",
                                 ("x is a positive integer",), ("x",))
    request_unscoped = AuditRequest(snapshot.prefix_sha256, "controlled_claim", "COUNTEREXAMPLE", "x=1", (), ("x",))
    unscoped_audit = run_side_audit(engine, snapshot, request_unscoped, study_seed=20261109, max_tokens=48)

    def outside_check(*_):
        return {"status": outside["checker_result"]["status"], "reason": "out_of_scope_controlled_witness"}, None

    ignored = handle_event(engine, snapshot, identity=identity, study_seed=20261109,
                           detect=lambda *_: request_scoped, verify=outside_check, max_audit_tokens=48)

    def valid_check(snap, proposal, *_):
        evidence = digest(valid)
        return {"status": valid["checker_result"]["status"], "verified_evidence_sha256": evidence}, RevisionPermit(
            snap.prefix_sha256, digest(proposal.token_ids), "controlled_claim", "REBASE", evidence)

    def replace_claim(snap, _proposal, _permit):
        engine.stage = "controlled_replay"
        cache, logits = replay_schedule(engine, snap.prompt_ids, opener)
        state = NativeState(snap.prompt_ids, list(opener), cache, logits, engine.rng(state=snap._rng_state.clone()),
                            len(snap.prompt_ids) + len(opener), True, "RUNNING", identity)
        bridge = "A verified counterexample is x=2, which is a positive integer and is not 1.\n\n"
        appended = reference.append_checked_text(engine, state, bridge, "controlled_verified_bridge")
        if appended["status"] != "APPENDED":
            raise RuntimeError("Controlled verified bridge did not reach the revised state")
        return state

    changed = handle_event(engine, snapshot, identity=identity, study_seed=20261109,
                           detect=lambda *_: None, verify=valid_check, revise=replace_claim)
    same_audit_rng = ignored.metadata["audit"]["sample_seed"] == unscoped_audit["sample_seed"]
    different_audit_inputs = ignored.metadata["audit"]["prompt_ids"] != unscoped_audit["prompt_ids"]
    distinct_state = ignored.state.prefix_ids != changed.state.prefix_ids
    reference.finish(engine, ignored.state, folder, "ScopeRejectedWitness")
    reference.finish(engine, changed.state, folder, "AcceptedRefutation")
    passed = (outside["checker_result"]["status"] == "INVALID_COUNTEREXAMPLE"
              and unscoped["checker_result"]["status"] == valid["checker_result"]["status"] == "REFUTED_CLAIM"
              and same_audit_rng and different_audit_inputs and distinct_state
              and ignored.metadata["decision"] == "ADOPT_NATIVE" and changed.metadata["decision"] == "REBASE"
              and ignored.state.stop_reason == changed.state.stop_reason == "EOS")
    report = {"status": "PASS" if passed else "FAIL", "scope": "GPU controlled injection, not natural accuracy evidence",
              "assertion": raw_claim, "checkpoint": snapshot.metadata(), "scope_rejection": outside,
              "unscoped_acceptance": unscoped, "valid_scoped_refutation": valid,
              "same_audit_seed": same_audit_rng, "different_audit_inputs": different_audit_inputs,
              "different_action_state": distinct_state, "scope_rejected_event": ignored.metadata,
              "scope_valid_event": changed.metadata, "unscoped_audit": unscoped_audit,
              "paid_work": work(engine.ledger), "wall_seconds": time.monotonic() - began}
    write(folder / "ScopeRejectedWitness.json", reference.state_result(engine, ignored.state))
    write(folder / "AcceptedRefutation.json", reference.state_result(engine, changed.state))
    write(folder / "CONTROLLED_GATE.json", report)
    if not passed:
        raise RuntimeError("Independent scoped action control failed")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--worker", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    verify_inputs(root, "identity_freeze.json")
    reference = reference_runtime()
    model, tokenizer, device, meta = load_runtime(D1, args.model, args.gpu)
    output = root / "identity_results" / f"worker_{args.worker}"
    output.mkdir(parents=True, exist_ok=True)
    write(output / "manifest.json", meta)
    selected = json.loads((root / "D2_SOURCE_SELECTION.json").read_bytes())["selected"]
    completed = []
    for row in selected:
        if f"/worker_{args.worker}/" not in row["source_result"]:
            continue
        source = root / "d2_sources" / row["source_result"]
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["source_result_sha256"]:
            raise ValueError("D2 source hash mismatch")
        baseline = json.loads(raw)
        folder = output / f"{row['case_id']}_{row['seed']}"
        folder.mkdir(exist_ok=True)
        engine = NativeEngine(model, tokenizer, device)
        identity = reference.execution_identity(D1, engine, meta)
        engine.torch.cuda.reset_peak_memory_stats(device)
        with engine.torch.inference_mode():
            snapshot = reference.checkpoint(engine, identity, baseline, row)
            write(folder / "checkpoint.json", {**snapshot.metadata(), "copy_cost": asdict(snapshot.copy_cost),
                                               "setup_work": work(engine.ledger)})
            result = run_identity(engine, snapshot, identity, baseline, row, folder, reference)
        write(folder / "paid_work.json", {"ledger": engine.ledger, "totals": work(engine.ledger),
                                           "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(device)})
        completed.append({"case_id": row["case_id"], "seed": row["seed"], "status": result["status"]})
        write(output / "progress.json", {"status": "RUNNING", "completed": completed})
        del snapshot, engine
    control = None
    if args.worker == 0:
        engine = NativeEngine(model, tokenizer, device)
        identity = reference.execution_identity(D1, engine, meta)
        folder = output / "controlled_action"
        folder.mkdir(exist_ok=True)
        engine.torch.cuda.reset_peak_memory_stats(device)
        with engine.torch.inference_mode():
            control = run_controlled_action(engine, identity, folder, reference)["status"]
        write(folder / "paid_work.json", {"ledger": engine.ledger, "totals": work(engine.ledger),
                                           "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(device)})
    write(output / "summary.json", {"status": "COMPLETE", "completed": completed, "controlled_gate": control})


if __name__ == "__main__":
    main()
