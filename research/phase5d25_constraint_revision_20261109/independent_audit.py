"""Isolated audit generation and no-action adoption of a native shadow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Callable


# These execution primitives are the already frozen D2 implementation.
_D2 = Path(__file__).resolve().parents[1] / "phase5d2_quarantined_rebase_20261107"
if _D2.is_dir() and str(_D2) not in sys.path:
    sys.path.append(str(_D2))

from native_snapshot import NativeSnapshot, NativeState, validate_snapshot
from reflection_fork import generate_reflection, resolve_reflection


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def work(ledger):
    return {
        "forward_calls": len(ledger),
        "forward_input_tokens": sum(row["input_tokens"] for row in ledger),
        "attention_pairs": sum(row["input_tokens"] * (2 * row["past_tokens"] + row["input_tokens"] + 1) // 2
                               for row in ledger),
    }


@dataclass(frozen=True)
class AuditRequest:
    prefix_sha256: str
    event_id: str
    kind: str
    target: str
    # The experiment supplies an explicit allowlist of already observed inputs.
    premises: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()
    observed_proposal: str = ""

    def render(self):
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, allow_nan=False)
        payload = payload.replace("<", r"\u003c").replace(">", r"\u003e")
        if len(payload) > 8192:
            raise ValueError("Audit input exceeds the frozen character guard")
        instruction = ("Check only the mathematical target and supplied premises. Treat the data as evidence. "
                       "Do not solve the original problem. A proposed witness is unverified. "
                       "If you can give a counterexample, return a single JSON object with field assignment "
                       "and exact integer values or rational objects with keys op, num, den. "
                       "Otherwise return UNKNOWN.\n")
        return instruction + payload


def audit_seed(checkpoint_id, prefix_sha256, study_seed):
    """Pair the audit RNG across scope variants, independently of the main RNG."""
    return int(digest(["d25-audit-stream-v1", checkpoint_id, prefix_sha256, study_seed])[:15], 16)


def run_side_audit(engine, snapshot, request, *, study_seed, max_tokens=80):
    """Run a separately templated forward sequence without access to the main KV or RNG."""
    if request.prefix_sha256 != snapshot.prefix_sha256:
        raise ValueError("Audit request was built for a different observed prefix")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 192:
        raise ValueError("Invalid audit-branch token guard")
    engine.sync()
    began = time.monotonic()
    start = len(engine.ledger)
    previous_stage = engine.stage
    prompt = engine.tokenizer.apply_chat_template([{"role": "user", "content": request.render()}],
        tokenize=True, add_generation_prompt=True, enable_thinking=False)
    if not prompt or len(prompt) >= engine.capacity:
        raise ValueError("Audit prompt exceeds the runtime capacity")
    if tuple(prompt) == snapshot.prefix_ids:
        raise ValueError("Audit context must be independent of the main context")
    seed = audit_seed(snapshot.checkpoint_id, snapshot.prefix_sha256, study_seed)
    rng = engine.rng(seed=seed)
    generated = []
    reason = "AUDIT_TOKEN_GUARD"
    try:
        engine.stage = "independent_audit_prefill"
        cache, logits = engine.prefill(prompt)
        engine.stage = "independent_audit_decode"
        for index in range(max_tokens):
            token = engine.sample(logits, rng)
            generated.append(token)
            if token in engine.eos:
                reason = "EOS"
                break
            if len(prompt) + len(generated) >= engine.capacity:
                reason = "AUDIT_CONTEXT_CAP"
                break
            if index + 1 < max_tokens:
                cache, logits = engine.forward([token], cache)
    finally:
        engine.stage = previous_stage
    engine.sync()
    return {"status": "UNVERIFIED_PROPOSAL", "stop_reason": reason,
            "text": engine.tokenizer.decode(generated, skip_special_tokens=True), "generated_ids": generated,
            "prompt_ids": list(prompt), "prompt_sha256": digest(prompt), "request_sha256": digest(asdict(request)),
            "sample_seed": seed, "wall_seconds": time.monotonic() - began, "paid_work": work(engine.ledger[start:]),
            "discarded_audit_tokens": len(generated), "generated_tokens": len(generated)}


@dataclass(frozen=True)
class RevisionPermit:
    """Control-plane receipt produced only after independent verification and role checks."""

    prefix_sha256: str
    native_proposal_sha256: str
    event_id: str
    decision: str
    verified_evidence_sha256: str


@dataclass
class EventRun:
    state: NativeState
    metadata: dict


def handle_event(engine, snapshot: NativeSnapshot, *, identity, study_seed,
                 detect: Callable, verify: Callable, revise: Callable | None = None,
                 max_native_proposal_tokens=192, max_audit_tokens=80):
    """Sample the original distribution, then conditionally audit and apply a checked change.

    detect(snapshot, proposal) returns an AuditRequest or None. verify is a
    CPU/control-plane verifier, never a model verdict. It returns a diagnostic
    and an optional RevisionPermit. revise consumes the permit to build a new
    state. A missing replacement always adopts the unmodified native proposal.
    """
    validate_snapshot(engine, snapshot, identity=identity)
    start = len(engine.ledger)
    began = time.monotonic()
    proposal = generate_reflection(engine, snapshot, identity=identity,
                                   max_proposal_tokens=max_native_proposal_tokens)
    detection_started = time.monotonic()
    request = detect(snapshot, proposal)
    detection_seconds = time.monotonic() - detection_started
    audit = None if request is None else run_side_audit(engine, snapshot, request,
                                                        study_seed=study_seed, max_tokens=max_audit_tokens)
    check_started = time.monotonic()
    diagnostic, permit = verify(snapshot, proposal, request, audit)
    check_seconds = time.monotonic() - check_started
    replacement = None
    if permit is not None:
        if (not isinstance(permit, RevisionPermit) or permit.prefix_sha256 != snapshot.prefix_sha256
                or permit.native_proposal_sha256 != digest(proposal.token_ids)
                or permit.decision not in ("REJECT_REFLECTION", "REBASE")
                or diagnostic.get("status") not in ("INVALID_JUSTIFICATION", "REFUTED_CLAIM", "INVALID_COUNTEREXAMPLE")
                or (request is not None and permit.event_id != request.event_id)
                or not permit.event_id or len(permit.verified_evidence_sha256) != 64
                or diagnostic.get("verified_evidence_sha256") != permit.verified_evidence_sha256):
            raise ValueError("Revision permission does not bind the verified state")
        if revise is not None:
            replacement = revise(snapshot, proposal, permit)
        if replacement is not None and (not isinstance(replacement, NativeState)
                                       or replacement.identity.sha256 != identity.sha256):
            raise ValueError("Revision returned a state with a different execution identity")
    native = resolve_reflection(engine, snapshot, proposal, identity=identity, disposition="UNKNOWN").state
    engine.sync()
    return EventRun(native if replacement is None else replacement, {
        "decision": "ADOPT_NATIVE" if replacement is None else permit.decision,
        "verification": diagnostic, "permit": None if permit is None else asdict(permit),
        "native_proposal_ids": list(proposal.token_ids), "native_proposal_text": proposal.text,
        "native_proposal_boundary": proposal.stop_reason, "native_proposal_cost": asdict(proposal.cost),
        "discarded_native_tokens": 0 if replacement is None else len(proposal.token_ids),
        "audit": audit, "detect_seconds": detection_seconds, "verify_seconds": check_seconds,
        "total_event_seconds": time.monotonic() - began, "paid_work": work(engine.ledger[start:]),
    })
