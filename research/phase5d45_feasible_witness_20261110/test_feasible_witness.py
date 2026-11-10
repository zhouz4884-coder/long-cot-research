from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
import unittest

from feasible_witness import (
    Feasibility,
    FeasibleWitnessVerifier,
    MAX_ABS_INTEGER,
    ObjectiveBinding,
    ReviewedContract,
    checker_source_sha256,
)


CONSTRAINTS = ("nonnegative", "at_most_two")


def synthetic_checker(binding, witness, meter):
    """Check an exact rational in [0, 2], with deliberate test-only error modes."""
    meter.charge("parse")
    x = witness["x"]
    if type(x) not in (int, str):
        raise ValueError("Expected an exact rational coordinate")
    x = Fraction(x)
    mode = witness.get("mode")
    if mode != "uncharged":
        meter.charge("constraint:nonnegative")
    nonnegative = x >= 0
    if mode == "missing":
        return Feasibility((("nonnegative", nonnegative),), x)
    meter.charge("constraint:at_most_two")
    at_most_two = x <= 2 if mode != "unknown" else None
    rows = (("nonnegative", nonnegative), ("at_most_two", at_most_two))
    if mode == "swapped":
        return Feasibility(tuple(reversed(rows)), x)
    if not nonnegative or at_most_two is not True:
        return Feasibility(rows, None)
    if mode != "uncharged_objective":
        meter.charge("objective")
    return Feasibility(rows, 1.5 if mode == "inexact_objective" else x)


def alternate_checker(binding, witness, meter):
    return synthetic_checker(binding, witness, meter)


def sha(text):
    return sha256(text.encode()).hexdigest()


def contract(direction="MAX"):
    binding = ObjectiveBinding(sha("given q"), "original-objective", sha("exact scope"), sha("all constraints"), direction)
    return ReviewedContract(binding, CONSTRAINTS, "test.interval", 1, "synthetic_checker",
                            checker_source_sha256(synthetic_checker), sha("proof"), sha("review"))


def verifier(reviewed=None, *, call_budget=8, work_budget=32, comparison_budget=8):
    reviewed = contract() if reviewed is None else reviewed
    return FeasibleWitnessVerifier(reviewed, reviewed.sha256, synthetic_checker, call_budget=call_budget,
                                   work_budget=work_budget, comparison_budget=comparison_budget)


