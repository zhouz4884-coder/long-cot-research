"""Compose source roles with bounded trusted arithmetic, without a solver."""

from dataclasses import asdict, dataclass
import json
import sys
from types import MappingProxyType

from freeze_scope_regressions import D35, D36, sha
from scope_adapter import bind_event_scope

sys.path.extend(str(path) for path in (D35, D36))
from goal_claim_detector import target_id_for
from point_verifier import PointVerifier
from witness_contract import DIGITS


INVENTORY_SHA256 = "ac00eaecebec716e3b30b1dd9b1ed44dc406cce36de3d217d9c429fa629f61bf"


class FrozenEventInventory:
    """This offline adapter admits only the independently reconstructed source frame."""

    def __init__(self, source):
        if sha(source) != INVENTORY_SHA256:
            raise ValueError("Event inventory differs from the verified D3.6 reconstruction")
        events = json.loads(source)["events"]
        self._events = MappingProxyType({event["id"]: json.dumps(event).encode() for event in events})

    def event(self, event_id):
        if not isinstance(event_id, str):
            raise TypeError("Only a frozen observed event ID is accepted")
        return json.loads(self._events[event_id])


@dataclass(frozen=True)
class VerifiedBound:
    value: int
    source_id: str
    prefix_sha256: str
    certificate_sha256: str


class ScopedPointGate:
    """Process verified observed events for one trajectory and one pinned goal."""

    def __init__(self, contract, inventory, *, point_budget=16, work_budget=1024):
        if contract.template_id != DIGITS:
            raise ValueError("Only the audited E15 discourse and checker are enabled")
        if type(inventory) is not FrozenEventInventory:
            raise TypeError("A verified frozen source frame is required")
        self.inventory = inventory
        self.checker = PointVerifier(contract, point_budget=point_budget, work_budget=work_budget)
        self.target = target_id_for(contract)
        self.bound = None
        self.trajectory = None
        self.last_sequence = -1

    def step(self, event_id):
        event = self.inventory.event(event_id)
        trajectory = event["trajectory"]
        if self.trajectory is None:
            self.trajectory = trajectory
        elif self.trajectory != trajectory:
            raise ValueError("Cannot carry a certified bound across trajectories")
        origin, _, sequence = event["id"].rpartition(":")
        if origin != trajectory or not sequence.isascii() or not sequence.isdigit() or int(sequence) <= self.last_sequence:
            raise ValueError("Source event is missing, repeated, or out of order")
        self.last_sequence = int(sequence)
        scope = bind_event_scope(event, trusted_target_id=self.target)
        value = event["value"]
        outcome = {"role": scope.role, "authority": "NONE", "point": None, "witness": None}
        if not scope.admits_point_check:
            return outcome
        if scope.may_refute_global_maximum and self.bound is not None and self.bound.value > value:
            # The existing feasible witness disproves the asserted global extremum.
            # Feasibility of the asserted (smaller) value is immaterial to that proof.
            outcome["authority"] = "REFUTE_GLOBAL_MAXIMUM"
            outcome["witness"] = asdict(self.bound)
            return outcome
        point = self.checker.check(value)
        outcome["point"] = point.as_dict()
        if point.status == "CERTIFIED_INFEASIBLE" and scope.may_refute_feasibility_claim:
            outcome["authority"] = "REFUTE_FEASIBILITY_ONLY"
        elif point.status == "CERTIFIED_FEASIBLE" and (self.bound is None or value > self.bound.value):
            self.bound = VerifiedBound(value, event["id"], event["observed_prefix_sha256"],
                                       point.math["certificate_sha256"])
            outcome["authority"] = "RAISE_FEASIBLE_BOUND_ONLY"
        return outcome
