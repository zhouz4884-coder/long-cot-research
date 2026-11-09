"""Same-checkpoint D3 audit comparisons with independent native and audit streams."""

import argparse
from dataclasses import asdict
from pathlib import Path
import time

from paired_d2_worker import D1, reference_runtime
from independent_audit import handle_event, work
from native_d2_worker import load_runtime, verify_inputs
from native_engine import NativeEngine
from native_snapshot import restore_snapshot
from native_worker import write
from proposal_check import check_proposal
from reflection_fork import generate_reflection, resolve_reflection
from select_d3_events import (CODE_FILES, DATA_SHA256, FORMAL_COUNT, FORMAL_SEEDS, PROTOCOL_SHA256, ROOT, audit_requests,
                              bank_questions, read, rebuild_selected, record_path, sha)


def in_context_cue(event):
    if event.kind == "SYMBOLIC_IDENTITY":
        left, right = event.normalized
        target = f"{left} = {right}"
    else:
        left, right, direction, result_left, result_right = event.normalized
        connector = "is equivalent to" if direction == "IFF" else "implies"
        target = f"{left} = {right} {connector} {result_left} = {result_right}"
    return f"\n\nCheck the observed relation {target} carefully, then continue solving the original problem.\n\n"


def route_audit(event, scope, predecessor, audit, *, unscoped):
    checked = check_proposal(event, audit["text"], mode="counterexample", scope=scope,
                             predecessor_scope=predecessor, unscoped=unscoped)
    disposition = {"INVALID_COUNTEREXAMPLE": "REJECTED_AUDIT_WITNESS",
                   "CHECKED_COUNTEREXAMPLE": "VALID_AUDIT_WITNESS_DIAGNOSTIC"}.get(checked["status"], "UNKNOWN_AUDIT_WITNESS")
    return {**checked, "audit_witness_disposition": disposition, "native_revision_authorized": False}, None


def _tensor_hash(engine, tensor):
    if tensor is None:
        return None
    return sha(tensor.detach().contiguous().view(engine.torch.uint8).cpu().numpy().tobytes())


def _state_signature(engine, state):
    from native_engine import digest_ids

    return {"prefix_sha256": digest_ids(list(state.prefix_ids)), "stop_reason": state.stop_reason,
            "thinking_open": state.thinking_open, "cache_position": state.cache_position,
            "kv": engine.kv_fingerprints(state.cache), "next_logits_sha256": _tensor_hash(engine, state.next_logits),
            "rng_sha256": _tensor_hash(engine, state.rng.get_state())}


def _snapshot_signature(engine, snapshot):
    return {"kv": engine.kv_fingerprints(snapshot._cache), "next_logits_sha256": _tensor_hash(engine, snapshot._next_logits),
            "rng_sha256": _tensor_hash(engine, snapshot._rng_state)}


def _native_proposal(engine, snapshot, identity):
    proposal = generate_reflection(engine, snapshot, identity=identity)
    metadata = {"decision": "ADOPT_NATIVE", "native_proposal_ids": list(proposal.token_ids),
                "native_proposal_boundary": proposal.stop_reason, "native_proposal_cost": asdict(proposal.cost),
                "discarded_native_tokens": 0, "audit": None, "permit": None}
    return resolve_reflection(engine, snapshot, proposal, identity=identity, disposition="UNKNOWN").state, metadata


