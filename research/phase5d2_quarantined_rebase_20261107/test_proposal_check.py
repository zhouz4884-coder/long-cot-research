"""CPU-only malformed-proposal and scope checks with synthetic statements."""
import hashlib
import json
import unittest

from natural_evidence import relations
from proposal_check import check_proposal, parse_counterexample
from restricted_math_checker import LIMITS


def relation(text):
    rows = list(relations({"text": text, "step": 1, "start": 0, "end": 30}))
    assert len(rows) == 1
    return rows[0]


class ProposalCheckTests(unittest.TestCase):
    def test_complete_integer_and_rational_assignment(self):
        text = ' {"assignment":{"x":-3,"y":{"op":"rat","num":1,"den":2}}} \n'
        parsed = parse_counterexample(text, ["x", "y"])
        self.assertEqual(parsed["status"], "parsed")
        self.assertEqual(parsed["assignment"], {"x": -3, "y": {"op": "rat", "num": 1, "den": 2}})
        self.assertEqual(parsed["proposal_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_zero_one_and_negative_denominator_are_exact_values(self):
        for value in (0, 1, -1, {"op": "rat", "num": 0, "den": 3}, {"op": "rat", "num": 1, "den": -2}):
            text = json.dumps({"assignment": {"x": value}})
            self.assertEqual(parse_counterexample(text, ["x"])["status"], "parsed")

    def test_duplicate_keys_at_every_level_are_rejected(self):
        samples = (
            '{"assignment":{"x":1},"assignment":{"x":2}}',
            '{"assignment":{"x":1,"x":2}}',
            '{"assignment":{"x":{"op":"rat","num":1,"num":2,"den":3}}}',
            '{"assignment":{"x":1,"\\u0078":2}}',
        )
        for text in samples:
            with self.subTest(text=text):
                result = parse_counterexample(text, ["x"])
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(result["reason"], "duplicate_json_key")

    def test_model_prose_code_and_multiple_objects_are_rejected(self):
        samples = (
            'A counterexample is x=2.',
            'Here is JSON {"assignment":{"x":2}}',
            '{"assignment":{"x":2}} then it is false.',
            '{"assignment":{"x":1}} {"assignment":{"x":2}}',
            '```json\n{"assignment":{"x":2}}\n```',
            '{"assignment":{"x":__import__("os")}}',
            '[{"assignment":{"x":2}}]',
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(parse_counterexample(text, ["x"])["status"], "UNKNOWN")

    def test_exact_one_field_and_exact_all_variables_required(self):
        samples = (
            '{"assignment":{"x":2},"reason":"trusted"}',
            '{"assignment":{"x":2,"y":3}}',
            '{"assignment":{}}',
            '{"assignment":[2]}',
            '{"x":2}',
        )
        for text in samples:
            self.assertEqual(parse_counterexample(text, ["x"])["status"], "UNKNOWN")
        self.assertEqual(parse_counterexample('{"assignment":{"x":2}}', ["x", "y"])["status"], "UNKNOWN")

    def test_boolean_float_string_and_inexact_forms_rejected(self):
        samples = (True, False, 0.5, "2", "1/2", [1], None,
                   {"op": "rat", "num": 1, "den": 0},
                   {"op": "rat", "num": True, "den": 2},
                   {"op": "rat", "num": 1, "den": 2.0},
                   {"op": "rat", "num": 1, "den": 2, "extra": 0},
                   {"op": "add", "args": [1, 2]})
        for value in samples:
            with self.subTest(value=value):
                text = json.dumps({"assignment": {"x": value}})
                self.assertEqual(parse_counterexample(text, ["x"])["status"], "UNKNOWN")
        for text in ('{"assignment":{"x":NaN}}', '{"assignment":{"x":Infinity}}', '{"assignment":{"x":1e3}}'):
            self.assertEqual(parse_counterexample(text, ["x"])["status"], "UNKNOWN")

    def test_integer_bit_bound_applies_to_every_rational_member(self):
        largest = (1 << LIMITS["input_integer_bits"]) - 1
        self.assertEqual(parse_counterexample(json.dumps({"assignment": {"x": largest}}), ["x"])["status"], "parsed")
        too_big = 1 << LIMITS["input_integer_bits"]
        for value in (too_big, -too_big, {"op": "rat", "num": too_big, "den": 1}, {"op": "rat", "num": 1, "den": too_big}):
            self.assertEqual(parse_counterexample(json.dumps({"assignment": {"x": value}}), ["x"])["status"], "UNKNOWN")

    def test_empty_duplicate_invalid_variable_list_rejected(self):
        text = '{"assignment":{"x":2}}'
        for variables in ([], (), ["x", "x"], [True], ["x;exec"], "x", ["x", "y", "z", "w", "v"]):
            with self.subTest(variables=variables):
                self.assertEqual(parse_counterexample(text, variables)["status"], "UNKNOWN")

    def test_unclosed_and_oversized_text_abstain(self):
        for text in ('{"assignment":{"x":2}', '', ' ' * 4097, '{"assignment":{"x":' + '[' * 1100 + '0' + ']' * 1100 + '}}'):
            self.assertEqual(parse_counterexample(text, ["x"])["status"], "UNKNOWN")
        oversized = parse_counterexample(" " * 4097, ["x"])
        self.assertIsNone(oversized["proposal_sha256"])
        self.assertEqual(parse_counterexample("\ud800", ["x"])["reason"], "invalid_unicode_text")

    def test_valid_in_scope_counterexample_targets_justification(self):
        row = relation("For all positive integer x: $x^2=x$.")
        result = check_proposal(row, '{"assignment":{"x":2}}')
        self.assertEqual(result["parser"]["status"], "parsed")
        self.assertEqual(result["status"], "INVALID_JUSTIFICATION")
        self.assertEqual(result["checker_result"]["witness"]["lhs"], "4")
        self.assertFalse(result["unscoped"])

    def test_outside_domain_counterexample_is_rejected(self):
        row = relation("For all positive integer x: $x^2=x$.")
        text = '{"assignment":{"x":-1}}'
        scoped = check_proposal(row, text)
        unscoped = check_proposal(row, text, unscoped=True)
        self.assertEqual(scoped["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(unscoped["status"], "INVALID_JUSTIFICATION")
        self.assertNotEqual(scoped["checker_result"]["binding"]["scope"], unscoped["checker_result"]["binding"]["scope"])

    def test_legal_point_that_satisfies_original_claim_is_invalid_counterexample(self):
        row = relation("For all positive integer x: $x^2=x$.")
        result = check_proposal(row, '{"assignment":{"x":1}}')
        self.assertEqual(result["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(result["checker_result"]["reason"], "counterexample_satisfies_statement")

    def test_closed_arithmetic_and_unbound_scope_have_no_proposal_action(self):
        closed = relation("$2+3=6$")
        self.assertEqual(check_proposal(closed, '{"assignment":{}}')["status"], "UNKNOWN")
        unknown = relation("$x=x$")
        self.assertEqual(check_proposal(unknown, '{"assignment":{"x":2}}')["status"], "UNKNOWN")

    def test_parser_failure_does_not_reach_math_decision(self):
        row = relation("For all positive integer x: $x^2=x$.")
        result = check_proposal(row, "try x=2")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["parser"]["status"], "UNKNOWN")
        self.assertNotIn("certificate", result["checker_result"])

    def test_scope_ablation_requires_an_explicit_boolean(self):
        row = relation("For all positive integer x: $x^2=x$.")
        result = check_proposal(row, '{"assignment":{"x":-1}}', unscoped="false")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["checker_result"]["reason"], "explicit_scope_mode_required")
        self.assertIsNone(result["unscoped"])


if __name__ == "__main__":
    unittest.main()
