"""Shared bounded point-access interface for control and ToolsOnly baselines."""

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sys
from time import perf_counter

from progress_state import canonical


_D35 = Path(__file__).resolve().parent.parent / "phase5d35_witness_gated_revision_20261109"
if _D35.is_dir():
    sys.path.append(str(_D35))

from witness_contract import DIGITS, MAX_BUDGET, PRIME, authentic, check_candidate, integer


@dataclass(frozen=True)
class PointCheck:
    status: str
    request_key: str | None
    check_budget: int
    paid_point_calls: int
    paid_operations: int
    cached: bool
    math_json: str

    @property
    def math(self):
        return json.loads(self.math_json)

    def as_dict(self):
        out = asdict(self)
        del out["math_json"]
        return {**out, "math": self.math}


class PointVerifier:
    """Validate a caller-supplied point. This interface does not propose points or solve goals."""

    def __init__(self, contract, *, point_budget=16, work_budget=1024, prerequisite=None):
        if not authentic(contract) or contract.template_id not in {DIGITS, PRIME}:
            raise ValueError("an authentic supported MAX or MIN contract is required")
        if type(point_budget) is not int or not 0 <= point_budget <= 32:
            raise ValueError("point budget must be an integer from 0 to 32")
        if type(work_budget) is not int or not 0 <= work_budget <= MAX_BUDGET:
            raise ValueError("invalid mathematical work budget")
        self.contract = contract
        self._prerequisite = canonical(prerequisite)
        self._point_budget = point_budget
        self._work_budget = work_budget
        self._point_calls = 0
        self._operations = 0
        self._point_seconds = 0.0
        self._proof_operations = 0
        self._cached = {}

    @property
    def remaining_work(self):
        return self._work_budget - self._operations

    def _charge_bound_proof(self, operations):
        if not 0 <= operations <= self.remaining_work:
            raise ValueError("bound proof exceeds the remaining work budget")
        self._operations += operations
        self._proof_operations += operations

    def _unknown(self, reason, key=None):
        return PointCheck("UNKNOWN", key, self.remaining_work, 0, 0, False,
                          canonical({"status": "UNKNOWN", "reason": reason}))

    def _valid_payload(self, point):
        if self.contract.template_id == DIGITS:
            return integer(point)
        return type(point) is dict and set(point) == {"p", "m"} and all(integer(x) for x in point.values())

    def check(self, point):
        if not self._valid_payload(point):
            return self._unknown("malformed_point")
        key = canonical(point)
        cached = self._cached.get(key)
        if cached is not None:
            return replace(cached, paid_point_calls=0, paid_operations=0, cached=True)
        if self._point_calls >= self._point_budget or self.remaining_work == 0:
            return self._unknown("common_point_or_work_budget_exhausted", key)
        budget = self.remaining_work
        began = perf_counter()
        result = check_candidate(self.contract, point, prerequisite=json.loads(self._prerequisite), budget=budget)
        self._point_seconds += perf_counter() - began
        operations = result["paid_check_count"]
        self._point_calls += 1
        self._operations += operations
        status = "UNKNOWN"
        if result["proof_scope"] == "FULL_ORIGINAL_CONSTRAINTS" and result["certificate_sha256"]:
            status = {"FEASIBLE_ONLY": "CERTIFIED_FEASIBLE", "INVALID_CANDIDATE": "CERTIFIED_INFEASIBLE"}.get(
                result["status"], "UNKNOWN")
        checked = PointCheck(status, key, budget, 1, operations, False, canonical(result))
        if status != "UNKNOWN":
            self._cached[key] = checked
        return checked

    def report(self):
        return {
            "point_budget": self._point_budget, "work_budget": self._work_budget, "point_calls": self._point_calls,
            "paid_operations": self._operations, "bound_proof_operations": self._proof_operations,
            "point_check_seconds": self._point_seconds,
        }
