"""Independent CPU regressions on synthetic source text and the public adapter."""
from copy import deepcopy
import hashlib
import unittest

import natural_evidence as adapter
from restricted_math_checker import make_request, verify


def source_step(text):
    return {"step": 3, "start": 20, "end": 40, "text": text}


def extracted(text):
    return list(adapter.relations(source_step(text)))


class NaturalEvidenceTests(unittest.TestCase):
    def single(self, text):
        rows = extracted(text)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_closed_arithmetic_is_checked_locally(self):
        row = self.single("Therefore $2+3=5$.")
        self.assertEqual(row["status"], "parsed")
        self.assertEqual(row["certificate_type"], "ARITHMETIC_EQ")
        self.assertTrue(row["literal_check_only"])
        self.assertTrue(row["actionable_role_candidate"])
        self.assertFalse(row["role_certified"])
        self.assertEqual(adapter.check_relation(row)["status"], "VERIFIED")

    def test_bad_arithmetic_marks_step_without_refuting_parent_claim(self):
        row = self.single("Thus $2^2=5$.")
        target = adapter.target_for(row)
        self.assertEqual(target["kind"], "justification")
        result = adapter.check_relation(row)
        self.assertEqual(result["status"], "INVALID_JUSTIFICATION")
        self.assertEqual(result["witness"]["lhs"], "4")
        self.assertFalse(row["role_certified"])

    def test_hypothetical_and_contextual_text_has_no_certified_action_role(self):
        texts = (
            "If we assume $2+3=6$.",
            "Suppose $2+3=6$.",
            "Assuming $2+3=6$.",
            "A hypothetical example is $2+3=6$.",
            "Could $2+3=6$?",
            "The incorrect statement is $2+3=6$.",
            "Check whether $2+3=6$.",
            "By the previous equation, $2+3=6$.",
            "We need $2+3=6$.",
            "It is not true that $2+3=6$.",
            "The calculation $2+3=6$ would be wrong.",
        )
        for text in texts:
            with self.subTest(text=text):
                row = self.single(text)
                self.assertEqual(row["status"], "parsed")
                self.assertTrue(row["literal_check_only"])
                self.assertFalse(row["actionable_role_candidate"])
                self.assertFalse(row["role_certified"])
                self.assertEqual(adapter.check_relation(row)["status"], "INVALID_JUSTIFICATION")

    def test_source_bound_alone_is_not_role_certification(self):
        row = self.single("$2+3=6$")
        self.assertEqual(row["token_span"], [20, 40])
        self.assertFalse(row["role_certified"])
        self.assertTrue(row["literal_check_only"])
        # A bare numeric line could follow a hypothetical paragraph. The local
        # API exposes a lexical candidate while keeping role certification false.
        self.assertTrue(row["actionable_role_candidate"])
        self.assertEqual(adapter.target_for(row)["kind"], "justification")

    def test_fraction_decimal_subtraction_and_negative_schema(self):
        cases = (
            (r"$\frac{1}{3}+\frac{1}{6}=\frac{1}{2}$", "VERIFIED"),
            (r"$\dfrac{2}{3}-\tfrac{1}{6}=\frac{1}{2}$", "VERIFIED"),
            (r"$\frac{\frac{1}{2}}{2}=\frac{1}{4}$", "VERIFIED"),
            ("$0.1+0.2=0.3$", "VERIFIED"),
            ("$-2^2=-4$", "VERIFIED"),
            ("$(-2)^2=4$", "VERIFIED"),
            ("$2(3+4)=14$", "VERIFIED"),
            (r"$\frac{1}{0}=0$", "UNKNOWN"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                row = self.single(text)
                self.assertEqual(adapter.check_relation(row)["status"], expected)

    def test_equality_chain_is_adjacent_and_does_not_certify_entire_chain(self):
        rows = extracted("$2+3=5=6$")
        self.assertEqual([row["equation_index"] for row in rows], [0, 1])
        self.assertEqual([row["surface"] for row in rows], ["2+3=5", "5=6"])
        self.assertEqual([adapter.check_relation(row)["status"] for row in rows], ["VERIFIED", "INVALID_JUSTIFICATION"])
        self.assertTrue(all(not row["role_certified"] for row in rows))

    def test_numeric_tail_of_unbound_symbolic_chain_stays_literal(self):
        first, second = extracted("$x=2=3$")
        self.assertEqual(first["status"], "UNKNOWN")
        self.assertEqual(first["reason"], "symbolic_scope_unbound")
        self.assertEqual(adapter.check_relation(second)["status"], "INVALID_JUSTIFICATION")
        self.assertTrue(second["literal_check_only"])
        self.assertFalse(second["role_certified"])
        self.assertEqual(adapter.target_for(second)["required_premises"], [])

    def test_overlong_chain_abstains_as_a_whole(self):
        row = self.single("$1=1=1=1=1=1=1=1$")
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["reason"], "equality_chain_bound")

    def test_multiple_math_surfaces_remain_unverified_in_context(self):
        rows = extracted("$2+2=4$ and $3+3=6$.")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row["actionable_role_candidate"] and not row["role_certified"] for row in rows))
        self.assertTrue(all(adapter.check_relation(row)["status"] == "VERIFIED" for row in rows))

    def test_symbolic_scope_is_required(self):
        for text in ("$x=x$", "Therefore $x=x$.", "If x is positive, $x=x$."):
            row = self.single(text)
            self.assertEqual(row["status"], "UNKNOWN")
            self.assertEqual(adapter.check_relation(row)["status"], "UNKNOWN")
            with self.assertRaises(ValueError):
                adapter.target_for(row)

    def test_explicit_domain_keeps_certificate_type_separate(self):
        row = self.single("For all positive integer x: $x^2=x$.")
        self.assertEqual(row["status"], "parsed")
        self.assertEqual(row["certificate_type"], "POLYNOMIAL_IDENTITY")
        self.assertEqual(row["domains"], {"x": {"kind": "integer", "lower": 0, "lower_closed": False}})
        self.assertFalse(row["literal_check_only"])
        self.assertFalse(row["role_certified"])

    def test_scoped_and_unscoped_checks_distinguish_outside_domain_point(self):
        row = self.single("For all positive integer x: $x^2=x$.")
        scoped = adapter.check_relation(row, assignment={"x": -1})
        unscoped = adapter.check_relation(row, assignment={"x": -1}, unscoped=True)
        self.assertEqual(scoped["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(scoped["reason"], "counterexample_outside_scope")
        self.assertEqual(unscoped["status"], "INVALID_JUSTIFICATION")
        self.assertNotEqual(scoped["binding"]["scope"], unscoped["binding"]["scope"])

    def test_nonzero_domain_retains_rational_definedness(self):
        row = self.single("For all nonzero real x: $x/x=1$.")
        self.assertEqual(adapter.check_relation(row)["status"], "VERIFIED")
        self.assertEqual(adapter.check_relation(row, assignment={"x": 0})["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(adapter.check_relation(row, unscoped=True)["status"], "UNKNOWN")

    def test_wrong_universal_variable_is_unknown(self):
        row = self.single("For all real x: $y=y$.")
        self.assertEqual(row["status"], "UNKNOWN")

    def test_unsafe_unsupported_surface_is_rejected(self):
        texts = (
            r"$__import__('os')=1$", r"$a.real=2$", r"$[1][0]=1$",
            r"$\sqrt{4}=2$", r"$\frac{1}{2=1$", "$1 2=12$",
        )
        for text in texts:
            with self.subTest(text=text):
                rows = extracted(text)
                self.assertTrue(all(row["status"] == "UNKNOWN" for row in rows))

    def test_inequality_surface_is_not_silently_converted_to_equality(self):
        self.assertEqual(extracted("$2<=3$"), [])
        self.assertEqual(extracted(r"$x\ge2$"), [])

    def test_plain_arithmetic_and_bounds(self):
        self.assertEqual(adapter.check_relation(self.single("2+3=5."))["status"], "VERIFIED")
        with self.assertRaises(ValueError):
            adapter.parse_expression("1+" * 300 + "1")

    def test_prefix_and_token_source_are_bound_when_supplied(self):
        row = self.single("$2+3=5$")
        first_hash = hashlib.sha256(b"synthetic-prefix-A").hexdigest()
        second_hash = hashlib.sha256(b"synthetic-prefix-B").hexdigest()
        row["observed_prefix_sha256"] = first_hash
        target = adapter.target_for(row)
        self.assertEqual(target["source_span"], [20, 40])
        self.assertEqual(target["observed_prefix_sha256"], first_hash)
        request = make_request(target)
        changed = deepcopy(row)
        changed["observed_prefix_sha256"] = second_hash
        other = adapter.target_for(changed)
        self.assertNotEqual(target["id"], other["id"])
        self.assertEqual(verify(request, target=other)["reason"], "snapshot_binding_mismatch")
        shifted = deepcopy(row)
        shifted["token_span"] = [21, 41]
        self.assertEqual(verify(request, target=adapter.target_for(shifted))["reason"], "snapshot_binding_mismatch")


if __name__ == "__main__":
    unittest.main()