def run_arm(engine, baseline, folder, reference, arm, start_state):
    engine.torch.cuda.reset_peak_memory_stats(engine.device)
    began, first = time.monotonic(), len(engine.ledger)
    state, metadata = start_state()
    merge = _state_signature(engine, state)
    continuation = reference.finish(engine, state, folder, arm)
    terminal = _state_signature(engine, state)
    result = {**reference.state_result(engine, state), "arm": arm, "case_id": baseline["case_id"],
              "seed": baseline["seed"], "event": metadata, "merge_state": merge, "terminal_state": terminal,
              "continuation": continuation, "standalone_prefix_reused": True,
              "wall_seconds": time.monotonic() - began, "paid_work_after_checkpoint": work(engine.ledger[first:]),
              "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(engine.device)}
    write(folder / (arm + ".json"), result)
    return result


def run_pair(engine, identity, baseline, selected, event, scope, predecessor, binding, folder, reference):
    began = time.monotonic()
    engine.torch.cuda.reset_peak_memory_stats(engine.device)
    snapshot = reference.regenerate_checkpoint(engine, identity, baseline, selected)
    checkpoint_seconds = time.monotonic() - began
    checkpoint_peak = engine.torch.cuda.max_memory_allocated(engine.device)
    checkpoint_work = work(engine.ledger)
    if snapshot.prefix_sha256 != selected["observed_prefix_sha256"]:
        raise ValueError("Regenerated snapshot differs from the frozen D3 selection")
    original = _snapshot_signature(engine, snapshot)
    write(folder / "checkpoint.json", {**snapshot.metadata(), "copy_cost": asdict(snapshot.copy_cost),
                                       "signature": original, "setup_work": checkpoint_work,
                                       "setup_seconds": checkpoint_seconds, "peak_allocated_bytes": checkpoint_peak})
    native = run_arm(engine, baseline, folder, reference, "NativeContinue",
                     lambda: _native_proposal(engine, snapshot, identity))
    native_matches = (native["generated_ids"] == baseline["generated_ids"]
                      and native["stop_reason"] == baseline["stop_reason"])
    if not native_matches:
        write(folder / "PAIR_AUDIT.json", {"status": "FAIL", "reason": "native_continuation_diverged_from_formal_bank",
                                          "selected": selected, "matches_recorded_native_ids": False})
        raise RuntimeError("D3 NativeContinue diverged from the recorded trajectory")

    def in_context():
        state = restore_snapshot(engine, snapshot, identity=identity)
        cue = reference.append_checked_text(engine, state, in_context_cue(event), "InContextCheck_cue")
        return state, {"cue": cue, "restore_cost": asdict(state.restore_cost),
                       "quality_exposure": cue["status"] == "APPENDED"}

    contextual = run_arm(engine, baseline, folder, reference, "InContextCheck", in_context)
    independent = {}
    for arm, request in audit_requests(event, binding).items():
        unscoped = arm == "UnscopedIndependent"

        def isolated():
            run = handle_event(engine, snapshot, identity=identity, study_seed=baseline["seed"],
                               detect=lambda *_: request,
                               verify=lambda _s, _p, _r, audit: route_audit(event, scope, predecessor, audit,
                                                                            unscoped=unscoped),
                               max_audit_tokens=80)
            if run.metadata["decision"] != "ADOPT_NATIVE" or run.metadata["permit"] is not None:
                raise RuntimeError("An audit witness cannot modify the native branch")
            return run.state, run.metadata

        independent[arm] = run_arm(engine, baseline, folder, reference, arm, isolated)

    first, second = (independent[arm]["event"]["audit"] for arm in ("UnscopedIndependent", "ScopedIndependent"))
    same_seed = first["sample_seed"] == second["sample_seed"]
    different_prompts = first["prompt_ids"] != second["prompt_ids"]
    exact_native = {
        arm: {"proposal_ids": result["event"]["native_proposal_ids"] == native["event"]["native_proposal_ids"],
              "merge_state": result["merge_state"] == native["merge_state"],
              "terminal_state": result["terminal_state"] == native["terminal_state"],
              "full_generated_ids": result["generated_ids"] == native["generated_ids"]}
        for arm, result in independent.items()
    }
    unchanged = original == _snapshot_signature(engine, snapshot)
    passed = same_seed and different_prompts and unchanged and all(all(checks.values()) for checks in exact_native.values())
    outputs = {"NativeContinue": native, "InContextCheck": contextual, **independent}
    result = {"status": "PASS" if passed else "FAIL", "case_id": baseline["case_id"], "seed": baseline["seed"],
              "selected": selected, "matches_recorded_native_ids": native_matches, "same_independent_audit_seed": same_seed,
              "different_audit_prompt_ids": different_prompts, "source_snapshot_unchanged": unchanged,
              "independent_native_identity": exact_native, "InContextCheck_cue_exposed": contextual["event"]["quality_exposure"],
              "audit_witness_statuses": {arm: row["event"]["verification"]["audit_witness_disposition"] for arm, row in independent.items()},
              "repair_status": "NO_INDEPENDENT_ROLE_AND_SUPPORTED_PLAN", "repair_executed": False,
              "checkpoint_work_shared": checkpoint_work, "total_paid_work": work(engine.ledger),
              "total_wall_seconds": time.monotonic() - began,
              "peak_allocated_bytes": max(checkpoint_peak, *(row["peak_allocated_bytes"] for row in outputs.values())),
              "arms": {arm: {"EOS": row["EOS"], "stop_reason": row["stop_reason"], "new_tokens": row["new_tokens"],
                             "paid_work_after_checkpoint": row["paid_work_after_checkpoint"],
                             "wall_seconds": row["wall_seconds"]} for arm, row in outputs.items()}}
    write(folder / "PAIR_AUDIT.json", result)
    if not passed:
        raise RuntimeError("D3 independent audit identity or context comparison failed")
    return result


def _selection(root):
    verify_inputs(root, "quality_freeze.json")
    frozen_paths = {(root / row["path"]).resolve() for row in read(root / "quality_freeze.json")["files"]}
    if (root / "D3_PAIR_SELECTION.json").resolve() not in frozen_paths or Path(__file__).resolve() not in frozen_paths:
        raise ValueError("Quality freeze must bind the selection and worker source")
    selected = read(root / "D3_PAIR_SELECTION.json")
    if (selected["status"] != "FROZEN" or selected["protocol_sha256"] != PROTOCOL_SHA256
            or selected["protocol_sha256"] != sha((ROOT / "D3_PAIRING_PROTOCOL.json").read_bytes())
            or selected["data_freeze_sha256"] != DATA_SHA256 or DATA_SHA256 != sha((ROOT / "D3_DATA_FREEZE.json").read_bytes())
            or selected["selection_code_sha256"] != {name: sha((ROOT / name).read_bytes()) for name in CODE_FILES}
            or selected["formal_problems"] != FORMAL_COUNT or selected["formal_trajectories"] != FORMAL_COUNT * len(FORMAL_SEEDS)
            or selected["quality_gate"] != ("READY" if selected["selected"] else "NO_ELIGIBLE_TARGET")):
        raise ValueError("Invalid D3 quality selection or protocol freeze")
    rows = selected["selected"]
    if (len(rows) > 4 or len(rows) != len({row["case_id"] for row in rows})
            or any(row["role_certified"] or row["repair_eligible"] or row["seed"] not in FORMAL_SEEDS
                   or row["worker"] not in (0, 1) or row["selection_priority"] != 1 for row in rows)):
        raise ValueError("D3 audit-only worker requires distinct cases and no repair permission")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--worker", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    selection = _selection(root)
    rows = [row for row in selection["selected"] if row["worker"] == args.worker]
    output = root / "quality_results" / f"worker_{args.worker}"
    output.mkdir(parents=True, exist_ok=True)
    if not rows:
        write(output / "summary.json", {"status": "COMPLETE", "completed": [], "reason": "no_assigned_eligible_case"})
        return
    native_manifest = ROOT / f"bank/native_results/worker_{args.worker}/manifest.json"
    if sha(native_manifest.read_bytes()) != selection["native_worker_manifest_sha256"][str(args.worker)]:
        raise ValueError("Native worker manifest differs from the D3 selection")
    reference = reference_runtime()
    began = time.monotonic()
    model, tokenizer, device, meta = load_runtime(ROOT / "bank", args.model, args.gpu)
    native_identity = read(native_manifest)
    comparable = ("gpu", "torch", "transformers", "dtype", "backend", "context_capacity", "sampling", "scientific_new_token_cap")
    if any(meta[key] != native_identity[key] for key in comparable) or meta["model_files"]["manifest_sha256"] != native_identity["model_files"]["manifest_sha256"]:
        raise ValueError("Quality runtime differs from the original native worker")
    write(output / "manifest.json", {**meta, "worker": args.worker, "load_seconds": time.monotonic() - began})
    visible = ROOT / "bank/d2_visible.jsonl"
    cases = {row["case_id"]: row for row in bank_questions(ROOT, visible if visible.exists() else None)}
    completed = []
    for selected in rows:
        path = record_path(selected["case_id"], selected["seed"], args.worker)
        if path != selected["source_result"]:
            raise ValueError("Selected native worker or path changed")
        raw = (ROOT / path).read_bytes()
        if sha(raw) != selected["source_result_sha256"]:
            raise ValueError("Selected native source differs from frozen bytes")
        source = read(ROOT / path)
        event, scope, predecessor, binding = rebuild_selected(source, cases[selected["case_id"]], selected, tokenizer)
        folder = output / f"{selected['case_id']}_{selected['seed']}"
        folder.mkdir(exist_ok=False)
        engine = NativeEngine(model, tokenizer, device)
        identity = reference.execution_identity(D1, engine, meta)
        case_began = time.monotonic()
        result = None
        try:
            with engine.torch.inference_mode():
                result = run_pair(engine, identity, source, selected, event, scope, predecessor, binding, folder, reference)
        finally:
            write(folder / "paid_work.json", {"ledger": engine.ledger, "totals": work(engine.ledger),
                                               "case_wall_seconds": time.monotonic() - case_began,
                                               "peak_allocated_bytes": (result or {}).get("peak_allocated_bytes"),
                                               "last_stage_peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(device)})
        completed.append({"case_id": selected["case_id"], "seed": selected["seed"], "status": result["status"]})
        write(output / "progress.json", {"status": "RUNNING", "completed": completed})
        del engine
    write(output / "summary.json", {"status": "COMPLETE", "completed": completed})


if __name__ == "__main__":
    main()
