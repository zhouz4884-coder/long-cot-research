"""Issue exact feasible bounds under an independently approved problem contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
from threading import Lock
from time import thread_time_ns


VERIFIER_ID = "d45.reviewed-feasible-witness"
VERIFIER_VERSION = 1
FEASIBLE_WITNESS = "FEASIBLE_WITNESS"
OPTIMUM_CLAIM = "OPTIMUM_CLAIM"
MAX_ABS_INTEGER = (1 << 63) - 1
MAX_CONSTRAINTS = 32
MAX_WITNESS_NODES = 512
MAX_WITNESS_DEPTH = 8


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _digest(value):
    return sha256(_canonical_bytes(value)).hexdigest()


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _label(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None


def _exact_fraction(value):
    if type(value) is int and abs(value) <= MAX_ABS_INTEGER:
        return Fraction(value)
    if type(value) is str:
        match = re.fullmatch(r"(-?(?:0|[1-9][0-9]{0,18}))(?:/([1-9][0-9]{0,18}))?", value)
        if match is None:
            return None
        numerator, denominator = int(match[1]), int(match[2] or "1")
        if abs(numerator) > MAX_ABS_INTEGER or denominator > MAX_ABS_INTEGER:
            return None
        value = Fraction(numerator, denominator)
    if type(value) is Fraction and abs(value.numerator) <= MAX_ABS_INTEGER and 1 <= value.denominator <= MAX_ABS_INTEGER:
        return value
    return None


def _witness_bytes(witness):
    """Accept a small plain JSON object without floating point, custom types, or cycles."""
    if type(witness) is not dict or not witness:
        return None
    pending = [(witness, 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > MAX_WITNESS_DEPTH or visited > MAX_WITNESS_NODES:
            return None
        if type(value) in (dict, list):
            if len(value) + len(pending) + visited > MAX_WITNESS_NODES:
                return None
            if type(value) is dict and any(not _label(k) for k in value):
                return None
            children = value.values() if type(value) is dict else value
            pending.extend((child, depth + 1) for child in children)
        elif type(value) is int:
            if abs(value) > MAX_ABS_INTEGER:
                return None
        elif type(value) is str:
            if len(value) > 256 or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
                return None
        elif type(value) is not bool and value is not None:
            return None
    return _canonical_bytes(witness)


@dataclass(frozen=True)
class ObjectiveBinding:
    question_sha256: str
    objective_id: str
    scope_sha256: str
    constraints_sha256: str
    direction: str


@dataclass(frozen=True)
class ReviewedContract:
    binding: ObjectiveBinding
    required_constraints: tuple[str, ...]
    checker_id: str
    checker_version: int
    checker_entrypoint: str
    checker_source_sha256: str
    proof_sha256: str
    review_sha256: str

    @property
    def sha256(self):
        return _digest({"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION, **asdict(self)})


@dataclass(frozen=True)
class Feasibility:
    """The checker reports original constraint statuses and an exact objective if feasible."""

    constraints: tuple[tuple[str, bool | None], ...]
    objective: Fraction | None


def _valid_binding(binding):
    return (
        type(binding) is ObjectiveBinding
        and all(_sha(x) for x in (binding.question_sha256, binding.scope_sha256, binding.constraints_sha256))
        and _label(binding.objective_id) and type(binding.direction) is str and binding.direction in ("MAX", "MIN")
    )


def _valid_contract(contract):
    if type(contract) is not ReviewedContract or not _valid_binding(contract.binding):
        return False
    names = contract.required_constraints
    return (
        all(_sha(x) for x in (contract.checker_source_sha256, contract.proof_sha256, contract.review_sha256))
        and type(names) is tuple and 1 <= len(names) <= MAX_CONSTRAINTS
        and all(_label(name) and len(name) <= 96 for name in names) and len(set(names)) == len(names)
        and _label(contract.checker_id) and _label(contract.checker_entrypoint)
        and type(contract.checker_version) is int and 1 <= contract.checker_version <= MAX_ABS_INTEGER
    )


def checker_source_sha256(checker):
    """Hash the reviewed module containing a named function without captured parameters."""
    if (not inspect.isfunction(checker) or checker.__qualname__ != checker.__name__ or checker.__closure__ is not None
            or checker.__defaults__ is not None or checker.__kwdefaults__ is not None):
        raise ValueError("Expected a named module-level checker with no hidden parameters")
    file = inspect.getsourcefile(checker)
    if file is None:
        raise ValueError("Checker has no reviewed Python source")
    return sha256(Path(file).read_bytes()).hexdigest()


class _BudgetExhausted(Exception):
    pass


class WorkMeter:
    """The reviewed checker charges before work and cannot borrow the comparison budget."""

    def __init__(self, limit):
        self._limit = limit
        self._charges = {}
        self._spent = 0
        self._denied = None

    def charge(self, label, count=1):
        if not _label(label) or type(count) is not int or not 1 <= count <= MAX_ABS_INTEGER:
            raise ValueError("Expected a bounded named operation count")
        if self._denied is not None:
            raise _BudgetExhausted()
        if count > self._limit - self._spent:
            self._denied = (label, count)
            raise _BudgetExhausted()
        self._charges[label] = self._charges.get(label, 0) + count
        self._spent += count


@dataclass(frozen=True)
class WitnessReceipt:
    status: str
    reason: str
    contract: ReviewedContract
    witness_sha256: str | None
    request_number: int
    checker_calls: int
    operation_charges: tuple[tuple[str, int], ...]
    denied_operation: tuple[str, int] | None
    constraints: tuple[tuple[str, bool | None], ...]
    objective: str | None
    bound_direction: str | None
    cpu_ns: int

    @property
    def work(self):
        return sum(count for _, count in self.operation_charges)

    def as_dict(self):
        data = {"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION,
                "contract_sha256": self.contract.sha256, "work": self.work, **asdict(self)}
        return {**data, "receipt_sha256": _digest(data)}


@dataclass(frozen=True)
class ClaimReceipt:
    status: str
    reason: str
    contract_sha256: str
    request_number: int
    bound_receipt_sha256: str | None
    optimum_claim: str | None
    comparison_operations: int
    cpu_ns: int

    def as_dict(self):
        data = {"verifier_id": VERIFIER_ID, "verifier_version": VERIFIER_VERSION, **asdict(self)}
        return {**data, "receipt_sha256": _digest(data)}


class FeasibleWitnessVerifier:
    """Single-question verifier and receipt custody. The approved checker is trusted code."""

    def __init__(self, contract, approved_contract_sha256, checker, *, call_budget, work_budget, comparison_budget):
        if (not _valid_contract(contract) or not _sha(approved_contract_sha256)
                or contract.sha256 != approved_contract_sha256):
            raise ValueError("Expected an exact independently approved contract")
        if (checker_source_sha256(checker) != contract.checker_source_sha256
                or checker.__name__ != contract.checker_entrypoint):
            raise ValueError("Checker implementation does not match the reviewed contract")
        budgets = (call_budget, work_budget, comparison_budget)
        if any(type(limit) is not int or not 0 <= limit <= MAX_ABS_INTEGER for limit in budgets):
            raise ValueError("Expected bounded nonnegative integer budgets")
        self._contract = contract
        self._checker = checker
        self._call_budget, self._work_budget, self._comparison_budget = budgets
        self._calls = self._work = self._comparisons = 0
        self._verification_receipts = []
        self._comparison_receipts = []
        self._issued = {}
        self._lock = Lock()

    def verify(self, binding, witness, *, witness_role=FEASIBLE_WITNESS):
        with self._lock:
            return self._verify(binding, witness, witness_role)

    def _verify(self, binding, witness, witness_role):
        began = thread_time_ns()
        meter = WorkMeter(self._work_budget - self._work)
        request = len(self._verification_receipts) + 1
        witness_hash = None
        calls = 0

        def finish(status, reason, constraints=(), objective=None):
            direction = None
            if objective is not None:
                direction = "LOWER" if binding.direction == "MAX" else "UPPER"
            receipt = WitnessReceipt(status, reason, self._contract, witness_hash, request, calls,
                                     tuple(meter._charges.items()), meter._denied, constraints,
                                     None if objective is None else str(objective), direction, thread_time_ns() - began)
            self._work += receipt.work
            self._verification_receipts.append(receipt)
            if status == "CERTIFIED_FEASIBLE_BOUND":
                self._issued[id(receipt)] = receipt.as_dict()["receipt_sha256"]
            return receipt

        if not _valid_binding(binding) or binding != self._contract.binding:
            return finish("UNKNOWN", "BINDING_MISMATCH")
        if type(witness_role) is not str or witness_role != FEASIBLE_WITNESS:
            return finish("UNKNOWN", "WITNESS_ROLE_MISMATCH")
        payload = _witness_bytes(witness)
        if payload is None:
            return finish("UNKNOWN", "MALFORMED_WITNESS")
        witness_hash = sha256(payload).hexdigest()
        if self._calls == self._call_budget or self._work == self._work_budget:
            return finish("UNKNOWN", "WITNESS_BUDGET_EXHAUSTED")
        self._calls += 1
        calls = 1
        try:
            # Only the exact hashed witness bytes are delivered to the reviewed checker.
            result = self._checker(binding, json.loads(payload), meter)
        except _BudgetExhausted:
            return finish("UNKNOWN", "WITNESS_BUDGET_EXHAUSTED")
        except Exception:
            return finish("UNKNOWN", "CHECKER_ERROR")
        if meter._denied is not None:
            return finish("UNKNOWN", "WITNESS_BUDGET_EXHAUSTED")
        if type(result) is not Feasibility or type(result.constraints) is not tuple:
            return finish("UNKNOWN", "MALFORMED_CHECKER_RESULT")
        rows = result.constraints
        if (len(rows) != len(self._contract.required_constraints)
                or any(type(row) is not tuple or len(row) != 2 or
                       not _label(row[0]) or (type(row[1]) is not bool and row[1] is not None) for row in rows)
                or tuple(row[0] for row in rows) != self._contract.required_constraints):
            return finish("UNKNOWN", "INCOMPLETE_CONSTRAINT_COVERAGE")
        if any(meter._charges.get("constraint:" + name, 0) < 1 for name, _ in rows):
            return finish("UNKNOWN", "UNCHARGED_CONSTRAINT")
        if any(value is None for _, value in rows):
            return finish("UNKNOWN", "UNRESOLVED_CONSTRAINT", rows)
        if any(value is False for _, value in rows):
            return finish("WITNESS_INFEASIBLE", "CONSTRAINT_VIOLATION", rows)
        value = _exact_fraction(result.objective) if type(result.objective) is Fraction else None
        if value is None or meter._charges.get("objective", 0) < 1:
            return finish("UNKNOWN", "MISSING_OR_UNCHARGED_EXACT_OBJECTIVE", rows)
        return finish("CERTIFIED_FEASIBLE_BOUND", "ALL_ORIGINAL_CONSTRAINTS_VERIFIED", rows, value)

    def compare(self, binding, optimum_claim, certificate, *, claim_role=OPTIMUM_CLAIM):
        with self._lock:
            return self._compare(binding, optimum_claim, certificate, claim_role)

    def _compare(self, binding, optimum_claim, certificate, claim_role):
        began = thread_time_ns()
        request = len(self._comparison_receipts) + 1
        certificate_hash = None
        value = None

        def finish(status, reason, operations=0):
            receipt = ClaimReceipt(status, reason, self._contract.sha256, request, certificate_hash,
                                   None if value is None else str(value), operations, thread_time_ns() - began)
            self._comparison_receipts.append(receipt)
            return receipt

        if not _valid_binding(binding) or binding != self._contract.binding:
            return finish("UNKNOWN", "BINDING_MISMATCH")
        if type(claim_role) is not str or claim_role != OPTIMUM_CLAIM:
            return finish("UNKNOWN", "CLAIM_ROLE_MISMATCH")
        value = _exact_fraction(optimum_claim)
        if value is None:
            return finish("UNKNOWN", "MALFORMED_EXACT_CLAIM")
        if type(certificate) is not WitnessReceipt or id(certificate) not in self._issued:
            return finish("UNKNOWN", "UNISSUED_BOUND")
        certificate_hash = self._issued[id(certificate)]
        if self._comparisons == self._comparison_budget:
            return finish("UNKNOWN", "COMPARISON_BUDGET_EXHAUSTED")
        self._comparisons += 1
        bound = Fraction(certificate.objective)
        violated = value < bound if binding.direction == "MAX" else value > bound
        if violated:
            return finish("REFUTED_OPTIMUM_CLAIM", "STRICTLY_BETTER_FEASIBLE_VALUE", 1)
        return finish("NOT_REFUTED", "BOUND_DOES_NOT_REFUTE_VALUE", 1)

    def report(self):
        with self._lock:
            return {
                "contract_sha256": self._contract.sha256,
                "budgets": {"checker_calls": self._call_budget, "witness_work": self._work_budget,
                            "comparison_operations": self._comparison_budget},
                "used": {"checker_calls": self._calls, "witness_work": self._work,
                         "comparison_operations": self._comparisons},
                "witness_receipts": [row.as_dict() for row in self._verification_receipts],
                "claim_receipts": [row.as_dict() for row in self._comparison_receipts],
            }
