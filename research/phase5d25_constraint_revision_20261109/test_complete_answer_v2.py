"""Positive and adverse controls for boxed RHS delivery after a final anchor."""
import unittest

import complete_answer as v1
import complete_answer_v2 as v2


def display(chain, prelude="", heading="### Final Answer"):
    return heading + "\n\n" + (prelude + "\n\n" if prelude else "") + "$$\n" + chain + "\n$$"


class ExactFinalChainTest(unittest.TestCase):
    def test_exact_closed_chains(self):
        for chain, expected in (
            (r"2+3=5=\boxed{5}", "5"),
            (r"(2+3)\times 3=15=\boxed{15}", "15"),
            (r"\frac{2}{3}+\frac{1}{3}=\boxed{1}", "1"),
            (r"0.1+0.2=\boxed{0.3}", "3/10"),
            (r"(-2)^2-5=\boxed{-1}", "-1"),
            (r"2+3=\boxed{005}", "5"),
        ):
            with self.subTest(chain=chain):
                text = display(chain)
                result = v2.extract_final_answer(text, "scalar")
                self.assertEqual(result["method"], "exact_final_chain_boxed_rhs", result)
                self.assertEqual(result["exact_chain_value"], expected)
                self.assertTrue(text[slice(*result["selected_span"])].startswith(r"\boxed"))
                self.assertEqual(result["version"], v2.VERSION)

    def test_local_assignments_and_source_spans(self):
        text = display(r"a+b+c=4+9+1=\boxed{14}", r"Thus, $a=4$, $b=9$, and $c=1$.", "### **Step 6: Final Answer**")
        result = v2.extract_final_answer(text, "scalar")
        self.assertEqual(result["components"], ["14"])
        self.assertEqual(result["checked_chain_terms"], 3)
        for name, binding in result["local_bindings"].items():
            self.assertEqual(text[slice(*binding["span"])], f"${name}={binding['value']}$")

    def test_an_unrelated_named_display_does_not_become_a_competing_scalar(self):
        prelude = r"The coordinate is obtained as follows. $$y=(3-\sqrt{57})/2$$ Thus, $a=4$, $b=9$."
        text = display(r"a+b=4+9=\boxed{13}", prelude)
        self.assertEqual(v2.extract_final_answer(text, "scalar")["components"], ["13"])

    def test_bracket_display_and_real_final_anchor(self):
        text = r"### Final Answer:" + "\n" + r"\[3 \cdot 4 = \boxed{12}\]."
        self.assertEqual(v2.extract_final_answer(text, "scalar")["components"], ["12"])

    def test_v1_output_is_preserved_for_every_nonrecovery_path(self):
        for text, kind in (
            (r"Final answer: \boxed{13}", "scalar"),
            (r"The solutions are \boxed{1}, \boxed{2}.", "set"),
            (r"Final answer: \boxed{(1,2,3)}", "tuple"),
            (r"Final answer: \boxed{1} or \boxed{2}", "scalar"),
            (display(r"2+3=5=\boxed{5}"), "set"),
        ):
            with self.subTest(text=text, kind=kind):
                self.assertEqual(v2.extract_final_answer(text, kind), v1.extract_final_answer(text, kind))

    def test_reject_wrong_malformed_unproved_and_alternative_chains(self):
        cases = [
            (r"2+3=4=\boxed{5}", ""),
            (r"2+3=\boxed{6}", ""),
            (r"x+1=4=\boxed{4}", ""),
            (r"x+1=4=\boxed{4}", r"Here, $x=2$."),
            (r"x+1=4=\boxed{4}", r"Here, $x=3$ or $x=4$."),
            (r"x+1=4=\boxed{4}", r"Here, $x=3$. Also, $x=4$."),
            (r"x+1=4=\boxed{4}", r"Suppose $x=3$."),
            (r"x+1=4=\boxed{4}", r"We rejected $x=3$."),
            (r"x+1=\boxed{4}", r"Here, $x=3$."),
            (r"x+1=x+1=\boxed{4}", r"Here, $x=3$."),
            (r"2+3\approx\boxed{5}", ""),
            (r"2+3=\boxed{5}", "Rounded to a whole number."),
            (r"2+3=\boxed{5}", "7."),
            (r"2+3=\boxed{5}", r"\[7\]"),
            (r"2+3=\boxed{5}", r"The answer is $7$."),
            (r"2+3=\boxed{5}", r"Earlier answer: \boxed{6}."),
            (r"2+3==\boxed{5}", ""),
            (r"2+3=5=\boxed{5} or 6", ""),
            (r"2+3=5=\boxed{5} + 1", ""),
            (r"2+3=5=\boxed{5", ""),
            (r"1/0=\boxed{1}", ""),
            (r"3^500000=\boxed{1}", ""),
            (r"0^0=\boxed{1}", ""),
            (r"abs(-1)=1=\boxed{1}", ""),
            (r"(1).real=1=\boxed{1}", ""),
            (r"2//2=\boxed{1}", ""),
            (r"2(3)=\boxed{6}", ""),
            (r"2+3=\boxed{5}", "Here, $x = 7 is unclosed."),
            (r"2+3=\boxed{5}", "Final Answer: 7"),
        ]
        for chain, prelude in cases:
            with self.subTest(chain=chain, prelude=prelude):
                text = display(chain, prelude)
                result = v2.extract_final_answer(text, "scalar")
                self.assertNotEqual(result["status"], "ok", result)
                self.assertEqual(result, v1.extract_final_answer(text, "scalar"))

    def test_intermediate_or_prior_competing_answer_remains_unselected(self):
        for text in (
            display(r"2+3=\boxed{5}", heading="### Intermediate Calculation"),
            "The answer is 7.\n\n" + display(r"2+3=\boxed{5}"),
            display(r"2+3=\boxed{5}") + "\n\nThe final choice is undecided.",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(v2.extract_final_answer(text, "scalar")["status"], "ok")

    def test_uncommitted_unchanged(self):
        text = display(r"2+3=\boxed{5}")
        for eos, closed in ((True, False), (False, True)):
            self.assertEqual(v2.score_final_answer(text, "5", eos=eos, think_closed=closed),
                             v1.score_final_answer(text, "5", eos=eos, think_closed=closed))

    @unittest.skipUnless(v2.backend_status()["status"] == "ok", "pinned grading backend required")
    def test_gold_only_affects_grade(self):
        text = display(r"2+3=\boxed{5}")
        good = v2.score_final_answer(text, "5", answer_kind="scalar")
        bad = v2.score_final_answer(text, "7", answer_kind="scalar")
        self.assertEqual(good["selection"], bad["selection"])
        self.assertTrue(good["grade"]["correct"])
        self.assertFalse(bad["grade"]["correct"])


if __name__ == "__main__":
    unittest.main()