class FeasibleWitnessTests(unittest.TestCase):
    def test_freeze_a_max_bound_before_seeing_claims_and_charge_reuse(self):
        reviewed = contract()
        engine = verifier(reviewed)
        binding = reviewed.binding
        bound = engine.verify(binding, {"x": "3/2"})
        self.assertEqual((bound.status, bound.objective, bound.bound_direction, bound.work),
                         ("CERTIFIED_FEASIBLE_BOUND", "3/2", "LOWER", 4))
        self.assertEqual(bound.constraints, (("nonnegative", True), ("at_most_two", True)))
        self.assertEqual(engine.report()["claim_receipts"], [])
        for candidate, expected in ((1, "REFUTED_OPTIMUM_CLAIM"), ("3/2", "NOT_REFUTED"), (2, "NOT_REFUTED")):
            result = engine.compare(binding, candidate, bound)
            self.assertEqual((result.status, result.comparison_operations), (expected, 1))
            self.assertEqual(result.bound_receipt_sha256, bound.as_dict()["receipt_sha256"])
        report = engine.report()
        self.assertEqual(report["used"], {"checker_calls": 1, "witness_work": 4, "comparison_operations": 3})
        self.assertEqual(json.loads(json.dumps(report))["contract_sha256"], reviewed.sha256)

    def test_min_upper_bound_uses_strict_reverse_order(self):
        reviewed = contract("MIN")
        engine = verifier(reviewed)
        binding = reviewed.binding
        bound = engine.verify(binding, {"x": "3/2"})
        self.assertEqual(bound.bound_direction, "UPPER")
        self.assertEqual(engine.compare(binding, Fraction(8, 5), bound).status, "REFUTED_OPTIMUM_CLAIM")
        self.assertEqual(engine.compare(binding, "6/4", bound).status, "NOT_REFUTED")
        self.assertEqual(engine.compare(binding, 1, bound).status, "NOT_REFUTED")

    def test_original_binding_and_roles_are_mandatory(self):
        reviewed = contract()
        engine = verifier(reviewed)
        binding = reviewed.binding
        bound = engine.verify(binding, {"x": 2})
        for field, value in (("question_sha256", sha("other q")), ("objective_id", "subgoal"),
                             ("scope_sha256", sha("other scope")), ("constraints_sha256", sha("relaxation")),
                             ("direction", "MIN")):
            wrong = replace(binding, **{field: value})
            with self.subTest(field=field):
                self.assertEqual(engine.verify(wrong, {"x": 2}).reason, "BINDING_MISMATCH")
                self.assertEqual(engine.compare(wrong, 0, bound).reason, "BINDING_MISMATCH")
        self.assertEqual(engine.verify(binding, {"x": 2}, witness_role="OPTIMUM_CLAIM").reason, "WITNESS_ROLE_MISMATCH")
        self.assertEqual(engine.compare(binding, 0, bound, claim_role="FEASIBLE_WITNESS").reason, "CLAIM_ROLE_MISMATCH")
        self.assertEqual(engine.report()["used"], {"checker_calls": 1, "witness_work": 4, "comparison_operations": 0})

    def test_missing_unknown_or_uncharged_work_cannot_issue_a_bound(self):
        reviewed = contract()
        for mode, reason in (
            ("missing", "INCOMPLETE_CONSTRAINT_COVERAGE"),
            ("swapped", "INCOMPLETE_CONSTRAINT_COVERAGE"),
            ("unknown", "UNRESOLVED_CONSTRAINT"),
            ("uncharged", "UNCHARGED_CONSTRAINT"),
            ("uncharged_objective", "MISSING_OR_UNCHARGED_EXACT_OBJECTIVE"),
            ("inexact_objective", "MISSING_OR_UNCHARGED_EXACT_OBJECTIVE"),
        ):
            with self.subTest(mode=mode):
                engine = verifier(reviewed)
                receipt = engine.verify(reviewed.binding, {"x": 1, "mode": mode})
                self.assertEqual((receipt.status, receipt.reason, receipt.objective), ("UNKNOWN", reason, None))
                self.assertEqual(engine.compare(reviewed.binding, 0, receipt).reason, "UNISSUED_BOUND")

    def test_infeasible_witness_is_not_authority_to_refute_a_claim(self):
        reviewed = contract()
        engine = verifier(reviewed)
        receipt = engine.verify(reviewed.binding, {"x": 3})
        self.assertEqual(receipt.status, "WITNESS_INFEASIBLE")
        self.assertEqual(receipt.constraints, (("nonnegative", True), ("at_most_two", False)))
        self.assertIsNone(receipt.bound_direction)
        self.assertEqual(engine.compare(reviewed.binding, 2, receipt).reason, "UNISSUED_BOUND")

    def test_malformed_numbers_and_witness_payloads_fail_closed(self):
        reviewed = contract()
        binding = reviewed.binding
        engine = verifier(reviewed)
        bound = engine.verify(binding, {"x": "3/2"})
        for x in (True, 1.5, float("nan"), "1.5", " 1", "1/0", "1e3", "2/-3", MAX_ABS_INTEGER + 1,
                  "9999999999999999999/9999999999999999999", "１２", Fraction(1, MAX_ABS_INTEGER + 1)):
            with self.subTest(x=x):
                receipt = engine.compare(binding, x, bound)
                self.assertEqual((receipt.reason, receipt.comparison_operations), ("MALFORMED_EXACT_CLAIM", 0))
        cyclic = {}
        cyclic["nested"] = cyclic
        for witness in ({}, [], {"x": 1.5}, {"x": Fraction(1, 2)}, {"x": 2 ** 80}, {"x": "\ud800"}, cyclic):
            with self.subTest(witness_type=type(witness)):
                receipt = engine.verify(binding, witness)
                self.assertEqual((receipt.reason, receipt.checker_calls, receipt.work), ("MALFORMED_WITNESS", 0, 0))

    def test_over_budget_keeps_prior_work_and_charges_no_denied_operation(self):
        reviewed = contract()
        binding = reviewed.binding
        engine = verifier(reviewed, work_budget=2)
        denied = engine.verify(binding, {"x": 1})
        self.assertEqual((denied.status, denied.reason, denied.work, denied.checker_calls),
                         ("UNKNOWN", "WITNESS_BUDGET_EXHAUSTED", 2, 1))
        self.assertEqual(denied.denied_operation, ("constraint:at_most_two", 1))
        retry = engine.verify(binding, {"x": 1})
        self.assertEqual((retry.reason, retry.work, retry.checker_calls), ("WITNESS_BUDGET_EXHAUSTED", 0, 0))
        engine = verifier(reviewed, call_budget=1, comparison_budget=1)
        bound = engine.verify(binding, {"x": 1})
        self.assertEqual(engine.verify(binding, {"x": 2}).reason, "WITNESS_BUDGET_EXHAUSTED")
        self.assertEqual(engine.compare(binding, 0, bound).status, "REFUTED_OPTIMUM_CLAIM")
        self.assertEqual(engine.compare(binding, 1, bound).reason, "COMPARISON_BUDGET_EXHAUSTED")

    def test_forged_or_cross_verifier_receipts_are_inadmissible(self):
        reviewed = contract()
        engine = verifier(reviewed)
        binding = reviewed.binding
        bound = engine.verify(binding, {"x": 1})
        for forged in (replace(bound), replace(bound, objective="4"), bound.as_dict()):
            self.assertEqual(engine.compare(binding, 0, forged).reason, "UNISSUED_BOUND")
        self.assertEqual(verifier(reviewed).compare(binding, 0, bound).reason, "UNISSUED_BOUND")

    def test_approval_and_source_identity_reject_semantic_substitution(self):
        reviewed = contract()
        opts = {"call_budget": 1, "work_budget": 10, "comparison_budget": 2}
        with self.assertRaisesRegex(ValueError, "approved contract"):
            FeasibleWitnessVerifier(replace(reviewed, required_constraints=("nonnegative",)), reviewed.sha256, synthetic_checker, **opts)
        with self.assertRaisesRegex(ValueError, "reviewed contract"):
            FeasibleWitnessVerifier(reviewed, reviewed.sha256, alternate_checker, **opts)
        wrong_sha = replace(reviewed, checker_source_sha256=sha("different source"))
        with self.assertRaisesRegex(ValueError, "reviewed contract"):
            FeasibleWitnessVerifier(wrong_sha, wrong_sha.sha256, synthetic_checker, **opts)

    def test_concurrent_comparisons_respect_one_shared_limit(self):
        reviewed = contract()
        binding = reviewed.binding
        engine = verifier(reviewed, comparison_budget=2)
        bound = engine.verify(binding, {"x": 2})
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda value: engine.compare(binding, value, bound), range(8)))
        self.assertEqual(sum(row.comparison_operations for row in outcomes), 2)
        self.assertEqual(sum(row.reason == "COMPARISON_BUDGET_EXHAUSTED" for row in outcomes), 6)
        self.assertEqual(sorted(row.request_number for row in outcomes), list(range(1, 9)))


if __name__ == "__main__":
    unittest.main()
