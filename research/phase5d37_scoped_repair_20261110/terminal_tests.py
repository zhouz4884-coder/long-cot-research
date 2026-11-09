"""Focused safety and source-span regression tests for the supplemental reader."""
import unittest

from terminal_scalar_fallback import exact_literal, terminal_scalar_fallback


ABSTAINED = {"status": "ambiguous", "reason": "boxed_objects_do_not_consume_final_payload"}


def fallback(text, f2=None, **change):
    args = {"target_kind": "scalar", "target_aliases": ("maximum score",),
            "eos": True, "think_closed": True, "delivered": True}
    args.update(change)
    return terminal_scalar_fallback(text, f2 if f2 is not None else ABSTAINED, **args)


class TerminalScalarFallbackTests(unittest.TestCase):
    def test_preserve_existing_f2_success(self):
        row = fallback(r"\boxed{9}", {"status": "ok"})
        self.assertEqual(row["status"], "KEEP_FROZEN_F2")
        self.assertIsNone(row["normalized_scalar"])

    def test_exact_box_source_offsets(self):
        text = "Either derivation agrees.\n\n### Final Result\n\nThe maximum score is:\n\n"
        text += r"\[\boxed{\tfrac{13}{8}}\]"
        result = fallback(text)
        self.assertEqual(result["status"], "FALLBACK_ACCEPT")
        self.assertEqual(result["normalized_scalar"], "13/8")
        a, b = result["box_span"]
        self.assertEqual(text[a:b], r"\boxed{\tfrac{13}{8}}")

    def test_prior_role_or_explicit_commitment_can_conflict(self):
        latest = "### Final Result\n\nThe maximum score is:\n\n" + r"\boxed{27}"
        for previous in ("The final answer is 29.\n\n", "The maximum score equals 29.\n\n"):
            with self.subTest(previous=previous):
                self.assertEqual(fallback(previous + latest)["reason"], "conflicting_explicit_answers")

    def test_scoped_same_value_repeat(self):
        text = "### Final Conclusion\n\nThe maximum score is:\n\n" + r"\boxed{27.0}"
        text += "\n\n---\n\n### Final Answer\n\n" + r"\boxed{27}"
        self.assertEqual(fallback(text)["normalized_scalar"], "27")

    def test_decline_missing_role_and_unsafe_containers(self):
        for text in [
            "### Final Result\n\nThe largest two-digit score is:\n\n" + r"\boxed{99}",
            "### Final Result\n\nThe best feasible score so far is:\n\n" + r"\boxed{9}",
            "### Final Result\n\nMaybe the answer is " + r"\boxed{9}",
            "> ### Final Result\n\n" + r"\boxed{9}",
            "~~~\n### Final Result\n\n" + r"\boxed{9}" + "\n~~~",
            "### Final Result\n\n" + r'"\boxed{9}"',
        ]:
            with self.subTest(text=text):
                self.assertEqual(fallback(text)["status"], "ABSTAIN")

    def test_delivery_and_target_preconditions_precede_f2(self):
        for metadata in ({"eos": False}, {"think_closed": False}, {"delivered": False}, {"target_kind": "unknown"}):
            with self.subTest(metadata=metadata):
                self.assertEqual(fallback(r"\boxed{9}", {"status": "ok"}, **metadata)["status"], "ABSTAIN")

    def test_frozen_explicit_conflict_cannot_be_overridden(self):
        prior = {"status": "ambiguous", "reason": "different_explicit_final_deliveries"}
        self.assertEqual(fallback("Final Answer: " + r"\boxed{9}", prior)["status"], "ABSTAIN")

    def test_incomplete_earlier_terminal_section_is_preserved(self):
        text = "### Final Conclusion\n\nThe answer is either " + r"\boxed{28}" + " or unknown."
        text += "\n\n### Final Answer\n\n" + r"\boxed{29}"
        self.assertEqual(fallback(text)["status"], "ABSTAIN")

    def test_scalar_syntax_limits(self):
        for surface in (r"\frac{5}{0}", "1.2...", "5 + 6", "12,34", "[1,2]", "1/−2"):
            with self.subTest(surface=surface):
                self.assertIsNone(exact_literal(surface))
        self.assertEqual(exact_literal("−0.125"), "-1/8")


if __name__ == "__main__":
    unittest.main()
