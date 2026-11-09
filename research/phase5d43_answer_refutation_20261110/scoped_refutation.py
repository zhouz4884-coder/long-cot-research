"""Bounded refutation of explicit integer candidates under reviewed necessary predicates.

The caller must independently approve prerequisite digests for this question.
The checker authenticates their exact use, not the mathematics of the review.
Neither a non-refutation nor a rejected request establishes a correct answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from threading import Lock
from time import thread_time_ns


CHECKER_ID = "d43.scoped-refutation.finite-integer"
CHECKER_VERSION = 1
PREDICATE_BUDGET = 2
MAX_CANDIDATES = 8
MAX_EXCLUSIONS = 16
MAX_ABS_INTEGER = (1 << 63) - 1
CONGRUENCE = "CONGRUENCE"
CLOSED_INTERVAL = "CLOSED_INTERVAL"
FINITE_EXCLUSIONS = "FINITE_EXCLUSIONS"
EXPLICIT_QUESTION = "EXPLICIT_QUESTION"
REVIEWED_NECESSARY_DERIVATION = "REVIEWED_NECESSARY_DERIVATION"


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _label(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is not None


def _integer(value):
    return type(value) is int and -MAX_ABS_INTEGER <= value <= MAX_ABS_INTEGER


@dataclass(frozen=True)
class ObjectiveBinding:
    question_sha256: str
    objective_id: str
    scope: str


@dataclass(frozen=True)
class NecessaryPredicate:
    """Canonical parameters are (modulus, residue), (low, high), or sorted excluded values."""

    kind: str
    args: tuple[int, ...]


def _binding_valid(binding):
    return (type(binding) is ObjectiveBinding and _sha(binding.question_sha256)
            and _label(binding.objective_id) and _label(binding.scope))


def _predicate_valid(predicate):
    if (type(predicate) is not NecessaryPredicate or type(predicate.kind) is not str
            or type(predicate.args) is not tuple or not 1 <= len(predicate.args) <= MAX_EXCLUSIONS
            or not all(_integer(x) for x in predicate.args)):
        return False
    args = predicate.args
    if predicate.kind == CONGRUENCE:
        return len(args) == 2 and args[0] >= 2 and 0 <= args[1] < args[0]
    if predicate.kind == CLOSED_INTERVAL:
        return len(args) == 2 and args[0] <= args[1]
    if predicate.kind == FINITE_EXCLUSIONS:
        return all(a < b for a, b in zip(args, args[1:]))
    return False


def application_signature(binding, predicate):
    """Bind the full typed objective, argument order and checker semantics for review."""
    if not _binding_valid(binding) or not _predicate_valid(predicate):
        raise ValueError("Application signature requires a valid integer target and predicate")
    return _digest({"checker_id": CHECKER_ID, "checker_version": CHECKER_VERSION,
                    "argument_type": "bounded_exact_integer", "max_abs_integer": MAX_ABS_INTEGER,
                    "binding": asdict(binding), "predicate": asdict(predicate)})


@dataclass(frozen=True)
class ReviewedPrerequisite:
    binding: ObjectiveBinding
    predicate: NecessaryPredicate
    source_kind: str
    source_sha256: str
    review_sha256: str
    application_sha256: str

    @property
    def sha256(self):
        return _digest(asdict(self))


def _provenance_valid(prerequisite):
    return (type(prerequisite.source_kind) is str
            and prerequisite.source_kind in (EXPLICIT_QUESTION, REVIEWED_NECESSARY_DERIVATION)
            and _sha(prerequisite.source_sha256) and _sha(prerequisite.review_sha256)
            and _sha(prerequisite.application_sha256)
            and (prerequisite.source_kind != EXPLICIT_QUESTION
                 or prerequisite.source_sha256 == prerequisite.binding.question_sha256))


@dataclass(frozen=True)
class RefutationReceipt:
    status: str
    candidate: int
    prerequisite: ReviewedPrerequisite
    prerequisite_sha256: str
    predicate_call: int
    candidate_index: int
    primitive_numeric_operations: int
    evaluation_cpu_ns: int
    arithmetic: tuple[tuple[str, int | bool], ...]

    def _payload(self):
        return {**asdict(self), "checker_id": CHECKER_ID, "checker_version": CHECKER_VERSION,
                "authority": "REJECT_THIS_VALUE_ONLY" if self.status == "REFUTED" else "NONE"}

    @property
    def sha256(self):
        return _digest(self._payload())

    def as_dict(self):
        return {**self._payload(), "receipt_sha256": self.sha256,
                "certificate_sha256": self.sha256 if self.status == "REFUTED" else None}


@dataclass(frozen=True)
class BatchReceipt:
    status: str
    reason: str
    question_sha256: str
    requested_binding: ObjectiveBinding | None
    candidates: tuple[int, ...]
    prerequisite_sha256: str | None
    application_sha256: str | None
    request_number: int
    paid_predicate_calls: int
    paid_candidate_evaluations: int
    primitive_numeric_operations: int
    request_cpu_ns: int
    receipts: tuple[RefutationReceipt, ...]

    def as_dict(self):
        data = {**asdict(self), "checker_id": CHECKER_ID, "checker_version": CHECKER_VERSION,
                "receipts": [row.as_dict() for row in self.receipts]}
        return {**data, "batch_receipt_sha256": _digest(data)}


def _evaluate(value, predicate):
    if predicate.kind == CONGRUENCE:
        modulus, expected = predicate.args
        observed = value % modulus
        satisfies = observed == expected
        return satisfies, 2, (("modulus", modulus), ("expected_residue", expected), ("observed_residue", observed))
    if predicate.kind == CLOSED_INTERVAL:
        lower, upper = predicate.args
        below, above = value < lower, value > upper
        return not (below or above), 2, (("lower", lower), ("upper", upper), ("below", below), ("above", above))
    # Count every numeric comparison; the reviewed finite set is never a solver.
    matched = False
    for excluded in predicate.args:
        equal = value == excluded
        matched = matched or equal
    return not matched, len(predicate.args), (("excluded_values_checked", len(predicate.args)), ("matched", matched))


class ScopedRefutationState:
    """One question/session, two new predicate applications, no per-candidate reset.

    Candidate occurrence selection (at most four final and four eligible thought
    occurrences) precedes this numeric checker. It receives up to eight distinct
    values. One admitted batch pays one predicate call and one arithmetic evaluation
    per value. Same application signature, including a different value subset or
    a newly authored review record for it, is not reevaluated. Zero-work requests
    still record CPU through validation; timings exclude receipt hashing/accounting.
    """

    def __init__(self, question_sha256, approved_prerequisite_sha256):
        if not _sha(question_sha256):
            raise ValueError("Question SHA-256 is malformed")
        approved = frozenset(approved_prerequisite_sha256)
        if len(approved) > PREDICATE_BUDGET or not all(_sha(x) for x in approved):
            raise ValueError("At most two exact approved prerequisite digests are allowed")
        self.question_sha256 = question_sha256
        self._approved = approved
        self._applications = set()
        self._issued = []
        self._lock = Lock()
        self._requests = self._candidate_evaluations = self._operations = 0
        self._request_cpu_ns = self._evaluation_cpu_ns = 0

    def _finish(self, began, status, reason, binding, values, prerequisite_sha=None, application=None, rows=()):
        used = int(bool(rows))
        operations = sum(row.primitive_numeric_operations for row in rows)
        evaluation_ns = sum(row.evaluation_cpu_ns for row in rows)
        request_ns = thread_time_ns() - began
        self._request_cpu_ns += request_ns
        self._candidate_evaluations += len(rows)
        self._operations += operations
        self._evaluation_cpu_ns += evaluation_ns
        result = BatchReceipt(status, reason, self.question_sha256, binding, values, prerequisite_sha, application,
                              self._requests, used, len(rows), operations, request_ns, rows)
        self._issued.extend(rows)
        return result

    def check_candidates(self, binding, candidates, prerequisite):
        began = thread_time_ns()
        with self._lock:
            self._requests += 1
            expected = binding if _binding_valid(binding) else None
            snapshot = tuple(candidates[:MAX_CANDIDATES + 1]) if type(candidates) in (list, tuple) else ()
            values = snapshot if 1 <= len(snapshot) <= MAX_CANDIDATES and all(_integer(x) for x in snapshot) else ()
            if not values or len(set(values)) != len(values):
                return self._finish(began, "UNKNOWN", "requires_one_to_eight_distinct_integer_values", expected, values)
            if expected is None or expected.question_sha256 != self.question_sha256:
                return self._finish(began, "UNKNOWN", "wrong_question_or_invalid_objective", expected, values)
            if (type(prerequisite) is not ReviewedPrerequisite or not _binding_valid(prerequisite.binding)
                    or prerequisite.binding != expected or not _predicate_valid(prerequisite.predicate)
                    or not _provenance_valid(prerequisite)):
                return self._finish(began, "UNKNOWN", "invalid_or_cross_scope_prerequisite", expected, values)
            signature = application_signature(expected, prerequisite.predicate)
            prerequisite_sha = prerequisite.sha256
            if prerequisite.application_sha256 != signature or prerequisite_sha not in self._approved:
                return self._finish(began, "UNKNOWN", "unapproved_review_or_application_signature", expected, values,
                                    prerequisite_sha, signature)
            if signature in self._applications:
                return self._finish(began, "UNKNOWN", "duplicate_predicate_application", expected, values,
                                    prerequisite_sha, signature)
            if len(self._applications) >= PREDICATE_BUDGET:
                return self._finish(began, "UNKNOWN", "shared_predicate_budget_exhausted", expected, values,
                                    prerequisite_sha, signature)
            self._applications.add(signature)
            call = len(self._applications)
            rows = []
            for index, candidate in enumerate(values, 1):
                start_eval = thread_time_ns()
                satisfies, operations, math = _evaluate(candidate, prerequisite.predicate)
                cpu_ns = thread_time_ns() - start_eval
                rows.append(RefutationReceipt("NOT_REFUTED" if satisfies else "REFUTED", candidate, prerequisite,
                                              prerequisite_sha, call, index, operations, cpu_ns, math))
            return self._finish(began, "EVALUATED", "checked_reviewed_necessary_predicate", expected, values,
                                prerequisite_sha, signature, tuple(rows))

    def authorizes_refutation(self, binding, candidate, receipt):
        """Require the actual state-issued receipt; serialized copies are evidence only."""
        if (type(receipt) is not RefutationReceipt or receipt.status != "REFUTED" or not _binding_valid(binding)
                or not _integer(candidate) or candidate != receipt.candidate
                or type(receipt.prerequisite) is not ReviewedPrerequisite or receipt.prerequisite.binding != binding):
            return False
        with self._lock:
            return any(row is receipt for row in self._issued)

    def report(self):
        with self._lock:
            return {"question_sha256": self.question_sha256, "checker_id": CHECKER_ID, "checker_version": CHECKER_VERSION,
                    "predicate_budget": PREDICATE_BUDGET, "paid_predicate_calls": len(self._applications),
                    "paid_candidate_evaluations": self._candidate_evaluations, "primitive_numeric_operations": self._operations,
                    "requests": self._requests, "request_cpu_ns": self._request_cpu_ns, "evaluation_cpu_ns": self._evaluation_cpu_ns}
