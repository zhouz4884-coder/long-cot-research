"""Immutable, source-bound state and receipts for progressive witness control."""

from dataclasses import asdict, dataclass, replace
import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PointReceipt:
    contract_id: str
    target_id: str
    question_sha256: str
    trajectory_id: str
    tokenizer_sha256: str
    observed_prefix_sha256: str
    observed_count: int
    candidate_id: str
    source_token_span: tuple[int, int]
    source_token_sha256: str
    objective: int
    status: str
    check_budget: int
    paid_point_calls: int
    paid_operations: int
    cached_from: str | None
    math_json: str

    @property
    def math(self):
        return json.loads(self.math_json)

    @property
    def receipt_sha256(self):
        return digest(asdict(self))

    def as_dict(self):
        result = asdict(self)
        del result["math_json"]
        return {**result, "math": self.math, "receipt_sha256": self.receipt_sha256}


@dataclass(frozen=True)
class OppositeBoundReceipt:
    contract_id: str
    target_id: str
    question_sha256: str
    direction: str
    value: int
    rule: str
    derivation: tuple[int, ...]
    paid_operations: int

    @property
    def receipt_sha256(self):
        return digest(asdict(self))

    def as_dict(self):
        return {**asdict(self), "receipt_sha256": self.receipt_sha256}


@dataclass(frozen=True)
class ProgressState:
    contract_id: str
    target_id: str
    question_sha256: str
    direction: str
    incumbent: PointReceipt | None = None
    opposite: OppositeBoundReceipt | None = None

    def dominates(self, value, previous):
        return value > previous if self.direction == "MAX" else value < previous

    def _check_scope(self, receipt):
        if (receipt.contract_id, receipt.target_id, receipt.question_sha256) != (
                self.contract_id, self.target_id, self.question_sha256):
            raise ValueError("receipt belongs to another objective")

    def promote(self, receipt):
        self._check_scope(receipt)
        if receipt.status != "CERTIFIED_FEASIBLE":
            raise ValueError("candidate promotion requires full feasibility")
        if self.opposite and self.dominates(receipt.objective, self.opposite.value):
            raise ValueError("candidate contradicts the certified opposite bound")
        if self.incumbent and not self.dominates(receipt.objective, self.incumbent.objective):
            return self
        return replace(self, incumbent=receipt)

    def tighten(self, receipt):
        self._check_scope(receipt)
        if receipt.direction != self.direction:
            raise ValueError("opposite bound has the wrong direction")
        if self.incumbent and self.dominates(self.incumbent.objective, receipt.value):
            raise ValueError("opposite bound contradicts the certified incumbent")
        if self.opposite and not self.dominates(self.opposite.value, receipt.value):
            return self
        return replace(self, opposite=receipt)

    @property
    def certified_answer(self):
        if self.incumbent and self.opposite and self.incumbent.objective == self.opposite.value:
            return self.incumbent.objective
        return None

    def as_dict(self):
        return {
            "contract_id": self.contract_id, "target_id": self.target_id,
            "question_sha256": self.question_sha256, "direction": self.direction,
            "incumbent": self.incumbent.as_dict() if self.incumbent else None,
            "opposite_bound": self.opposite.as_dict() if self.opposite else None,
            "certified_answer": self.certified_answer,
        }
