"""Historical extraction regressions and independent adversarial controls."""

from decimal import Decimal
import json
from pathlib import Path
import re
import unittest

from proposal_check import check_event
from typed_math_events import digest, extract_events


OLD = Path(__file__).resolve().parents[1] / "phase5d2_quarantined_rebase_20261107"
PREFIX = "f" * 64


def step(text, n=0):
    return {"step": n, "start": n * 10, "end": (n + 1) * 10, "text": text}


def extract(text, history=()):
    return extract_events(step(text, len(history)), observed_prefix_sha256=PREFIX, prior_steps=history)


class TypedEventTests(unittest.TestCase):
    def test_historical_regressions_and_nine_wrong_result_controls(self):
        cases = json.loads((OLD / "INVALID_LITERAL_FAILURE_MODES.json").read_text(encoding="utf-8"))["rows"]
        seen = {"ROUNDING_MATCH": 0, "CROSS_PARAGRAPH_SUM": 0}
        for case in cases:
            with self.subTest(case=case["case_id"], seed=case["seed"], step=case["step"]):
                raw = json.loads((OLD / case["source_result"]).read_text(encoding="utf-8"))
                index = case["step"]
                current = raw["steps"][index]
                history = raw["steps"][:index]
                prefix = digest(raw["prompt_ids"] + raw["generated_ids"][:current["end"]])
                event, = extract_events(current, observed_prefix_sha256=prefix, prior_steps=history)
                outcome = check_event(event)
                if case["reason"] == "ROUNDING_MATCH":
                    self.assertEqual(event.kind, "APPROX_ARITHMETIC")
                    self.assertEqual(event.statement["precision_mode"], "INFERRED_DISPLAY_PRECISION")
                    self.assertEqual(outcome["status"], "ROUNDING_COMPATIBLE")
                    negative_status = "ROUNDING_INCOMPATIBLE"
                else:
                    self.assertEqual(event.kind, "RUNNING_SUM_CONTINUATION")
                    self.assertEqual(outcome["status"], "VERIFIED_RUNNING_SUM")
                    negative_status = "INVALID_RUNNING_SUM"
                self.assertEqual(outcome["action"], "NONE")
                self.assertTrue(event.dependencies)
                self.assertTrue(all(dep.token_span[1] <= current["start"] for dep in event.dependencies))
                printed = re.search(r"=\s*([+-]?\d+(?:\.\d+)?)\s*$", current["text"])
                self.assertIsNotNone(printed)
                value = Decimal(printed[1])
                wrong = value + Decimal(1).scaleb(value.as_tuple().exponent)
                changed_text = current["text"][:printed.start(1)] + str(wrong) + current["text"][printed.end(1):]
                changed = {**current, "text": changed_text}
                bad_event, = extract_events(changed, observed_prefix_sha256=digest([prefix, changed_text]), prior_steps=history)
                bad = check_event(bad_event)
                self.assertEqual(bad_event.kind, event.kind)
                self.assertEqual(bad["status"], negative_status)
                self.assertFalse(bad["truth"])
                self.assertEqual(bad["action"], "NONE")
                self.assertNotEqual(bad_event.event_id, event.event_id)
                seen[case["reason"]] += 1
        self.assertEqual(seen, {"ROUNDING_MATCH": 5, "CROSS_PARAGRAPH_SUM": 4})

    def test_rounding_requires_context_or_an_explicit_marker(self):
        plain, = extract("1.33822558 * 0.04 = 0.053529023")
        self.assertEqual(plain.kind, "CLOSED_ARITHMETIC")
        self.assertEqual(check_event(plain)["status"], "FALSE_LITERAL")
        scope_reset = [step("Compute 1.33822558 * 0.74727 ≈ ?", 0), step("New exact calculation:", 1)]
        reset, = extract("1.33822558 * 0.04 = 0.053529023", scope_reset)
        self.assertEqual(reset.kind, "CLOSED_ARITHMETIC")
        explicit, = extract("Rounded to 2 decimal places: 1/3 = 0.33")
        self.assertEqual(explicit.statement["precision_mode"], "DECLARED_DECIMAL_PLACES")
        self.assertEqual(check_event(explicit)["status"], "ROUNDING_COMPATIBLE")
        invalid_grid, = extract("Rounded to 2 decimal places: 1/3 = 0.333")
        self.assertEqual(check_event(invalid_grid)["status"], "ROUNDING_INCOMPATIBLE")

    def test_terminal_factorial_is_preserved_in_bare_and_delimited_equations(self):
        examples = (
            ("k=2, sum is 1 + 1 + 4 = 6 = 3!.\n\n", "3!"),
            ("k=3, sum is 1 + 1 + 4 + 18 = 24 = 4!.\n\n", "4!"),
            (r"\[1 + 1 + 4 = 6 = 3!\].", "3!"),
            ("$24=4!$.", "4!"),
        )
        for text, terminal in examples:
            with self.subTest(text=text):
                events = extract(text)
                self.assertIn(terminal, events[-1].raw)
                self.assertEqual(events[-1].eligibility, "UNSUPPORTED_EQUATION_SURFACE")
                self.assertEqual(check_event(events[-1])["status"], "UNKNOWN")
                self.assertNotIn("FALSE_LITERAL", [check_event(event)["status"] for event in events])

    def test_open_approximation_chain_supplies_local_display_context(self):
        current = "First, 1.349858 * 0.99 = 1.336359\n\n"
        history = [step("So e^0.2913 ≈ 1.349858 * 0.99135 ≈ \n\n")]
        event, = extract(current, history)
        result = check_event(event)
        self.assertEqual(event.kind, "APPROX_ARITHMETIC")
        self.assertEqual(event.statement["precision_mode"], "INFERRED_DISPLAY_PRECISION")
        self.assertEqual(result["status"], "ROUNDING_COMPATIBLE")
        self.assertEqual(result["action"], "NONE")
        wrong, = extract(current.replace("1.336359", "1.336358"), history)
        self.assertEqual(check_event(wrong)["status"], "ROUNDING_INCOMPATIBLE")
        unrelated = [step("Approximate background value. 1.349858 * 0.99135 ≈ \n\n")]
        isolated, = extract(current, unrelated)
        self.assertEqual(isolated.kind, "CLOSED_ARITHMETIC")
        self.assertEqual(check_event(isolated)["status"], "FALSE_LITERAL")

    def test_calibration_list_items_are_not_read_as_negative_operands(self):
        observed = (
            "- 1 + 3 + 5 = 9\n\n",
            "- 1 + 3 + 7 = 11\n\n",
            "- 1 + 5 + 7 = 13\n\n",
            "- 3 + 5 + 7 = 15\n\n",
        )
        for index, text in enumerate(observed, 100):
            with self.subTest(case="D3_P03", step=index):
                event, = extract(text)
                self.assertEqual(event.raw, text)
                result = check_event(event)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(result["reason"], "ambiguous_leading_hyphen")
                self.assertEqual(result["action"], "NONE")

    def test_signed_math_and_list_marker_adversaries(self):
        controls = (("-1+3=2", "VERIFIED"), ("-1+3=4", "FALSE_LITERAL"),
                    ("$- 1+3=2$", "VERIFIED"), ("- $- 1+3=2$", "VERIFIED"),
                    ("− 1+3=2", "VERIFIED"), ("5 - 1=4", "VERIFIED"),
                    ("  -\t1+3=2", "UNKNOWN"), ("- 1+3=4", "UNKNOWN"))
        for text, expected in controls:
            with self.subTest(text=text):
                event, = extract(text)
                self.assertEqual(check_event(event)["status"], expected)

    def test_leading_list_marker_cannot_supply_a_predecessor(self):
        history = [dict(step("- 1+3=2\n\n"), boundary="paragraph")]
        current = dict(step("This implies $1=1$.\n\n", 1), boundary="paragraph")
        event, = extract_events(current, observed_prefix_sha256=PREFIX, prior_steps=history)
        self.assertEqual(check_event(event)["reason"], "unsupported_transition_surface")
        subtotal, = extract("+ 1=3", [step("Adding these up:", 0), step("- 1+3=2", 1)])
        self.assertEqual(check_event(subtotal)["reason"], "unbound_running_subtotal")

    def test_subtotal_requires_anchor_and_verified_contiguous_history(self):
        unrelated, = extract("+ 1 = 5", [step("2 + 2 = 4")])
        self.assertEqual(check_event(unrelated)["reason"], "unbound_running_subtotal")
        wrong_history = [step("Adding these up:", 0), step("2+2=5", 1)]
        invalid, = extract("+ 1 = 6", wrong_history)
        self.assertEqual(check_event(invalid)["reason"], "prior_subtotal_not_verified")
        interrupted = [step("Adding these up:", 0), step("2+2=4", 1), step("New branch:", 2)]
        stale, = extract("+ 1 = 5", interrupted)
        self.assertEqual(check_event(stale)["reason"], "unbound_running_subtotal")

    def test_extraction_keeps_equations_and_assignments_distinct(self):
        plain, = extract("x=1")
        candidate, = extract("Candidate solution: x=1, y=-2/3")
        identity, = extract("Identity: $x+x=2*x$")
        transition, = extract(r"$x+2=5 \Leftrightarrow x=3$")
        self.assertEqual((plain.kind, candidate.kind, identity.kind, transition.kind),
                         ("EQUATION", "CANDIDATE_SOLUTION", "SYMBOLIC_IDENTITY", "EQUATION_TRANSITION"))
        self.assertEqual(candidate.statement["assignment"]["y"], {"op": "rat", "num": -2, "den": 3})
        self.assertEqual(transition.statement["direction"], "IFF")
        self.assertEqual(transition.raw, r"$x+2=5 \Leftrightarrow x=3$")

    def test_cross_paragraph_transition_does_not_skip_an_intervening_step(self):
        prior = [dict(step("$x=1$\n\n", 0), boundary="paragraph"),
                 dict(step("Try a different argument.\n\n", 1), boundary="paragraph")]
        current = dict(step("This implies $x^2=1$.\n\n", 2), boundary="paragraph")
        event, = extract_events(current, observed_prefix_sha256=PREFIX, prior_steps=prior)
        self.assertEqual(event.kind, "EQUATION_TRANSITION")
        self.assertEqual(event.eligibility, "UNSUPPORTED_TRANSITION_SURFACE")
        self.assertEqual(check_event(event)["status"], "UNKNOWN")
        same_paragraph = extract("$x=1$. This implies $x^2=1$.\n\n")
        self.assertNotIn("EQUATION_TRANSITION", [item.kind for item in same_paragraph])

    def test_event_payload_is_detached_and_roles_remain_untrusted(self):
        original = {**step("2+2=5"), "role_certified": True, "role": "ASSERTED_JUSTIFICATION"}
        event, = extract_events(original, observed_prefix_sha256=PREFIX)
        binding = event.event_id
        event.statement["rhs"] = 4
        self.assertEqual(event.event_id, binding)
        self.assertEqual(event.statement["rhs"], 5)
        self.assertEqual(check_event(event)["action"], "NONE")


if __name__ == "__main__":
    unittest.main()
