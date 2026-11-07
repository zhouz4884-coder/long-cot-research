"""State snapshots for the D1 batch-one contiguous native execution schedule."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExecutionIdentity:
    """Runtime fingerprints supplied by the worker after checking its assets."""

    model_sha256: str
    tokenizer_sha256: str
    engine_sha256: str
    backend: str
    dtype: str
    device: str
    runtime: str
    sampling_config: Mapping[str, str | int | float | bool | None]

    def __post_init__(self) -> None:
        fields = (self.model_sha256, self.tokenizer_sha256, self.engine_sha256,
                  self.backend, self.dtype, self.device, self.runtime)
        if any(not isinstance(value, str) or not value for value in fields):
            raise ValueError("Execution identity fields require nonempty strings")
        sampling = dict(self.sampling_config)
        if not sampling or any(
            not isinstance(key, str) or type(value) not in (str, int, float, bool, type(None))
            for key, value in sampling.items()
        ):
            raise ValueError("Sampling config must contain named scalar settings")
        json.dumps(sampling, allow_nan=False)
        object.__setattr__(self, "sampling_config", MappingProxyType(sampling))

    def as_dict(self) -> dict:
        return {
            "model_sha256": self.model_sha256,
            "tokenizer_sha256": self.tokenizer_sha256,
            "engine_sha256": self.engine_sha256,
            "backend": self.backend,
            "dtype": self.dtype,
            "device": self.device,
            "runtime": self.runtime,
            "sampling_config": dict(self.sampling_config),
            "position_policy": "batch_one_zero_based_contiguous_all_ones",
            "prefill_schedule": "D1_prompt_chunks_then_singleton_decode",
        }

    @property
    def sha256(self) -> str:
        data = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StateCopyCost:
    """Measured copy wall time and tensor payload bytes."""

    wall_seconds: float
    cache_bytes: int
    logits_bytes: int
    rng_bytes: int


@dataclass
class NativeState:
    prompt_ids: tuple[int, ...]
    generated_ids: list[int]
    cache: Any = field(repr=False)
    next_logits: Any = field(repr=False)
    rng: Any = field(repr=False)
    cache_position: int
    thinking_open: bool
    stop_reason: str
    identity: ExecutionIdentity
    restore_cost: StateCopyCost | None = None

    @property
    def prefix_ids(self) -> tuple[int, ...]:
        return self.prompt_ids + tuple(self.generated_ids)


@dataclass(frozen=True)
class NativeSnapshot:
    """The snapshot owns private copies. Restoring creates another owner."""

    checkpoint_id: str
    identity: ExecutionIdentity
    prompt_ids: tuple[int, ...]
    generated_ids: tuple[int, ...]
    cache_position: int
    thinking_open: bool
    stop_reason: str
    capacity: int
    eos_ids: frozenset[int]
    open_ids: tuple[int, ...]
    close_ids: tuple[int, ...]
    copy_cost: StateCopyCost
    _cache: Any = field(repr=False, compare=False)
    _next_logits: Any = field(repr=False, compare=False)
    _rng_state: Any = field(repr=False, compare=False)

    @property
    def prefix_ids(self) -> tuple[int, ...]:
        return self.prompt_ids + self.generated_ids

    @property
    def prefix_sha256(self) -> str:
        encoded = json.dumps(self.prefix_ids, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def metadata(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "execution_sha256": self.identity.sha256,
            "prefix_sha256": self.prefix_sha256,
            "prompt_tokens": len(self.prompt_ids),
            "generated_tokens": len(self.generated_ids),
            "cache_position": self.cache_position,
            "thinking_open": self.thinking_open,
            "stop_reason": self.stop_reason,
        }


def _tensor_bytes(tensor: Any) -> int:
    return 0 if tensor is None else tensor.numel() * tensor.element_size()


def _copy_payload(engine: Any, cache: Any, logits: Any, rng_state: Any):
    cache_bytes = sum(
        _tensor_bytes(tensor) for layer in cache.layers
        for tensor in (layer.keys, layer.values)
    )
    engine.sync()
    started = time.monotonic()
    with engine.torch.inference_mode():
        cache_copy = copy.deepcopy(cache)
        logits_copy = None if logits is None else logits.detach().clone()
        rng_copy = rng_state.clone()
    engine.sync()
    cost = StateCopyCost(time.monotonic() - started, cache_bytes,
                         _tensor_bytes(logits), _tensor_bytes(rng_state))
    return cache_copy, logits_copy, rng_copy, cost


def _check_execution(engine: Any, identity: ExecutionIdentity) -> None:
    if str(engine.device) != identity.device:
        raise ValueError("Engine and execution identity use different devices")
    if len(engine.open_ids) != 1 or len(engine.close_ids) != 1:
        raise ValueError("D1 execution requires single-token thinking boundaries")


def validate_snapshot(engine: Any, snapshot: NativeSnapshot, *, identity: ExecutionIdentity) -> None:
    _check_execution(engine, identity)
    if (snapshot.identity.sha256 != identity.sha256
            or snapshot.capacity != engine.capacity
            or snapshot.eos_ids != frozenset(engine.eos)
            or snapshot.open_ids != tuple(engine.open_ids)
            or snapshot.close_ids != tuple(engine.close_ids)):
        raise ValueError("Snapshot execution identity or boundary configuration differs")


def _validate_token_ids(ids: tuple[int, ...]) -> None:
    if any(type(token) is not int or token < 0 for token in ids):
        raise ValueError("Token IDs must be nonnegative integers")


def capture_snapshot(
    engine: Any,
    *,
    identity: ExecutionIdentity,
    prompt_ids: Sequence[int],
    generated_ids: Sequence[int],
    cache: Any,
    next_logits: Any,
    rng: Any,
    thinking_open: bool,
    checkpoint_id: str,
    stop_reason: str = "RUNNING",
) -> NativeSnapshot:
    """Capture sampled IDs and the cache, logits and RNG at the same position.

    At a D1 terminal state the last emitted token never enters the cache.
    """
    _check_execution(engine, identity)
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise ValueError("Checkpoint ID is required")
    prompt = tuple(prompt_ids)
    generated = tuple(generated_ids)
    prefix = prompt + generated
    _validate_token_ids(prefix)
    if not prompt or len(prefix) > engine.capacity:
        raise ValueError("Snapshot prefix exceeds context capacity or lacks a prompt")
    cache_position = int(cache.get_seq_length())
    eos_positions = [i for i, token in enumerate(generated) if token in engine.eos]
    if stop_reason == "RUNNING":
        if eos_positions or len(prefix) >= engine.capacity:
            raise ValueError("Running snapshot must have context and precede EOS")
        if cache_position != len(prefix) or next_logits is None or next_logits.ndim != 1:
            raise ValueError("Running snapshot requires cached prefix and next-token logits")
        if str(next_logits.device) != identity.device:
            raise ValueError("Next-token logits use a different device")
    elif stop_reason in ("EOS", "CONTEXT_CAP"):
        if not generated or cache_position != len(prefix) - 1 or next_logits is not None:
            raise ValueError("Terminal snapshot must retain the D1 unforwarded final token")
        if stop_reason == "EOS" and eos_positions != [len(generated) - 1]:
            raise ValueError("EOS snapshot must end at its first EOS token")
        if stop_reason == "CONTEXT_CAP" and (eos_positions or len(prefix) != engine.capacity):
            raise ValueError("Context-cap snapshot must fill the context without EOS")
    else:
        raise ValueError("Unsupported native stop reason")
    active = False
    for token in prefix:
        if token == engine.open_ids[0]:
            active = True
        elif token == engine.close_ids[0]:
            active = False
    if type(thinking_open) is not bool or thinking_open != active:
        raise ValueError("Thinking state does not match observed token IDs")
    if str(rng.device) != identity.device:
        raise ValueError("RNG uses a different device")
    copied_cache, copied_logits, rng_state, cost = _copy_payload(
        engine, cache, next_logits, rng.get_state()
    )
    return NativeSnapshot(
        checkpoint_id, identity, prompt, generated, cache_position, thinking_open,
        stop_reason, engine.capacity, frozenset(engine.eos), tuple(engine.open_ids),
        tuple(engine.close_ids), cost, copied_cache, copied_logits, rng_state,
    )


def restore_snapshot(engine: Any, snapshot: NativeSnapshot, *, identity: ExecutionIdentity) -> NativeState:
    validate_snapshot(engine, snapshot, identity=identity)
    cache, logits, rng_state, cost = _copy_payload(
        engine, snapshot._cache, snapshot._next_logits, snapshot._rng_state
    )
    return NativeState(
        snapshot.prompt_ids, list(snapshot.generated_ids), cache, logits,
        engine.rng(state=rng_state), snapshot.cache_position, snapshot.thinking_open,
        snapshot.stop_reason, identity, cost,
    )


def replay_schedule(engine: Any, prompt_ids: Sequence[int], generated_ids: Sequence[int]):
    """Teacher force observed IDs under the original prefill/decode schedule."""
    if not prompt_ids or len(prompt_ids) + len(generated_ids) > engine.capacity:
        raise ValueError("Replay prefix does not fit the context")
    with engine.torch.inference_mode():
        cache, logits = engine.prefill(list(prompt_ids))
        for token in generated_ids:
            cache, logits = engine.forward([token], cache)
    return cache, logits


def replay_snapshot(engine: Any, snapshot: NativeSnapshot, *, identity: ExecutionIdentity) -> NativeState:
    validate_snapshot(engine, snapshot, identity=identity)
    cached_generated = snapshot.generated_ids[:snapshot.cache_position - len(snapshot.prompt_ids)]
    cache, logits = replay_schedule(engine, snapshot.prompt_ids, cached_generated)
    if int(cache.get_seq_length()) != snapshot.cache_position:
        raise ValueError("Replay produced a different cache position")
    return NativeState(
        snapshot.prompt_ids, list(snapshot.generated_ids), cache,
        logits if snapshot.stop_reason == "RUNNING" else None,
        engine.rng(state=snapshot._rng_state.clone()), snapshot.cache_position,
        snapshot.thinking_open, snapshot.stop_reason, identity,
    )


def advance_native(engine: Any, state: NativeState) -> int:
    """Emit one token with D1's terminal cache convention."""
    if state.stop_reason != "RUNNING" or state.next_logits is None:
        raise ValueError("Cannot advance a terminal native state")
    if state.cache_position != len(state.prompt_ids) + len(state.generated_ids):
        raise ValueError("Native state position differs from the observed prefix")
    if state.cache_position >= engine.capacity:
        raise ValueError("Native state already fills the context")
    with engine.torch.inference_mode():
        token = engine.sample(state.next_logits, state.rng)
        state.generated_ids.append(token)
        if token == engine.open_ids[0]:
            state.thinking_open = True
        elif token == engine.close_ids[0]:
            state.thinking_open = False
        if token in engine.eos:
            state.stop_reason = "EOS"
            state.next_logits = None
        elif state.cache_position + 1 == engine.capacity:
            state.stop_reason = "CONTEXT_CAP"
            state.next_logits = None
        else:
            state.cache, state.next_logits = engine.forward([token], state.cache)
            state.cache_position += 1
    return token
