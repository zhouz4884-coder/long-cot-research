from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import unittest

from delivery_preservation import (
    CONTEXT_CAP, ELIGIBLE_NATIVE_EOS, FINAL, FORMAT_FAILURE, KEEP_NATIVE, RETAIN_CERTIFIED_INCUMBENT,
    SCOPE_UNKNOWN, THINKING, UNCERTAIN_TERMINATION, DeliveryPreserver, DeliveryScope, Observation, PointCustody,
    naive_best_verified, point,
)


def digest(text):
    return sha256(text.encode()).hexdigest()


def domain_checker(binding, value, meter):
    meter.charge("range_predicate")
    if value == 999:
        return point.PointEvidence(point.UNKNOWN)
    if value < 0:
        meter.charge("exclusion_proof")
        return point.PointEvidence(point.PROVEN_INFEASIBLE, point.EXACT_NECESSARY_PREDICATE,
                                   (("negative_value", str(value)),), True)
    meter.charge("constraint:nonnegative")
    return point.PointEvidence(point.PROVEN_FEASIBLE, point.EXACT_FEASIBILITY_WITNESS,
                               (("value", str(value)),), True, ("nonnegative",))


def case(direction="MAX", sample="test:draw-00"):
    binding = point.ObjectiveBinding(digest("question"), "target", digest("scope"), digest("constraints"), direction)
    contract = point.ReviewedPointContract(binding, ("nonnegative",), "test.delivery", 1, "domain_checker",
                                           point.checker_source_sha256(domain_checker), point.EXACT_NECESSARY_PREDICATE,
                                           digest("proof"), digest("review"))
    scope = DeliveryScope(binding, "original-units", contract.sha256, contract.checker_source_sha256, sample,
                          digest("response-" + sample))
    return contract, scope


def observation(scope, value, ordinal, previous=""):
    label = "\nThe original target equals "
    declaration = label + value + "."
    prefix = previous + declaration
    start = len(previous)
    numeric_start = start + len(label)
    candidate = point.CandidateReceipt(scope.binding, scope.sample_id, scope.response_sha256, digest(prefix),
                                       (numeric_start, numeric_start + len(value)), value,
                                       (start, len(prefix)), digest(declaration), point.ASSERTED_ORIGINAL_CANDIDATE,
                                       digest("independent role review"))
    return Observation(candidate, scope.unit_id, FINAL if ordinal == 3 else THINKING, ordinal), prefix


def custody(contract, scope, *observations):
    checker = point.PointVerifier(contract, contract.sha256, domain_checker,
                                  approved_candidate_sha256=[item.candidate.sha256 for item, _ in observations],
                                  call_budget=8, work_budget=100)
    return PointCustody(scope, scope.sha256, checker, approved_observation_sha256=[item.sha256 for item, _ in observations])


