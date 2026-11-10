"""Verify one reviewed and source-bound point under its original question constraints."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
from threading import Lock
from time import perf_counter_ns, thread_time_ns


VERIFIER_ID = "d46.reviewed-point-verifier"
VERIFIER_VERSION = 1
ASSERTED_ORIGINAL_CANDIDATE = "ASSERTED_ORIGINAL_CANDIDATE"
PROVEN_INFEASIBLE = "PROVEN_INFEASIBLE"
PROVEN_FEASIBLE = "PROVEN_FEASIBLE"
UNKNOWN = "UNKNOWN"
EXACT_NECESSARY_PREDICATE = "EXACT_NECESSARY_PREDICATE"
COMPLETE_FIXED_VALUE_FIBER = "COMPLETE_FIXED_VALUE_FIBER"
EXACT_CONTRADICTION = "EXACT_CONTRADICTION"
EXACT_FEASIBILITY_WITNESS = "EXACT_FEASIBILITY_WITNESS"
EXCLUSIONS = (EXACT_NECESSARY_PREDICATE, COMPLETE_FIXED_VALUE_FIBER, EXACT_CONTRADICTION)
MAX_ABS_INTEGER = (1 << 63) - 1
MAX_PREFIX_CHARACTERS = 500_000
MAX_ASSERTION_CHARACTERS = 4096
MAX_NUMERIC_CHARACTERS = 256
MAX_CONSTRAINTS = 32
MAX_DETAILS = 16
CONTROL_MARKERS = ("<think>", "</think>", "<|im_start|>", "<|im_end|>", "<|endoftext|>")
SIGNED_INTEGER = r"[+-]?[0-9]{1,24}"
PLAIN = re.compile(rf"({SIGNED_INTEGER})\s*/\s*({SIGNED_INTEGER})")
DECIMAL = re.compile(rf"{SIGNED_INTEGER}(?:\.[0-9]{{1,24}})?")
TEX = re.compile(rf"([+-]?)\\(?:frac|dfrac|tfrac)\s*"
                 rf"\{{\s*({SIGNED_INTEGER})\s*\}}\s*\{{\s*({SIGNED_INTEGER})\s*\}}")
WRAP = re.compile(r"\\(?:text|mathrm|mathbf|mathit|mbox)\s*\{(.*)\}", re.S)


def _digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(data.encode()).hexdigest()


def _sha(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _label(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", value) is not None


def _bounded_text(value, limit):
    return (type(value) is str and 0 < len(value) <= limit
            and all(not 0xD800 <= ord(char) <= 0xDFFF for char in value))


def _integer(value):
    return type(value) is int and abs(value) <= MAX_ABS_INTEGER


def exact_literal(text):
    """Normalize the archived numeric lexeme to a finite exact rational."""
    if type(text) is not str or not 1 <= len(text) <= MAX_NUMERIC_CHARACTERS:
        return None
    text = text.strip().replace("−", "-")
    for _ in range(6):
        wrapper = WRAP.fullmatch(text)
        if wrapper:
            text = wrapper[1].strip()
        elif text.startswith("$") and text.endswith("$") and len(text) > 2:
            text = text[1:-1].strip()
        elif (text[:2], text[-2:]) in {(r"\(", r"\)"), (r"\[", r"\]")}:
            text = text[2:-2].strip()
        else:
            break
    try:
        tex = TEX.fullmatch(text)
        plain = PLAIN.fullmatch(text)
        if tex:
            value = Fraction((-1 if tex[1] == "-" else 1) * int(tex[2]), int(tex[3]))
        elif plain:
            value = Fraction(int(plain[1]), int(plain[2]))
        elif DECIMAL.fullmatch(text):
            value = Fraction(text)
        else:
            return None
    except ZeroDivisionError:
        return None
    return value if _integer(value.numerator) and _integer(value.denominator) else None


@dataclass(frozen=True)
class ObjectiveBinding:
    question_sha256: str
    objective_id: str
    scope_sha256: str
    constraints_sha256: str
    direction: str


@dataclass(frozen=True)
class ReviewedPointContract:
    binding: ObjectiveBinding
    required_constraints: tuple[str, ...]
    checker_id: str
    checker_version: int
    checker_entrypoint: str
    checker_source_sha256: str
    exclusion_kind: str
    proof_sha256: str
    review_sha256: str

    @property
    def sha256(self):
        return _digest({"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION, **asdict(self)})


@dataclass(frozen=True)
class CandidateReceipt:
    """The independent issuer supplies role evidence and approves this exact digest."""

    binding: ObjectiveBinding
    sample_id: str
    response_sha256: str
    observed_prefix_sha256: str
    numeric_span: tuple[int, int]
    numeric_text: str
    assertion_span: tuple[int, int]
    assertion_sha256: str
    assertion_role: str
    assertion_review_sha256: str

    @property
    def sha256(self):
        return _digest(asdict(self))


@dataclass(frozen=True)
class PointEvidence:
    """Typed evidence from the reviewed checker for one exact scalar."""

    status: str
    proof_kind: str | None = None
    details: tuple[tuple[str, int | str | bool], ...] = ()
    complete: bool = False
    covered_constraints: tuple[str, ...] = ()
    fiber_expected: int | None = None
    fiber_visited: int | None = None


def _valid_binding(binding):
    return (type(binding) is ObjectiveBinding
            and all(_sha(x) for x in (binding.question_sha256, binding.scope_sha256, binding.constraints_sha256))
            and _label(binding.objective_id) and type(binding.direction) is str
            and binding.direction in ("MAX", "MIN", "VALUE"))


def _labels(names):
    return (type(names) is tuple and len(names) <= MAX_CONSTRAINTS
            and all(_label(x) and len(x) <= 80 for x in names) and len(set(names)) == len(names))


def _valid_contract(contract):
    return (type(contract) is ReviewedPointContract and _valid_binding(contract.binding)
            and _labels(contract.required_constraints) and bool(contract.required_constraints)
            and _label(contract.checker_id) and _label(contract.checker_entrypoint)
            and _integer(contract.checker_version) and contract.checker_version > 0
            and all(_sha(x) for x in (contract.checker_source_sha256, contract.proof_sha256, contract.review_sha256))
            and type(contract.exclusion_kind) is str and contract.exclusion_kind in EXCLUSIONS)


def _span(value, limit):
    return (type(value) is tuple and len(value) == 2 and all(type(x) is int for x in value)
            and 0 <= value[0] < value[1] <= limit)


def _valid_candidate(candidate):
    return (type(candidate) is CandidateReceipt and _valid_binding(candidate.binding)
            and _label(candidate.sample_id) and _bounded_text(candidate.numeric_text, MAX_NUMERIC_CHARACTERS)
            and all(_sha(x) for x in (candidate.response_sha256, candidate.observed_prefix_sha256,
                                     candidate.assertion_sha256, candidate.assertion_review_sha256))
            and type(candidate.assertion_role) is str
            and _span(candidate.numeric_span, MAX_PREFIX_CHARACTERS)
            and _span(candidate.assertion_span, MAX_PREFIX_CHARACTERS)
            and candidate.assertion_span[0] <= candidate.numeric_span[0]
            and candidate.numeric_span[1] <= candidate.assertion_span[1]
            and candidate.assertion_span[1] - candidate.assertion_span[0] <= MAX_ASSERTION_CHARACTERS)


def checker_source_sha256(checker):
    """Hash a reviewed module and require a named entrypoint with no captured parameters."""
    if (not inspect.isfunction(checker) or checker.__qualname__ != checker.__name__ or checker.__closure__ is not None
            or checker.__defaults__ is not None or checker.__kwdefaults__ is not None):
        raise ValueError("Expected a named module-level point checker")
    path = inspect.getsourcefile(checker)
    if path is None:
        raise ValueError("Checker has no reviewed source file")
    return sha256(Path(path).read_bytes()).hexdigest()


class _BudgetExhausted(Exception):
    pass


class WorkMeter:
    """The independently reviewed code charges each named operation before doing it."""

    def __init__(self, limit):
        self._limit = limit
        self._charges = {}
        self._spent = 0
        self._denied = None

    def charge(self, label, count=1):
        if not _label(label) or not _integer(count) or count <= 0:
            raise ValueError("Expected a bounded positive count and named operation")
        if self._denied is not None:
            raise _BudgetExhausted()
        if count > self._limit - self._spent:
            self._denied = (label, count)
            raise _BudgetExhausted()
        self._charges[label] = self._charges.get(label, 0) + count
        self._spent += count


def _valid_evidence(result, contract):
    if (type(result) is not PointEvidence or type(result.status) is not str
            or result.status not in (PROVEN_FEASIBLE, PROVEN_INFEASIBLE, UNKNOWN)
            or (result.proof_kind is not None and not _label(result.proof_kind))
            or type(result.complete) is not bool
            or not _labels(result.covered_constraints)
            or not set(result.covered_constraints).issubset(contract.required_constraints)
            or type(result.details) is not tuple or len(result.details) > MAX_DETAILS
            or not all(v is None or _integer(v) and v >= 0 for v in (result.fiber_expected, result.fiber_visited))):
        return False
    keys = set()
    for pair in result.details:
        if type(pair) is not tuple or len(pair) != 2:
            return False
        key, value = pair
        if (not _label(key) or key in keys or
                not (_integer(value) or type(value) is bool or _bounded_text(value, 256))):
            return False
        keys.add(key)
    return True


def _verdict(result, contract, meter):
    if result.status == UNKNOWN:
        return UNKNOWN, "CHECKER_UNRESOLVED"
    if not result.complete or not result.details:
        return UNKNOWN, "INCOMPLETE_EXACT_EVIDENCE"
    if result.status == PROVEN_FEASIBLE:
        if (result.proof_kind != EXACT_FEASIBILITY_WITNESS or result.covered_constraints != contract.required_constraints
                or any(not meter._charges.get("constraint:" + name) for name in result.covered_constraints)):
            return UNKNOWN, "INCOMPLETE_OR_UNCHARGED_FEASIBILITY"
        return PROVEN_FEASIBLE, "EXACT_FEASIBILITY_ONLY"
    if result.proof_kind != contract.exclusion_kind or not meter._charges.get("exclusion_proof"):
        return UNKNOWN, "UNREVIEWED_OR_UNCHARGED_EXCLUSION"
    if result.proof_kind == COMPLETE_FIXED_VALUE_FIBER and (
            result.fiber_expected is None or result.fiber_expected != result.fiber_visited
            or meter._charges.get("fiber_points", 0) != result.fiber_visited):
        return UNKNOWN, "UNEXHAUSTED_FIXED_VALUE_FIBER"
    return PROVEN_INFEASIBLE, "COMPLETE_REVIEWED_POINT_EXCLUSION"


@dataclass(frozen=True)
class PointReceipt:
    status: str
    reason: str
    contract: ReviewedPointContract
    candidate: CandidateReceipt | None
    request_number: int
    checked_value: str | None
    checker_calls: int
    operation_charges: tuple[tuple[str, int], ...]
    denied_operation: tuple[str, int] | None
    evidence: PointEvidence | None
    cpu_ns: int
    wall_ns: int

    @property
    def authority(self):
        return {PROVEN_INFEASIBLE: "REJECT_THIS_VALUE_ONLY", PROVEN_FEASIBLE: "FEASIBILITY_ONLY"}.get(self.status, "NONE")

    @property
    def work(self):
        return sum(count for _, count in self.operation_charges)

    def as_dict(self):
        evidence_sha = None if self.evidence is None else _digest(asdict(self.evidence))
        data = {"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION, "contract_sha256": self.contract.sha256,
                "candidate_sha256": None if self.candidate is None else self.candidate.sha256,
                "evidence_sha256": evidence_sha, "authority": self.authority, "work": self.work, **asdict(self)}
        return {**data, "receipt_sha256": _digest(data)}


class PointVerifier:
    """Trusted checker and independently issued candidates for a single original scope."""

    def __init__(self, contract, approved_contract_sha256, checker, *, approved_candidate_sha256, call_budget, work_budget):
        if (not _valid_contract(contract) or not _sha(approved_contract_sha256)
                or contract.sha256 != approved_contract_sha256):
            raise ValueError("Expected an exact independently reviewed contract")
        if checker_source_sha256(checker) != contract.checker_source_sha256 or checker.__name__ != contract.checker_entrypoint:
            raise ValueError("Point checker implementation does not match the reviewed source")
        if type(approved_candidate_sha256) not in (tuple, list, frozenset) or not all(_sha(x) for x in approved_candidate_sha256):
            raise ValueError("Expected separately issued candidate digests")
        if any(not _integer(x) or x < 0 for x in (call_budget, work_budget)):
            raise ValueError("Expected bounded nonnegative budgets")
        self._contract = contract
        self._checker = checker
        self._approved = frozenset(approved_candidate_sha256)
        self._call_budget, self._work_budget = call_budget, work_budget
        self._calls = self._work = 0
        self._receipts = []
        self._authorized = {}
        self._lock = Lock()

    def check(self, candidate, observed_prefix):
        with self._lock:
            return self._check(candidate, observed_prefix)

    def _check(self, candidate, prefix):
        wall, cpu = perf_counter_ns(), thread_time_ns()
        meter = WorkMeter(self._work_budget - self._work)
        valid_candidate = None
        candidate_sha = None
        value = None
        calls = 0

        def finish(status, reason, evidence=None):
            receipt = PointReceipt(status, reason, self._contract, valid_candidate, len(self._receipts) + 1,
                                   None if value is None else str(value), calls, tuple(meter._charges.items()),
                                   meter._denied, evidence, thread_time_ns() - cpu, perf_counter_ns() - wall)
            self._receipts.append(receipt)
            self._work += receipt.work
            if status == PROVEN_INFEASIBLE:
                self._authorized[id(receipt)] = candidate_sha
            return receipt

        if not _valid_candidate(candidate):
            return finish(UNKNOWN, "MALFORMED_CANDIDATE_RECEIPT")
        valid_candidate = candidate
        if candidate.binding != self._contract.binding:
            return finish(UNKNOWN, "ORIGINAL_BINDING_MISMATCH")
        if candidate.assertion_role != ASSERTED_ORIGINAL_CANDIDATE:
            return finish(UNKNOWN, "ASSERTION_ROLE_MISMATCH")
        candidate_sha = candidate.sha256
        if candidate_sha not in self._approved:
            return finish(UNKNOWN, "CANDIDATE_NOT_ISSUED")
        if type(prefix) is not str or not 0 < len(prefix) <= MAX_PREFIX_CHARACTERS:
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        try:
            prefix_sha = sha256(prefix.encode()).hexdigest()
        except UnicodeEncodeError:
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        if prefix_sha != candidate.observed_prefix_sha256:
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        if any(marker in prefix for marker in CONTROL_MARKERS):
            return finish(UNKNOWN, "NOT_OPEN_THINKING_PREFIX")
        start, end = candidate.assertion_span
        nstart, nend = candidate.numeric_span
        if (end > len(prefix) or sha256(prefix[start:end].encode()).hexdigest() != candidate.assertion_sha256
                or prefix[nstart:nend] != candidate.numeric_text):
            return finish(UNKNOWN, "ASSERTION_OR_NUMERIC_SPAN_MISMATCH")
        value = exact_literal(candidate.numeric_text)
        if value is None:
            return finish(UNKNOWN, "NONEXACT_OR_OUT_OF_RANGE_NUMBER")
        if self._calls >= self._call_budget or self._work >= self._work_budget:
            return finish(UNKNOWN, "POINT_BUDGET_EXHAUSTED")
        self._calls += 1
        calls = 1
        try:
            result = self._checker(candidate.binding, value, meter)
        except _BudgetExhausted:
            return finish(UNKNOWN, "POINT_BUDGET_EXHAUSTED")
        except Exception:
            return finish(UNKNOWN, "CHECKER_ERROR")
        if meter._denied is not None:
            return finish(UNKNOWN, "POINT_BUDGET_EXHAUSTED")
        if not _valid_evidence(result, self._contract):
            return finish(UNKNOWN, "MALFORMED_POINT_EVIDENCE")
        status, reason = _verdict(result, self._contract, meter)
        return finish(status, reason, result)

    def authorizes_exclusion(self, candidate, receipt):
        """Check custody of this run's exact candidate/receipt pair."""
        with self._lock:
            return (_valid_candidate(candidate) and type(receipt) is PointReceipt
                    and self._authorized.get(id(receipt)) == candidate.sha256)

    def report(self):
        with self._lock:
            return {"contract_sha256": self._contract.sha256, "budgets": {"checker_calls": self._call_budget, "work": self._work_budget},
                    "used": {"checker_calls": self._calls, "work": self._work},
                    "receipts": [row.as_dict() for row in self._receipts]}
