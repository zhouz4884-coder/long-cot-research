"""Synthetic exact-channel and terminal-box association controls."""
import json
import unittest

from extract_d47_delivery import HERE, RULES_SHA, extract, final_point, prior, thinking_rules


PARSER = HERE.parents[1] / "outputs" / "d43_aime_source_20261110" / "aime_scorer.py"
RULES = json.loads((HERE / "D47_OBSERVATION_RULES.json").read_bytes())
QUESTION = "Find the least positive integer n."
CASE = {"case_id": "synthetic", "direction": "MIN", "subject_patterns": [r"n", r"positive integer n"],
        "question_sha256": prior.digest(QUESTION.encode()), "eval_index": 0, "unit": "integer index"}
THOUGHT = r"The least n is \boxed{397}."


def sample(final, *, thought=THOUGHT, cap=False, wrong_stop=False, draw=0, boundary="</think>"):
    text = "<think>" + thought + boundary + final
    return {"problem_id": CASE["case_id"], "eval_index": 0, "draw_index": draw, "sample_id": f"synthetic:draw-{draw:02d}",
            "seed": 1234 + 480 * draw, "response_sha256": prior.digest(text.encode()), "model_id": prior.MODEL_ID,
            "model_revision": prior.MODEL_REVISION, "contract_sha256": prior.GENERATION_CONTRACT,
            "problem": QUESTION, "response": text, "finish_reason": "length" if cap else "stop",
            "stop_condition": "length_cap" if cap else "im_end", "stop_token_id": None if cap else (151643 if wrong_stop else 151645),
            "cap_hit": cap, "input_tokens": 200, "output_tokens": 32568 if cap else 50, "effective_max_new_tokens": 32568}


