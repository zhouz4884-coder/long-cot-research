"""Adversarial and historical development controls for complete final answers."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import unittest

from complete_answer import (
    backend_status, extract_final_answer, grade_final_answer, score_final_answer,
)


class ExtractionTest(unittest.TestCase):
    def test_single_box_and_exact_source(self):
        text = "An intermediate value is " + r"\boxed{2}" + "\n\n### Final answer\n\n" + r"\[\boxed{\frac{1}{2}}\]"
        result = extract_final_answer(text, "scalar")
        self.assertEqual(result["components"], [r"\frac{1}{2}"])
        self.assertEqual(text[slice(*result["selected_span"])], r"\[\boxed{\frac{1}{2}}\]")
        self.assertFalse(result["selection_uses_gold"])

    def test_unlabeled_terminal_box(self):
        result = extract_final_answer("We find the requested quantity.\n\n" + r"\[\boxed{23}\]")
        self.assertEqual((result["status"], result["components"]), ("ok", ["23"]))

    def test_terminal_conclusion_inside_a_step(self):
        text = "### Step 3: Verify\nThe calculation is complete.\n\nThus, the required value is:\n" + r"\[\boxed{23}\]"
        self.assertEqual(extract_final_answer(text)["components"], ["23"])

    def test_explicit_inline_answer_after_heading(self):
        result = extract_final_answer("### Final answer\nTherefore, the answer is " + r"$\boxed{4}$.")
        self.assertEqual((result["status"], result["components"]), ("ok", ["4"]))

    def test_types_do_not_follow_list_punctuation_alone(self):
        text = r"Final answer: \boxed{1}, \quad \boxed{2}"
        self.assertEqual(extract_final_answer(text)["status"], "ambiguous")
        self.assertEqual(extract_final_answer(text, "scalar")["status"], "ambiguous")
        self.assertEqual(extract_final_answer(text, "set")["components"], ["1", "2"])

    def test_explicit_solution_set_and_or(self):
        result = extract_final_answer(r"Final answer: The solutions are \boxed{1} or \boxed{2}.")
        self.assertEqual((result["status"], result["kind"], result["components"]), ("ok", "set", ["1", "2"]))

    def test_quad_is_a_visible_set_separator(self):
        result = extract_final_answer(r"The solution set is \boxed{11}\quad\boxed{22}.")
        self.assertEqual((result["kind"], result["components"]), ("set", ["11", "22"]))

    def test_nested_delimiters_and_negative_values(self):
        result = extract_final_answer(r"Final answer: \boxed{(-1,\sqrt{4+5},\frac{1}{2})}", "tuple")
        self.assertEqual(result["components"], ["-1", r"\sqrt{4+5}", r"\frac{1}{2}"])

    def test_open_pair_requires_kind(self):
        text = r"Final answer: \boxed{(1,2)}"
        self.assertEqual(extract_final_answer(text)["reason"], "open_interval_or_ordered_pair")
        self.assertEqual(extract_final_answer(text, "interval")["closure"], [False, False])
        self.assertEqual(extract_final_answer(text, "tuple")["kind"], "tuple")

    def test_mixed_interval_and_vector_shape(self):
        self.assertEqual(extract_final_answer(r"\boxed{[-2,3)}", "interval")["closure"], [True, False])
        result = extract_final_answer(r"\boxed{\begin{pmatrix}2\\3\\5\end{pmatrix}}", "vector")
        self.assertEqual((result["components"], result["vector_shape"]), (["2", "3", "5"], [3, 1]))

    def test_two_boxes_inside_tuple_are_ordered(self):
        result = extract_final_answer(r"Final answer: $(\boxed{2},\boxed{1})$", "tuple")
        self.assertEqual((result["kind"], result["components"]), ("tuple", ["2", "1"]))

    def test_units_outside_wrappers_and_inside_box(self):
        cases = [
            (r"Final answer: $\boxed{12}$ square meters.", "m^2"),
            (r"Final answer: \boxed{12\text{ cm}^{2}}", "cm^2"),
            (r"Final answer: \boxed{3} miles per hour", "mi/h"),
            (r"Final answer: \boxed{7} in.", "in"),
        ]
        for text, unit in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_final_answer(text, "scalar")["unit"], unit)

    def test_equivalent_rational_repetitions_and_equality_chain(self):
        cases = [
            "Final answer: 0.5\nFinal answer: " + r"\boxed{\frac{1}{2}}",
            r"Final answer: \boxed{0.5}=\boxed{\frac{1}{2}}",
        ]
        for text in cases:
            with self.subTest(text=text):
                result = extract_final_answer(text, "scalar")
                self.assertEqual(result["status"], "ok")
                self.assertEqual(len(result["components"]), 1)

    def test_factorial_and_percent_remain_math(self):
        self.assertEqual(extract_final_answer(r"Final answer: \boxed{5!}")["components"], ["5!"])
        self.assertEqual(extract_final_answer(r"Final answer: \boxed{50%}")["components"], [r"50\%"])

    def test_set_metadata_does_not_override_uncertain_alternatives(self):
        for text in (r"Final answer: \boxed{3} or \boxed{5}", r"The solutions are possibly \boxed{3}, \boxed{5}"):
            with self.subTest(text=text):
                self.assertEqual(extract_final_answer(text, "set")["status"], "ambiguous")

    def test_conflicting_repeats_do_not_choose_a_winner(self):
        for text in (r"Final answer: \boxed{3}=\boxed{5}", "Final answer: 3\nFinal answer: 5"):
            with self.subTest(text=text):
                self.assertEqual(extract_final_answer(text, "scalar")["status"], "ambiguous")

    def test_disjoint_midtrace_or_incomplete_payload_never_delivers(self):
        examples = [
            "Intermediate: " + r"\boxed{8}",
            "### Step 2: intermediate result\nWe compute the value\n\n" + r"\boxed{8}",
            "Interim math " + r"\boxed{8}" + " and the last step is still needed.",
            r"Final answer: \boxed{3} plus the as yet unknown adjustment",
            r"Final answer: \boxed{3} or \boxed{",
            r"Final answer: \boxed{7}\text{m",
            r"Final answer: \boxed{7} cm^2}",
            "Final answer:\n$$\n" + r"\boxed{3}",
            "Final answer:\n\\[\n" + r"\boxed{3}",
            r"Final answer: \boxed{7} is the length, but 9 is the requested perimeter",
            r"Final answer: \boxed{3}\boxed{4}",
            r"Final answer: \boxed{(3,4,)}",
            r"Final answer: \boxed{\begin{pmatrix}3\\4}",
            "Final answer: 7...",
            "Final answer: <think>2</think>" + r"\boxed{7}",
            "```\n" + r"\boxed{7}" + "\n```",
            r"Final answer: \boxed{7} apples and 3 oranges",
            r"Final answer: \boxed{1.5} or uncertain",
            r"Final answer: \boxed{7}^{2}",
            r"Final answer: \boxed{8} -",
            "Final answer: 4\n\n" + r"\boxed{7}",
            "The final answer is 4.\nFinal answer: " + r"\boxed{7}",
            "Final answer:\n$$\n2+3\n" + r"\boxed{5}",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertNotEqual(extract_final_answer(text, "scalar")["status"], "ok")

    def test_non_eos_or_open_thinking_is_uncommitted(self):
        for eos, closed in ((True, False), (False, True), (False, False)):
            out = score_final_answer(r"\boxed{7}", "7", eos=eos, think_closed=closed)
            self.assertEqual(out["selection"]["status"], "uncommitted")
            self.assertFalse(out["grade"]["correct"])

    def test_different_gold_cannot_change_selection(self):
        text = r"Final answer: \boxed{3} or \boxed{5}"
        a = score_final_answer(text, "3", answer_kind="scalar")
        b = score_final_answer(text, "5", answer_kind="scalar")
        self.assertEqual(a["selection"], b["selection"])
        self.assertFalse(a["grade"]["correct"])


@unittest.skipUnless(backend_status()["status"] == "ok", "pinned math grading dependencies required")
class GradingTest(unittest.TestCase):
    def test_mathematical_and_type_controls(self):
        cases = [
            (r"\boxed{\frac{1}{3}}", "1/3", "scalar", True),
            (r"\boxed{0.333333}", "1/3", "scalar", False),
            (r"\boxed{\sqrt{8}}", r"2\sqrt{2}", "scalar", True),
            (r"\boxed{5!}", "120", "scalar", True),
            (r"\boxed{50%}", "1/2", "scalar", True),
            (r"\boxed{1,200}", "1200", "scalar", True),
            (r"\boxed{7} meters", "7 m", "scalar", True),
            (r"\boxed{7} cm", "7 m", "scalar", False),
            (r"\boxed{7} cm", "7", "scalar", True),
            (r"\boxed{575}", r"575\text{ students}", "scalar", True),
            (r"\boxed{(-\infty,2]}", r"(-\infty,2]", "interval", True),
            (r"\boxed{(-\infty,2]}", r"(-\infty,2)", "interval", False),
            (r"\boxed{(3,2)}", "(2,3)", "tuple", False),
            (r"\boxed{(6,31,-1)}", "(6,31,-1)", "tuple", True),
            (r"\boxed{6}", "(6,31,-1)", "tuple", False),
            (r"\boxed{(2,3)}", r"\begin{pmatrix}2\\3\end{pmatrix}", "vector", True),
            (r"\boxed{\begin{pmatrix}2&3\end{pmatrix}}", r"\begin{pmatrix}2\\3\end{pmatrix}", "vector", False),
            (r"\boxed{\{3,2,2\}}", r"\{2,3\}", "set", True),
            (r"\boxed{\{3,2,2\}}", r"\{2,3\}", "multiset", False),
            (r"\boxed{\{3,2,2\}}", r"\{2,3,2\}", "multiset", True),
            (r"\boxed{\{3,2,2\}}", "(2,3)", "tuple", False),
            (r"\boxed{\{\frac{1}{2},0.5\}}", r"\{0.5\}", "set", True),
            (r"\boxed{2\pm\sqrt{3}}", r"2-\sqrt{3},2+\sqrt{3}", "set", True),
            (r"\boxed{\varnothing}", "{}", "set", True),
            (r"\boxed{2}", "broken prose", "scalar", None),
            (r"\boxed{1/0}", "1", "scalar", None),
            (r"\boxed{7 garbage}", "7", "scalar", False),
            (r"\boxed{7} 8", "7", "scalar", False),
            (r"\boxed{7 8}", "7", "scalar", False),
        ]
        def run(case):
            text, gold, kind, expected = case
            return case, score_final_answer(text, gold, answer_kind=kind)
        with ThreadPoolExecutor(max_workers=6) as pool:
            for case, result in pool.map(run, cases):
                with self.subTest(case=case):
                    self.assertIs(result["grade"]["correct"], case[3], result)

    def test_historical_failures_replayed_with_frozen_bytes(self):
        d2 = Path(__file__).resolve().parent.parent / "phase5d2_quarantined_rebase_20261107"
        audit = json.loads((d2 / "FINAL_OBJECT_READOUT_AUDIT.json").read_bytes())
        old_scores = (d2 / "D2_SCORES.json").read_bytes()
        self.assertEqual(hashlib.sha256(old_scores).hexdigest(), audit["scores_sha256"])
        answers = {row["case_id"]: row["gold"] for row in map(json.loads, (d2 / "d2_eval_only.jsonl").read_bytes().splitlines())}
        d0 = d2.parent / "phase5d_scope_rebase_20261106"
        sys.path.insert(0, str(d0))
        try:
            from d0_answer_extract import extract_policy
        finally:
            sys.path.remove(str(d0))
        for row in audit["rows"]:
            with self.subTest(seed=row["seed"]):
                raw = (d2 / row["source_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row["source_sha256"])
                response = json.loads(raw)["final_response"]
                old = extract_policy(response, "LastBox")
                self.assertEqual((old["status"], old.get("surface")),
                                 (row["frozen_selection_status"], row["frozen_selected_surface"]))
                new = extract_final_answer(response, "set")
                self.assertEqual(new["components"], row["four_raw_box_surfaces"])
                graded = grade_final_answer(new, answers[row["case_id"]])
                self.assertTrue(graded["correct"], graded)
                self.assertEqual(graded["candidate_arity"], 4)


if __name__ == "__main__":
    unittest.main()
