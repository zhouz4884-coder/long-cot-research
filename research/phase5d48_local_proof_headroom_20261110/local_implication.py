"""Verify one fixed counterexample to an independently reviewed local implication."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Lock
from time import perf_counter_ns, thread_time_ns


VERIFIER_ID = "d48.reviewed-local-implication"
VERIFIER_VERSION = 1
VERIFIER_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
ASSERT_IMPLICATION = "ASSERT_IMPLICATION"
A_IMPLIES_B = "A_IMPLIES_B"
REFUTE_THIS_LOCAL_ASSERTION_ONLY = "REFUTE_THIS_LOCAL_ASSERTION_ONLY"
UNKNOWN = "UNKNOWN"
NO_COUNTEREXAMPLE = "NO_COUNTEREXAMPLE"
MAX_ABS_INTEGER = (1 << 63) - 1
MAX_RESULT_BITS = 256
MAX_PREFIX_CHARACTERS = 500_000
MAX_ASSERTION_CHARACTERS = 4096
MAX_VARIABLES = 12
MAX_PREDICATES = 24
MAX_EXPRESSION_DEPTH = 8
MAX_EXPONENT = 16
TERMS = ("ADD", "SUB", "MUL", "DIV", "MOD", "POW")
RELATIONS = ("EQ", "NE", "LT", "LE", "GT", "GE", "DIVIDES")
CONTROL_MARKERS = ("<think>", "</think>", "<|im_start|>", "<|im_end|>", "<|endoftext|>")


def _encode_fraction(value):
    if type(value) is Fraction:
        return {"numerator": value.numerator, "denominator": value.denominator}
    raise TypeError("Expected a reviewed exact arithmetic value")


def _json(value):
    return json.dumps(value, default=_encode_fraction, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _label(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value) is not None


def _number(value):
    if type(value) is int and abs(value) <= MAX_ABS_INTEGER:
        return Fraction(value)
    if type(value) is Fraction and abs(value.numerator) <= MAX_ABS_INTEGER and 1 <= value.denominator <= MAX_ABS_INTEGER:
        return value
    return None


@dataclass(frozen=True)
class ImplicationBinding:
    question_sha256: str
    objective_id: str
    scope_sha256: str
    direction: str


@dataclass(frozen=True)
class Variable:
    name: str
    domain: str


@dataclass(frozen=True)
class Predicate:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class ReviewedImplication:
    binding: ImplicationBinding
    variables: tuple[Variable, ...]
    domain_predicates: tuple[Predicate, ...]
    premises: tuple[Predicate, ...]
    consequent: Predicate
    fixed_witness: tuple[tuple[str, int | Fraction], ...]
    proof_sha256: str
    review_sha256: str

    @property
    def statement_sha256(self):
        return _digest({"binding": asdict(self.binding), "variables": [asdict(x) for x in self.variables],
                        "domain_predicates": [asdict(x) for x in self.domain_predicates], "arrow": A_IMPLIES_B,
                        "premises": [asdict(x) for x in self.premises], "consequent": asdict(self.consequent)})

    @property
    def sha256(self):
        return _digest({"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION,
                        "verifier_source_sha256": VERIFIER_SOURCE_SHA256,
                        "statement_sha256": self.statement_sha256, **asdict(self)})


@dataclass(frozen=True)
class AssertionReceipt:
    binding: ImplicationBinding
    implication_sha256: str
    sample_id: str
    response_sha256: str
    observed_prefix_sha256: str
    assertion_span: tuple[int, int]
    assertion_sha256: str
    issuer_sha256: str
    role: str = ASSERT_IMPLICATION
    arrow: str = A_IMPLIES_B

    @property
    def sha256(self):
        return _digest(asdict(self))


def _valid_binding(binding):
    return (type(binding) is ImplicationBinding and _sha(binding.question_sha256) and _sha(binding.scope_sha256)
            and _label(binding.objective_id) and type(binding.direction) is str
            and binding.direction in ("MIN", "MAX", "VALUE", "PROVE"))


def _valid_term(term, names, depth=0):
    if depth > MAX_EXPRESSION_DEPTH:
        return False
    if type(term) is str:
        return term in names
    if type(term) is tuple:
        return (len(term) == 3 and type(term[0]) is str and term[0] in TERMS
                and _valid_term(term[1], names, depth + 1) and _valid_term(term[2], names, depth + 1))
    return _number(term) is not None


def _valid_predicate(predicate, names):
    return (type(predicate) is Predicate and type(predicate.op) is str and predicate.op in RELATIONS
            and _valid_term(predicate.left, names) and _valid_term(predicate.right, names))


def _valid_contract(contract):
    if (type(contract) is not ReviewedImplication or not _valid_binding(contract.binding)
            or not _sha(contract.proof_sha256) or not _sha(contract.review_sha256)
            or type(contract.variables) is not tuple or not 1 <= len(contract.variables) <= MAX_VARIABLES
            or type(contract.domain_predicates) is not tuple or type(contract.premises) is not tuple
            or not contract.premises or len(contract.domain_predicates) + len(contract.premises) > MAX_PREDICATES
            or type(contract.fixed_witness) is not tuple or len(contract.fixed_witness) != len(contract.variables)):
        return False
    if any(type(v) is not Variable or not _label(v.name) or type(v.domain) is not str or v.domain not in ("INTEGER", "RATIONAL")
           for v in contract.variables):
        return False
    names = tuple(v.name for v in contract.variables)
    if len(set(names)) != len(names):
        return False
    for (name, item) in zip(names, contract.fixed_witness):
        if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or item[0] != name or _number(item[1]) is None:
            return False
    return all(_valid_predicate(atom, names) for atom in (*contract.domain_predicates, *contract.premises, contract.consequent))


def _valid_assertion(assertion):
    if (type(assertion) is not AssertionReceipt or not _valid_binding(assertion.binding)
            or not _label(assertion.sample_id) or not _label(assertion.role) or not _label(assertion.arrow)
            or not all(_sha(x) for x in (assertion.implication_sha256, assertion.response_sha256,
                                         assertion.observed_prefix_sha256, assertion.assertion_sha256, assertion.issuer_sha256))
            or type(assertion.assertion_span) is not tuple or len(assertion.assertion_span) != 2
            or not all(type(x) is int for x in assertion.assertion_span)):
        return False
    start, stop = assertion.assertion_span
    return 0 <= start < stop <= MAX_PREFIX_CHARACTERS and stop - start <= MAX_ASSERTION_CHARACTERS


class _Abstain(Exception):
    pass


class _Work:
    def __init__(self, limit, deadline):
        self.limit = limit
        self.deadline = deadline
        self.charges = {}
        self.spent = 0
        self.denied_operation = None

    def ensure_time(self):
        if perf_counter_ns() >= self.deadline:
            raise _Abstain("POINT_WALL_DEADLINE")

    def charge(self, operation):
        self.ensure_time()
        if self.spent >= self.limit:
            self.denied_operation = operation
            raise _Abstain("NAMED_WORK_BUDGET_EXHAUSTED")
        self.spent += 1
        self.charges[operation] = self.charges.get(operation, 0) + 1


def _bounded(value):
    if abs(value.numerator).bit_length() > MAX_RESULT_BITS or value.denominator.bit_length() > MAX_RESULT_BITS:
        raise _Abstain("ARITHMETIC_SIZE_BOUND")
    return value


def _term(node, witness, work):
    if type(node) is str:
        return witness[node]
    if type(node) is not tuple:
        return _number(node)
    op, left, right = node
    a, b = _term(left, witness, work), _term(right, witness, work)
    if op == "POW":
        work.charge("power_domain_check")
        if b.denominator != 1 or not 0 <= b.numerator <= MAX_EXPONENT or (a == 0 and b == 0):
            raise _Abstain("UNDEFINED_OR_UNSUPPORTED_POWER")
        result = Fraction(1)
        for _ in range(b.numerator):
            work.charge("exact_mul")
            result = _bounded(result * a)
        return result
    work.charge("exact_" + op.lower())
    if op == "ADD":
        return _bounded(a + b)
    if op == "SUB":
        return _bounded(a - b)
    if op == "MUL":
        return _bounded(a * b)
    if op == "DIV":
        if b == 0:
            raise _Abstain("UNDEFINED_DIVISION")
        return _bounded(a / b)
    if a.denominator != 1 or b.denominator != 1 or b <= 0:
        raise _Abstain("UNDEFINED_MODULO")
    return _bounded(Fraction(a.numerator % b.numerator))


def _predicate(predicate, witness, work):
    a, b = _term(predicate.left, witness, work), _term(predicate.right, witness, work)
    op = predicate.op
    if op == "DIVIDES":
        work.charge("exact_divisibility")
        if a.denominator != 1 or b.denominator != 1 or a == 0:
            raise _Abstain("UNDEFINED_DIVISIBILITY")
        return b.numerator % a.numerator == 0
    work.charge("exact_compare")
    if op == "EQ":
        return a == b
    if op == "NE":
        return a != b
    if op == "LT":
        return a < b
    if op == "LE":
        return a <= b
    if op == "GT":
        return a > b
    return a >= b


@dataclass(frozen=True)
class ImplicationCheckReceipt:
    status: str
    reason: str
    contract_sha256: str
    statement_sha256: str
    assertion: AssertionReceipt | None
    fixed_witness: tuple[tuple[str, str], ...]
    variable_checks: tuple[tuple[str, bool], ...]
    domain_checks: tuple[bool, ...]
    premise_checks: tuple[bool, ...]
    consequent: bool | None
    request_number: int
    checker_calls: int
    operation_charges: tuple[tuple[str, int], ...]
    denied_operation: str | None
    cpu_ns: int
    wall_ns: int

    @property
    def work(self):
        return sum(count for _, count in self.operation_charges)

    @property
    def authority(self):
        return REFUTE_THIS_LOCAL_ASSERTION_ONLY if self.status == REFUTE_THIS_LOCAL_ASSERTION_ONLY else "NONE"

    def as_dict(self):
        data = {"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION,
                "verifier_source_sha256": VERIFIER_SOURCE_SHA256,
                "assertion_receipt_sha256": None if self.assertion is None else self.assertion.sha256,
                "work": self.work, "authority": self.authority, **asdict(self)}
        return {**data, "receipt_sha256": _digest(data)}


class LocalImplicationVerifier:
    """Bounded exact replay of one independently reviewed statement and witness."""

    def __init__(self, contract, approved_contract_sha256, *, approved_assertion_sha256,
                 call_budget, work_budget, wall_budget_ns):
        if not _valid_contract(contract) or not _sha(approved_contract_sha256) or contract.sha256 != approved_contract_sha256:
            raise ValueError("Expected an independently approved exact implication and fixed witness")
        if (type(approved_assertion_sha256) not in (tuple, list, frozenset)
                or not all(_sha(x) for x in approved_assertion_sha256)):
            raise ValueError("Expected an independently issued assertion allowlist")
        if any(type(x) is not int or not 0 <= x <= MAX_ABS_INTEGER for x in (call_budget, work_budget, wall_budget_ns)):
            raise ValueError("Expected bounded nonnegative call, work and wall budgets")
        self._contract = contract
        self._contract_sha = approved_contract_sha256
        self._statement_sha = contract.statement_sha256
        self._approved = frozenset(approved_assertion_sha256)
        self._witness = {name: _number(value) for name, value in contract.fixed_witness}
        self._witness_wire = tuple((name, str(value)) for name, value in self._witness.items())
        self._call_budget, self._work_budget, self._wall_budget = call_budget, work_budget, wall_budget_ns
        self._calls = self._work = 0
        self._receipts = []
        self._authorized = {}
        self._lock = Lock()

    def check(self, assertion, observed_prefix):
        with self._lock:
            return self._check(assertion, observed_prefix)

    def _check(self, assertion, prefix):
        wall, cpu = perf_counter_ns(), thread_time_ns()
        meter = _Work(self._work_budget - self._work, wall + self._wall_budget)
        issued = None
        assertion_sha = None
        calls = 0
        variable, domain, premises = [], [], []
        consequent = None

        def finish(status, reason):
            ended = perf_counter_ns()
            if status != UNKNOWN and ended >= meter.deadline:
                status, reason = UNKNOWN, "POINT_WALL_DEADLINE"
            receipt = ImplicationCheckReceipt(
                status, reason, self._contract_sha, self._statement_sha, issued, self._witness_wire,
                tuple(variable), tuple(domain), tuple(premises), consequent, len(self._receipts) + 1,
                calls, tuple(meter.charges.items()), meter.denied_operation, thread_time_ns() - cpu, ended - wall,
            )
            self._receipts.append(receipt)
            self._work += receipt.work
            if status == REFUTE_THIS_LOCAL_ASSERTION_ONLY:
                self._authorized[id(receipt)] = assertion_sha
            return receipt

        if not _valid_assertion(assertion):
            return finish(UNKNOWN, "MALFORMED_ASSERTION_RECEIPT")
        issued = assertion
        if assertion.binding != self._contract.binding or assertion.implication_sha256 != self._statement_sha:
            return finish(UNKNOWN, "ORIGINAL_BINDING_OR_STATEMENT_MISMATCH")
        if assertion.role != ASSERT_IMPLICATION:
            return finish(UNKNOWN, "ASSERTION_ROLE_MISMATCH")
        if assertion.arrow != A_IMPLIES_B:
            return finish(UNKNOWN, "UNREVIEWED_IMPLICATION_DIRECTION")
        assertion_sha = assertion.sha256
        if assertion_sha not in self._approved:
            return finish(UNKNOWN, "ASSERTION_NOT_ISSUED")
        if type(prefix) is not str or not 0 < len(prefix) <= MAX_PREFIX_CHARACTERS:
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        try:
            prefix_sha = sha256(prefix.encode()).hexdigest()
        except UnicodeEncodeError:
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        if prefix_sha != assertion.observed_prefix_sha256 or any(marker in prefix for marker in CONTROL_MARKERS):
            return finish(UNKNOWN, "OBSERVED_PREFIX_MISMATCH")
        start, stop = assertion.assertion_span
        if stop > len(prefix) or sha256(prefix[start:stop].encode()).hexdigest() != assertion.assertion_sha256:
            return finish(UNKNOWN, "ASSERTION_SPAN_MISMATCH")
        if self._calls >= self._call_budget or self._work >= self._work_budget:
            return finish(UNKNOWN, "POINT_CALL_OR_WORK_BUDGET_EXHAUSTED")
        try:
            meter.ensure_time()
            self._calls += 1
            calls = 1
            for item in self._contract.variables:
                meter.charge("variable_domain_check")
                valid = item.domain == "RATIONAL" or self._witness[item.name].denominator == 1
                variable.append((item.name, valid))
                if not valid:
                    return finish(NO_COUNTEREXAMPLE, "WITNESS_OUTSIDE_VARIABLE_DOMAIN")
            for atom in self._contract.domain_predicates:
                domain.append(_predicate(atom, self._witness, meter))
                if not domain[-1]:
                    return finish(NO_COUNTEREXAMPLE, "WITNESS_OUTSIDE_ORIGINAL_DOMAIN")
            for atom in self._contract.premises:
                premises.append(_predicate(atom, self._witness, meter))
                if not premises[-1]:
                    return finish(NO_COUNTEREXAMPLE, "PREMISE_FALSE_AT_FIXED_WITNESS")
            consequent = _predicate(self._contract.consequent, self._witness, meter)
        except _Abstain as error:
            return finish(UNKNOWN, str(error))
        if consequent:
            return finish(NO_COUNTEREXAMPLE, "CONSEQUENT_TRUE_AT_FIXED_WITNESS")
        return finish(REFUTE_THIS_LOCAL_ASSERTION_ONLY, "COMPLETE_EXACT_COUNTEREXAMPLE")

    def authorizes_refutation(self, assertion, receipt):
        with self._lock:
            return (_valid_assertion(assertion) and type(receipt) is ImplicationCheckReceipt
                    and self._authorized.get(id(receipt)) == assertion.sha256)

    def report(self):
        with self._lock:
            return {
                "contract_sha256": self._contract_sha, "statement_sha256": self._statement_sha,
                "verifier_source_sha256": VERIFIER_SOURCE_SHA256,
                "budgets": {"checker_calls": self._call_budget, "named_work": self._work_budget, "wall_ns_per_request": self._wall_budget},
                "used": {"checker_calls": self._calls, "named_work": self._work},
                "receipts": [r.as_dict() for r in self._receipts],
            }
