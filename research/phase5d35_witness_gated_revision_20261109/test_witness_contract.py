"""Source coverage, exact candidate certification and partial-claim controls."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from witness_contract import (COINS, DIGITS, DIVISORS, PRIME, SEQUENCE, check_candidate,
                              check_claim_witness, compile_contract, canonical)


DATA = Path(__file__).resolve().parents[1] / "phase5d25_constraint_revision_20261109/prepared_data"
QUESTIONS = {row["case_id"]: row["question"] for bank in ("bank", "precheck")
             for row in map(json.loads, (DATA / bank / "visible.jsonl").read_bytes().splitlines())}


def contract(case):
    return compile_contract(QUESTIONS[case])


HALF = {"op": "rat", "num": 1, "den": 2}
EXACT_E12 = {"a1": HALF, "d": 5, "b1": HALF, "r": -3, "answer": 61}
E14_CLAIM = {"kind": "ALL_REMOVED_PAIR_LCM_FAILS_BOTH", "lower": 16, "upper": 30}
E06_CLAIM = {"kind": "GREEDY_RESIDUE_CLASS", "lower": 25, "upper": 1000, "modulus": 25,
             "residues": [0, 1, 2, 3, 4, 10, 11, 12, 13, 14], "relation": "IFF"}


class WitnessContractTests(unittest.TestCase):
    def test_five_whole_visible_questions_without_reference_records(self):
        expected = {"D3_E12": SEQUENCE, "D3_E15": DIGITS, "D3_P02": PRIME, "D3_E14": DIVISORS, "D3_E06": COINS}
        compiled = {case: c.template_id for case, q in QUESTIONS.items() if (c := compile_contract(q)) is not None}
        self.assertEqual(compiled, expected)
        for case in expected:
            q = QUESTIONS[case]
            self.assertEqual(contract(case).question_sha256, hashlib.sha256(q.encode()).hexdigest())
            self.assertEqual(contract(case).as_dict()["source_char_span"], [0, len(q)])
            self.assertIsNone(compile_contract(q + " Assume a further restriction."))

    def test_unsupported_or_changed_semantic_constraints_abstain(self):
        q = QUESTIONS["D3_E15"]
        self.assertIsNone(compile_contract(q.replace("at least", "greater than")))
        self.assertIsNone(compile_contract(q.replace("positive integer", "nonnegative integer")))
        q = QUESTIONS["D3_P02"]
        self.assertIsNone(compile_contract(q.replace("$m^{4}+1$", "$m^{3}+1$")))
        self.assertIsNone(compile_contract(q.replace("least prime", "a prime")))
        q = QUESTIONS["D3_E06"]
        self.assertIsNone(compile_contract(q.replace("unlimited supply", "limited supply")))

    def test_exact_recurrence_candidate_and_final_conflict(self):
        target = contract("D3_E12")
        checked = check_candidate(target, EXACT_E12)
        self.assertEqual((checked["status"], checked["certified_value"], checked["proof_scope"]),
                         ("CERTIFIED_EXACT", 61, "FULL_OBJECTIVE"))
        self.assertEqual(checked["evidence"]["uniqueness"]["first_second_difference"], 8)
        self.assertEqual([c["actual"] for c in checked["evidence"]["constraints"]], [1, 4, 15, 2])
        broken = check_candidate(target, {**EXACT_E12, "d": 1, "answer": 45})
        self.assertEqual(broken["status"], "INVALID_CANDIDATE")
        self.assertEqual([c["actual"] for c in broken["evidence"]["constraints"]], [1, 0, 7, -10])
        slip = check_candidate(target, {**EXACT_E12, "answer": 45})
        self.assertEqual((slip["status"], slip["proof_scope"]), ("INVALID_CANDIDATE", "FULL_OBJECTIVE"))

    def test_partial_and_degenerate_sequence_do_not_certify_unique_objective(self):
        self.assertEqual(check_candidate(contract("D3_E12"), {"answer": 61})["status"], "UNKNOWN")
        changed = QUESTIONS["D3_E12"].replace("$c_{1}=1, c_{2}=4, c_{3}=15$", "$c_{1}=1, c_{2}=2, c_{3}=3$").replace("$c_{4}=2$", "$c_{4}=4$")
        degenerate = compile_contract(changed)
        self.assertIsNotNone(degenerate)
        checked = check_candidate(degenerate, {"a1": 1, "d": 1, "b1": 0, "r": 2, "answer": 5})
        self.assertEqual(checked["status"], "FEASIBLE_ONLY")
        self.assertIsNone(checked["certified_value"])

    def test_tampered_program_and_inexact_rational_do_not_gain_authority(self):
        original = contract("D3_E12")
        counterfeit = replace(original, program_json=canonical({**original.program, "target_index": 6}))
        self.assertEqual(check_candidate(counterfeit, EXACT_E12)["status"], "UNKNOWN")
        bad = check_candidate(original, {**EXACT_E12, "a1": 0.5})
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertIsNone(bad["certificate_sha256"])

    def test_greater_fibbish_witness_only_refutes_old_maximum(self):
        task = contract("D3_E15")
        self.assertEqual(check_candidate(task, 1011235)["status"], "FEASIBLE_ONLY")
        checked = check_claim_witness(task, {"kind": "MAX", "value": 303369}, 1011235)
        self.assertEqual(checked["status"], "DOMINATED_CANDIDATE")
        self.assertIsNone(checked["certified_value"])
        for bad in (303369, 1010235, -3, True):
            self.assertEqual(check_claim_witness(task, {"kind": "MAX", "value": 303369}, bad)["status"], "INVALID_COUNTEREXAMPLE")

    def test_residue_candidate_alone_cannot_certify_original_minimum(self):
        task = contract("D3_P02")
        checked = check_candidate(task, {"p": 17, "m": 134})
        self.assertEqual((checked["status"], checked["proof_scope"]), ("FEASIBLE_ONLY", "CONDITIONAL_DOMAIN"))
        counter = check_claim_witness(task, {"kind": "MIN", "value": 134, "p": 17}, {"p": 17, "m": 110})
        self.assertEqual(counter["status"], "UNKNOWN")

    def test_lcm_pair_refutes_only_the_registered_local_universal(self):
        task = contract("D3_E14")
        checked = check_claim_witness(task, E14_CLAIM, {"pair": [16, 18]})
        self.assertEqual((checked["status"], checked["proof_scope"]), ("UNIVERSAL_REFUTATION", "PARTIAL_CLAIM_REFUTATION"))
        self.assertEqual(checked["evidence"]["removed_members_still_dividing"], [18])
        self.assertIsNone(checked["certified_value"])
        for pair in ([16, 17], [18, 18], [15, 16]):
            self.assertEqual(check_claim_witness(task, E14_CLAIM, {"pair": pair})["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(check_candidate(task, 23)["status"], "UNKNOWN")

    def test_coin_residue_implication_direction_is_checked(self):
        task = contract("D3_E06")
        checked = check_claim_witness(task, E06_CLAIM, {"n": 45})
        self.assertEqual((checked["status"], checked["proof_scope"]), ("UNIVERSAL_REFUTATION", "PARTIAL_CLAIM_REFUTATION"))
        self.assertEqual(checked["evidence"]["minimum_coins"], 3)
        self.assertIsNone(checked["certified_value"])
        self.assertEqual(check_claim_witness(task, {**E06_CLAIM, "relation": "ONLY_IF"}, {"n": 45})["status"], "UNIVERSAL_REFUTATION")
        self.assertEqual(check_claim_witness(task, {**E06_CLAIM, "relation": "IF"}, {"n": 45})["status"], "INVALID_COUNTEREXAMPLE")
        self.assertEqual(check_claim_witness(task, E06_CLAIM, {"n": 20})["status"], "INVALID_COUNTEREXAMPLE")


if __name__ == "__main__":
    unittest.main()
