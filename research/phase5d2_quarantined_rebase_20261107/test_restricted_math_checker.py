from copy import deepcopy
import random
import unittest
from unittest.mock import patch

from restricted_math_checker import LIMITS, make_request, replay_certificate, verify


def variable(name):
    return {"op": "var", "name": name}


def rat(num, den):
    return {"op": "rat", "num": num, "den": den}


def binary(op, lhs, rhs):
    return {"op": op, "lhs": lhs, "rhs": rhs}


def add(*args):
    return {"op": "add", "args": list(args)}


def mul(*args):
    return {"op": "mul", "args": list(args)}


def power(base, exponent):
    return {"op": "pow", "base": base, "exp": exponent}


def premise(identifier, predicate, *, version=0, scope="S", scope_version=0):
    return {"id": identifier, "version": version, "scope_id": scope, "scope_version": scope_version,
            "predicate": predicate, "evidence_id": f"trusted-{identifier}"}


def target(certificate_type, statement, domains=None, *, premises=(), kind="claim", ring="Q", version=0):
    refs = [{key: item[key] for key in ("id", "version", "scope_id", "scope_version")} for item in premises]
    return {"id": "claim-or-proof", "version": version, "kind": kind, "certificate_type": certificate_type,
            "scope": {"id": "S", "version": 0, "coefficient_domain": ring, "domains": domains or {}},
            "statement": statement, "required_premises": refs}


def check(snapshot, premises=(), **request_options):
    request = make_request(snapshot, premises, **request_options)
    return verify(request, target=snapshot, premises=premises)


def cancellation(domains, premises=()):
    x = variable("x")
    lhs = binary("div", binary("sub", power(x, 2), 1), binary("sub", x, 1))
    return target("POLYNOMIAL_IDENTITY", {"lhs": lhs, "rhs": add(x, 1)}, domains, premises=premises)


