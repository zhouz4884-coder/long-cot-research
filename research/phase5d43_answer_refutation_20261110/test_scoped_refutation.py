"""Trust boundary, exact finite predicate and shared-budget regressions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import unittest

from scoped_refutation import (CHECKER_ID, CHECKER_VERSION, CLOSED_INTERVAL, CONGRUENCE, EXPLICIT_QUESTION,
                               FINITE_EXCLUSIONS, MAX_ABS_INTEGER, MAX_CANDIDATES, MAX_EXCLUSIONS, PREDICATE_BUDGET,
                               REVIEWED_NECESSARY_DERIVATION, NecessaryPredicate, ObjectiveBinding,
                               ReviewedPrerequisite, ScopedRefutationState, application_signature)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


Q = sha("synthetic question")
BINDING = ObjectiveBinding(Q, "q.control.final", "REQUESTED_INTEGER")


def reviewed(kind, args, binding=BINDING, review="review-a"):
    predicate = NecessaryPredicate(kind, args)
    return ReviewedPrerequisite(binding, predicate, REVIEWED_NECESSARY_DERIVATION, sha("prerequisite-source"),
                                sha(review), application_signature(binding, predicate))


def state(*prerequisites):
    return ScopedRefutationState(Q, (p.sha256 for p in prerequisites))


class ScopedRefutationTests(unittest.TestCase):
    def assert_unknown(self, batch):
        self.assertEqual(batch.status, "UNKNOWN")
        self.assertEqual(batch.paid_predicate_calls, 0)
        self.assertEqual(batch.paid_candidate_evaluations, 0)
        self.assertEqual(batch.primitive_numeric_operations, 0)
        self.assertEqual(batch.receipts, ())
        self.assertGreaterEqual(batch.request_cpu_ns, 0)

    def test_congruence_records_exact_negative_residue_and_refutes_only_wrong_point(self):
        prior = reviewed(CONGRUENCE, (5, 4))
        checker = state(prior)
        batch = checker.check_candidates(BINDING, (-1, -2, 9, 0), prior)
        self.assertEqual(batch.status, "EVALUATED")
        self.assertEqual((batch.paid_predicate_calls, batch.paid_candidate_evaluations, batch.primitive_numeric_operations), (1, 4, 8))
        self.assertEqual([r.status for r in batch.receipts], ["NOT_REFUTED", "REFUTED", "NOT_REFUTED", "REFUTED"])
        self.assertEqual(dict(batch.receipts[1].arithmetic), {"modulus": 5, "expected_residue": 4, "observed_residue": 3})
        self.assertFalse(checker.authorizes_refutation(BINDING, -1, batch.receipts[0]))
        self.assertTrue(checker.authorizes_refutation(BINDING, -2, batch.receipts[1]))
        self.assertFalse(checker.authorizes_refutation(BINDING, 9, batch.receipts[1]))
        self.assertIsNone(batch.receipts[0].as_dict()["certificate_sha256"])

    def test_interval_is_closed_and_signed(self):
        prior = reviewed(CLOSED_INTERVAL, (-7, 3))
        batch = state(prior).check_candidates(BINDING, (-8, -7, 0, 3, 4), prior)
        self.assertEqual([r.status for r in batch.receipts], ["REFUTED", "NOT_REFUTED", "NOT_REFUTED", "NOT_REFUTED", "REFUTED"])
        self.assertEqual(batch.primitive_numeric_operations, 10)
        self.assertEqual(dict(batch.receipts[0].arithmetic), {"lower": -7, "upper": 3, "below": True, "above": False})
        self.assertEqual(dict(batch.receipts[-1].arithmetic), {"lower": -7, "upper": 3, "below": False, "above": True})

    def test_finite_exclusions_account_for_all_candidate_comparisons(self):
        prior = reviewed(FINITE_EXCLUSIONS, (-5, 0, 8))
        batch = state(prior).check_candidates(BINDING, (0, 2, -5), prior)
        self.assertEqual([r.status for r in batch.receipts], ["REFUTED", "NOT_REFUTED", "REFUTED"])
        self.assertEqual(batch.primitive_numeric_operations, 9)
        self.assertEqual([r.primitive_numeric_operations for r in batch.receipts], [3, 3, 3])
        self.assertEqual(dict(batch.receipts[0].arithmetic), {"excluded_values_checked": 3, "matched": True})

    def test_no_provenance_no_math_even_for_obvious_violation(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        checker = state()
        self.assert_unknown(checker.check_candidates(BINDING, (1,), None))
        self.assert_unknown(checker.check_candidates(BINDING, (1,), prior))
        report = checker.report()
        self.assertEqual(report["requests"], 2)
        self.assertEqual(report["paid_predicate_calls"], 0)
        self.assertEqual(report["evaluation_cpu_ns"], 0)

    def test_trace_source_and_invalid_explicit_question_source_cannot_authorize(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        trace = replace(prior, source_kind="MODEL_TRACE")
        unrelated = replace(prior, source_kind=EXPLICIT_QUESTION)
        checker = state(trace, unrelated)
        for fake in (trace, unrelated):
            self.assert_unknown(checker.check_candidates(BINDING, (1,), fake))
        self.assertEqual(checker.report()["paid_predicate_calls"], 0)

    def test_explicit_problem_source_requires_matching_question_digest(self):
        prior = replace(reviewed(CONGRUENCE, (2, 0)), source_kind=EXPLICIT_QUESTION, source_sha256=Q)
        checker = state(prior)
        hit, = checker.check_candidates(BINDING, (1,), prior).receipts
        self.assertTrue(checker.authorizes_refutation(BINDING, 1, hit))

    def test_cross_question_objective_and_application_signatures_abstain(self):
        prior = reviewed(CLOSED_INTERVAL, (0, 1))
        wrong_signature = replace(prior, application_sha256=sha("other signature"))
        checker = state(prior, wrong_signature)
        other_q = replace(BINDING, question_sha256=sha("different question"))
        other_objective = replace(BINDING, objective_id="q.control.helper")
        other_scope = replace(BINDING, scope="INTERMEDIATE_INTEGER")
        for binding in (other_q, other_objective, other_scope, None):
            self.assert_unknown(checker.check_candidates(binding, (2,), prior))
        self.assert_unknown(checker.check_candidates(BINDING, (2,), wrong_signature))
        self.assertEqual(checker.report()["paid_predicate_calls"], 0)

    def test_reauthoring_same_predicate_and_batch_splitting_cannot_recheck(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        different_review = reviewed(CONGRUENCE, (2, 0), review="review-b")
        self.assertNotEqual(prior.sha256, different_review.sha256)
        self.assertEqual(prior.application_sha256, different_review.application_sha256)
        checker = state(prior, different_review)
        first = checker.check_candidates(BINDING, (1, 2), prior)
        repeat = checker.check_candidates(BINDING, (3,), prior)
        alias = checker.check_candidates(BINDING, (4,), different_review)
        self.assert_unknown(repeat)
        self.assert_unknown(alias)
        self.assertEqual(repeat.reason, "duplicate_predicate_application")
        self.assertEqual(alias.reason, "duplicate_predicate_application")
        report = checker.report()
        self.assertEqual((report["requests"], report["paid_predicate_calls"], report["paid_candidate_evaluations"]), (3, 1, 2))
        self.assertEqual(report["request_cpu_ns"], first.request_cpu_ns + repeat.request_cpu_ns + alias.request_cpu_ns)

    def test_two_calls_are_shared_over_all_candidates_and_scopes(self):
        first = reviewed(CONGRUENCE, (2, 0))
        second_binding = replace(BINDING, scope="ALTERNATE_INTEGER")
        second = reviewed(CLOSED_INTERVAL, (-2, 2), binding=second_binding)
        third = reviewed(CONGRUENCE, (3, 1))
        checker = state(first, second)
        values = tuple(range(MAX_CANDIDATES))
        one = checker.check_candidates(BINDING, values, first)
        two = checker.check_candidates(second_binding, values, second)
        self.assertEqual({r.predicate_call for r in one.receipts}, {1})
        self.assertEqual({r.predicate_call for r in two.receipts}, {2})
        self.assertEqual([r.candidate_index for r in two.receipts], list(range(1, 9)))
        self.assert_unknown(checker.check_candidates(BINDING, (9,), third))
        self.assert_unknown(checker.check_candidates(second_binding, (9,), second))
        report = checker.report()
        self.assertEqual((report["paid_predicate_calls"], report["paid_candidate_evaluations"],
                          report["primitive_numeric_operations"]), (PREDICATE_BUDGET, 16, 32))
        with self.assertRaises(ValueError):
            state(first, second, third)

    def test_bad_points_and_batch_size_do_not_consume_evaluations(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        checker = state(prior)
        for payload in ([], [False], [1.0], ["1"], [MAX_ABS_INTEGER + 1], [-MAX_ABS_INTEGER - 1],
                        [1, 1], tuple(range(9)), (i for i in range(1))):
            with self.subTest(payload_type=type(payload)):
                self.assert_unknown(checker.check_candidates(BINDING, payload, prior))
        self.assertEqual(checker.report()["paid_predicate_calls"], 0)
        self.assertEqual(checker.check_candidates(BINDING, (MAX_ABS_INTEGER,), prior).paid_predicate_calls, 1)

    def test_noncanonical_or_unbounded_predicates_fail_closed_even_if_allowlisted(self):
        prior = reviewed(CONGRUENCE, (5, 4))
        malformed = (
            NecessaryPredicate(CONGRUENCE, (0, 0)), NecessaryPredicate(CONGRUENCE, (5, -1)),
            NecessaryPredicate(CONGRUENCE, (5, 5)), NecessaryPredicate(CLOSED_INTERVAL, (2, 1)),
            NecessaryPredicate(FINITE_EXCLUSIONS, (1, 1)), NecessaryPredicate(FINITE_EXCLUSIONS, (2, 1)),
            NecessaryPredicate(FINITE_EXCLUSIONS, tuple(range(MAX_EXCLUSIONS + 1))),
            NecessaryPredicate("UNREVIEWED_PROGRAM", (1,)), NecessaryPredicate(CONGRUENCE, (True, 0)),
        )
        for invalid in malformed:
            with self.subTest(invalid=invalid):
                fake = replace(prior, predicate=invalid)
                self.assert_unknown(state(fake).check_candidates(BINDING, (1,), fake))
                with self.assertRaises(ValueError):
                    application_signature(BINDING, invalid)

    def test_receipt_proof_authority_requires_state_identity_and_exact_value(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        checker = state(prior)
        hit, = checker.check_candidates(BINDING, (1,), prior).receipts
        copy = replace(hit)
        same_numeric_new_scope = replace(BINDING, scope="OTHER")
        self.assertTrue(checker.authorizes_refutation(BINDING, 1, hit))
        self.assertFalse(checker.authorizes_refutation(BINDING, 1, copy))
        self.assertFalse(checker.authorizes_refutation(same_numeric_new_scope, 1, hit))
        self.assertFalse(checker.authorizes_refutation(BINDING, True, hit))
        self.assertFalse(state(prior).authorizes_refutation(BINDING, 1, hit))

    def test_receipt_fingerprint_binds_checker_target_provenance_arithmetic_and_cost(self):
        prior = reviewed(CONGRUENCE, (2, 0))
        batch = state(prior).check_candidates(BINDING, (1,), prior)
        hit = batch.receipts[0]
        raw = batch.as_dict()
        item, = raw["receipts"]
        self.assertEqual((raw["checker_id"], raw["checker_version"]), (CHECKER_ID, CHECKER_VERSION))
        self.assertEqual(item["prerequisite"]["binding"]["question_sha256"], Q)
        self.assertEqual(item["prerequisite"]["review_sha256"], prior.review_sha256)
        self.assertEqual(item["prerequisite"]["application_sha256"], prior.application_sha256)
        self.assertEqual(item["certificate_sha256"], item["receipt_sha256"])
        self.assertEqual(json.loads(json.dumps(raw))["batch_receipt_sha256"], raw["batch_receipt_sha256"])
        self.assertNotEqual(hit.sha256, replace(hit, evaluation_cpu_ns=hit.evaluation_cpu_ns + 1).sha256)
        self.assertNotEqual(hit.sha256, replace(hit, arithmetic=(("observed_residue", 0),)).sha256)
        self.assertGreaterEqual(item["evaluation_cpu_ns"], 0)

    def test_concurrent_retries_cannot_split_predicate_budget(self):
        first = reviewed(CONGRUENCE, (2, 0))
        second = reviewed(CLOSED_INTERVAL, (-1, 1))
        checker = state(first, second)
        plans = [first, second] * 8
        with ThreadPoolExecutor(max_workers=6) as workers:
            receipts = list(workers.map(lambda p: checker.check_candidates(BINDING, (2, 3), p), plans))
        self.assertEqual(sum(row.paid_predicate_calls for row in receipts), 2)
        self.assertEqual(sum(row.paid_candidate_evaluations for row in receipts), 4)
        self.assertEqual(checker.report()["requests"], len(plans))
        self.assertEqual(checker.report()["request_cpu_ns"], sum(row.request_cpu_ns for row in receipts))


if __name__ == "__main__":
    unittest.main()
