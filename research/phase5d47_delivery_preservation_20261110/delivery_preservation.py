"""Retain an issued feasible certificate for one ordered delivery trajectory."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import cached_property
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Lock
from time import perf_counter_ns, thread_time_ns


D46 = Path(__file__).resolve().parent.parent / "phase5d46_point_infeasibility_20261110"
D46_SOURCE_SHA256 = "ead84d2e0f69955f27d20ab83ab34d95dd732642a63dbadbd7685d079434f76d"
sys.path.insert(0, str(D46))
import point_verifier as point

if (Path(point.__file__).resolve() != D46 / "point_verifier.py"
        or sha256(Path(point.__file__).read_bytes()).hexdigest() != D46_SOURCE_SHA256):
    raise ImportError("The frozen D4.6 point verifier identity differs")

THINKING = "THINKING"
FINAL = "FINAL"
ELIGIBLE_NATIVE_EOS = "ELIGIBLE_NATIVE_EOS"
FORMAT_FAILURE = "FORMAT_FAILURE"
CONTEXT_CAP = "CONTEXT_CAP"
SCOPE_UNKNOWN = "SCOPE_UNKNOWN"
UNCERTAIN_TERMINATION = "UNCERTAIN_TERMINATION"
KEEP_NATIVE = "KEEP_NATIVE"
RETAIN_CERTIFIED_INCUMBENT = "RETAIN_CERTIFIED_INCUMBENT"

_TERMINAL_WITHOUT_REPLACEMENT = {
    FORMAT_FAILURE: "FINAL_FORMAT_FAILURE",
    CONTEXT_CAP: "FINAL_CONTEXT_CAP",
    SCOPE_UNKNOWN: "FINAL_SCOPE_UNKNOWN",
    UNCERTAIN_TERMINATION: "FINAL_TERMINATION_UNCERTAIN",
}


def _digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class DeliveryScope:
    binding: point.ObjectiveBinding
    unit_id: str
    contract_sha256: str
    checker_source_sha256: str
    sample_id: str
    response_sha256: str

    @property
    def sha256(self):
        return _digest(asdict(self))


@dataclass(frozen=True)
class Observation:
    candidate: point.CandidateReceipt
    unit_id: str
    stage: str
    ordinal: int

    @property
    def sha256(self):
        return _digest(asdict(self))


def _valid_scope(scope):
    return (type(scope) is DeliveryScope and point._valid_binding(scope.binding)
            and scope.binding.direction in ("MAX", "MIN")
            and point._label(scope.unit_id) and point._label(scope.sample_id)
            and all(point._sha(x) for x in (scope.contract_sha256, scope.checker_source_sha256, scope.response_sha256)))


def _valid_observation(observation):
    return (type(observation) is Observation and point._valid_candidate(observation.candidate)
            and point._label(observation.unit_id) and type(observation.stage) is str
            and type(observation.ordinal) is int
            and ((observation.stage == THINKING and observation.ordinal in (1, 2))
                 or (observation.stage == FINAL and observation.ordinal == 3)))


@dataclass(frozen=True)
class IssuedPoint:
    status: str
    scope_sha256: str
    observation: Observation | None
    point_receipt: point.PointReceipt | None
    custody_request_number: int
    cpu_ns: int
    wall_ns: int

    @property
    def value(self):
        return None if self.point_receipt is None else self.point_receipt.checked_value

    def _payload(self):
        return {
            "status": self.status, "scope_sha256": self.scope_sha256,
            "observation_sha256": None if self.observation is None else self.observation.sha256,
            "point_receipt": None if self.point_receipt is None else self.point_receipt.as_dict(),
            "custody_request_number": self.custody_request_number, "cpu_ns": self.cpu_ns, "wall_ns": self.wall_ns,
        }

    @cached_property
    def sha256(self):
        return _digest(self._payload())

    def as_dict(self):
        return {**self._payload(), "receipt_sha256": self.sha256}


class PointCustody:
    """Call the frozen verifier directly and retain its run-local issued checks."""

    def __init__(self, scope, approved_scope_sha256, d46_engine, *, approved_observation_sha256):
        if not _valid_scope(scope) or not point._sha(approved_scope_sha256) or scope.sha256 != approved_scope_sha256:
            raise ValueError("Expected an independently approved original delivery scope")
        if type(d46_engine) is not point.PointVerifier or d46_engine.report()["contract_sha256"] != scope.contract_sha256:
            raise ValueError("Point verifier does not match the approved delivery scope")
        if (type(approved_observation_sha256) not in (tuple, list, frozenset)
                or not all(point._sha(x) for x in approved_observation_sha256)):
            raise ValueError("Expected independently issued observation digests")
        self._scope = scope
        self._scope_sha = approved_scope_sha256
        self._engine = d46_engine
        self._approved = frozenset(approved_observation_sha256)
        self._ordinal = 0
        self._thinking_prefix = None
        self._receipts = []
        self._issued = set()
        self._lock = Lock()

    @property
    def scope(self):
        return self._scope

    def check(self, observation, source_slice):
        with self._lock:
            return self._check(observation, source_slice)

    def _check(self, observation, source_slice):
        wall, cpu = perf_counter_ns(), thread_time_ns()
        observed = None
        proof = None

        def finish(status):
            result = IssuedPoint(status, self._scope_sha, observed, proof, len(self._receipts) + 1,
                                 thread_time_ns() - cpu, perf_counter_ns() - wall)
            self._receipts.append(result)
            if status == "ISSUED_POINT_CHECK":
                self._issued.add(id(result))
            return result

        if not _valid_observation(observation):
            return finish("MALFORMED_OBSERVATION")
        observed = observation
        c = observation.candidate
        if (observation.unit_id != self.scope.unit_id or c.binding != self.scope.binding
                or c.sample_id != self.scope.sample_id or c.response_sha256 != self.scope.response_sha256):
            return finish("DELIVERY_SCOPE_MISMATCH")
        if observation.sha256 not in self._approved:
            return finish("OBSERVATION_NOT_ISSUED")
        if observation.ordinal <= self._ordinal:
            return finish("OUT_OF_ORDER_OBSERVATION")
        if type(source_slice) is not str or not 0 < len(source_slice) <= point.MAX_PREFIX_CHARACTERS:
            return finish("INVALID_SOURCE_SLICE")
        if observation.stage == THINKING and self._thinking_prefix is not None:
            previous_length, previous_sha = self._thinking_prefix
            if (len(source_slice) < previous_length
                    or sha256(source_slice[:previous_length].encode(errors="surrogatepass")).hexdigest() != previous_sha):
                return finish("NONMONOTONE_THINKING_PREFIX")
        proof = self._engine.check(c, source_slice)
        if (type(proof) is not point.PointReceipt or proof.contract.sha256 != self.scope.contract_sha256
                or proof.contract.checker_source_sha256 != self.scope.checker_source_sha256
                or proof.contract.binding != self.scope.binding):
            return finish("POINT_PROOF_BINDING_MISMATCH")
        if proof.candidate != c or proof.checked_value is None:
            return finish("POINT_INPUT_REJECTED")
        self._ordinal = observation.ordinal
        if observation.stage == THINKING:
            self._thinking_prefix = (len(source_slice), c.observed_prefix_sha256)
        return finish("ISSUED_POINT_CHECK")

    def authentic(self, ticket):
        with self._lock:
            return type(ticket) is IssuedPoint and id(ticket) in self._issued

    def report(self):
        with self._lock:
            proofs = [r.point_receipt for r in self._receipts if r.point_receipt is not None]
            return {
                "scope_sha256": self._scope_sha, "custody_requests": len(self._receipts),
                "point_checker_calls": sum(p.checker_calls for p in proofs), "point_work": sum(p.work for p in proofs),
                "custody_cpu_ns": sum(r.cpu_ns for r in self._receipts),
                "custody_wall_ns": sum(r.wall_ns for r in self._receipts),
                "point_cpu_ns_included_in_custody": sum(p.cpu_ns for p in proofs),
                "point_wall_ns_included_in_custody": sum(p.wall_ns for p in proofs),
                "receipts": [r.as_dict() for r in self._receipts],
            }


def _number(value):
    if type(value) is int:
        return Fraction(value) if point._integer(value) else None
    if type(value) is Fraction:
        return value if point._integer(value.numerator) and point._integer(value.denominator) else None
    return point.exact_literal(value)


def _ticket_sha(ticket):
    return None if ticket is None else ticket.sha256


@dataclass(frozen=True)
class IncumbentUpdate:
    status: str
    considered_ticket_sha256: str | None
    incumbent_ticket_sha256: str | None
    incumbent_value: str | None
    comparison_operations: int
    cpu_ns: int
    wall_ns: int


@dataclass(frozen=True)
class DeliveryDecision:
    status: str
    action: str
    native_value: str | None
    proposed_value: str | None
    incumbent_value: str | None
    incumbent_ticket_sha256: str | None
    final_ticket_sha256: str | None
    comparison_operations: int
    cpu_ns: int
    wall_ns: int

    def as_dict(self):
        data = asdict(self)
        return {**data, "decision_sha256": _digest(data)}


def _resolve(custody, incumbent, termination, final_ticket, native_value, wall, cpu, comparisons):
    native = _number(native_value)
    native_text = None if native is None else str(native)
    best = None if incumbent is None else incumbent.value
    trusted_final = (custody.authentic(final_ticket) and final_ticket.observation.stage == FINAL)
    final = final_ticket if trusted_final else None

    def finish(status, action=KEEP_NATIVE):
        proposal = best if action == RETAIN_CERTIFIED_INCUMBENT else native_text
        best_sha, final_sha = _ticket_sha(incumbent), _ticket_sha(final)
        return DeliveryDecision(status, action, native_text, proposal, best, best_sha, final_sha,
                                comparisons, thread_time_ns() - cpu, perf_counter_ns() - wall)

    if type(termination) is not str or termination not in (ELIGIBLE_NATIVE_EOS, *_TERMINAL_WITHOUT_REPLACEMENT):
        return finish("FINAL_TERMINATION_UNCERTAIN")
    if termination != ELIGIBLE_NATIVE_EOS:
        return finish(_TERMINAL_WITHOUT_REPLACEMENT[termination])
    if native is None:
        return finish("FINAL_FORMAT_FAILURE")
    if final is None:
        return finish("FINAL_SCOPE_UNKNOWN")
    comparisons += 1
    if Fraction(final.value) != native:
        return finish("FINAL_READOUT_MISMATCH")
    if final.point_receipt.status == point.PROVEN_INFEASIBLE:
        return finish("FINAL_INFEASIBLE")
    if final.point_receipt.status != point.PROVEN_FEASIBLE:
        return finish("FINAL_FEASIBILITY_UNKNOWN")
    if incumbent is None:
        return finish("FEASIBLE_WITHOUT_INCUMBENT")
    comparisons += 1
    before = Fraction(best)
    if native == before:
        return finish("FEASIBLE_TIE")
    comparisons += 1
    worse = native < before if custody.scope.binding.direction == "MAX" else native > before
    if worse:
        return finish("FEASIBLE_REGRESSION", RETAIN_CERTIFIED_INCUMBENT)
    return finish("FEASIBLE_IMPROVEMENT")


class DeliveryPreserver:
    """Maintain the best issued thinking certificate, retaining its first exact tie."""

    def __init__(self, custody):
        if type(custody) is not PointCustody:
            raise TypeError("Expected trusted point custody")
        self._custody = custody
        self._incumbent = None
        self._ordinal = 0
        self._updates = []
        self._decision = None
        self._lock = Lock()

    def observe(self, ticket):
        with self._lock:
            return self._observe(ticket)

    def _observe(self, ticket):
        wall, cpu = perf_counter_ns(), thread_time_ns()
        genuine = self._custody.authentic(ticket)
        comparisons = 0

        def finish(status):
            best = self._incumbent
            considered_sha, best_sha = _ticket_sha(ticket if genuine else None), _ticket_sha(best)
            record = IncumbentUpdate(status, considered_sha, best_sha, None if best is None else best.value,
                                     comparisons, thread_time_ns() - cpu, perf_counter_ns() - wall)
            self._updates.append(record)
            return record

        if self._decision is not None:
            return finish("DELIVERY_ALREADY_FINALIZED")
        if not genuine or ticket.observation.stage != THINKING:
            return finish("UNTRUSTED_OR_NONTHINKING_POINT")
        if ticket.observation.ordinal <= self._ordinal:
            return finish("OUT_OF_ORDER_OBSERVATION")
        self._ordinal = ticket.observation.ordinal
        if ticket.point_receipt.status != point.PROVEN_FEASIBLE:
            return finish("POINT_NOT_PROVEN_FEASIBLE")
        if self._incumbent is None:
            self._incumbent = ticket
            return finish("FIRST_FEASIBLE_INCUMBENT")
        current, proposed = Fraction(self._incumbent.value), Fraction(ticket.value)
        comparisons = 1
        better = proposed > current if self._custody.scope.binding.direction == "MAX" else proposed < current
        if better:
            self._incumbent = ticket
            return finish("IMPROVED_INCUMBENT")
        return finish("KEPT_INCUMBENT")

    def finish(self, termination, final_ticket=None, *, native_value=None):
        with self._lock:
            if self._decision is not None:
                raise RuntimeError("Delivery is already finalized")
            self._decision = _resolve(self._custody, self._incumbent, termination, final_ticket, native_value,
                                      perf_counter_ns(), thread_time_ns(), 0)
            return self._decision

    def report(self):
        with self._lock:
            return {"updates": [asdict(r) for r in self._updates],
                    "decision": None if self._decision is None else self._decision.as_dict(),
                    "incumbent_ticket_sha256": _ticket_sha(self._incumbent),
                    "incumbent_value": None if self._incumbent is None else self._incumbent.value}


def naive_best_verified(custody, thinking_tickets, termination, final_ticket=None, *, native_value=None):
    """Reduce the same issued evidence in one batch with no additional checker calls."""
    if type(custody) is not PointCustody:
        raise TypeError("Expected trusted point custody")
    wall, cpu = perf_counter_ns(), thread_time_ns()
    feasible = []
    ordinal = 0
    for ticket in thinking_tickets:
        if not custody.authentic(ticket) or ticket.observation.stage != THINKING or ticket.observation.ordinal <= ordinal:
            continue
        ordinal = ticket.observation.ordinal
        if ticket.point_receipt.status == point.PROVEN_FEASIBLE:
            feasible.append(ticket)
    select = max if custody.scope.binding.direction == "MAX" else min
    best = select(feasible, key=lambda x: Fraction(x.value), default=None)
    return _resolve(custody, best, termination, final_ticket, native_value, wall, cpu, max(0, len(feasible)-1))
