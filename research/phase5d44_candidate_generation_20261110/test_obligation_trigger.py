from copy import deepcopy
import unittest

from obligation_trigger import SCOPE_PATTERNS, detect


class ObligationTriggerTests(unittest.TestCase):
    def setUp(self):
        self.case = {"case_id": "2009-II-12", "problem_kind": "EXTREMUM", "question_sha256": "a" * 64,
                     "obligation": {"kind": "congruence", "args": [9, 0],
                                    "question_sha256": "a" * 64, "proof_sha256": "b" * 64,
                                    "review_sha256": "c" * 64, "cue": "Check the necessary congruence.",
                                    "scope_patterns": SCOPE_PATTERNS["2009-II-12"]}}

    def test_wrong_commitment_has_actual_arithmetic(self):
        result = detect(self.case, "Maximum number of pairs.\n**Final Answer**\n\\boxed{19}.\n")
        self.assertEqual(result["observed_candidate"], 19)
        self.assertEqual(result["arithmetic"]["observed_residue"], 1)

    def test_satisfying_condition_does_not_trigger(self):
        self.assertIsNone(detect(self.case, "Maximum number of pairs.\n**Final Answer**\n\\boxed{18}"))

    def test_incomplete_tentative_and_reopened_candidate(self):
        for prefix in (
            "Maybe \\boxed{19}.",
            "**Final Answer**\n\\boxed{19",
            "**Final Answer**\n\\boxed{19}.\nWait, that does not follow.",
            "**Final Answer**\n\\boxed{19}\n\\boxed{18}",
            "**Final Answer**\n\\boxed{19}\n</think>",
        ):
            with self.subTest(prefix=prefix):
                self.assertIsNone(detect(self.case, "Maximum number of pairs.\n" + prefix))

    def test_subgoal_box_is_not_bound_to_original_target(self):
        self.assertIsNone(detect(self.case, "Intermediate addition.\n**Final Answer**\n\\boxed{19}"))

    def test_bad_scope_and_format_only(self):
        prefix = "Maximum number of pairs.\n### ✅ Final Answer:\n$$\\boxed{1004}$$"
        item = deepcopy(self.case)
        item["obligation"]["question_sha256"] = "0" * 64
        self.assertIsNone(detect(item, prefix))
        item = deepcopy(self.case)
        item["obligation"].update(kind="closed_interval", args=[0, 999])
        self.assertIsNone(detect(item, prefix))


if __name__ == "__main__":
    unittest.main()
