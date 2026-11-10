from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import unittest

from point_verifier import (
    ASSERTED_ORIGINAL_CANDIDATE, COMPLETE_FIXED_VALUE_FIBER, EXACT_CONTRADICTION, EXACT_FEASIBILITY_WITNESS,
    EXACT_NECESSARY_PREDICATE, PROVEN_FEASIBLE, PROVEN_INFEASIBLE, UNKNOWN, CandidateReceipt, ObjectiveBinding,
    PointEvidence, PointVerifier, ReviewedPointContract, checker_source_sha256, exact_literal,
)


CONSTRAINTS = ("integer_domain", "even_nonnegative")


def synthetic_checker(binding, value, meter):
    """A small reviewed domain with test-only bad checker responses."""
    task = binding.objective_id
    if task in ("fiber", "unexhausted", "unmetered-fiber", "empty-fiber", "budget"):
        expected = 0 if task == "empty-fiber" else 3
        meter.charge("exclusion_proof")
        visited = 0
        for _ in range(expected - int(task == "unexhausted")):
            if task != "unmetered-fiber":
                meter.charge("fiber_points")
            visited += 1
        return PointEvidence(PROVEN_INFEASIBLE, COMPLETE_FIXED_VALUE_FIBER, (("target", str(value)),),
                             complete=True, fiber_expected=expected, fiber_visited=visited)
    if value.denominator != 1 or value < 0 or value.numerator % 2:
        if task != "unmetered":
            meter.charge("exclusion_proof")
        kind = EXACT_CONTRADICTION if task in ("contradiction", "unreviewed") else EXACT_NECESSARY_PREDICATE
        detail = () if task == "no-detail" else (("value", str(value)), ("requires_nonnegative_even_integer", True))
        return PointEvidence(PROVEN_INFEASIBLE, kind, detail, complete=task != "partial")
    covered = CONSTRAINTS[:1] if task == "partial-positive" else CONSTRAINTS
    for key in covered:
        meter.charge("constraint:" + key)
    return PointEvidence(PROVEN_FEASIBLE, EXACT_FEASIBILITY_WITNESS, (("half", value.numerator // 2),),
                         complete=True, covered_constraints=covered)


def alternate_checker(binding, value, meter):
    return synthetic_checker(binding, value, meter)


def digest(text):
    return sha256(text.encode()).hexdigest()


def contract(task="even", direction="MIN", proof_kind=EXACT_NECESSARY_PREDICATE):
    binding = ObjectiveBinding(digest("question"), task, digest("original scope"), digest("original constraints"), direction)
    return ReviewedPointContract(binding, CONSTRAINTS, "test.synthetic-point", 1, "synthetic_checker",
                                 checker_source_sha256(synthetic_checker), proof_kind, digest("proof"), digest("review"))


def issue(binding, text, *, sample="test:draw-00", prefix_tail=""):
    prior = "例 🙂\n"
    subject = "The original requested value is "
    assertion = subject + text + "."
    prefix = prior + assertion + prefix_tail
    left = len(prior)
    num_start = left + len(subject)
    candidate = CandidateReceipt(binding, sample, digest("known source identity " + sample), digest(prefix),
                                 (num_start, num_start + len(text)), text, (left, left + len(assertion)),
                                 digest(assertion), ASSERTED_ORIGINAL_CANDIDATE, digest("role approval"))
    return candidate, prefix


def verifier(reviewed, *candidates, calls=4, work=30):
    return PointVerifier(reviewed, reviewed.sha256, synthetic_checker, approved_candidate_sha256=[c.sha256 for c in candidates],
                         call_budget=calls, work_budget=work)


class PointVerifierTests(unittest.TestCase):
    def test_exact_positive_and_negative_differ_in_authority(self):
        reviewed = contract()
        impossible, prefix = issue(reviewed.binding, "397")
        feasible, next_prefix = issue(reviewed.binding, "398", sample="test:draw-01")
        engine = verifier(reviewed, impossible, feasible)
        a = engine.check(impossible, prefix)
        b = engine.check(feasible, next_prefix)
        self.assertEqual((a.status, a.authority, a.checked_value), (PROVEN_INFEASIBLE, "REJECT_THIS_VALUE_ONLY", "397"))
        self.assertEqual((b.status, b.authority), (PROVEN_FEASIBLE, "FEASIBILITY_ONLY"))
        self.assertTrue(engine.authorizes_exclusion(impossible, a))
        self.assertFalse(engine.authorizes_exclusion(feasible, b))
        self.assertFalse(engine.authorizes_exclusion(feasible, a))
        self.assertEqual(engine.report()["used"], {"checker_calls": 2, "work": 3})
        self.assertEqual(a.as_dict()["candidate_sha256"], impossible.sha256)
        self.assertIsNotNone(a.as_dict()["evidence_sha256"])

    def test_exact_rational_and_unicode_input_with_scalar_value_direction(self):
        reviewed = contract(direction="VALUE")
        candidate, prefix = issue(reviewed.binding, r"$\mathrm{\frac{−6}{ 8 }}$")
        out = verifier(reviewed, candidate).check(candidate, prefix)
        self.assertEqual((out.status, out.checked_value), (PROVEN_INFEASIBLE, "-3/4"))
        for lexeme, exact in (("0007", 7), ("+0.50", Fraction(1, 2)), ("1 / -2", Fraction(-1, 2)),
                              (r"\(\dfrac{ 1 }{3}\)", Fraction(1, 3))):
            self.assertEqual(exact_literal(lexeme), exact)

    def test_numeric_lookalikes_and_nonfinite_values_do_not_call_the_checker(self):
        reviewed = contract()
        lexemes = ("1e2", "nan", "1/0", "++5", "3.2.0", "一", "9999999999999999999", "2^3", r"\boxed{7}")
        pairs = [issue(reviewed.binding, text, sample=f"test:malformed-{i}") for i, text in enumerate(lexemes)]
        engine = verifier(reviewed, *(c for c, _ in pairs))
        for candidate, prefix in pairs:
            with self.subTest(text=candidate.numeric_text):
                row = engine.check(candidate, prefix)
                self.assertEqual((row.status, row.reason, row.checker_calls, row.work),
                                 (UNKNOWN, "NONEXACT_OR_OUT_OF_RANGE_NUMBER", 0, 0))

    def test_contract_approval_binds_checker_and_original_constraints(self):
        reviewed = contract()
        params = {"approved_candidate_sha256": (), "call_budget": 4, "work_budget": 30}
        with self.assertRaisesRegex(ValueError, "reviewed contract"):
            PointVerifier(replace(reviewed, required_constraints=("integer_domain",)), reviewed.sha256, synthetic_checker, **params)
        with self.assertRaisesRegex(ValueError, "reviewed source"):
            PointVerifier(reviewed, reviewed.sha256, alternate_checker, **params)

    def test_forged_scope_source_and_role_fail_closed(self):
        reviewed = contract()
        base, prefix = issue(reviewed.binding, "300")
        cases = [
            (replace(base, binding=replace(base.binding, direction="MAX")), "ORIGINAL_BINDING_MISMATCH"),
            (replace(base, binding=replace(base.binding, question_sha256=digest("different question"))), "ORIGINAL_BINDING_MISMATCH"),
            (replace(base, binding=replace(base.binding, scope_sha256=digest("subgoal scope"))), "ORIGINAL_BINDING_MISMATCH"),
            (replace(base, binding=replace(base.binding, constraints_sha256=digest("relaxed"))), "ORIGINAL_BINDING_MISMATCH"),
            (replace(base, assertion_role="CONSTRAINT_THRESHOLD"), "ASSERTION_ROLE_MISMATCH"),
            (replace(base, assertion_role="TRIAL_VALUE"), "ASSERTION_ROLE_MISMATCH"),
        ]
        engine = verifier(reviewed, base, *(c for c, _ in cases))
        for candidate, reason in cases:
            self.assertEqual(engine.check(candidate, prefix).reason, reason)
        self.assertEqual(engine.check(replace(base, response_sha256=digest("different trajectory")), prefix).reason, "CANDIDATE_NOT_ISSUED")
        self.assertEqual(engine.check(base, prefix + " future").reason, "OBSERVED_PREFIX_MISMATCH")
        self.assertEqual(engine.report()["used"], {"checker_calls": 0, "work": 0})

    def test_numeric_and_assertion_spans_and_no_final_bytes(self):
        reviewed = contract()
        base, prefix = issue(reviewed.binding, "23")
        wrong_assertion = replace(base, assertion_sha256=digest("other source proposition"))
        wrong_number = replace(base, numeric_text="32")
        past_close, unsafe = issue(reviewed.binding, "23", prefix_tail="</think>future answer")
        engine = verifier(reviewed, base, wrong_assertion, wrong_number, past_close)
        for wrong in (wrong_assertion, wrong_number):
            self.assertEqual(engine.check(wrong, prefix).reason, "ASSERTION_OR_NUMERIC_SPAN_MISMATCH")
        self.assertEqual(engine.check(past_close, unsafe).reason, "NOT_OPEN_THINKING_PREFIX")
        self.assertEqual(engine.check(base, prefix).status, PROVEN_INFEASIBLE)

    def test_reviewed_exact_fiber_requires_measured_exhaustion(self):
        for task, expected, reason in (
            ("fiber", PROVEN_INFEASIBLE, "COMPLETE_REVIEWED_POINT_EXCLUSION"),
            ("empty-fiber", PROVEN_INFEASIBLE, "COMPLETE_REVIEWED_POINT_EXCLUSION"),
            ("unexhausted", UNKNOWN, "UNEXHAUSTED_FIXED_VALUE_FIBER"),
            ("unmetered-fiber", UNKNOWN, "UNEXHAUSTED_FIXED_VALUE_FIBER"),
        ):
            with self.subTest(task=task):
                reviewed = contract(task, proof_kind=COMPLETE_FIXED_VALUE_FIBER)
                candidate, prefix = issue(reviewed.binding, "5")
                receipt = verifier(reviewed, candidate).check(candidate, prefix)
                self.assertEqual((receipt.status, receipt.reason), (expected, reason))
                self.assertEqual(receipt.work, 1 + dict(receipt.operation_charges).get("fiber_points", 0))

    def test_exact_contradiction_must_match_reviewed_proof_mode(self):
        for task, kind, expected, reason in (
            ("contradiction", EXACT_CONTRADICTION, PROVEN_INFEASIBLE, "COMPLETE_REVIEWED_POINT_EXCLUSION"),
            ("unreviewed", EXACT_NECESSARY_PREDICATE, UNKNOWN, "UNREVIEWED_OR_UNCHARGED_EXCLUSION"),
            ("unmetered", EXACT_NECESSARY_PREDICATE, UNKNOWN, "UNREVIEWED_OR_UNCHARGED_EXCLUSION"),
            ("partial", EXACT_NECESSARY_PREDICATE, UNKNOWN, "INCOMPLETE_EXACT_EVIDENCE"),
            ("no-detail", EXACT_NECESSARY_PREDICATE, UNKNOWN, "INCOMPLETE_EXACT_EVIDENCE"),
            ("partial-positive", EXACT_NECESSARY_PREDICATE, UNKNOWN, "INCOMPLETE_OR_UNCHARGED_FEASIBILITY"),
        ):
            with self.subTest(task=task):
                reviewed = contract(task, proof_kind=kind)
                candidate, prefix = issue(reviewed.binding, "4" if task == "partial-positive" else "5")
                result = verifier(reviewed, candidate).check(candidate, prefix)
                self.assertEqual((result.status, result.reason), (expected, reason))
                self.assertEqual(result.authority, "NONE" if expected == UNKNOWN else "REJECT_THIS_VALUE_ONLY")

    def test_mid_fiber_budget_keeps_paid_work_and_withholds_authority(self):
        reviewed = contract("budget", proof_kind=COMPLETE_FIXED_VALUE_FIBER)
        c, prefix = issue(reviewed.binding, "5")
        engine = verifier(reviewed, c, work=3)
        result = engine.check(c, prefix)
        self.assertEqual((result.status, result.reason, result.checker_calls, result.work),
                         (UNKNOWN, "POINT_BUDGET_EXHAUSTED", 1, 3))
        self.assertEqual(result.denied_operation, ("fiber_points", 1))
        self.assertFalse(engine.authorizes_exclusion(c, result))
        retry = engine.check(c, prefix)
        self.assertEqual((retry.reason, retry.checker_calls, retry.work), ("POINT_BUDGET_EXHAUSTED", 0, 0))

    def test_copied_receipt_and_other_run_cannot_authorize(self):
        reviewed = contract()
        c, prefix = issue(reviewed.binding, "5")
        engine = verifier(reviewed, c)
        result = engine.check(c, prefix)
        self.assertFalse(engine.authorizes_exclusion(c, replace(result)))
        self.assertFalse(engine.authorizes_exclusion(c, result.as_dict()))
        self.assertFalse(verifier(reviewed, c).authorizes_exclusion(c, result))

    def test_repeated_concurrent_requests_do_not_escape_call_budget(self):
        reviewed = contract()
        c, prefix = issue(reviewed.binding, "5")
        engine = verifier(reviewed, c, calls=2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: engine.check(c, prefix), range(8)))
        self.assertEqual(sum(x.status == PROVEN_INFEASIBLE for x in results), 2)
        self.assertEqual(sum(x.reason == "POINT_BUDGET_EXHAUSTED" for x in results), 6)
        self.assertEqual(engine.report()["used"], {"checker_calls": 2, "work": 2})


if __name__ == "__main__":
    unittest.main()
