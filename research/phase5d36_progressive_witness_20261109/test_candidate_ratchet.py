"""Adverse controls for the event-driven state and point-only release policy."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from candidate_ratchet import ProgressiveWitness
from candidate_archive import ObservedPrefix, observe
from goal_claim_detector import target_id_for
from point_verifier import PointVerifier
from progress_state import OppositeBoundReceipt
from witness_contract import WorkMeter, compile_contract, least_prime_certificate


ROOT = Path(__file__).resolve().parent.parent / "phase5d25_constraint_revision_20261109/prepared_data"


def contract_from_visible(case, subset="bank"):
    path = ROOT / subset / "visible.jsonl"
    record = next(record for line in path.read_bytes().splitlines() if (record := json.loads(line))["case_id"] == case)
    return compile_contract(record["question"])


def prefix(contract, text, *, trajectory="trial"):
    return ObservedPrefix.from_tokens(list(map(ord, text)), lambda ids: "".join(map(chr, ids)),
                                      prompt_ids=list(map(ord, "<think>")), tokenizer_sha256=sha256(b"ascii").hexdigest(),
                                      trajectory_id=trajectory, question_sha256=contract.question_sha256)


def commitment(contract, observation, value, *, terminal=False, prime=None):
    value_text = str(value)
    left = observation.text.rindex(value_text)
    value_span = (left, left + len(value_text))
    fields = {"value": value_span}
    assignments = {}
    if prime is not None:
        marker = f"p={prime}"
        start = observation.text.rindex(marker, 0, left)
        fields["p"] = (start + 2, start + len(marker))
        assignments["p"] = prime
    goal = contract.goal
    kind = {"MAX": "MAXIMALITY_CLAIM", "MIN": "MINIMALITY_CLAIM"}[goal] if terminal else "FEASIBLE_CANDIDATE"
    claim = {"kind": goal, "value": value, **assignments} if terminal else {}
    return observe(observation, contract_id=contract.contract_id, target_id=target_id_for(contract),
                   goal_claim_type=kind, role="explicit_commitment" if terminal else "observed_candidate",
                   source=value_span, fields=fields, value=value, assignments=assignments, claim=claim)


class CandidateRatchetTest(unittest.TestCase):
    def setUp(self):
        self.contract = contract_from_visible("D3_E15")
        self.initial = prefix(self.contract, "Candidate 1011235.\n\n")

    def append(self, text):
        return prefix(self.contract, self.initial.text + text)

    def seed(self, controller):
        return controller.admit(self.initial, commitment(self.contract, self.initial, 1011235), feedback=False)

    def admit(self, controller, suffix, value, **kwargs):
        p = self.append(suffix)
        return controller.admit(p, commitment(self.contract, p, value, terminal=kwargs.get("terminal", False)), **kwargs)

    def test_e15_dual_ratchet_uses_real_point_arithmetic(self):
        ratchet = ProgressiveWitness(self.contract, self.initial)
        seed = self.seed(ratchet)
        self.assertIsNone(seed.obligation)
        improved = self.admit(ratchet, "Candidate 10112358.\n\n", 10112358)
        self.assertEqual(improved.action, "UPDATE_BOUND")
        self.assertEqual(improved.receipt.status, "CERTIFIED_FEASIBLE")
        self.assertIn("Find a strictly greater feasible", improved.obligation.message)
        invalid = self.admit(ratchet, "Candidate 10112357.\n\n", 10112357)
        self.assertEqual(invalid.action, "REPAIR_INFEASIBLE")
        self.assertEqual(invalid.receipt.status, "CERTIFIED_INFEASIBLE")
        self.assertIn("position 8 because 7 < 3 + 5", invalid.obligation.message)
        self.assertFalse(invalid.veto)
        dominated = self.admit(ratchet, "</think>\nFinal answer 303369.", 303369, terminal=True)
        self.assertTrue(dominated.veto)
        self.assertEqual(dominated.action, "BLOCK_REGRESSION")
        self.assertEqual(ratchet.state.incumbent.objective, 10112358)
        self.assertEqual(ratchet.report()["point_calls"], 4)
        self.assertEqual(ratchet.report()["paid_operations"], 6 + 7 + 7 + 5)

    def test_exhaustion_preserves_unknown_and_cached_veto(self):
        ratchet = ProgressiveWitness(self.contract, self.initial, point_budget=2, feedback_budget=0)
        self.seed(ratchet)
        first = self.admit(ratchet, "Candidate 10112357.", 10112357)
        last = self.admit(ratchet, "</think>\nFinal answer 10112357.", 10112357, terminal=True)
        self.assertTrue(last.veto)
        self.assertIsNone(last.obligation)
        self.assertEqual(last.receipt.cached_from, first.receipt.receipt_sha256)
        self.assertEqual(last.receipt.paid_point_calls, 0)
        unknown = self.admit(ratchet, "</think>\nFinal answer 10112369.", 10112369, terminal=True)
        self.assertEqual(unknown.action, "NATIVE_CONTINUE")
        self.assertFalse(unknown.veto)
        self.assertIsNone(unknown.certified_answer)
        self.assertEqual(ratchet.state.incumbent.objective, 1011235)
        self.assertEqual(ratchet.report()["point_calls"], 2)

    def test_work_exhaustion_is_paid_and_cannot_promote(self):
        ratchet = ProgressiveWitness(self.contract, self.initial, work_budget=1)
        seed = self.seed(ratchet)
        self.assertEqual(seed.action, "NATIVE_CONTINUE")
        self.assertEqual(seed.receipt.paid_operations, 1)
        self.assertIsNone(ratchet.state.incumbent)
        self.assertEqual(ratchet.report()["paid_operations"], 1)

    def test_tools_only_and_source_bound_ratchet_pay_the_same_point_predicate(self):
        tool = PointVerifier(self.contract, point_budget=1)
        controller = ProgressiveWitness(self.contract, self.initial, point_budget=1)
        direct = tool.check(1011235)
        source_bound = self.seed(controller).receipt
        self.assertEqual(direct.status, source_bound.status)
        self.assertEqual(direct.math, source_bound.math)
        self.assertEqual(direct.paid_operations, source_bound.paid_operations)
        self.assertEqual(tool.check(1011235).paid_point_calls, 0)
        self.assertEqual(tool.check(10112358).status, "UNKNOWN")
        self.assertEqual(tool.check({"python": "not a point"}).math["reason"], "malformed_point")
        self.assertEqual(tool.report()["point_calls"], 1)

    def test_feasibility_alone_never_certifies_a_natural_final(self):
        ratchet = ProgressiveWitness(self.contract, self.initial)
        self.seed(ratchet)
        decision = self.admit(ratchet, "</think>\nFinal answer 10112369.", 10112369, terminal=True)
        self.assertEqual(decision.receipt.status, "CERTIFIED_FEASIBLE")
        self.assertFalse(decision.veto)
        self.assertIsNone(decision.obligation)
        self.assertIsNone(decision.certified_answer)
        self.assertIsNone(ratchet.state.certified_answer)

    def test_event_cadence_distinct_from_every_step_with_same_point_cost(self):
        event = ProgressiveWitness(self.contract, self.initial, mode="event")
        every = ProgressiveWitness(self.contract, self.initial, mode="every_step")
        for controller in (event, every):
            self.seed(controller)
            repeat = self.admit(controller, "I reconstructed 1011235.", 1011235)
            self.assertEqual(repeat.action, "KEEP_BOUND")
            self.assertEqual(repeat.receipt.paid_operations, 0)
            self.assertEqual(controller.report()["point_calls"], 1)
        self.assertEqual(event.report()["feedback_emitted"], 0)
        self.assertEqual(every.report()["feedback_emitted"], 1)

    def test_source_cannot_be_future_forced_forged_or_cross_trajectory(self):
        ratchet = ProgressiveWitness(self.contract, self.initial)
        later = self.append("Candidate 10112358.")
        candidate = commitment(self.contract, later, 10112358)
        with self.assertRaises(ValueError):
            ratchet.admit(self.initial, candidate)
        with self.assertRaises(ValueError):
            ratchet.admit(later, candidate, authored_span=(0, self.initial.observed_count))
        with self.assertRaises(ValueError):
            ratchet.admit(replace(later, text=later.text.replace("10112358", "10112357")), candidate)
        with self.assertRaises(ValueError):
            ratchet.admit(replace(later, trajectory_id="different"), candidate)
        with self.assertRaises(ValueError):
            ratchet.admit(later, candidate, terminal=True)
        self.assertEqual(ratchet.report()["point_calls"], 0)

    def test_receipt_is_immutable_and_bound_to_observed_prefix(self):
        ratchet = ProgressiveWitness(self.contract, self.initial)
        verdict = self.seed(ratchet)
        self.assertEqual(verdict.receipt.observed_prefix_sha256, self.initial.prefix_sha256)
        with self.assertRaises(FrozenInstanceError):
            verdict.receipt.objective = 0
        verdict.receipt.math["status"] = "UNKNOWN"
        self.assertEqual(verdict.receipt.math["status"], "FEASIBLE_ONLY")
        self.assertEqual(verdict.obligation, None)

    def test_opposite_bound_requires_scope_and_consistency(self):
        ratchet = ProgressiveWitness(self.contract, self.initial)
        self.seed(ratchet)
        bound = ratchet.certify_opposite_bound()
        self.assertEqual(bound.value, 99_999_999)
        self.assertEqual(bound.derivation, (1, 0, 1, 1, 2, 3, 5, 8, 13))
        self.assertIsNone(ratchet.state.certified_answer)
        with self.assertRaises(ValueError):
            ratchet.state.tighten(replace(bound, value=0))
        with self.assertRaises(ValueError):
            ratchet.state.tighten(replace(bound, target_id="other"))
        fixture = OppositeBoundReceipt(ratchet.state.contract_id, ratchet.state.target_id,
                                       ratchet.state.question_sha256, "MAX", 1011235, "invariant_fixture", (), 0)
        self.assertEqual(ratchet.state.tighten(fixture).certified_answer, 1011235)
        self.assertIsNone(ratchet.state.certified_answer)

    def test_min_only_promotes_under_replayable_complete_domain_proof(self):
        contract = contract_from_visible("D3_P02", "precheck")
        p = prefix(contract, "Using p=17, candidate 134.\n\n")
        c = commitment(contract, p, 134, prime=17)
        unknown = ProgressiveWitness(contract, p)
        self.assertEqual(unknown.admit(p, c).action, "NATIVE_CONTINUE")
        self.assertIsNone(unknown.state.incumbent)
        prerequisite = least_prime_certificate(contract, WorkMeter(1_000))
        controller = ProgressiveWitness(contract, p, work_budget=3_000, prerequisite=prerequisite)
        self.assertEqual(controller.admit(p, c).action, "UPDATE_BOUND")
        better = prefix(contract, p.text + "Using p=17, candidate 110.")
        verdict = controller.admit(better, commitment(contract, better, 110, prime=17))
        self.assertEqual(verdict.action, "UPDATE_BOUND")
        self.assertIn("feasible upper bound is 110", verdict.obligation.message)
        self.assertGreater(verdict.receipt.paid_operations, 500)
        self.assertIsNone(verdict.certified_answer)


if __name__ == "__main__":
    unittest.main()
