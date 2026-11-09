"""Event-driven feasibility ratchet using the frozen D3.5 point verifier."""

from dataclasses import asdict, dataclass

from event_trigger import EventTrigger
from point_verifier import PointVerifier
from progress_state import OppositeBoundReceipt, PointReceipt, ProgressState
from search_obligation import SearchObligation, make_obligation

from candidate_archive import ArchiveCandidate, CandidateArchive, ObservedPrefix
from goal_claim_detector import target_id_for
from witness_contract import DIGITS, integer


@dataclass(frozen=True)
class Decision:
    action: str
    obligation: SearchObligation | None
    receipt: PointReceipt
    veto: bool
    certified_answer: int | None
    terminal: bool

    def as_dict(self):
        return {**asdict(self), "receipt": self.receipt.as_dict()}


class ProgressiveWitness:
    """Check one observed commitment at a time. Source history is append-only across repairs."""

    def __init__(self, contract, initial_prefix, *, point_budget=16, work_budget=1024, feedback_budget=4,
                 mode="event", prerequisite=None):
        self._verifier = PointVerifier(contract, point_budget=point_budget, work_budget=work_budget,
                                       prerequisite=prerequisite)
        if not isinstance(initial_prefix, ObservedPrefix) or initial_prefix.question_sha256 != contract.question_sha256:
            raise ValueError("initial observation belongs to a different problem")
        self.contract = contract
        self._initial = initial_prefix
        self._trigger = EventTrigger(mode, feedback_budget)
        self._state = ProgressState(contract.contract_id, target_id_for(contract), contract.question_sha256,
                                    contract.goal)
        self._archive = CandidateArchive(self._state.contract_id, self._state.target_id, self._state.question_sha256)
        self._first_receipts = {}
        self._events = []

    @property
    def state(self):
        return self._state

    def _check_source(self, prefix, candidate, terminal, authored_span):
        initial = self._initial
        if (not isinstance(prefix, ObservedPrefix) or prefix.trajectory_id != initial.trajectory_id
                or prefix.tokenizer_sha256 != initial.tokenizer_sha256 or prefix.question_sha256 != initial.question_sha256
                or prefix.prompt_ids != initial.prompt_ids
                or prefix.generated_ids[:initial.observed_count] != initial.generated_ids):
            raise ValueError("observation is not derived from the trusted checkpoint")
        replay = ObservedPrefix.from_tokens(prefix.generated_ids, initial._decode, prompt_ids=initial.prompt_ids,
                                            trajectory_id=initial.trajectory_id, tokenizer_sha256=initial.tokenizer_sha256,
                                            question_sha256=initial.question_sha256)
        if replay != prefix:
            raise ValueError("supplied observation disagrees with its token decode")
        if not isinstance(candidate, ArchiveCandidate):
            raise ValueError("source-bound archive candidate required")
        goal_kind = "MAXIMALITY_CLAIM" if self.state.direction == "MAX" else "MINIMALITY_CLAIM"
        if not integer(candidate.value) or candidate.goal_claim_type not in {goal_kind, "FEASIBLE_CANDIDATE"}:
            raise ValueError("source must name a bounded integer commitment to the active objective")
        if terminal and (candidate.goal_claim_type != goal_kind or candidate.segment != "final"):
            raise ValueError("terminal control requires an explicit final objective commitment")
        if authored_span is not None:
            if not isinstance(authored_span, (tuple, list)) or len(authored_span) != 2 or any(
                    type(offset) is not int for offset in authored_span):
                raise ValueError("sampled source must provide two integer token offsets")
            start, end = authored_span
            if not (0 <= start <= candidate.source_span.token_start < candidate.source_span.token_end <= end <= prefix.observed_count
                    and all(start <= span.token_start < span.token_end <= end for span in candidate.field_spans.values())):
                raise ValueError("candidate and proof fields must be inside the sampled source span")
        return self._archive.admit(candidate, replay)

    def _check_point(self, candidate):
        point = candidate.value if self.contract.template_id == DIGITS else {
            "p": candidate.assignments.get("p"), "m": candidate.value,
        }
        checked = self._verifier.check(point)
        cached = self._first_receipts.get(checked.request_key) if checked.cached else None
        receipt = PointReceipt(
            candidate.contract_id, candidate.target_id, candidate.question_sha256, candidate.trajectory_id,
            candidate.tokenizer_sha256, candidate.observed_prefix_sha256, candidate.observed_count,
            candidate.candidate_id, candidate.source_span.token_span, candidate.source_span.token_sha256,
            candidate.value, checked.status, checked.check_budget, checked.paid_point_calls, checked.paid_operations,
            cached.receipt_sha256 if cached else None, checked.math_json,
        )
        if not checked.cached and checked.status != "UNKNOWN":
            self._first_receipts[checked.request_key] = receipt
        return receipt

    def admit(self, prefix, archive_candidate, *, terminal=False, feedback=True, authored_span=None):
        candidate = self._check_source(prefix, archive_candidate, terminal, authored_span)
        receipt = self._check_point(candidate)
        prior = self._state
        if receipt.status == "UNKNOWN":
            action = "NATIVE_CONTINUE"
        elif receipt.status == "CERTIFIED_INFEASIBLE":
            action = "REPAIR_INFEASIBLE"
        else:
            self._state = prior.promote(receipt)
            if prior.incumbent and prior.dominates(prior.incumbent.objective, receipt.objective):
                action = "BLOCK_REGRESSION"
            elif terminal and self._state.certified_answer == receipt.objective:
                action = "CERTIFY_EXACT"
            else:
                action = "KEEP_BOUND" if self._state is prior else "UPDATE_BOUND"
        incumbent = self.state.incumbent.objective if self.state.incumbent else None
        obligation = None
        if self._trigger.permits(action, receipt, incumbent, terminal=terminal, enabled=feedback):
            obligation = make_obligation(self.state, action, receipt)
        veto = terminal and action in {"BLOCK_REGRESSION", "REPAIR_INFEASIBLE"}
        certified = self.state.certified_answer if action == "CERTIFY_EXACT" else None
        decision = Decision(action, obligation, receipt, veto, certified, terminal)
        self._events.append(decision)
        return decision

    def certify_opposite_bound(self):
        """Optional elementary domain proof. Point-only experiments leave this unused."""
        if self.state.opposite:
            return self.state.opposite
        if self.contract.template_id == DIGITS:
            digits = [1, 0]
            while digits[-1] <= 9:
                digits.append(digits[-1] + digits[-2])
            value, rule, proof = 10 ** (len(digits) - 1) - 1, "monotone_minimum_decimal_recurrence", tuple(digits)
            operations = len(digits) - 2
        else:
            value, rule, proof, operations = 1, "positive_integer_domain", (1,), 1
        if operations > self._verifier.remaining_work:
            return None
        receipt = OppositeBoundReceipt(self.state.contract_id, self.state.target_id, self.state.question_sha256,
                                       self.state.direction, value, rule, proof, operations)
        self._state = self._state.tighten(receipt)
        self._verifier._charge_bound_proof(operations)
        return receipt

    def report(self):
        return {
            "state": self.state.as_dict(), **self._verifier.report(),
            "mode": self._trigger.mode, "feedback_budget": self._trigger.budget, "feedback_emitted": self._trigger.emitted,
            "events": [event.as_dict() for event in self._events],
        }
