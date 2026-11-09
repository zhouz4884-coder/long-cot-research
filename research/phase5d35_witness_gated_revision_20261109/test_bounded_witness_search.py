"""Deterministic paid search, budget boundaries and forgery tests."""

from copy import deepcopy
import json
import unittest

from bounded_witness_search import replay_search, search_witness
from test_witness_contract import E06_CLAIM, E14_CLAIM, QUESTIONS, contract
from witness_contract import check_candidate, check_claim_witness, compile_contract


P02_COMPLETE = {"kind": "COMPLETE_SOLUTIONS", "values": [155, 134], "modulus": 289}


class BoundedSearchTests(unittest.TestCase):
    def test_p02_generates_witness_and_proves_the_least_prime_without_oracle(self):
        task = contract("D3_P02")
        claim = {"kind": "MIN", "p": 17, "value": 134}
        checked = search_witness(task, claim, budget=4096)
        self.assertEqual((checked["status"], checked["witness_source"], checked["witness"]),
                         ("DOMINATED_CANDIDATE", "ONLINE_SEARCH", {"p": 17, "m": 110}))
        self.assertIsNone(checked["certified_value"])
        proof = checked["prerequisite"]
        self.assertEqual(proof["exhausted_smaller_primes"], [2, 3, 5, 7, 11, 13])
        self.assertGreater(proof["positive_residue_witness"], checked["witness"]["m"])
        self.assertTrue(replay_search(task, json.loads(json.dumps(checked))))
        repeated = check_claim_witness(task, claim, checked["witness"], prerequisite=proof)
        self.assertEqual(repeated["status"], "DOMINATED_CANDIDATE")
        self.assertEqual(repeated["paid_check_count"], proof["work"]["used"] + 1)

    def test_forged_least_prime_proof_and_inexact_prime_are_rejected(self):
        task = contract("D3_P02")
        claim = {"kind": "MIN", "p": 17, "value": 134}
        checked = search_witness(task, claim, budget=4096)
        forged = {**checked["prerequisite"], "exhausted_smaller_primes": [2, 3, 5, 7, 11]}
        self.assertEqual(check_candidate(task, checked["witness"], prerequisite=forged)["status"], "UNKNOWN")
        invalid = check_claim_witness(task, claim, {"p": 17.0, "m": 110}, prerequisite=checked["prerequisite"])
        self.assertEqual(invalid["status"], "INVALID_COUNTEREXAMPLE")
        self.assertFalse(replay_search(task, {**checked, "prerequisite": forged}))

    def test_complete_residue_claim_requires_matching_least_prime_and_modulus(self):
        task = contract("D3_P02")
        result = search_witness(task, P02_COMPLETE, budget=20_000)
        proof, witness = result["prerequisite"], result["witness"]
        checked = check_claim_witness(task, P02_COMPLETE, witness, prerequisite=proof)
        self.assertEqual((checked["status"], checked["proof_scope"], checked["certified_value"]),
                         ("UNIVERSAL_REFUTATION", "PARTIAL_CLAIM_REFUTATION", None))
        self.assertEqual(checked["evidence"]["canonical_residue_interval"], [0, 288])
        missing = check_claim_witness(task, P02_COMPLETE, witness)
        self.assertEqual((missing["status"], missing["reason"]),
                         ("UNKNOWN", "least_prime_proof_required_for_residue_completeness"))
        wrong_scope = {**P02_COMPLETE, "modulus": 361}
        checked = check_claim_witness(task, wrong_scope, witness, prerequisite=proof)
        self.assertEqual((checked["status"], checked["reason"]),
                         ("UNKNOWN", "claim_modulus_differs_from_certified_prime_square"))
        self.assertEqual(search_witness(task, wrong_scope, budget=20_000)["status"], "UNKNOWN")
        tampered = check_claim_witness(task, P02_COMPLETE, witness, prerequisite={**proof, "prime": 19})
        self.assertEqual(tampered["status"], "UNKNOWN")

    def test_malformed_complete_residue_lists_and_points(self):
        task = contract("D3_P02")
        searched = search_witness(task, P02_COMPLETE, budget=4096)
        proof = searched["prerequisite"]
        for values in ([134, 134], [134, -1], [134, 289], [134, 155.0], [134, True], "134,155", []):
            with self.subTest(values=values):
                claim = {**P02_COMPLETE, "values": values}
                self.assertEqual(check_claim_witness(task, claim, searched["witness"], prerequisite=proof)["status"], "UNKNOWN")
                self.assertEqual(search_witness(task, claim, budget=4096)["paid_check_count"], 0)
        for witness in ({"m": 110}, {"p": 17.0, "m": 110}, {"p": 19, "m": 110}, {"p": 17, "m": -1},
                        {"p": 17, "m": 289}, {"p": 17, "m": 110.0}, {"p": 17, "m": True},
                        {"p": 17, "m": 134}, {"p": 17, "m": 1}):
            with self.subTest(witness=witness):
                self.assertEqual(check_claim_witness(task, P02_COMPLETE, witness, prerequisite=proof)["status"],
                                 "INVALID_COUNTEREXAMPLE")

    def test_complete_residue_search_uses_frozen_budget_without_upgrading_the_result(self):
        task = contract("D3_P02")
        for budget in (4096, 20_000):
            with self.subTest(budget=budget):
                checked = search_witness(task, P02_COMPLETE, budget=budget)
                self.assertEqual((checked["status"], checked["witness"], checked["certified_value"]),
                                 ("UNIVERSAL_REFUTATION", {"p": 17, "m": 110}, None))
                self.assertEqual(checked["paid_check_count"], 635)
                self.assertTrue(replay_search(task, json.loads(json.dumps(checked))))
        for budget, expected in ((634, "UNKNOWN"), (635, "UNIVERSAL_REFUTATION")):
            self.assertEqual(search_witness(task, P02_COMPLETE, budget=budget)["status"], expected)
        complete = search_witness(task, {**P02_COMPLETE, "values": [110, 134, 155, 179]}, budget=20_000)
        self.assertEqual((complete["status"], complete["certified_value"]), ("UNKNOWN", None))
        self.assertIsNone(complete["witness"])

    def test_zero_residue_can_refute_completeness_without_being_a_positive_solution(self):
        task = compile_contract(QUESTIONS["D3_P02"].replace("+1$", "+0$"))
        claim = {"kind": "COMPLETE_SOLUTIONS", "values": [2], "modulus": 4}
        checked = search_witness(task, claim, budget=32)
        self.assertEqual((checked["status"], checked["witness"]), ("UNIVERSAL_REFUTATION", {"p": 2, "m": 0}))
        self.assertEqual(check_candidate(task, checked["witness"], prerequisite=checked["prerequisite"])["status"], "UNKNOWN")

    def test_budget_exhaustion_cannot_turn_partial_search_into_proof(self):
        task = contract("D3_P02")
        claim = {"kind": "MIN", "p": 17, "value": 134}
        full = search_witness(task, claim, budget=4096)
        for limit in (0, 20, full["paid_check_count"] - 1):
            checked = search_witness(task, claim, budget=limit)
            self.assertEqual((checked["status"], checked["reason"], checked["paid_check_count"]), ("UNKNOWN", "budget_exhausted", limit))
            self.assertIsNone(checked["witness"])
            self.assertTrue(replay_search(task, checked))

    def test_tampering_with_request_witness_or_cost_breaks_search_replay(self):
        task = contract("D3_E14")
        checked = search_witness(task, E14_CLAIM, budget=100)
        self.assertEqual((checked["status"], checked["witness"]), ("UNIVERSAL_REFUTATION", {"pair": [16, 18]}))
        self.assertTrue(replay_search(task, checked))
        for field, value in (("paid_check_count", 1), ("witness", {"pair": [16, 17]}), ("certified_value", 23)):
            self.assertFalse(replay_search(task, {**checked, field: value}))
        request = deepcopy(checked["request"])
        request["claim"]["lower"] = 17
        self.assertFalse(replay_search(task, {**checked, "request": request}))
        self.assertFalse(replay_search(contract("D3_E06"), checked))

    def test_coin_refutation_returns_first_supported_amount_and_no_count(self):
        task = contract("D3_E06")
        checked = search_witness(task, E06_CLAIM, budget=256)
        self.assertEqual((checked["status"], checked["witness"]), ("UNIVERSAL_REFUTATION", {"n": 45}))
        self.assertIsNone(checked["certified_value"])
        self.assertTrue(replay_search(task, checked))

    def test_same_access_direct_program_baselines_are_explicit_full_objectives(self):
        cases = (("D3_E12", 61, 32), ("D3_E15", 10112369, 10_000), ("D3_P02", 110, 4096),
                 ("D3_E14", 23, 300_000), ("D3_E06", 610, 30_000))
        for case, answer, budget in cases:
            with self.subTest(case=case):
                task = contract(case)
                checked = search_witness(task, budget=budget, purpose="SOLVE")
                self.assertEqual((checked["status"], checked["certified_value"], checked["proof_scope"]),
                                 ("CERTIFIED_EXACT", answer, "FULL_OBJECTIVE"))
                self.assertGreater(checked["paid_check_count"], 0)
                self.assertTrue(replay_search(task, json.loads(json.dumps(checked))))

    def test_sequence_compiler_uses_source_constants_not_case_answers(self):
        modified = QUESTIONS["D3_E12"].replace("$c_{1}=1, c_{2}=4, c_{3}=15$", "$c_{1}=4, c_{2}=7, c_{3}=11$").replace("$c_{4}=2$", "$c_{4}=17$")
        task = compile_contract(modified)
        checked = search_witness(task, budget=32, purpose="SOLVE")
        self.assertEqual((checked["status"], checked["certified_value"]), ("CERTIFIED_EXACT", 27))
        self.assertNotEqual(task.contract_id, contract("D3_E12").contract_id)


if __name__ == "__main__":
    unittest.main()
