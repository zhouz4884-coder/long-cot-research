"""Immutable source bindings for observations. Certificates live in a separate ledger."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from fractions import Fraction
from hashlib import sha256
import json
import re
from typing import Callable

_CLAIM_TYPES = frozenset({
    "EXACT_ANSWER", "FEASIBLE_CANDIDATE", "MAXIMALITY_CLAIM", "MINIMALITY_CLAIM",
    "UNIVERSAL_CLAIM", "COMPLETE_SOLUTIONS_CLAIM", "FINAL_ANSWER_REVISION",
})
_HEX = re.compile(r"[a-f0-9]{64}")
_MAX_TOKENS = 131_072
_MAX_SOURCE_CHARS = 2_500
_MAX_CACHED_PREFIXES = 256


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def _tokens(values):
    if type(values) not in (list, tuple) or len(values) > _MAX_TOKENS:
        raise ValueError("bounded token list required")
    if any(type(value) is not int or not 0 <= value < 2**31 for value in values):
        raise ValueError("invalid token ID")
    return tuple(values)


def _sha(value):
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError("SHA-256 required")
    return value


@dataclass(frozen=True)
class SourceSpan:
    char_span: tuple[int, int]
    token_span: tuple[int, int]
    token_sha256: str
    text: str

    @property
    def token_start(self):
        return self.token_span[0]

    @property
    def token_end(self):
        return self.token_span[1]

    @property
    def char_start(self):
        return self.char_span[0]

    @property
    def char_end(self):
        return self.char_span[1]

    def as_dict(self):
        return {"char_span": list(self.char_span), "token_span": list(self.token_span),
                "token_sha256": self.token_sha256, "text": self.text}


@dataclass(frozen=True)
class ObservedPrefix:
    """A token-bound, past-only snapshot. Span token offsets count generated tokens."""

    prompt_ids: tuple[int, ...]
    generated_ids: tuple[int, ...]
    text: str
    initial_segment: str
    tokenizer_sha256: str
    trajectory_id: str
    question_sha256: str
    observed_prefix_sha256: str
    _decode: Callable = field(repr=False, compare=False)
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_tokens(cls, generated_ids, decode, *, prompt_ids, tokenizer_sha256, trajectory_id, question_sha256):
        prompt = _tokens(prompt_ids)
        generated = _tokens(generated_ids)
        if not prompt or len(prompt) + len(generated) > _MAX_TOKENS or not callable(decode):
            raise ValueError("invalid prefix input")
        if type(trajectory_id) is not str or not trajectory_id or len(trajectory_id) > 200:
            raise ValueError("trajectory identity required")
        text = decode(list(generated))
        prompt_tail = decode(list(prompt[-48:]))
        if type(text) is not str or type(prompt_tail) is not str:
            raise ValueError("decoder must return text")
        starts_thinking = prompt_tail.rstrip().endswith("<think>") or text.lstrip().startswith("<think>")
        if not starts_thinking and ("</think>" in text or "<think>" in text):
            raise ValueError("thinking marker lacks a source-bound opener")
        if text.count("</think>") > 1 or text.count("<think>") > int(text.lstrip().startswith("<think>")):
            raise ValueError("unsupported thinking boundaries")
        for marker in ("<|im_end|>", "<|endoftext|>"):
            if marker in text and text.split(marker, 1)[1].strip():
                raise ValueError("content after generation terminator")
        return cls(prompt, generated, text, "thinking" if starts_thinking else "final",
                   _sha(tokenizer_sha256), trajectory_id, _sha(question_sha256), digest(prompt + generated),
                   decode, {0: "", len(generated): text})

    @classmethod
    def from_record(cls, record, cutoff, decode, *, tokenizer_sha256, trajectory_id=None):
        """Offline replay helper for a recorded step boundary or its complete endpoint."""
        prompt = _tokens(record["prompt_ids"])
        generated = _tokens(record["generated_ids"])
        if digest(prompt) != record["prompt_sha256"] or digest(generated) != record["generated_sha256"]:
            raise ValueError("raw record token hash mismatch")
        if type(cutoff) is not int or not 0 <= cutoff <= len(generated):
            raise ValueError("cutoff outside recorded generation")
        approved = {0, *(step["end"] for step in record.get("steps", ()))}
        if record.get("status") == "COMPLETE":
            approved.add(len(generated))
        if cutoff not in approved:
            raise ValueError("cutoff is not a recorded observation boundary")
        if trajectory_id is None:
            trajectory_id = f"{record['case_id']}:{record['seed']}"
        return cls.from_tokens(generated[:cutoff], decode, prompt_ids=prompt, tokenizer_sha256=tokenizer_sha256,
                               trajectory_id=trajectory_id, question_sha256=record["question_hash"])

    @classmethod
    def from_frozen_record(cls, raw, expected_sha256, cutoff, decode, *, tokenizer_sha256, trajectory_id=None):
        if type(raw) is not bytes or sha256(raw).hexdigest() != _sha(expected_sha256):
            raise ValueError("record differs from the frozen source bytes")
        return cls.from_record(json.loads(raw), cutoff, decode, tokenizer_sha256=tokenizer_sha256,
                               trajectory_id=trajectory_id)

    @property
    def observed_count(self):
        return len(self.generated_ids)

    @property
    def prefix_sha256(self):
        return self.observed_prefix_sha256

    def at(self, cutoff):
        self.digest_at(cutoff)
        return self.from_tokens(self.generated_ids[:cutoff], self._decode, prompt_ids=self.prompt_ids,
                                tokenizer_sha256=self.tokenizer_sha256, trajectory_id=self.trajectory_id,
                                question_sha256=self.question_sha256)

    def digest_at(self, cutoff):
        if type(cutoff) is not int or not 0 <= cutoff <= self.observed_count:
            raise ValueError("future cutoff")
        return digest(self.prompt_ids + self.generated_ids[:cutoff])

    def _prefix_text(self, end):
        if end not in self._cache:
            if len(self._cache) >= _MAX_CACHED_PREFIXES:
                oldest = next(key for key in self._cache if key not in (0, self.observed_count))
                del self._cache[oldest]
            self._cache[end] = self._decode(list(self.generated_ids[:end]))
        return self._cache[end]

    def segment(self, start, end):
        if not 0 <= start < end <= len(self.text):
            raise ValueError("source span exceeds observed text")
        if self.initial_segment == "final":
            return "final"
        close = self.text.find("</think>")
        if close < 0 or end <= close:
            return "thinking"
        if start >= close + len("</think>"):
            return "final"
        raise ValueError("source span crosses thinking boundary")

    def span(self, start, end):
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(self.text)
                or end - start > _MAX_SOURCE_CHARS):
            raise ValueError("invalid or future source span")
        self.segment(start, end)
        indices = range(self.observed_count + 1)
        left_guess = bisect_left(indices, start, key=lambda n: len(self._prefix_text(n)))
        right_guess = bisect_left(indices, end, key=lambda n: len(self._prefix_text(n)))
        # An incomplete UTF-8 character at a token edge can decode as U+FFFD.
        # Only accept exact prefix strings as covering boundaries.
        left = next((n for n in range(min(self.observed_count, left_guess + 6), max(-1, left_guess - 13), -1)
                     if len(self._prefix_text(n)) <= start and self.text.startswith(self._prefix_text(n))), None)
        right = next((n for n in range(max(0, right_guess - 6), min(self.observed_count, right_guess + 12) + 1)
                      if len(self._prefix_text(n)) >= end and self.text.startswith(self._prefix_text(n))), None)
        if left is None or right is None or left >= right:
            raise ValueError("no exact decoded token coverage")
        return SourceSpan((start, end), (left, right), digest(self.generated_ids[left:right]), self.text[start:end])


@dataclass(frozen=True)
class ArchiveCandidate:
    candidate_id: str
    goal_claim_type: str
    segment: str
    role: str
    contract_id: str
    target_id: str
    question_sha256: str
    trajectory_id: str
    tokenizer_sha256: str
    observed_count: int
    observed_prefix_sha256: str
    source_span: SourceSpan
    _field_spans: tuple[tuple[str, SourceSpan], ...]
    _payload: str
    lineage: tuple[str, ...]
    source_origin: str = "OBSERVED_CANDIDATE"

    @property
    def value(self):
        return json.loads(self._payload)["value"]

    @property
    def assignments(self):
        return json.loads(self._payload)["assignments"]

    @property
    def claim(self):
        return json.loads(self._payload)["claim"]

    @property
    def field_spans(self):
        return dict(self._field_spans)

    def as_dict(self):
        return {
            "candidate_id": self.candidate_id, "goal_claim_type": self.goal_claim_type, "segment": self.segment,
            "role": self.role, "contract_id": self.contract_id, "target_id": self.target_id,
            "question_sha256": self.question_sha256, "trajectory_id": self.trajectory_id,
            "tokenizer_sha256": self.tokenizer_sha256, "observed_count": self.observed_count,
            "observed_prefix_sha256": self.observed_prefix_sha256, "source_span": self.source_span.as_dict(),
            "field_spans": {name: span.as_dict() for name, span in self._field_spans},
            "lineage": list(self.lineage), "source_origin": self.source_origin, **json.loads(self._payload),
        }


def _observation_id(prefix, contract_id, target_id, kind, role, source, field_spans, payload, lineage):
    return "obs_" + digest({
        "trajectory_id": prefix.trajectory_id, "tokenizer_sha256": prefix.tokenizer_sha256,
        "question_sha256": prefix.question_sha256, "contract_id": contract_id, "target_id": target_id,
        "source_prefix_sha256": prefix.digest_at(source.token_span[1]),
        "kind": kind, "role": role, "source": source.as_dict(),
        "fields": {name: span.as_dict() for name, span in field_spans},
        "payload": payload, "lineage": list(lineage),
    })


def _number_matches(value, surface, *, digit_list=False):
    if not digit_list and re.search(r"\d\s+\d|[+-]\s+\d", surface):
        return False
    raw = re.sub(r"\s+", "", surface).replace("−", "-")
    if len(raw) > 120:
        return False
    if digit_list:
        if not re.fullmatch(r"[1-9](?:,\d){2,15}", raw):
            return False
        raw = raw.replace(",", "")
    tex = re.fullmatch(r"([+-]?)\\(?:dfrac|tfrac|frac)\{([+-]?\d+)\}\{([+-]?\d+)\}", raw)
    try:
        if tex:
            exact = Fraction((-1 if tex[1] == "-" else 1) * int(tex[2]), int(tex[3]))
        elif re.fullmatch(r"[+-]?\d+/[+-]?\d+", raw):
            a, b = raw.split("/")
            exact = Fraction(int(a), int(b))
        elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
            exact = Fraction(raw)
        else:
            return False
    except (ValueError, ZeroDivisionError):
        return False
    if exact.denominator == 1:
        return type(value) is int and value == exact.numerator
    return (type(value) is dict and set(value) == {"op", "num", "den"} and value["op"] == "rat"
            and type(value["num"]) is int and type(value["den"]) is int
            and value["num"] == exact.numerator and value["den"] == exact.denominator)


def _check_payload(kind, role, value, assignments, claim, spans):
    if role == "observed_pair_trial":
        if (kind != "FEASIBLE_CANDIDATE" or type(value) is not dict or set(value) != {"pair"}
                or type(value["pair"]) is not list or len(value["pair"]) != 2
                or any(name not in spans or not _number_matches(member, spans[name].text)
                       for name, member in zip(("first", "second"), value["pair"], strict=True))):
            raise ValueError("pair witness does not match its two source fields")
    elif role == "observed_greedy_point_trial":
        if (kind != "FEASIBLE_CANDIDATE" or type(value) is not dict or set(value) != {"n"}
                or "n" not in spans or not _number_matches(value["n"], spans["n"].text)):
            raise ValueError("greedy point does not match its source field")
    elif value is not None and ("value" not in spans or not _number_matches(
            value, spans["value"].text, digit_list=role == "constructed_digit_candidate")):
        raise ValueError("candidate value does not match the exact observed field")
    if set(assignments) - {"a1", "b1", "d", "r", "p"} or any(
            name not in spans or not _number_matches(value, spans[name].text)
            for name, value in assignments.items()):
        raise ValueError("assignment does not match an exact observed field")
    if kind in {"EXACT_ANSWER", "FEASIBLE_CANDIDATE"}:
        if value is None or claim:
            raise ValueError("unsupported candidate payload")
        return
    if kind == "MAXIMALITY_CLAIM":
        if type(value) is not int or claim != {"kind": "MAX", "value": value}:
            raise ValueError("maximum is not bound to the observed value")
        return
    if kind == "MINIMALITY_CLAIM":
        if (type(value) is not int or set(assignments) != {"p"}
                or claim != {"kind": "MIN", "value": value, "p": assignments["p"]}):
            raise ValueError("minimum is not bound to the observed value and prime")
        return
    if kind == "FINAL_ANSWER_REVISION":
        if value is None or set(claim) != {"prior_candidate_id", "later_candidate_id"} or any(
                type(item) is not str or not item.startswith("obs_") for item in claim.values()):
            raise ValueError("unsupported revision payload")
        return
    predicate_kind = claim.get("kind")
    if type(predicate_kind) is not str:
        raise ValueError("predicate type required")
    expected = {
        "ALL_REMOVED_PAIR_LCM_FAILS_BOTH": {"kind", "lower", "upper"},
        "GREEDY_RESIDUE_CLASS": {"kind", "lower", "upper", "modulus", "residues", "relation"},
        "COMPLETE_SOLUTIONS": {"kind", "values"},
    }.get(predicate_kind)
    if expected is None or value is not None or assignments:
        raise ValueError("unsupported predicate")
    if claim["kind"] == "COMPLETE_SOLUTIONS" and "modulus" in claim:
        expected = expected | {"modulus"}
    if set(claim) != expected or (kind == "COMPLETE_SOLUTIONS_CLAIM") != (claim["kind"] == "COMPLETE_SOLUTIONS"):
        raise ValueError("unexpected predicate fields")
    for name in {"lower", "upper", "modulus"} & expected:
        field_text = spans[name].text if name in spans else ""
        square = re.fullmatch(r"(\d{1,24})(?:²|\^2)", field_text) if name == "modulus" else None
        observed = int(square[1]) ** 2 == claim[name] if square else _number_matches(claim[name], field_text)
        if type(claim[name]) is not int or not observed:
            raise ValueError("unbound predicate endpoint")
    for name, field_name in (("values", "solutions"), ("residues", "residues")):
        if name in expected:
            if field_name not in spans or type(claim[name]) is not list or any(type(x) is not int for x in claim[name]):
                raise ValueError("unbound predicate members")
            exact = [int(x.replace("−", "-")) for x in re.findall(r"[+\-−]?\d+", spans[field_name].text)]
            if not exact or claim[name] != exact:
                raise ValueError("unbound predicate members")
    if "relation" in expected and (
            "relation" not in spans or claim["relation"] != "IFF"
            or " ".join(spans["relation"].text.casefold().split()) not in
            {"if and only if", "otherwise, it's not.", "otherwise, it is not."}):
        raise ValueError("unbound classification direction")


def observe(prefix, *, contract_id, target_id, goal_claim_type, role, source, fields=None,
            value=None, assignments=None, claim=None, lineage=()):
    """Create a lexical observation. This function issues no verifier verdict."""
    if (not isinstance(prefix, ObservedPrefix) or goal_claim_type not in _CLAIM_TYPES
            or not all(type(s) is str and s for s in (contract_id, target_id, role))):
        raise ValueError("unsupported observation")
    bound = prefix.span(*source)
    spans = tuple((name, prefix.span(*location)) for name, location in sorted((fields or {}).items()))
    segment = prefix.segment(*source)
    if any(prefix.segment(*span.char_span) != segment or span.char_span[1] > source[1] for _, span in spans):
        raise ValueError("evidence must precede claim end in the same observed segment")
    assignments = {} if assignments is None else assignments
    claim = {} if claim is None else claim
    if type(assignments) is not dict or type(claim) is not dict:
        raise ValueError("structured observation payload required")
    _check_payload(goal_claim_type, role, value, assignments, claim, dict(spans))
    if not all(type(item) is str and item.startswith("obs_") for item in lineage):
        raise ValueError("invalid observation lineage")
    payload = canonical_json({"value": value, "assignments": assignments, "claim": claim})
    identifier = _observation_id(prefix, contract_id, target_id, goal_claim_type, role, bound, spans, payload, lineage)
    return ArchiveCandidate(identifier, goal_claim_type, segment, role, contract_id, target_id,
                            prefix.question_sha256, prefix.trajectory_id, prefix.tokenizer_sha256,
                            prefix.observed_count, prefix.observed_prefix_sha256, bound, spans,
                            payload, tuple(lineage))


class CandidateArchive:
    """Observations are retained even when later statements revise the answer."""

    def __init__(self, contract_id, target_id, question_sha256):
        self.contract_id = contract_id
        self.target_id = target_id
        self.question_sha256 = _sha(question_sha256)
        self._observations = {}

    def _check(self, candidate, prefix):
        if (not isinstance(candidate, ArchiveCandidate) or candidate.source_origin != "OBSERVED_CANDIDATE"
                or candidate.contract_id != self.contract_id or candidate.target_id != self.target_id
                or candidate.question_sha256 != self.question_sha256 or prefix.question_sha256 != self.question_sha256
                or candidate.trajectory_id != prefix.trajectory_id or candidate.tokenizer_sha256 != prefix.tokenizer_sha256
                or candidate.observed_prefix_sha256 != prefix.digest_at(candidate.observed_count)):
            raise ValueError("observation is from a different source, target, or future")
        last_observed = candidate.observed_count
        if candidate.source_span.token_span[1] > last_observed or any(
                span.token_span[1] > last_observed for _, span in candidate._field_spans):
            raise ValueError("observation contains future token evidence")
        rebuilt = observe(prefix, contract_id=self.contract_id, target_id=self.target_id,
                          goal_claim_type=candidate.goal_claim_type, role=candidate.role,
                          source=candidate.source_span.char_span,
                          fields={name: span.char_span for name, span in candidate._field_spans},
                          value=candidate.value, assignments=candidate.assignments, claim=candidate.claim,
                          lineage=candidate.lineage)
        if (rebuilt.candidate_id != candidate.candidate_id or rebuilt.segment != candidate.segment
                or rebuilt.source_span != candidate.source_span or rebuilt._field_spans != candidate._field_spans):
            raise ValueError("observation source replay disagrees")
        return candidate

    def admit(self, candidate, prefix):
        checked = self._check(candidate, prefix)
        for prior_id in checked.lineage:
            prior = self.validated(prior_id, prefix)
            if prior.source_span.char_span[1] > checked.source_span.char_span[0]:
                raise ValueError("lineage is not prior source evidence")
        if checked.goal_claim_type == "FINAL_ANSWER_REVISION":
            old_id, new_id = checked.claim["prior_candidate_id"], checked.claim["later_candidate_id"]
            if checked.lineage != (old_id,):
                raise ValueError("revision lineage is inconsistent")
            old, new = self.validated(old_id, prefix), self.validated(new_id, prefix)
            if (old.goal_claim_type != "EXACT_ANSWER" or new.goal_claim_type != "EXACT_ANSWER"
                    or old.segment != "thinking" or checked.segment != "final" or new.segment != "final"
                    or old.value == new.value or new.value != checked.value or new.source_span != checked.source_span):
                raise ValueError("revision does not link distinct thinking and final values")
        return self._observations.setdefault(checked.candidate_id, checked)

    def validated(self, candidate_id, prefix):
        """Replay source lineage under the supplied observed prefix before use."""
        if candidate_id not in self._observations:
            raise ValueError("unknown observation")
        return self._check(self._observations[candidate_id], prefix)

    def observations(self):
        return tuple(self._observations.values())
