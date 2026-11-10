"""Synthetic scope, exact numeric custody and archive-boundary controls."""
import json
import unittest

from extract_d46_points import (
    ASSERTED, BOUND, GENERATION_CONTRACT, HERE, MODEL_ID, MODEL_REVISION, RULES_SHA,
    digest, extract, extract_row, load_author_scorer, observation,
)


PARSER = HERE.parents[1] / "outputs" / "d43_aime_source_20261110" / "aime_scorer.py"
RULES = json.loads((HERE / "D46_OBSERVATION_RULES.json").read_bytes())
QUESTION = "Find the least positive integer index n."
MIN_N = {"case_id": "synthetic", "direction": "MIN", "subject_patterns": [r"(?:positive integer )?n", r"(?:valid )?index"],
         "question_sha256": digest(QUESTION.encode()), "eval_index": 0}
MAX_N = {**MIN_N, "direction": "MAX"}
MIN_SUM = {**MIN_N, "subject_patterns": [r"(?:value of )?m\s*\+\s*n", r"sum of m and n"]}
DIRECT = {**MIN_N, "direction": "VALUE", "subject_patterns": [r"number of matchings", r"N"]}


def sample(text, *, cap=False, draw=0):
    return {"problem_id": "synthetic", "eval_index": 0, "draw_index": draw, "sample_id": f"synthetic:draw-{draw:02d}",
            "seed": 1234 + 480 * draw, "response_sha256": digest(text.encode()), "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION, "contract_sha256": GENERATION_CONTRACT, "problem": QUESTION,
            "response": text, "finish_reason": "length" if cap else "stop",
            "stop_condition": "length_cap" if cap else "im_end", "stop_token_id": None if cap else 151645,
            "cap_hit": cap, "input_tokens": 200, "output_tokens": 32568 if cap else 23, "effective_max_new_tokens": 32568}


