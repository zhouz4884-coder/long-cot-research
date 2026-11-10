"""Synthetic claim-scope and archive-boundary regressions. No heldout text."""
import json
from pathlib import Path
import unittest

from extract_d45_claims import (
    HERE, MODEL_ID, MODEL_REVISION, RULES_SHA, digest, exact_value, extract,
    extract_row, load_author_scorer, observation,
)


PARSER = HERE.parents[1] / "outputs" / "d43_aime_source_20261110" / "aime_scorer.py"
RULES = json.loads((HERE / "D45_OBSERVATION_RULES.json").read_bytes())
QUESTION = "Find the maximum number of disjoint pairs."
CASE = {"case_id": "synthetic", "direction": "MAX", "role_patterns": [r"\bpairs\b"],
        "question_sha256": digest(QUESTION.encode()), "eval_index": 0}


def sample(text, *, cap=False, draw=0):
    return {"problem_id": "synthetic", "eval_index": 0, "draw_index": draw, "sample_id": f"synthetic:draw-{draw:02d}",
            "seed": 1234 + 480 * draw, "response_sha256": digest(text.encode()), "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION, "contract_sha256": "a" * 64, "problem": QUESTION, "response": text,
            "finish_reason": "length" if cap else "stop", "stop_condition": "length_cap" if cap else "im_end",
            "stop_token_id": None if cap else 151645, "cap_hit": cap,
            "input_tokens": 200, "output_tokens": 32568 if cap else 23, "effective_max_new_tokens": 32568}


