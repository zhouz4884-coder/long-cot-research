from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from itertools import count
import json
import unittest
from unittest.mock import patch

from local_implication import (
    ASSERT_IMPLICATION, NO_COUNTEREXAMPLE, REFUTE_THIS_LOCAL_ASSERTION_ONLY, UNKNOWN, AssertionReceipt,
    ImplicationBinding, LocalImplicationVerifier, Predicate, ReviewedImplication, Variable,
)


def digest(text):
    return sha256(text.encode()).hexdigest()


def contract():
    binding = ImplicationBinding(digest("question"), "original-object", digest("original scope"), "PROVE")
    return ReviewedImplication(
        binding, (Variable("x", "INTEGER"),), (Predicate("GT", "x", 0),),
        (Predicate("EQ", ("MOD", "x", 4), 1),), Predicate("DIVIDES", 3, "x"),
        (("x", 5),), digest("typed implication proof"), digest("independent review"),
    )


def issue(reviewed, *, extra=""):
    prior = "例🙂\n"
    assertion = "I assert that the stated antecedent implies the stated consequent."
    prefix = prior + assertion + extra
    receipt = AssertionReceipt(reviewed.binding, reviewed.statement_sha256, "test:draw-00", digest("response identity"),
                               digest(prefix), (len(prior), len(prior + assertion)), digest(assertion), digest("issuer"))
    return receipt, prefix


def verifier(reviewed, *assertions, calls=8, work=64, wall=1_000_000_000):
    return LocalImplicationVerifier(reviewed, reviewed.sha256, approved_assertion_sha256=[x.sha256 for x in assertions],
                                    call_budget=calls, work_budget=work, wall_budget_ns=wall)