@unittest.skipUnless(PARSER.is_file(), "Requires pinned D43 author parser asset")
class ScopedPoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorer = load_author_scorer(PARSER)

    def see(self, text, case=MIN_N, known_close=True, offset=7):
        return observation(self.scorer, text, offset, case, 3000, known_close)

    def test_persistent_development_points_are_subject_bound(self):
        examples = [(r"The least possible value of $m+n$ is \boxed{23}.", MIN_SUM, 23),
                    (r"Therefore, the least positive integer \(n\) is \boxed{397}.", MIN_N, 397),
                    (r"The least possible value of $n$ is \boxed{397}.", MIN_N, 397),
                    ("The first valid index is 397.", MIN_N, 397),
                    (r"Thus the number of matchings equals \boxed{18}.", DIRECT, 18)]
        for text, case, value in examples:
            with self.subTest(text=text):
                got = self.see(text, case)
                self.assertEqual(got["status"], BOUND)
                self.assertEqual(got["assertion_role"], ASSERTED)
                self.assertEqual(got["value"], value)
                n0, n1 = got["numeric_span"]
                a0, a1 = got["assertion_span"]
                self.assertTrue(a0 <= n0 < n1 <= a1)
                self.assertEqual(text[n0:n1], got["numeric_text"])
                self.assertEqual(digest(text[a0:a1].encode()), got["assertion_sha256"])
                for item in (got, got["assertion_operator_receipt"], got["subject_receipt"]):
                    lo, hi = item["char_span_in_response"]
                    self.assertEqual(digest(text[lo-7:hi-7].encode()), item["source_excerpt_sha256"])

    def test_threshold_including_equality_counterexample(self):
        for relation in ("<=", "≤", r"\leq", "=", ">=", r"\ge", "≠"):
            for lead in ("Find the maximum", "The maximum"):
                text = f"{lead} n where f(n) {relation} 300."
                with self.subTest(text=text):
                    self.assertNotEqual(self.see(text, MAX_N)["status"], BOUND)
        self.assertEqual(self.see("The maximum n = 300.", MAX_N)["value"], 300)

    def test_trials_inequalities_unrelated_expressions_and_partial_rhs(self):
        for text, case in (
            ("Try the least n = 397.", MIN_N), ("The smallest n >= 397.", MIN_N),
            (r"The least n \equiv 397.", MIN_N), ("The least n == 397.", MIN_N),
            (r"The least n is \boxed{397}+2.", MIN_N), ("The least n is 397 or 797.", MIN_N),
            ("The least n is 397 assuming p.", MIN_N), ("If we try n=397, the least n is 397.", MIN_N),
            ("Assume a special case.\nThe least n is 397.", MIN_N),
            ("Assume a special case.\nNow compute.\nThe least n is 397.", MIN_N),
            ("Case A:\nThe least n is 397.", MIN_N), ("The largest n is 397.", MIN_N),
            ("The first n is 397.", MIN_N), ("```text\nThe least n is 397.\n```", MIN_N),
            ("The least m is 23.", MIN_SUM), ("The least sum is 23.", MIN_SUM),
            ("The least f(n) is 397.", MIN_N), (r"**Final Answer**\boxed{397}", MIN_N),
            ("The least n is 397?", MIN_N), ("The least n is 397!", MIN_N),
            ("The least n is 397/0.", MIN_N), ("The least n is --397.", MIN_N),
        ):
            with self.subTest(text=text):
                self.assertNotEqual(self.see(text, case)["status"], BOUND)

    def test_exact_rationals_preserve_source_spellings(self):
        result = self.see(r"The least n is \boxed{\frac{-6}{8}}.")
        self.assertEqual(result["rational"], {"numerator": -3, "denominator": 4})
        self.assertEqual(result["numeric_text"], r"\frac{-6}{8}")
        self.assertEqual(self.see("The least n is 0.50.")["value"], "1/2")

    def test_echo_keeps_original_declaring_spans(self):
        prior = "The least n is 397.\n"
        echo = "**Final Answer**:\n" + r"\[\boxed{397}\]"
        original, repeated = self.see(prior), self.see(prior + echo)
        self.assertEqual(repeated["extraction_method"], "adjacent_repeated_box")
        for key in ("assertion_span", "assertion_sha256", "numeric_span", "numeric_text"):
            self.assertEqual(original[key], repeated[key])
        self.assertNotEqual(original["char_span_in_response"], repeated["char_span_in_response"])
        for tail in (r"\boxed{398}", "Recompute.\n" + echo, " " * 240 + echo, echo + "\n" + r"\boxed{397}"):
            with self.subTest(tail=tail):
                self.assertEqual(self.see(prior + tail)["status"], "LATER_UNSCOPED_BOX")

    def test_retraction_and_later_partial_target_deauthorize(self):
        prior = "The least n is 397.\n"
        self.assertEqual(self.see(prior + "My previous answer is wrong.")["status"], "EXPLICIT_RETRACTION")
        self.assertEqual(self.see(prior + "The least n is ", known_close=False)["status"],
                         "INCOMPLETE_OR_NONSCALAR_TARGET_ASSERTION")
        self.assertEqual(self.see(prior + r"\boxed{39")["status"], "LATER_UNCLOSED_BOX")
        self.assertEqual(self.see(prior + "Actually, the least n is 797.")["value"], 797)

    def test_cutoff_late_native_and_cap_are_distinct(self):
        phrase = "The least n is 397.\n"
        prefix = "x" * (12000 - len(phrase) - 1) + "\n" + phrase
        out = extract_row(self.scorer, sample("<think>" + prefix + "The least n is 797.</think>" + r"\boxed{797}"), MIN_N, RULES)
        self.assertEqual(out["early"]["value"], 397)
        self.assertEqual(out["late"]["value"], 797)
        self.assertEqual(out["early"]["observation_char_span_in_response"], [7, 12007])
        self.assertEqual(out["early"]["observation_prefix_sha256"], digest(prefix.encode()))
        self.assertTrue(out["native_final_eligible"])
        self.assertEqual(self.see("The least n is 397", known_close=False)["status"], "INCOMPLETE_OR_NONSCALAR_TARGET_ASSERTION")
        short = extract_row(self.scorer, sample("<think>" + phrase, cap=True), MIN_N, RULES)
        self.assertEqual(short["early"]["status"], "UNREACHED_EARLY_BOUNDARY_CAP")
        self.assertEqual(short["late"]["status"], "UNOBSERVABLE_THINKING_CLOSE")
        self.assertFalse(short["native_final_eligible"])
        capped = extract_row(self.scorer, sample("<think>" + prefix, cap=True), MIN_N, RULES)
        self.assertEqual(capped["early"]["value"], 397)
        self.assertFalse(capped["native_final_eligible"])
        unmarked = extract_row(self.scorer, sample(prefix, cap=True), MIN_N, RULES)
        self.assertEqual(unmarked["early"]["status"], "UNOBSERVABLE_OPEN_THINKING_PREFIX")
        ambiguous = extract_row(self.scorer, sample("<think>" + phrase + "</think></think>" + r"\boxed{397}"), MIN_N, RULES)
        self.assertEqual(ambiguous["late"]["status"], "UNOBSERVABLE_THINKING_CLOSE")
        self.assertFalse(ambiguous["native_final_eligible"])

    def test_frozen_archive_draw_matrix_and_blind_schema(self):
        traces = [sample(r"<think>The least n is \boxed{397}.</think>\boxed{397}", draw=draw) for draw in RULES["source_draws"]]
        draws = [{key: row[key] for key in ("draw_index", "sample_id", "seed", "response_sha256")} for row in traces]
        cohort = {"rows": [{**MIN_N, "draws": draws}], "selected_question_count": 1, "planned_trace_count": 8,
                  "observation_rules_sha256": RULES_SHA, "generation_contract_sha256": GENERATION_CONTRACT}
        blind = {"cohort_freeze_sha256": "b" * 64, "draws": RULES["source_draws"], "rows": traces}
        report = extract(self.scorer, blind, cohort, "b" * 64, RULES)
        self.assertEqual(report["paid_full_source_tokens"], {"input_tokens": 1600, "output_tokens": 184})
        self.assertEqual(len(report["rows"]), 8)
        for changed in (traces[:-1], [{**traces[0], "gold": 397}, *traces[1:]], [{**traces[0], "seed": 2}, *traces[1:]]):
            with self.assertRaises(ValueError):
                extract(self.scorer, {**blind, "rows": changed}, cohort, "b" * 64, RULES)


if __name__ == "__main__":
    unittest.main()