@unittest.skipUnless(PARSER.is_file(), "Requires the pinned D43 author parser asset")
class ScopedClaims(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorer = load_author_scorer(PARSER)

    def observe(self, text, known_close=True, **case):
        return observation(self.scorer, text, 7, {**CASE, **case}, 3000, known_close)

    def test_integer_scope_and_receipts(self):
        text = r"Thus the maximum number of disjoint pairs is \boxed{42}."
        row = self.observe(text)
        self.assertEqual(row["status"], "EXPLICIT_SCOPED_OPTIMUM")
        self.assertEqual(row["rational"], {"numerator": 42, "denominator": 1})
        for proof in [row, row["direction_receipt"], *row["role_receipts"]]:
            lo, hi = proof["char_span_in_response"]
            self.assertEqual(digest(text[lo - 7:hi - 7].encode()), proof["source_excerpt_sha256"])

    def test_exact_rational(self):
        row = self.observe(r"The maximum number of pairs equals \boxed{-\frac{3}{6}}.")
        self.assertEqual(row["value"], "-1/2")
        self.assertEqual(exact_value(r"\mathrm{0.50}"), exact_value("1 / 2"))
        for invalid in ("1/0", "1+2", r"\frac{1+1}{3}", r"\(1/2\]"):
            self.assertIsNone(exact_value(invalid))

    def test_scope_direction_and_tentative(self):
        for text, expected in (
            (r"The maximum area is \boxed{5}.", "LATER_UNSCOPED_BOX"),
            ("The minimum number of pairs is 5.", "WRONG_OPTIMUM_DIRECTION"),
            (r"Maybe the maximum number of pairs is \boxed{5}.", "TENTATIVE_OR_CONSTRUCTION_CLAIM"),
            ("In this construction the maximum number of pairs is 5.", "TENTATIVE_OR_CONSTRUCTION_CLAIM"),
            ("The maximum number of pairs is 5?", "NO_COMPLETE_SCOPED_OPTIMUM"),
            (r"The maximum number of pairs is \boxed{5}+2.", "LATER_UNSCOPED_BOX"),
            ("The maximum number of pairs is 5!", "NO_COMPLETE_SCOPED_OPTIMUM"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.observe(text)["status"], expected)

    def test_retraction_and_unscoped_new_box(self):
        prior = "The maximum number of pairs is 8.\n"
        for tail, expected in (
            ("Our previous answer is wrong.", "EXPLICIT_RETRACTION"),
            ("The earlier conclusion was not correct.", "EXPLICIT_RETRACTION"),
            (r"\boxed{9}", "LATER_UNSCOPED_BOX"),
            (r"\boxed{8", "LATER_UNCLOSED_BOX"),
            ("We now discuss another quantity.\n" + r"\boxed{8}", "LATER_UNSCOPED_BOX"),
            (" " * 240 + r"\boxed{8}", "LATER_UNSCOPED_BOX"),
        ):
            with self.subTest(tail=tail):
                self.assertEqual(self.observe(prior + tail)["status"], expected)
        self.assertEqual(self.observe(prior + "The maximum number of pairs is 9.")["value"], 9)

    def test_same_value_adjacent_header_only(self):
        prior = "The maximum number of pairs is 1/2.\n"
        tail = "**Final Answer**:\n" + r"\[\boxed{\frac{2}{4}}\]"
        row = self.observe(prior + tail)
        self.assertEqual(row["extraction_method"], "adjacent_repeated_box")
        self.assertEqual(row["value"], "1/2")
        self.assertIn("preceding_scoped_claim", row)
        self.assertEqual(self.observe(prior + tail + "\n" + r"\boxed{1/2}")["status"], "LATER_UNSCOPED_BOX")
        self.assertEqual(self.observe(prior + tail + "+2")["status"], "LATER_UNSCOPED_BOX")

    def test_early_never_reads_future_and_plain_token_is_complete(self):
        declaration = "The maximum number of pairs is 12.\n"
        prefix = "x" * (12000 - len(declaration) - 1) + "\n" + declaration
        row = extract_row(self.scorer, sample("<think>" + prefix + "The previous answer is wrong.</think>" + r"\boxed{10}"), CASE, RULES)
        self.assertEqual(row["early"]["value"], 12)
        self.assertEqual(row["early"]["observed_characters"], 12000)
        self.assertEqual(row["late"]["status"], "EXPLICIT_RETRACTION")
        self.assertTrue(row["native_final_eligible"])
        self.assertEqual(self.observe("The maximum number of pairs is 12", False)["status"], "NO_COMPLETE_SCOPED_OPTIMUM")
        self.assertEqual(self.observe("The maximum number of pairs is 12", True)["value"], 12)

    def test_boundaries_and_termination(self):
        short = extract_row(self.scorer, sample(r"<think>The maximum number of pairs is \boxed{8}.</think>\boxed{8}"), CASE, RULES)
        self.assertEqual(short["early"]["status"], "UNREACHED_EARLY_BOUNDARY")
        self.assertEqual(short["late"]["value"], 8)
        capped = extract_row(self.scorer, sample(r"<think>The maximum number of pairs is \boxed{8}.", cap=True), CASE, RULES)
        self.assertEqual(capped["early"]["status"], "UNREACHED_EARLY_BOUNDARY_CAP")
        self.assertEqual(capped["late"]["status"], "UNOBSERVABLE_THINKING_CLOSE")
        self.assertFalse(capped["native_final_eligible"])
        ambiguous = extract_row(self.scorer, sample(r"<think>The maximum number of pairs is \boxed{8}.</think></think>\boxed{8}"), CASE, RULES)
        self.assertEqual(ambiguous["late"]["status"], "UNOBSERVABLE_THINKING_CLOSE")
        self.assertFalse(ambiguous["native_final_eligible"])

    def test_complete_frozen_draw_grid_and_no_label_columns(self):
        traces = [sample(r"<think>The maximum number of pairs is \boxed{8}.</think>\boxed{8}", draw=draw) for draw in RULES["draws"]]
        draws = [{key: row[key] for key in ("draw_index", "sample_id", "seed", "response_sha256")} for row in traces]
        cohort = {"rows": [{**CASE, "draws": draws}], "selected_question_count": 1, "planned_draw_count": 8,
                  "planned_trace_count": 8, "observation_rules_sha256": RULES_SHA, "generation_contract_sha256": "a" * 64}
        blind = {"cohort_freeze_sha256": "b" * 64, "draws": RULES["draws"], "rows": traces}
        report = extract(self.scorer, blind, cohort, "b" * 64, RULES)
        self.assertEqual(report["paid_full_source_tokens"], {"input_tokens": 1600, "output_tokens": 184})
        self.assertEqual(len(report["rows"]), 8)
        with self.assertRaises(ValueError):
            extract(self.scorer, {**blind, "rows": traces[:-1]}, cohort, "b" * 64, RULES)
        with self.assertRaises(ValueError):
            extract_row(self.scorer, {**traces[0], "gold": 8}, CASE, RULES)
        with self.assertRaises(ValueError):
            extract(self.scorer, {**blind, "rows": [{**traces[0], "seed": 8}, *traces[1:]]}, cohort, "b" * 64, RULES)


if __name__ == "__main__":
    unittest.main()