class DeliveryPreservationTests(unittest.TestCase):
    def compare_policies(self, proofs, thinking, termination, final=None, native_value=None):
        preserver = DeliveryPreserver(proofs)
        updates = [preserver.observe(ticket) for ticket in thinking]
        result = preserver.finish(termination, final, native_value=native_value)
        ordinary = naive_best_verified(proofs, thinking, termination, final, native_value=native_value)
        for name in ("status", "action", "native_value", "proposed_value", "incumbent_value",
                     "incumbent_ticket_sha256", "final_ticket_sha256"):
            self.assertEqual(getattr(result, name), getattr(ordinary, name), name)
        self.assertEqual(sum(update.comparison_operations for update in updates) + result.comparison_operations,
                         ordinary.comparison_operations)
        return updates, result, preserver

    def test_max_and_min_regression_with_independent_naive_parity(self):
        for direction, first, better, final_value in (("MAX", "40", "50", "42"), ("MIN", "50", "40", "42")):
            with self.subTest(direction=direction):
                contract, scope = case(direction)
                early = observation(scope, first, 1)
                late = observation(scope, better, 2, early[1])
                final = observation(scope, final_value, 3)
                authority = custody(contract, scope, early, late, final)
                thinking = [authority.check(*item) for item in (early, late)]
                terminal = authority.check(*final)
                updates, result, _ = self.compare_policies(authority, thinking, ELIGIBLE_NATIVE_EOS, terminal, final_value)
                self.assertEqual([r.status for r in updates], ["FIRST_FEASIBLE_INCUMBENT", "IMPROVED_INCUMBENT"])
                self.assertEqual((result.status, result.action, result.proposed_value),
                                 ("FEASIBLE_REGRESSION", RETAIN_CERTIFIED_INCUMBENT, better))
                self.assertEqual((authority.report()["point_checker_calls"], authority.report()["point_work"]), (3, 6))

    def test_earliest_exact_tie_and_improving_final(self):
        contract, scope = case()
        early = observation(scope, r"\frac{1}{2}", 1)
        late = observation(scope, "0.50", 2, early[1])
        final = observation(scope, "3/4", 3)
        authority = custody(contract, scope, early, late, final)
        a, b, c = [authority.check(*row) for row in (early, late, final)]
        updates, result, _ = self.compare_policies(authority, [a, b], ELIGIBLE_NATIVE_EOS, c, Fraction(3, 4))
        self.assertEqual(updates[-1].status, "KEPT_INCUMBENT")
        self.assertEqual(result.incumbent_ticket_sha256, a.sha256)
        self.assertEqual((result.status, result.action, result.proposed_value),
                         ("FEASIBLE_IMPROVEMENT", KEEP_NATIVE, "3/4"))

    def test_feasible_final_tie_and_no_incumbent(self):
        contract, scope = case()
        early, final = observation(scope, "1/2", 1), observation(scope, "0.50", 3)
        authority = custody(contract, scope, early, final)
        a, b = [authority.check(*row) for row in (early, final)]
        _, tied, _ = self.compare_policies(authority, [a], ELIGIBLE_NATIVE_EOS, b, "2/4")
        _, absent, _ = self.compare_policies(authority, [], ELIGIBLE_NATIVE_EOS, b, "2/4")
        self.assertEqual((tied.status, tied.action), ("FEASIBLE_TIE", KEEP_NATIVE))
        self.assertEqual((absent.status, absent.action), ("FEASIBLE_WITHOUT_INCUMBENT", KEEP_NATIVE))

    def test_infeasible_or_unknown_thinking_cannot_overwrite(self):
        for value in ("-1", "999"):
            with self.subTest(value=value):
                contract, scope = case("MIN")
                early = observation(scope, "50", 1)
                late = observation(scope, value, 2, early[1])
                final = observation(scope, "60", 3)
                authority = custody(contract, scope, early, late, final)
                a, b, c = [authority.check(*row) for row in (early, late, final)]
                updates, result, _ = self.compare_policies(authority, [a, b], ELIGIBLE_NATIVE_EOS, c, 60)
                self.assertEqual(updates[-1].status, "POINT_NOT_PROVEN_FEASIBLE")
                self.assertEqual(result.incumbent_value, "50")

    def test_infeasible_unknown_and_ineligible_finals_keep_native(self):
        for value, termination, expected in (
            ("-5", ELIGIBLE_NATIVE_EOS, "FINAL_INFEASIBLE"),
            ("999", ELIGIBLE_NATIVE_EOS, "FINAL_FEASIBILITY_UNKNOWN"),
            ("40", FORMAT_FAILURE, "FINAL_FORMAT_FAILURE"),
            ("40", CONTEXT_CAP, "FINAL_CONTEXT_CAP"),
            ("40", SCOPE_UNKNOWN, "FINAL_SCOPE_UNKNOWN"),
            ("40", UNCERTAIN_TERMINATION, "FINAL_TERMINATION_UNCERTAIN"),
        ):
            with self.subTest(value=value, termination=termination):
                contract, scope = case()
                early, final = observation(scope, "50", 1), observation(scope, value, 3)
                authority = custody(contract, scope, early, final)
                a, b = [authority.check(*row) for row in (early, final)]
                _, result, _ = self.compare_policies(authority, [a], termination, b, value)
                self.assertEqual((result.status, result.action, result.proposed_value, result.incumbent_value),
                                 (expected, KEEP_NATIVE, value, "50"))

    def test_separate_final_scalar_and_stage_must_agree(self):
        contract, scope = case()
        early, final = observation(scope, "50", 1), observation(scope, "40", 3)
        authority = custody(contract, scope, early, final)
        a, b = [authority.check(*row) for row in (early, final)]
        _, mismatch, _ = self.compare_policies(authority, [a], ELIGIBLE_NATIVE_EOS, b, 41)
        _, wrong_stage, _ = self.compare_policies(authority, [a], ELIGIBLE_NATIVE_EOS, a, 50)
        self.assertEqual((mismatch.status, mismatch.action), ("FINAL_READOUT_MISMATCH", KEEP_NATIVE))
        self.assertEqual((wrong_stage.status, wrong_stage.action), ("FINAL_SCOPE_UNKNOWN", KEEP_NATIVE))

    def test_forged_or_other_custody_receipts_cannot_authorize(self):
        contract, scope = case()
        early, final = observation(scope, "50", 1), observation(scope, "40", 3)
        a = custody(contract, scope, early, final)
        b = custody(contract, scope, early, final)
        early_a, final_b = a.check(*early), b.check(*final)
        policy = DeliveryPreserver(a)
        self.assertEqual(policy.observe(replace(early_a)).status, "UNTRUSTED_OR_NONTHINKING_POINT")
        self.assertEqual(policy.observe(early_a.as_dict()).status, "UNTRUSTED_OR_NONTHINKING_POINT")
        policy.observe(early_a)
        self.assertEqual(policy.finish(ELIGIBLE_NATIVE_EOS, final_b, native_value=40).status, "FINAL_SCOPE_UNKNOWN")

    def test_unit_scope_and_response_identity_must_match_approval(self):
        contract, scope = case()
        early = observation(scope, "50", 1)
        item, prefix = early
        mismatches = [replace(item, unit_id="converted-units")]
        for field, value in (("sample_id", "test:draw-01"), ("response_sha256", digest("unrelated")),
                             ("binding", replace(scope.binding, direction="MIN")),
                             ("binding", replace(scope.binding, objective_id="other-target")),
                             ("binding", replace(scope.binding, question_sha256=digest("other question")))):
            mismatches.append(replace(item, candidate=replace(item.candidate, **{field: value})))
        authority = custody(contract, scope, early, *((x, prefix) for x in mismatches))
        for wrong in mismatches:
            self.assertEqual(authority.check(wrong, prefix).status, "DELIVERY_SCOPE_MISMATCH")
        different = replace(item, candidate=replace(item.candidate, assertion_review_sha256=digest("unissued review")))
        self.assertEqual(authority.check(different, prefix).status, "OBSERVATION_NOT_ISSUED")
        self.assertEqual(authority.report()["point_checker_calls"], 0)

    def test_prefix_lineage_and_chronology_come_before_policy_updates(self):
        contract, scope = case()
        early = observation(scope, "50", 1)
        bad_late = observation(scope, "55", 2)
        late = observation(scope, "60", 2, early[1])
        final = observation(scope, "42", 3)
        authority = custody(contract, scope, early, bad_late, late, final)
        a = authority.check(*early)
        self.assertEqual(authority.check(*bad_late).status, "NONMONOTONE_THINKING_PREFIX")
        b = authority.check(*late)
        self.assertEqual(authority.check(*early).status, "OUT_OF_ORDER_OBSERVATION")
        c = authority.check(*final)
        updates, decision, engine = self.compare_policies(authority, [b, a], ELIGIBLE_NATIVE_EOS, c, 42)
        self.assertEqual(updates[-1].status, "OUT_OF_ORDER_OBSERVATION")
        self.assertEqual(decision.proposed_value, "60")
        self.assertEqual(engine.observe(a).status, "DELIVERY_ALREADY_FINALIZED")
        with self.assertRaisesRegex(RuntimeError, "already finalized"):
            engine.finish(ELIGIBLE_NATIVE_EOS, c, native_value=42)

    def test_bad_source_cannot_consume_ordinal_or_replace_incumbent(self):
        contract, scope = case()
        early = observation(scope, "50", 1)
        authority = custody(contract, scope, early)
        a = authority.check(early[0], early[1] + " future")
        self.assertEqual(a.status, "POINT_INPUT_REJECTED")
        self.assertFalse(authority.authentic(a))
        b = authority.check(*early)
        self.assertTrue(authority.authentic(b))
        self.assertEqual(authority.report()["point_checker_calls"], 1)


if __name__ == "__main__":
    unittest.main()
