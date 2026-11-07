"""Isolated reflection sampling and transfer of the resulting native state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from native_snapshot import (
    ExecutionIdentity,
    NativeSnapshot,
    NativeState,
    StateCopyCost,
    advance_native,
    restore_snapshot,
    validate_snapshot,
)


@dataclass(frozen=True)
class ReflectionCost:
    """Proposal wall time includes its initial clone and model calls."""

    wall_seconds: float
    initial_copy: StateCopyCost
    generated_tokens: int
    forward_calls: int
    forward_input_tokens: int


@dataclass
class ReflectionProposal:
    source_checkpoint_id: str
    token_ids: tuple[int, ...]
    text: str
    stop_reason: str
    native_stop_reason: str
    cost: ReflectionCost
    _source: NativeSnapshot = field(repr=False)
    _shadow: NativeState | None = field(repr=False)

    @property
    def completed_step(self) -> bool:
        return self.stop_reason == "COMPLETED_STEP"


@dataclass
class ReflectionResolution:
    disposition: Literal["ACCEPT", "REJECT", "UNKNOWN"]
    state: NativeState
    requires_redirect: bool
    discarded_proposal_tokens: int
    rollback_copy_cost: StateCopyCost | None


def generate_reflection(
    engine: Any,
    snapshot: NativeSnapshot,
    *,
    identity: ExecutionIdentity,
    max_proposal_tokens: int = 192,
    completed_step: Callable[[tuple[int, ...], str], bool] | None = None,
) -> ReflectionProposal:
    """Sample a shadow until its first observed boundary or local guard.

    The default boundary is a blank paragraph. A caller can supply a stricter
    predicate over the observed proposal IDs and text. The local proposal limit
    leaves the shadow's native state ready for normal continuation.
    """
    if type(max_proposal_tokens) is not int or max_proposal_tokens < 1:
        raise ValueError("The proposal token guard must be a positive integer")
    if snapshot.stop_reason != "RUNNING" or not snapshot.thinking_open:
        raise ValueError("Reflection requires a live checkpoint inside thinking")
    engine.sync()
    started = time.monotonic()
    first_forward = len(engine.ledger)
    shadow = restore_snapshot(engine, snapshot, identity=identity)
    copy_cost = shadow.restore_cost
    if copy_cost is None:
        raise RuntimeError("Missing initial reflection copy cost")
    observed = []
    text = ""
    reason = "PROPOSAL_LIMIT"
    previous_stage = engine.stage
    engine.stage = "reflection_proposal"
    try:
        for _ in range(max_proposal_tokens):
            observed.append(advance_native(engine, shadow))
            text = engine.tokenizer.decode(observed, skip_special_tokens=False)
            if shadow.stop_reason != "RUNNING":
                reason = shadow.stop_reason
                break
            if not shadow.thinking_open:
                reason = "THINK_CLOSED"
                break
            complete = text.endswith("\n\n") if completed_step is None else completed_step(tuple(observed), text)
            if complete:
                reason = "COMPLETED_STEP"
                break
    finally:
        engine.stage = previous_stage
    engine.sync()
    ledger = engine.ledger[first_forward:]
    cost = ReflectionCost(
        wall_seconds=time.monotonic() - started,
        initial_copy=copy_cost,
        generated_tokens=len(observed),
        forward_calls=len(ledger),
        forward_input_tokens=sum(row["input_tokens"] for row in ledger),
    )
    return ReflectionProposal(
        snapshot.checkpoint_id, tuple(observed), text, reason, shadow.stop_reason,
        cost, snapshot, shadow,
    )


def resolve_reflection(
    engine: Any,
    snapshot: NativeSnapshot,
    proposal: ReflectionProposal,
    *,
    identity: ExecutionIdentity,
    disposition: Literal["ACCEPT", "REJECT", "UNKNOWN"],
) -> ReflectionResolution:
    """Transfer the shadow or restore the checkpoint under a caller verdict.

    A rejected proposal restores the original RNG. A caller must redirect that
    state before sampling again if it intends to avoid repeating the proposal.
    """
    if disposition not in ("ACCEPT", "REJECT", "UNKNOWN"):
        raise ValueError("Unknown reflection disposition")
    if proposal._source is not snapshot or proposal._shadow is None:
        raise ValueError("Proposal is already resolved or belongs to another snapshot")
    validate_snapshot(engine, snapshot, identity=identity)
    if disposition == "REJECT":
        state = restore_snapshot(engine, snapshot, identity=identity)
        resolution = ReflectionResolution(disposition, state, True, len(proposal.token_ids), state.restore_cost)
    else:
        resolution = ReflectionResolution(disposition, proposal._shadow, False, 0, None)
    proposal._shadow = None
    return resolution