@unittest.skipUnless(PARSER.is_file(), "Requires pinned D43 author parser asset")
class DeliveryReadout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorer = prior.load_author_scorer(PARSER)
        cls.prior_rules = thinking_rules(RULES)

    def examine(self, final, **kwargs):
        trace = sample(final, **kwargs)
        row = prior.extract_row(self.scorer, trace, CASE, self.prior_rules)
        return trace, row, final_point(self.scorer, trace, row, CASE, 3000)

    def test_final_has_its_own_prefix_and_custody_spans(self):
        trace, row, bound = self.examine(r"The least n is \boxed{533}.")
        self.assertEqual(row["late"]["value"], 397)
        self.assertEqual(row["final"]["value"], 533)
        self.assertEqual(bound["value"], 533)
        self.assertEqual(bound["status"], prior.BOUND)
        self.assertEqual(bound["unit"], CASE["unit"])
        start, end = bound["observation_char_span_in_response"]
        text = trace["response"][start:end]
        self.assertEqual(text, r"The least n is \boxed{533}.")
        n0, n1 = bound["numeric_span"]
        a0, a1 = bound["assertion_span"]
        self.assertTrue(a0 <= n0 < n1 <= a1)
        self.assertEqual(text[n0:n1], bound["numeric_text"])
        self.assertEqual(prior.digest(text[a0:a1].encode()), bound["assertion_sha256"])
        self.assertEqual(prior.digest(text.encode()), bound["observation_prefix_sha256"])
        self.assertEqual(bound["official_final_box_receipt"]["source_excerpt_sha256"], row["final"]["source_excerpt_sha256"])

    def test_same_value_does_not_import_thinking_scope(self):
        for final in (r"\boxed{397}", r"The least m is \boxed{397}.",
                      "The least n is 397.\nThe residue is discussed here.\n" + r"\boxed{397}"):
            with self.subTest(final=final):
                _, row, bound = self.examine(final)
                self.assertTrue(row["native_final_eligible"])
                self.assertEqual(row["late"]["value"], 397)
                self.assertEqual(bound["status"], "LATER_UNSCOPED_BOX")
                self.assertIsNone(bound["value"])

    def test_separate_scoped_prose_cannot_bind_unrelated_box(self):
        _, row, bound = self.examine(r"The residue is \boxed{397}." + "\nThe least n is 397.")
        self.assertTrue(row["native_final_eligible"])
        self.assertEqual(bound["status"], "FINAL_BOX_NOT_BOUND_TO_SCOPED_ASSERTION")
        self.assertEqual(bound["scoped_value"], 397)
        _, row, bound = self.examine(r"The residue is \boxed{396}." + "\nThe least n is 397.")
        self.assertEqual(row["final"]["value"], 396)
        self.assertEqual(bound["status"], "FINAL_SCOPED_SCALAR_DIFFERS_FROM_DELIVERED_BOX")

    def test_adjacent_echo_is_the_selected_box_with_original_assertion(self):
        _, row, bound = self.examine("The least n is 397.\n**Final Answer**\n" + r"\boxed{397}")
        self.assertEqual(bound["status"], prior.BOUND)
        self.assertEqual(bound["extraction_method"], "adjacent_repeated_box")
        self.assertEqual(bound["terminal_echo_receipt"]["char_span_in_response"], row["final"]["char_span_in_response"])
        self.assertLess(bound["assertion_span"][1], bound["terminal_echo_receipt"]["char_span_in_response"][0]
                        - bound["observation_char_span_in_response"][0])

    def test_cap_format_and_ambiguous_channels_never_bind_final(self):
        cases = ((r"The least n is \boxed{397}.", {"cap": True}, "FINAL_LENGTH_CAP"),
                 (r"The least n is \boxed{397}.", {"wrong_stop": True}, "FINAL_TERMINATION_UNKNOWN"),
                 (r"The least n is \boxed{397}.", {"boundary": "</think></think>"}, "FINAL_THINKING_BOUNDARY_UNKNOWN"),
                 (r"The least n is \boxed{397}.", {"boundary": ""}, "FINAL_THINKING_BOUNDARY_UNKNOWN"),
                 (r"The least n is \boxed{\frac{397}{1}}.", {}, "FINAL_NO_ELIGIBLE_STRICT_SCALAR"),
                 (r"The least n is \boxed{397}.\boxed{3", {}, "FINAL_NO_ELIGIBLE_STRICT_SCALAR"))
        for final, kwargs, expected in cases:
            with self.subTest(final=final, kwargs=kwargs):
                _, row, bound = self.examine(final, **kwargs)
                self.assertFalse(row["native_final_eligible"])
                self.assertEqual(bound["status"], expected)

    def test_exact_eos_marker_is_not_part_of_final_custody(self):
        trace, row, bound = self.examine(r"The least n is \boxed{397}<|im_end|>")
        self.assertEqual(bound["status"], prior.BOUND)
        self.assertTrue(bound["stripped_exact_eos_suffix"])
        self.assertEqual(bound["observation_char_span_in_response"][1], len(trace["response"]) - len("<|im_end|>"))
        _, row, bound = self.examine(r"The least n is \boxed{397}<|endoftext|>")
        self.assertTrue(row["native_final_eligible"])
        self.assertEqual(bound["status"], "FINAL_CHANNEL_CONTROL_AMBIGUOUS")

    def test_frozen_grid_uses_prior_thinking_and_full_paid_tokens(self):
        traces = [sample(r"The least n is \boxed{533}.", draw=draw) for draw in RULES["source_draws"]]
        draws = [{key: row[key] for key in ("draw_index", "sample_id", "seed", "response_sha256")} for row in traces]
        cohort = {"rows": [{**CASE, "draws": draws}], "selected_question_count": 1, "planned_trace_count": 8,
                  "observation_rules_sha256": RULES_SHA, "generation_contract_sha256": prior.GENERATION_CONTRACT}
        blind = {"cohort_freeze_sha256": "b" * 64, "draws": RULES["source_draws"], "rows": traces}
        report = extract(self.scorer, blind, cohort, "b" * 64, RULES)
        self.assertEqual(report["paid_full_source_tokens"], {"input_tokens": 1600, "output_tokens": 400})
        self.assertEqual(report["final_point_counts"], {prior.BOUND: 8})
        for trace, row in zip(traces, report["rows"], strict=True):
            old = prior.extract_row(self.scorer, trace, CASE, self.prior_rules)
            self.assertEqual({key: row[key] for key in ("early", "late", "final")},
                             {key: old[key] for key in ("early", "late", "final")})
        with self.assertRaises(ValueError):
            extract(self.scorer, {**blind, "rows": traces[:-1]}, cohort, "b" * 64, RULES)
        with self.assertRaises(ValueError):
            extract(self.scorer, {**blind, "rows": [{**traces[0], "gold": 397}, *traces[1:]]}, cohort, "b" * 64, RULES)


if __name__ == "__main__":
    unittest.main()
