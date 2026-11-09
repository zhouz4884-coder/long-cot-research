"""Source-gated arbitration. Certificates authorize only their proved proposition."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time

from candidate_archive import CandidateArchive
from goal_claim_detector import detect_claims, target_id_for
from witness_contract import check_candidate, check_claim_witness, rational
from bounded_witness_search import replay_search


OBSERVED = "OBSERVED_CANDIDATE"
ONLINE = "ONLINE_SEARCH"
OFFLINE = "OFFLINE_ORACLE_DIAGNOSTIC"
POINT_TARGETS = frozenset({"MAXIMALITY_CLAIM", "MINIMALITY_CLAIM", "UNIVERSAL_CLAIM", "COMPLETE_SOLUTIONS_CLAIM"})
VALUE_TARGETS = frozenset({"FEASIBLE_CANDIDATE", "EXACT_ANSWER", "FINAL_ANSWER_REVISION"})


def digest(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Witness:
    source: str
    candidate_id: str | None = None
    search_receipt: dict | None = None


def candidate_payload(contract, item):
    if contract.template_id == "arithmetic_geometric_sequence_v1":
        return {**item.assignments, "answer": item.value}
    if contract.template_id == "least_prime_square_residue_v1":
        return {**item.assignments, "m": item.value}
    return item.value


class WitnessGate:
    """Re-extract claims from a trusted runtime prefix rather than trusting payload flags."""

    def __init__(self, contract, prefix):
        if prefix.question_sha256 != contract.question_sha256:
            raise ValueError("Constraint program is bound to a different question")
        self.contract = contract
        self.prefix = prefix
        self.target_id = target_id_for(contract)
        self.archive = CandidateArchive(contract.contract_id, self.target_id, contract.question_sha256)
        began = time.perf_counter()
        self.records = tuple(detect_claims(prefix, contract))
        for item in self.records:
            self.archive.admit(item, prefix)
        self.extract_seconds = time.perf_counter() - began

    def _item(self, candidate_id):
        try:
            return self.archive.validated(candidate_id, self.prefix)
        except (ValueError, TypeError, LookupError):
            return None

    def _out(self, item, status, action, reason, *, witness=None, mathematical=None,
             released_value=None, elapsed=0.0):
        body = {"checker": "d35-witness-arbitration-v1", "contract_id": self.contract.contract_id,
                "question_sha256": self.contract.question_sha256, "target_id": self.target_id,
                "claim_id": None if item is None else item.candidate_id,
                "claim_type": None if item is None else item.goal_claim_type,
                "observed_prefix_sha256": self.prefix.prefix_sha256,
                "status": status, "action": action, "reason": reason,
                "witness": witness, "mathematical": mathematical, "released_value": released_value}
        return {**body, "certificate_sha256": None if status == "UNKNOWN" else digest(body),
                "verification_wall_seconds": elapsed}

    def verify(self, candidate_id, witness: Witness | None = None, *, prerequisite=None):
        """Direct verification or arbitration for one already-observed candidate/claim."""
        began = time.perf_counter()
        item = self._item(candidate_id)
        elapsed = lambda: time.perf_counter() - began
        if item is None:
            return self._out(None, "UNKNOWN", "NONE", "claim_source_unvalidated", elapsed=elapsed())
        if witness is not None and witness.source == OFFLINE:
            return self._out(item, "UNKNOWN", "NONE", "offline_oracle_not_admissible_online", elapsed=elapsed())
        if item.goal_claim_type in VALUE_TARGETS and witness is None:
            direct = check_candidate(self.contract, candidate_payload(self.contract, item), prerequisite=prerequisite)
            status = direct["status"]
            action = {"CERTIFIED_EXACT": "PERMIT_EXACT_DELIVERY", "FEASIBLE_ONLY": "RETAIN_FEASIBLE",
                      "INVALID_CANDIDATE": "REJECT_CANDIDATE"}.get(status, "NONE")
            return self._out(item, status, action, direct.get("reason", status), mathematical=direct,
                             released_value=direct.get("certified_value") if status == "CERTIFIED_EXACT" else None,
                             elapsed=elapsed())
        if item.goal_claim_type == "FINAL_ANSWER_REVISION":
            earlier = self._item(witness.candidate_id) if witness and witness.source == OBSERVED else None
            if (earlier is None or earlier.goal_claim_type not in {"FEASIBLE_CANDIDATE", "EXACT_ANSWER"}
                    or earlier.segment != "thinking" or item.segment != "final"
                    or earlier.source_span.token_end > item.source_span.token_start):
                return self._out(item, "UNKNOWN", "NONE", "revision_lacks_prior_observed_candidate", elapsed=elapsed())
            checked = check_candidate(self.contract, candidate_payload(self.contract, earlier), prerequisite=prerequisite)
            certified = checked.get("certified_value")
            if checked["status"] != "CERTIFIED_EXACT" or certified is None:
                return self._out(item, "UNKNOWN", "NONE", "prior_candidate_lacks_exact_certificate",
                                 mathematical=checked, elapsed=elapsed())
            try:
                proposed, approved = rational(item.value), rational(certified)
            except (ValueError, TypeError, ZeroDivisionError):
                proposed = approved = None
            if proposed is None or approved is None:
                return self._out(item, "UNKNOWN", "NONE", "final_value_not_exactly_comparable", elapsed=elapsed())
            matches = proposed == approved
            evidence = {"source": OBSERVED, "candidate_id": earlier.candidate_id, "value": certified}
            return self._out(item, "CONSISTENT_DELIVERY" if matches else "FINAL_ANSWER_CONFLICT",
                             "NONE" if matches else "VETO_DRAFT_AND_DELIVER_CERTIFIED",
                             "checked_unique_answer", witness=evidence, mathematical=checked,
                             released_value=certified, elapsed=elapsed())
        if item.goal_claim_type not in POINT_TARGETS or witness is None or not item.claim:
            return self._out(item, "UNKNOWN", "NONE", "no_applicable_bound_witness", elapsed=elapsed())
        if witness.source == OBSERVED:
            earlier = self._item(witness.candidate_id)
            if earlier is None or earlier.goal_claim_type not in {"FEASIBLE_CANDIDATE", "EXACT_ANSWER"}:
                return self._out(item, "UNKNOWN", "NONE", "witness_source_unvalidated", elapsed=elapsed())
            point = candidate_payload(self.contract, earlier)
            evidence = {"source": OBSERVED, "candidate_id": earlier.candidate_id, "value": point}
        elif witness.source == ONLINE:
            searched = witness.search_receipt
            if (not isinstance(searched, dict) or not replay_search(self.contract, searched)
                    or searched.get("request", {}).get("claim") != item.claim
                    or searched.get("request", {}).get("purpose") != "COUNTEREXAMPLE"
                    or searched.get("witness") is None):
                return self._out(item, "UNKNOWN", "NONE", "online_search_receipt_unbound_or_exhausted", elapsed=elapsed())
            point = searched["witness"]
            prerequisite = searched.get("prerequisite")
            evidence = {"source": ONLINE, "search_receipt": searched, "value": point}
        else:
            return self._out(item, "UNKNOWN", "NONE", "unsupported_witness_source", elapsed=elapsed())
        old_checked = None
        if item.goal_claim_type in {"MAXIMALITY_CLAIM", "MINIMALITY_CLAIM"}:
            old_checked = check_candidate(self.contract, candidate_payload(self.contract, item), prerequisite=prerequisite)
            if old_checked["status"] != "FEASIBLE_ONLY" or old_checked["proof_scope"] != "FULL_ORIGINAL_CONSTRAINTS":
                return self._out(item, "UNKNOWN", "NONE", "incumbent_not_verified_under_complete_constraints",
                                 witness=evidence, mathematical=old_checked, elapsed=elapsed())
        checked = check_claim_witness(self.contract, item.claim, point, prerequisite=prerequisite)
        status = checked["status"]
        action = {"DOMINATED_CANDIDATE": "RETRACT_EXTREMUM_ONLY", "UNIVERSAL_REFUTATION": "RETRACT_CLAIM_ONLY"}.get(status, "NONE")
        if old_checked is not None:
            checked = {**checked, "incumbent_feasibility": old_checked}
        return self._out(item, status, action, checked.get("reason", status), witness=evidence,
                         mathematical=checked, elapsed=elapsed())