class LocalImplicationTests(unittest.TestCase):
    def test_exact_modular_counterexample_and_local_authority(self):
        reviewed = contract()
        assertion, prefix = issue(reviewed)
        engine = verifier(reviewed, assertion)
        outcome = engine.check(assertion, prefix)
        self.assertEqual((outcome.status, outcome.authority), (REFUTE_THIS_LOCAL_ASSERTION_ONLY,) * 2)
        self.assertEqual(outcome.fixed_witness, (("x", "5"),))
        self.assertEqual(outcome.variable_checks, (("x", True),))
        self.assertEqual((outcome.domain_checks, outcome.premise_checks, outcome.consequent), ((True,), (True,), False))
        self.assertEqual(dict(outcome.operation_charges),
                         {"variable_domain_check": 1, "exact_compare": 2, "exact_mod": 1, "exact_divisibility": 1})
        self.assertTrue(engine.authorizes_refutation(assertion, outcome))
        self.assertFalse(engine.authorizes_refutation(assertion, replace(outcome)))
        self.assertFalse(verifier(reviewed, assertion).authorizes_refutation(assertion, outcome))
        data = json.loads(json.dumps(engine.report()))
        self.assertEqual(data["used"], {"checker_calls": 1, "named_work": 5})
        self.assertEqual(data["receipts"][0]["assertion_receipt_sha256"], assertion.sha256)

    def test_exact_rational_squared_geometry(self):
        reviewed = replace(
            contract(), variables=(Variable("x", "RATIONAL"), Variable("y", "RATIONAL")),
            fixed_witness=(("x", Fraction(3, 2)), ("y", Fraction(1, 2))),
            premises=(Predicate("EQ", ("ADD", ("POW", "x", 2), ("MUL", "y", "y")), Fraction(5, 2)),),
            consequent=Predicate("LE", ("DIV", ("SUB", "x", "y"), 2), Fraction(1, 3)),
        )
        assertion, prefix = issue(reviewed)
        receipt = verifier(reviewed, assertion).check(assertion, prefix)
        self.assertEqual(receipt.status, REFUTE_THIS_LOCAL_ASSERTION_ONLY)
        self.assertEqual(receipt.fixed_witness, (("x", "3/2"), ("y", "1/2")))
        self.assertEqual(dict(receipt.operation_charges)["exact_mul"], 3)

    def test_false_domain_false_premise_or_true_consequent_have_no_authority(self):
        for witness, reason in (
            (Fraction(5, 2), "WITNESS_OUTSIDE_VARIABLE_DOMAIN"),
            (-3, "WITNESS_OUTSIDE_ORIGINAL_DOMAIN"),
            (2, "PREMISE_FALSE_AT_FIXED_WITNESS"),
            (9, "CONSEQUENT_TRUE_AT_FIXED_WITNESS"),
        ):
            with self.subTest(witness=witness):
                reviewed = replace(contract(), fixed_witness=(("x", witness),))
                assertion, prefix = issue(reviewed)
                engine = verifier(reviewed, assertion)
                receipt = engine.check(assertion, prefix)
                self.assertEqual((receipt.status, receipt.reason, receipt.authority), (NO_COUNTEREXAMPLE, reason, "NONE"))
                self.assertFalse(engine.authorizes_refutation(assertion, receipt))

    def test_reversed_uncommitted_wrong_scope_and_forged_issuer_fail_closed(self):
        reviewed = contract()
        clean, prefix = issue(reviewed)
        wrong = [
            (replace(clean, arrow="B_IMPLIES_A"), "UNREVIEWED_IMPLICATION_DIRECTION"),
            (replace(clean, role="TRIAL"), "ASSERTION_ROLE_MISMATCH"),
            (replace(clean, binding=replace(clean.binding, direction="MIN")), "ORIGINAL_BINDING_OR_STATEMENT_MISMATCH"),
            (replace(clean, binding=replace(clean.binding, scope_sha256=digest("subgoal"))), "ORIGINAL_BINDING_OR_STATEMENT_MISMATCH"),
            (replace(clean, binding=replace(clean.binding, objective_id="other-object")), "ORIGINAL_BINDING_OR_STATEMENT_MISMATCH"),
            (replace(clean, implication_sha256=digest("different AST")), "ORIGINAL_BINDING_OR_STATEMENT_MISMATCH"),
        ]
        engine = verifier(reviewed, clean, *(x for x, _ in wrong))
        for assertion, reason in wrong:
            receipt = engine.check(assertion, prefix)
            self.assertEqual((receipt.status, receipt.reason, receipt.work), (UNKNOWN, reason, 0))
        unissued = replace(clean, issuer_sha256=digest("different issuer"))
        self.assertEqual(engine.check(unissued, prefix).reason, "ASSERTION_NOT_ISSUED")
        self.assertEqual(engine.report()["used"], {"checker_calls": 0, "named_work": 0})

    def test_raw_prefix_unicode_assertion_span_and_no_future_bytes(self):
        reviewed = contract()
        assertion, prefix = issue(reviewed)
        wrong_span = replace(assertion, assertion_span=(0, assertion.assertion_span[1]))
        closed, final = issue(reviewed, extra="</think>final answer")
        engine = verifier(reviewed, assertion, wrong_span, closed)
        self.assertEqual(engine.check(wrong_span, prefix).reason, "ASSERTION_SPAN_MISMATCH")
        self.assertEqual(engine.check(closed, final).reason, "OBSERVED_PREFIX_MISMATCH")
        self.assertEqual(engine.check(assertion, prefix + " unapproved").reason, "OBSERVED_PREFIX_MISMATCH")
        self.assertEqual(engine.check(assertion, prefix).status, REFUTE_THIS_LOCAL_ASSERTION_ONLY)

    def test_division_zero_after_true_premise_retains_partial_work_and_abstains(self):
        good = contract()
        bad_premise = Predicate("EQ", ("DIV", "x", 0), 1)
        reviewed = replace(good, premises=good.premises + (bad_premise,))
        assertion, prefix = issue(reviewed)
        out = verifier(reviewed, assertion).check(assertion, prefix)
        self.assertEqual((out.status, out.reason, out.premise_checks, out.consequent),
                         (UNKNOWN, "UNDEFINED_DIVISION", (True,), None))
        self.assertEqual(dict(out.operation_charges)["exact_div"], 1)

    def test_undefined_modulus_and_unbounded_powers_abstain(self):
        for expr, reason in (
            (("MOD", "x", -2), "UNDEFINED_MODULO"),
            (("POW", "x", 17), "UNDEFINED_OR_UNSUPPORTED_POWER"),
            (("POW", "x", -1), "UNDEFINED_OR_UNSUPPORTED_POWER"),
            (("POW", "x", 5), "ARITHMETIC_SIZE_BOUND"),
        ):
            with self.subTest(expr=expr):
                reviewed = replace(contract(), fixed_witness=(("x", 1 << 62),),
                                   premises=(Predicate("EQ", expr, 0),))
                assertion, prefix = issue(reviewed)
                result = verifier(reviewed, assertion).check(assertion, prefix)
                self.assertEqual((result.status, result.reason, result.authority), (UNKNOWN, reason, "NONE"))

    def test_budget_timeout_and_repeat_are_finite_and_charge_actual_work(self):
        reviewed = contract()
        assertion, prefix = issue(reviewed)
        engine = verifier(reviewed, assertion, work=2)
        denied = engine.check(assertion, prefix)
        self.assertEqual((denied.status, denied.reason, denied.denied_operation, denied.work),
                         (UNKNOWN, "NAMED_WORK_BUDGET_EXHAUSTED", "exact_mod", 2))
        self.assertEqual(engine.check(assertion, prefix).reason, "POINT_CALL_OR_WORK_BUDGET_EXHAUSTED")
        timed = verifier(reviewed, assertion, wall=4)
        with patch("local_implication.perf_counter_ns", side_effect=count()):
            result = timed.check(assertion, prefix)
        self.assertEqual((result.status, result.reason, result.checker_calls, result.work),
                         (UNKNOWN, "POINT_WALL_DEADLINE", 1, 2))
        edge = verifier(reviewed, assertion, wall=7)
        with patch("local_implication.perf_counter_ns", side_effect=count()):
            end_of_budget = edge.check(assertion, prefix)
        self.assertEqual((end_of_budget.status, end_of_budget.reason, end_of_budget.work, end_of_budget.consequent),
                         (UNKNOWN, "POINT_WALL_DEADLINE", 5, False))
        cold = verifier(reviewed, assertion, wall=0).check(assertion, prefix)
        self.assertEqual((cold.status, cold.reason, cold.checker_calls, cold.work), (UNKNOWN, "POINT_WALL_DEADLINE", 0, 0))

    def test_contract_pins_fixed_witness_and_requires_complete_typed_inputs(self):
        reviewed = contract()
        alternate = replace(reviewed, fixed_witness=(("x", 9),))
        self.assertEqual(reviewed.statement_sha256, alternate.statement_sha256)
        self.assertNotEqual(reviewed.sha256, alternate.sha256)
        params = {"approved_assertion_sha256": (), "call_budget": 1, "work_budget": 20, "wall_budget_ns": 1_000_000}
        with self.assertRaises(ValueError):
            LocalImplicationVerifier(alternate, reviewed.sha256, **params)
        for broken in (
            replace(reviewed, premises=()),
            replace(reviewed, fixed_witness=()),
            replace(reviewed, fixed_witness=(("x", True),)),
            replace(reviewed, premises=(Predicate("GT", "undeclared", 0),)),
        ):
            with self.assertRaises(ValueError):
                LocalImplicationVerifier(broken, broken.sha256, **params)

    def test_concurrent_checks_share_one_budget(self):
        reviewed = contract()
        assertion, prefix = issue(reviewed)
        engine = verifier(reviewed, assertion, calls=2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: engine.check(assertion, prefix), range(8)))
        self.assertEqual(sum(r.status == REFUTE_THIS_LOCAL_ASSERTION_ONLY for r in rows), 2)
        self.assertEqual(sum(r.status == UNKNOWN for r in rows), 6)
        self.assertEqual(engine.report()["used"], {"checker_calls": 2, "named_work": 10})


if __name__ == "__main__":
    unittest.main()
