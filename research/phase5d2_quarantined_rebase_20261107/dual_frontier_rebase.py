"""Reference rebase planner for the frozen Phase5-D evidence ledger.

Span coordinates count generated assistant tokens, with a half-open end.
The caller owns extraction and binds the ledger to its observed transcript.
This module checks that binding, replays certificates, and plans a fresh
native prefill. The caller commits the revised ledger after replay succeeds.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from fractions import Fraction
import hashlib
import json
import re


_CONTROL_TAGS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>")
_CLOSED_THINKING_TAGS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "</think>")
_PARAGRAPH_END = re.compile(r"(?:\r?\n[ \t]*){2}$")
_MARKUP = re.compile(r"```|\\\[|\\\]|\\\(|\\\)|(?<!\\)\$\$|(?<!\\)\$|(?<!\\)[{}]")


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _digest(value):
    encoded = json.dumps(_json_value(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _token_ids(ids):
    result = tuple(ids)
    if any(type(token) is not int or token < 0 for token in result):
        raise ValueError("Expected nonnegative integer token IDs")
    return result


def _ledger_identity(ledger):
    # The pinned ledger issues checker receipts without advancing revision.
    # Bind receipts actually in use, plus the trusted registries and version
    # slots. An unrelated freshly issued challenge cannot stale a transcript.
    receipts = [proof.certificate for proof in ledger.proofs.values() if proof.certificate is not None]
    receipts.extend(challenge.certificate for challenge in ledger._refutations.values())
    registered = {receipt.id: ledger._certificates.get(receipt.id) for receipt in receipts if receipt is not None}
    return _digest({
        "revision": ledger.revision,
        "observed_token_length": ledger.observed_token_length,
        "revised_span_source": getattr(ledger, "_d2_revised_span_source", None),
        "boundaries": ledger.boundaries,
        "scopes": ledger._scopes,
        "claims": dict(ledger.claims),
        "proofs": dict(ledger.proofs),
        "current_versions": dict(ledger.current_versions),
        "givens": ledger._givens,
        "constraints": ledger._constraints,
        "refutations": ledger._refutations,
        "live_receipt_records": registered,
    })


@dataclass(frozen=True)
class ObservedThinking:
    snapshot_id: str
    source_version: str | int
    prompt_ids: tuple[int, ...]
    generated_ids: tuple[int, ...]
    complete_boundaries: tuple[int, ...]
    prefix_sha256: str
    ledger_sha256: str
    tokenizer: object = field(repr=False, compare=False)


def _opener_offset(tokenizer, prompt, generated):
    rendered = tokenizer.decode(list(prompt), skip_special_tokens=False)
    _, separator, assistant = rendered.rpartition("<|im_start|>")
    if not separator or not assistant.startswith("assistant\n"):
        raise ValueError("Expected native assistant thinking prompt")
    assistant = assistant[len("assistant\n"):].strip()
    if assistant not in ("", "<think>"):
        raise ValueError("Expected fresh or pre-opened thinking prompt")
    text = tokenizer.decode(list(generated), skip_special_tokens=False)
    if any(tag in text for tag in _CLOSED_THINKING_TAGS):
        raise ValueError("Observed assistant thinking has closed or crossed a role boundary")
    if assistant:
        if "<think>" in text:
            raise ValueError("Duplicate thinking opener")
        return 0
    opener_ids = _token_ids(tokenizer.encode("<think>", add_special_tokens=False))
    if len(opener_ids) != 1 or text.count("<think>") != 1 or not text.lstrip().startswith("<think>"):
        raise ValueError("Missing unique observed thinking opener")
    try:
        return generated.index(opener_ids[0]) + 1
    except ValueError as error:
        raise ValueError("Thinking opener lacks the pinned token identity") from error


def _closed_paragraph(text):
    if not _PARAGRAPH_END.search(text):
        return False
    openings = {r"\[": r"\]", r"\(": r"\)", "{": "}"}
    stack = []
    fenced = False
    for mark in _MARKUP.findall(text):
        if mark == "```":
            fenced = not fenced
        elif fenced:
            continue
        elif stack and mark == stack[-1]:
            stack.pop()
        elif mark in openings:
            stack.append(openings[mark])
        elif mark in ("$", "$$"):
            stack.append(mark)
        else:
            return False
    return not fenced and not stack


def bind_observed_thinking(ledger, tokenizer, *, snapshot_id, source_version, prompt_ids, generated_ids, boundary_offsets):
    """Bind observed IDs and verify proposed complete paragraph boundaries.

    The actual thinking opener is also a legal restart boundary. For D1 it
    normally lives in the generated sequence, after the original prompt.
    """
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("Snapshot identity is required")
    if not (type(source_version) is int and source_version >= 0 or isinstance(source_version, str) and source_version):
        raise ValueError("Source version is required")
    prompt, generated = _token_ids(prompt_ids), _token_ids(generated_ids)
    if ledger.observed_token_length != len(generated):
        raise ValueError("Ledger and observed assistant length differ")
    prefix_sha256 = _digest(prompt + generated)
    old_span_source = getattr(ledger, "_d2_revised_span_source", None)
    if old_span_source is not None and old_span_source != prefix_sha256:
        raise ValueError("Revised ledger spans require rebinding to the reconstructed source")
    opening = _opener_offset(tokenizer, prompt, generated)
    boundaries = {opening}
    for offset in boundary_offsets:
        if type(offset) is not int or not 0 <= offset <= len(generated):
            raise ValueError("Boundary outside observed assistant tokens")
        # Frozen ledger fixtures use zero as a sentinel even for a generated
        # thinking opener. Such a sentinel cannot become an actual cut.
        if offset == 0 and opening > 0:
            continue
        if offset == opening:
            continue
        prefix = tokenizer.decode(list(generated[:offset]), skip_special_tokens=False)
        if offset < opening or not _closed_paragraph(prefix):
            raise ValueError("Boundary lacks an observed closed paragraph")
        boundaries.add(offset)
    return ObservedThinking(snapshot_id, source_version, prompt, generated, tuple(sorted(boundaries)),
                            prefix_sha256, _ledger_identity(ledger), tokenizer)


@dataclass(frozen=True)
class CarriedFact:
    claim_id: str
    subject: str
    value: str
    scope_id: str
    scope_revision: int
    domain: str
    assumptions: tuple[str, ...]
    claim_version: int
    proof_id: str
    certificate_id: str
    certificate_binding: str
    checker_id: str
    premise_ids: tuple[str, ...]
    premise_certificate_ids: tuple[str, ...]
    expression: str | None
    trusted_source: str | None
    constraint_id: str | None
    claim_span: tuple[int, int]
    proof_span: tuple[int, int]
    claim_source_sha256: str | None
    proof_source_sha256: str | None


@dataclass(frozen=True)
class RebasePlan:
    status: str
    reason: str
    snapshot_id: str
    source_version: str | int
    source_prefix_sha256: str
    source_ledger_sha256: str
    lost_support: frozenset[str] = frozenset()
    invalidated_justifications: tuple[str, ...] = ()
    invalidated_text_spans: tuple[tuple[int, int], ...] = ()
    cut_token: int | None = None
    carried_claims: tuple[str, ...] = ()
    carry_witness: tuple[CarriedFact, ...] = ()
    incomplete_carry_provenance: tuple[str, ...] = ()
    bridge_text: str = ""
    revised_ledger_sha256: str | None = None
    carry_requested: bool = True
    challenge: object = field(default=None, repr=False)
    updated_ledger: object = field(default=None, repr=False, compare=False)


def _observed_span(span, observation, *, allow_given=False):
    start, end = span
    if type(start) is not int or type(end) is not int:
        raise ValueError("Span requires integer token offsets")
    if allow_given and start == end == 0:
        return None
    if not observation.complete_boundaries[0] <= start < end <= observation.complete_boundaries[-1]:
        raise ValueError("Span lacks observed, complete thinking provenance")
    return _digest(observation.generated_ids[start:end])


def _grounded_witnesses(ledger, supported, observation, cut):
    facts = {}
    proofs = sorted(ledger.proofs.values(), key=lambda proof: proof.id)
    # Exhaust grounded proofs inside the retained prefix first, so a later
    # alternative cannot create an unnecessary bridge for an intact proof.
    for bound in (cut, observation.complete_boundaries[-1]):
        previous_count = -1
        while len(facts) > previous_count:
            previous_count = len(facts)
            for proof in proofs:
                claim_id = proof.conclusion
                if (claim_id in facts or claim_id not in supported or proof.revoked
                        or not all(premise in facts for premise in proof.premises) or not ledger._certificate_valid(proof)):
                    continue
                claim = ledger.claims[claim_id]
                if claim.token_end > bound or proof.token_end > bound:
                    continue
                scope = ledger._scopes[claim.scope_id]
                claim_span = (claim.token_start, claim.token_end)
                proof_span = (proof.token_start, proof.token_end)
                given = proof.checker_id == "trusted-input-v1" and proof.source_id is not None
                try:
                    claim_source = _observed_span(claim_span, observation, allow_given=given)
                    proof_source = _observed_span(proof_span, observation, allow_given=given)
                except ValueError:
                    # A different grounded proof may have complete provenance.
                    continue
                facts[claim_id] = CarriedFact(
                    claim_id, claim.subject, str(claim.value), claim.scope_id, scope.revision, scope.domain,
                    scope.assumptions, claim.version, proof.id, proof.certificate.id, proof.certificate.binding_hash,
                    proof.checker_id, proof.premises, tuple(facts[p].certificate_id for p in proof.premises),
                    proof.expression, proof.source_id, proof.constraint_id, claim_span, proof_span,
                    claim_source, proof_source,
                )
    return facts


def _carry(ledger, supported, observation, cut):
    facts = _grounded_witnesses(ledger, supported, observation, cut)
    displaced = set()
    for claim_id, fact in facts.items():
        if (fact.claim_span[1] > cut or fact.proof_span[1] > cut
                or any(premise in displaced for premise in fact.premise_ids)):
            displaced.add(claim_id)
    needed = set(displaced)
    for claim_id, fact in reversed(tuple(facts.items())):
        if claim_id in needed:
            needed.update(fact.premise_ids)
    carried = tuple(cid for cid in facts if cid in displaced)
    witness = tuple(fact for cid, fact in facts.items() if cid in needed)
    return carried, witness, tuple(sorted(supported.difference(facts)))


def _bridge(facts):
    if not facts:
        return ""
    payload = json.dumps([asdict(fact) for fact in facts], ensure_ascii=True, separators=(",", ":"))
    payload = payload.replace("<", r"\u003c").replace(">", r"\u003e")
    return "\n\nVerified scoped evidence for this continuation. Use the stated premises and scopes.\n" + payload + "\n\n"


def plan_rebase(ledger, challenge, observation, *, carry=True):
    """Plan a checked transition on a private copy of the evidence ledger."""
    if type(carry) is not bool:
        raise ValueError("Carry must be a boolean")
    checked_observation = bind_observed_thinking(
        ledger, observation.tokenizer, snapshot_id=observation.snapshot_id, source_version=observation.source_version,
        prompt_ids=observation.prompt_ids, generated_ids=observation.generated_ids, boundary_offsets=observation.complete_boundaries,
    )
    if checked_observation != observation:
        raise ValueError("Stale observed prefix or ledger binding")
    base = dict(snapshot_id=observation.snapshot_id, source_version=observation.source_version,
                source_prefix_sha256=observation.prefix_sha256, source_ledger_sha256=observation.ledger_sha256,
                carry_requested=carry, challenge=challenge)
    checked = ledger.verify_challenge(challenge)
    if checked.verdict != "PASS":
        return RebasePlan("NO_REBASE", checked.reason, **base)
    draft = deepcopy(ledger)
    delta = draft.apply_challenge(challenge)
    frontiers = dict(lost_support=delta.lost_support, invalidated_justifications=delta.invalidated_justifications,
                     invalidated_text_spans=delta.invalidated_text_spans)
    if delta.verdict != "PASS" or delta.after_status != "OK":
        return RebasePlan("QUARANTINE_CONFLICT", delta.after_status, **base, **frontiers)
    lost_spans = tuple((draft.claims[cid].token_start, draft.claims[cid].token_end) for cid in sorted(delta.lost_support))
    spans = delta.invalidated_text_spans + lost_spans
    if not spans:
        return RebasePlan("NO_REBASE", "empty_frontiers", **base, **frontiers)
    try:
        for span in spans:
            _observed_span(span, observation)
    except ValueError:
        return RebasePlan("UNSAFE_SPAN", "frontier_requires_complete_observed_provenance", **base, **frontiers)
    earliest = min(start for start, _ in spans)
    cut = max(offset for offset in observation.complete_boundaries if offset <= earliest)
    carried, witness, incomplete = _carry(draft, draft.supported(), observation, cut) if carry else ((), (), ())
    # The semantic transition preserves proof receipts with historical spans.
    # A later planner must reconstruct provenance before using those spans on
    # another transcript, even when its generated length happens to match.
    draft._d2_revised_span_source = observation.prefix_sha256
    return RebasePlan("READY", delta.reason, cut_token=cut, carried_claims=carried, carry_witness=witness,
                      incomplete_carry_provenance=incomplete, bridge_text=_bridge(witness),
                      revised_ledger_sha256=_ledger_identity(draft),
                      updated_ledger=draft, **base, **frontiers)


@dataclass(frozen=True)
class ReplayedRebase:
    prefix_ids: tuple[int, ...]
    cache: object = field(repr=False)
    next_logits: object = field(repr=False)
    revised_ledger: object = field(repr=False)
    retained_generated_tokens: int
    appended_bridge_tokens: int


def replay_rebase(engine, plan, ledger, observation, *, snapshot_id, source_version, current_prefix_ids):
    """Reconstruct from original prompt and retained generated tokens.

    A repaired prefix needs an explicit continuation RNG policy supplied by
    its caller. Replay here performs no sampling and returns fresh next logits.
    """
    if (snapshot_id != observation.snapshot_id or type(source_version) is not type(observation.source_version)
            or source_version != observation.source_version
            or _token_ids(current_prefix_ids) != observation.prompt_ids + observation.generated_ids):
        raise ValueError("Stale source snapshot")
    if engine.tokenizer is not observation.tokenizer:
        raise ValueError("Replay requires the tokenizer used to bind the observation")
    expected = plan_rebase(ledger, plan.challenge, observation, carry=plan.carry_requested)
    if plan.status != "READY" or plan != expected or _ledger_identity(plan.updated_ledger) != plan.revised_ledger_sha256:
        raise ValueError("Rebase plan no longer matches checked evidence")
    retained = observation.generated_ids[:plan.cut_token]
    bridge_ids = _token_ids(engine.tokenizer.encode(plan.bridge_text, add_special_tokens=False)) if plan.bridge_text else ()
    if plan.bridge_text and not bridge_ids:
        raise ValueError("Nonempty bridge lost during tokenization")
    reserved_ids = set(engine.eos)
    reserved_sequences = [_token_ids(engine.tokenizer.encode(tag, add_special_tokens=False)) for tag in _CONTROL_TAGS]
    contains_reserved = any(seq and any(bridge_ids[index:index+len(seq)] == seq for index in range(len(bridge_ids)))
                            for seq in reserved_sequences)
    if reserved_ids.intersection(bridge_ids) or contains_reserved:
        raise ValueError("Bridge contains native control token IDs")
    prefix = observation.prompt_ids + retained + bridge_ids
    if len(prefix) >= engine.capacity:
        raise ValueError("Rebase prefix leaves no context for continuation")
    from native_snapshot import replay_schedule

    previous_stage = engine.stage
    try:
        with engine.torch.inference_mode():
            engine.stage = "rebase_cold_prompt_and_retained"
            cache, logits = replay_schedule(engine, observation.prompt_ids, retained)
            engine.stage = "rebase_evidence_bridge"
            for token in bridge_ids:
                cache, logits = engine.forward([token], cache)
    finally:
        engine.stage = previous_stage
    if cache.get_seq_length() != len(prefix):
        raise ValueError("Reconstructed cache length differs from prefix")
    if _ledger_identity(ledger) != observation.ledger_sha256 or _ledger_identity(plan.updated_ledger) != plan.revised_ledger_sha256:
        raise ValueError("Evidence changed during replay")
    return ReplayedRebase(prefix, cache, logits, plan.updated_ledger, len(retained), len(bridge_ids))
