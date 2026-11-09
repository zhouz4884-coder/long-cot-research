import unittest

from audit_d3_cross_phase import certificate_for_change, final_observation, numeric_same, target_metadata, thinking_readout
from audit_numeric_context import review_numeric_relations
from numeric_contradiction import scan_numeric_relations


class NumericLiteralTests(unittest.TestCase):
    def test_e15_coreference_only_refutes_comparison(self):
        text = "So the seven-digit number is 1011235. But that's smaller than 303369."
        row, = scan_numeric_relations(text)
        self.assertEqual((row["left"], row["operator"], row["right"]), ("1011235", "<", "303369"))
        self.assertFalse(row["exact_truth"])
        self.assertEqual(row["scope"], "ASSERTED_EXACT")
        self.assertEqual(text[row["start"]:row["end"]], row["source"])

    def test_condition_quote_and_self_correction(self):
        text = 'If $7 < 3$, the proof would fail.\n\nWe wrote "$7 < 3$".\n\n$7 < 3$ is false.\n\n$7 > 3$.'
        rows = scan_numeric_relations(text)
        self.assertEqual([r["scope"] for r in rows], [
            "CONDITIONAL_OR_UNCERTAIN", "QUOTED_OR_CODE", "REPORTED_OR_REJECTED", "ASSERTED_EXACT",
        ])
        self.assertEqual([r["exact_truth"] for r in rows], [False, False, False, True])

    def test_exact_chain_and_fail_closed(self):
        text = r"$0.1 + 0.2 = \frac{3}{10} = 0.3$" + "\n\n" + r"$x = 4$ $2^500 = 0$ $1/0=0$ $1.2\approx1$"
        self.assertEqual([r["left"] for r in scan_numeric_relations(text)], ["3/10", "3/10"])

    def test_context_rejects_fragments_bullets_and_running_totals(self):
        text = "The fraction 287/3 is equal to 95.666...\n\nChecks:\n\n- 2*2 = 4 ≤ 30\n\n- 2*3 = 6 ≤ 30"
        text += "\n\nStart with 15 + 8 = 23\n\n+5 = 28\n\nThen 21 is larger than 31."
        rows = review_numeric_relations(text)
        flags = [r for r in rows if r["scope"] == "ASSERTED_EXACT" and not r["exact_truth"]]
        self.assertEqual([r["source"] for r in flags], ["21 is larger than 31"])
        self.assertIn("DEFERRED_RUNNING_TOTAL", {r["scope"] for r in rows})
        self.assertIn("DEFERRED_COMPOSITE_OPERAND", {r["scope"] for r in rows})
        self.assertTrue(any(r["context_rule"] == "remove_markdown_list_marker" and r["exact_truth"] for r in rows))


class ThinkingReadoutTests(unittest.TestCase):
    def setUp(self):
        self.target = target_metadata({"question": "Find $n+t$.", "answer_kind": "scalar"})

    def test_earlier_box_does_not_override_late_target(self):
        text = r"For a trial we get \boxed{6}." + "\n\n**Final Answer**\n" + r"\boxed{11}"
        answer = thinking_readout(text, self.target)
        self.assertEqual(answer["status"], "EXPLICIT_COMMIT")
        self.assertEqual(answer["selection"]["components"], ["11"])

    def test_distinguish_tentative_malformed_and_absent(self):
        expected = [
            (r"\boxed{5}", "TENTATIVE_COMPLETE"),
            ("Final Answer\n" + r"\boxed{5", "MALFORMED_TARGET_CANDIDATE"),
            (r"Intermediate \boxed{5}. Need to find n+t.", "NO_COMPLETE_TARGET_CANDIDATE"),
        ]
        for text, status in expected:
            with self.subTest(text=text):
                self.assertEqual(thinking_readout(text, self.target)["status"], status)

    def test_subject_and_scope_before_boxed_rhs_diagnostic(self):
        target = target_metadata({"question": "Compute the greatest fibbish number.", "answer_kind": "scalar"})
        thought = thinking_readout("Final Answer\n" + r"The greatest fibbish number is \boxed{77}.", target)
        _, final = final_observation("Final Answer\n" + r"The greatest fibbish number is \boxed{88}.", target)
        self.assertEqual(numeric_same(thought["selection"], final["selection"]), "DIFFERENT_VALUE")
        wrong_role = thinking_readout("Final Answer\n" + r"The trial digit is \boxed{77}.", target)
        self.assertNotEqual(wrong_role["status"], "EXPLICIT_COMMIT")

    def test_reverse_corrective_final_is_not_overwritten_without_certificate(self):
        observed = thinking_readout("Final Answer\n" + r"\boxed{10}", self.target)
        _, final = final_observation("Final Answer\n" + r"\boxed{11}", self.target)
        comparison = numeric_same(observed["selection"], final["selection"])
        self.assertEqual(comparison, "DIFFERENT_VALUE")
        decision = certificate_for_change({"question": "Find n+t, where n=5 and t=6."}, {}, observed,
                                          observed["selection"], comparison, None, None)
        self.assertEqual(decision["action"], "RETAIN_NATIVE")


if __name__ == "__main__":
    unittest.main()