class RestrictedCheckerTests(unittest.TestCase):
    def test_closed_rational_equality_and_negative_powers(self):
        snapshot = target("ARITHMETIC_EQ", {"lhs": add(rat(1, 8), power(2, -3)), "rhs": rat(1, 4)})
        result = check(snapshot)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["witness"]["lhs"], "1/4")

    def test_exact_wrong_step_classification_respects_target_kind(self):
        source = premise("x2", binary("eq", variable("x"), 2))
        statement = {"lhs": power(variable("x"), 2), "rhs": 5}
        domain = {"x": {"kind": "integer"}}
        bad_proof = target("ARITHMETIC_EQ", statement, domain, premises=(source,), kind="justification")
        refuted_claim = target("ARITHMETIC_EQ", statement, domain, premises=(source,))
        self.assertEqual(check(bad_proof, (source,))["status"], "INVALID_JUSTIFICATION")
        self.assertEqual(check(refuted_claim, (source,))["status"], "REFUTED_CLAIM")

    def test_request_assignment_cannot_certify_unbound_equality(self):
        snapshot = target("ARITHMETIC_EQ", {"lhs": power(variable("x"), 2), "rhs": 4}, {"x": {"kind": "integer"}})
        result = check(snapshot, assignment={"x": 2})
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "point_values_need_trusted_grounding")

    def test_scope_version_target_version_role_and_semantics_all_bound(self):
        snapshot = target("ARITHMETIC_EQ", {"lhs": 1, "rhs": 1}, version=1)
        request = make_request(snapshot)
        for mutate in (
            lambda s: s.update(version=2),
            lambda s: s["scope"].update(version=1),
            lambda s: s.update(kind="justification"),
            lambda s: s["statement"].update(rhs=2),
        ):
            changed = deepcopy(snapshot)
            mutate(changed)
            self.assertEqual(verify(request, target=changed)["reason"], "snapshot_binding_mismatch")
        forged = deepcopy(request)
        forged["binding"]["target"]["version"] = True
        self.assertEqual(verify(forged, target=snapshot)["reason"], "snapshot_binding_mismatch")

    def test_complete_current_premises_and_content_fingerprint(self):
        x2 = premise("p", binary("eq", variable("x"), 2), version=3)
        y3 = premise("q", binary("eq", variable("y"), 3))
        scope = {"x": {"kind": "integer"}, "y": {"kind": "integer"}}
        snapshot = target("ARITHMETIC_EQ", {"lhs": add(variable("x"), variable("y")), "rhs": 5}, scope, premises=(x2, y3))
        request = make_request(snapshot, (x2, y3))
        self.assertEqual(verify(request, target=snapshot, premises=(y3, x2))["status"], "VERIFIED")
        stale = {**x2, "version": 2}
        modified = {**x2, "predicate": binary("eq", variable("x"), 4)}
        for records in ((x2,), (stale, y3), (x2, y3, premise("extra", binary("eq", 1, 1))), (x2, x2, y3), (modified, y3)):
            self.assertEqual(verify(request, target=snapshot, premises=records)["status"], "UNKNOWN")

    def test_cross_scope_premise_is_rejected_even_with_matching_names(self):
        foreign = premise("p", binary("eq", variable("x"), 2), scope="T")
        snapshot = target("ARITHMETIC_EQ", {"lhs": variable("x"), "rhs": 2}, {"x": {"kind": "integer"}}, premises=(foreign,))
        result = verify({"binding": {}, "mode": "verify"}, target=snapshot, premises=(foreign,))
        self.assertEqual(result["reason"], "premise_scope_mismatch")

    def test_cancellation_preserves_original_denominator(self):
        without = check(cancellation({"x": {"kind": "real"}}))
        self.assertEqual(without["reason"], "original_denominator_guard_unproven")
        with_exclusion = check(cancellation({"x": {"kind": "real", "exclude": [1]}}))
        self.assertEqual(with_exclusion["status"], "VERIFIED")
        guard = with_exclusion["witness"]["original_denominator_checks"][0]
        self.assertEqual(guard["type"], "linear_root_excluded_by_domain")
        self.assertEqual(guard["root"], "1")

    def test_explicit_nonzero_premise_can_discharge_denominator(self):
        exclusion = premise("x-not-one", binary("ne", variable("x"), 1))
        result = check(cancellation({"x": {"kind": "rational"}}, (exclusion,)), (exclusion,))
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["witness"]["original_denominator_checks"][0]["premise"], "x-not-one")

    def test_negative_and_zero_powers_retain_definedness(self):
        x = variable("x")
        zero_power = target("POLYNOMIAL_IDENTITY", {"lhs": power(x, 0), "rhs": 1}, {"x": {"kind": "real"}})
        self.assertEqual(check(zero_power)["status"], "UNKNOWN")
        inverse = target("POLYNOMIAL_IDENTITY", {"lhs": mul(x, power(x, -1)), "rhs": 1}, {"x": {"kind": "real", "exclude": [0]}})
        self.assertEqual(check(inverse)["status"], "VERIFIED")
        nested = target("POLYNOMIAL_IDENTITY", {"lhs": binary("div", 1, binary("div", 1, x)), "rhs": x}, {"x": {"kind": "rational"}})
        self.assertEqual(check(nested)["reason"], "original_denominator_guard_unproven")

    def test_undefined_arithmetic_abstains(self):
        for expression in (binary("div", 1, 0), power(0, 0), power(0, -1)):
            snapshot = target("ARITHMETIC_EQ", {"lhs": expression, "rhs": 0})
            self.assertEqual(check(snapshot)["status"], "UNKNOWN")

    def test_counterexample_scope_truth_and_original_expression(self):
        x = variable("x")
        snapshot = target("POLYNOMIAL_IDENTITY", {"lhs": power(x, 2), "rhs": x}, {"x": {"kind": "integer", "lower": 1}})
        self.assertEqual(check(snapshot, mode="counterexample", assignment={"x": 0})["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(check(snapshot, mode="counterexample", assignment={"x": 1})["status"], "INVALID_COUNTEREXAMPLE")
        result = check(snapshot, mode="counterexample", assignment={"x": 2})
        self.assertEqual(result["status"], "REFUTED_CLAIM")
        self.assertEqual(result["witness"]["lhs"], "4")
        self.assertEqual(check(cancellation({"x": {"kind": "real"}}), mode="counterexample", assignment={"x": 1})["status"], "UNKNOWN")

    def test_counterexample_checks_every_required_premise(self):
        x = variable("x")
        first = premise("nonnegative", {"op": "nonnegative", "arg": x})
        second = premise("upper", binary("le", x, 1))
        snapshot = target("POLYNOMIAL_IDENTITY", {"lhs": power(x, 2), "rhs": x}, {"x": {"kind": "integer"}}, premises=(first, second))
        rejected = check(snapshot, (first, second), mode="counterexample", assignment={"x": 2})
        self.assertEqual(rejected["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(rejected["witness"]["violated_premises"], ["upper"])

    def test_finite_scope_equality_differs_from_formal_coefficients(self):
        x = variable("x")
        statement = {"lhs": power(x, 2), "rhs": x}
        domain = {"x": {"kind": "integer", "values": [0, 1]}}
        scoped = check(target("POLYNOMIAL_IDENTITY", statement, domain))
        formal = check(target("POLYNOMIAL_IDENTITY", {**statement, "semantics": "formal"}, domain))
        self.assertEqual(scoped["status"], "VERIFIED")
        self.assertEqual(scoped["witness"]["exhaustive_scope_points"], 2)
        self.assertEqual(formal["status"], "REFUTED_CLAIM")

    def test_integer_coefficient_divisibility_differs_from_rational(self):
        x = variable("x")
        statement = {"dividend": x, "divisor": mul(2, x)}
        domain = {"x": {"kind": "integer"}}
        rational = check(target("POLYNOMIAL_DIVISIBILITY", statement, domain, ring="Q"))
        integer = check(target("POLYNOMIAL_DIVISIBILITY", statement, domain, ring="Z"))
        self.assertEqual(rational["status"], "VERIFIED")
        self.assertEqual(integer["status"], "REFUTED_CLAIM")
        self.assertEqual(integer["witness"]["remainder"]["term_count"], 0)
        self.assertFalse(integer["witness"]["quotient_in_coefficient_ring"])

    def test_multivariate_division_remainder_and_zero_divisor(self):
        x, y = variable("x"), variable("y")
        domains = {name: {"kind": "rational"} for name in ("x", "y")}
        divisor = add(x, y)
        good = target("POLYNOMIAL_DIVISIBILITY", {"dividend": mul(divisor, add(x, 1)), "divisor": divisor}, domains)
        bad = target("POLYNOMIAL_DIVISIBILITY", {"dividend": add(mul(divisor, add(x, 1)), 1), "divisor": divisor}, domains)
        zero = target("POLYNOMIAL_DIVISIBILITY", {"dividend": 0, "divisor": 0})
        self.assertEqual(check(good)["status"], "VERIFIED")
        self.assertEqual(check(bad)["witness"]["remainder"]["terms"], [{"exponents": [0, 0], "coefficient": "1"}])
        self.assertEqual(check(zero)["status"], "UNKNOWN")
        self.assertEqual(check(good, mode="counterexample", assignment={"x": 0, "y": 0})["status"], "UNKNOWN")

    def test_polynomial_counterexample_cannot_bypass_declared_ring(self):
        x = variable("x")
        scope = {"x": {"kind": "rational"}}
        statement = {"lhs": mul(rat(1, 2), x), "rhs": x, "semantics": "formal"}
        snapshot = target("POLYNOMIAL_IDENTITY", statement, scope, ring="Z")
        result = check(snapshot, mode="counterexample", assignment={"x": 2})
        self.assertEqual(result["reason"], "outside_integer_coefficient_ring")

    def test_all_substitution_constraints_and_candidate_are_bound(self):
        x = variable("x")
        statements = [binary("eq", power(x, 2), 9), {"op": "positive", "arg": x}]
        domain = {"x": {"kind": "integer"}}
        good = target("SUBSTITUTION", {"assignment": {"x": 3}, "constraints": statements}, domain)
        bad = target("SUBSTITUTION", {"assignment": {"x": -3}, "constraints": statements}, domain)
        self.assertEqual(check(good)["status"], "VERIFIED")
        result = check(bad)
        self.assertEqual(result["status"], "REFUTED_CLAIM")
        self.assertEqual([row["satisfied"] for row in result["witness"]["constraints"]], [True, False])
        self.assertEqual(check(bad, assignment={"x": 3})["reason"], "assignment_binding_mismatch")

    def test_inconsistent_scope_and_undefined_premise_abstain(self):
        x = variable("x")
        domain = {"x": {"kind": "integer", "values": [0, 1]}}
        contradictory = (premise("x0", binary("eq", x, 0)), premise("x1", binary("eq", x, 1)))
        invalid = (premise("domain", binary("gt", binary("div", 1, x), 0)),)
        for records in (contradictory, invalid):
            snapshot = target("POLYNOMIAL_IDENTITY", {"lhs": x, "rhs": x}, domain, premises=records)
            self.assertEqual(check(snapshot, records)["status"], "UNKNOWN")

    def test_explicit_domain_predicates(self):
        cases = (
            (binary("coprime", 15, 8), True),
            (binary("coprime", 6, 8), False),
            ({"op": "is_integer", "arg": rat(4, 2)}, True),
            ({"op": "positive", "arg": 0}, False),
            ({"op": "distinct", "args": [1, 2, rat(2, 2)]}, False),
            ({"op": "vector_dimension", "items": [1, 2], "size": 3}, False),
            ({"op": "in_domain", "arg": 1, "domain": {"kind": "rational", "lower": 1, "lower_closed": False}}, False),
            ({"op": "in_domain", "arg": rat(1, 2), "domain": {"kind": "real", "lower": 0, "upper": 1}}, True),
        )
        for predicate, expected in cases:
            result = check(target("DOMAIN_PREDICATE", {"predicate": predicate}))
            self.assertIs(result["truth"], expected)

    def test_no_vacuous_or_unbounded_certificate(self):
        x, y, z, w = (variable(name) for name in ("x", "y", "z", "w"))
        domains = {name: {"kind": "rational"} for name in ("x", "y", "z", "w")}
        expressions = (power(power(x, 12), 12), power(add(x, y, z, w), 12), power(x, 13))
        for expression in expressions:
            snapshot = target("POLYNOMIAL_IDENTITY", {"lhs": expression, "rhs": expression}, domains)
            result = check(snapshot)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertIsNone(result["certificate"])
        snapshot = target("ARITHMETIC_EQ", {"lhs": add(1, 2), "rhs": 3})
        with patch.dict(LIMITS, {"work_units": 2}):
            first, second = check(snapshot), check(snapshot)
        self.assertEqual(first, second)
        self.assertEqual(first["reason"], "work_limit")

    def test_raw_text_float_boolean_and_extra_fields_are_rejected(self):
        expressions = ("__import__('os').system('echo ignored')", 0.5, True,
                       {"op": "rat", "num": 1, "den": 2, "ignored": 0},
                       {"op": "call", "name": "sqrt", "arg": 2})
        for expression in expressions:
            snapshot = target("ARITHMETIC_EQ", {"lhs": expression, "rhs": 1})
            result = verify({"mode": "verify", "binding": {}}, target=snapshot)
            self.assertEqual(result["status"], "UNKNOWN")
            if type(expression) is not float:
                self.assertEqual(check(snapshot)["status"], "UNKNOWN")

    def test_certificate_replay_uses_owned_statement_and_predicates(self):
        snapshot = target("ARITHMETIC_EQ", {"lhs": 4, "rhs": 4})
        request = make_request(snapshot)
        result = verify(request, target=snapshot)
        self.assertTrue(replay_certificate(result["certificate"], request, target=snapshot))
        forged = {**result["certificate"], "truth": False}
        self.assertFalse(replay_certificate(forged, request, target=snapshot))
        type_changed = {**result["certificate"], "truth": 1}
        self.assertFalse(replay_certificate(type_changed, request, target=snapshot))
        self.assertFalse(replay_certificate(result["certificate"], request, target={**snapshot, "version": 1}))

    def test_exact_division_matches_independent_integer_convolution(self):
        rng = random.Random(20261107)
        x = variable("x")
        domains = {"x": {"kind": "integer"}}

        def expression(coefficients):
            terms = [coefficient if degree == 0 else mul(coefficient, power(x, degree))
                     for degree, coefficient in enumerate(coefficients) if coefficient]
            if not terms:
                return 0
            return terms[0] if len(terms) == 1 else add(*terms)

        for _ in range(64):
            quotient = [rng.randint(-4, 4) for _ in range(rng.randint(1, 4))]
            divisor = [rng.randint(-4, 4) for _ in range(rng.randint(1, 4))]
            divisor[-1] = rng.choice((-3, -2, 2, 3))
            dividend = [0] * (len(quotient) + len(divisor) - 1)
            for left, coefficient_a in enumerate(quotient):
                for right, coefficient_b in enumerate(divisor):
                    dividend[left + right] += coefficient_a * coefficient_b
            snapshot = target("POLYNOMIAL_DIVISIBILITY", {"dividend": expression(dividend), "divisor": expression(divisor)}, domains, ring="Z")
            result = check(snapshot)
            self.assertEqual(result["status"], "VERIFIED")
            expected = {i: str(coefficient) for i, coefficient in enumerate(quotient) if coefficient}
            actual = {term["exponents"][0]: term["coefficient"] for term in result["witness"]["quotient"]["terms"]}
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
