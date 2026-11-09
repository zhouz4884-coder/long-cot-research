import json
import unittest

from freeze_scope_regressions import D36, ROOT
from scope_adapter import bind_event_scope, classify_scope, permits_existing_action
from scoped_obligation import FrozenEventInventory, ScopedPointGate
from witness_contract import check_candidate, compile_contract


def load(path):
    return json.loads(path.read_bytes())


class ScopedObligationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packet = load(D36 / "prepared/early_checkpoint.json")
        cls.contract = compile_contract(packet["question"])
        raw = (ROOT / "scope_event_inventory.json").read_bytes()
        cls.events = {item["id"]: item for item in json.loads(raw)["events"]}
        cls.inventory = FrozenEventInventory(raw)

    def test_frozen_adversaries(self):
        cases = load(ROOT / "scope_challenge.json")["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                result = classify_scope(case["text"], case["phase"], case["value"],
                                        terminal_committed=case.get("terminal_committed", True))
                self.assertEqual(case["label"], result.role)

    def test_same_scalar_two_scopes(self):
        gate = ScopedPointGate(self.contract, self.inventory)
        local = self.events["early/s20261111/EveryStepAudit:5"]
        final = self.events["early/s20261111/ProgressiveWitness:17"]
        self.assertFalse(permits_existing_action(bind_event_scope(local, trusted_target_id=gate.target), "BLOCK_REGRESSION"))
        self.assertTrue(permits_existing_action(bind_event_scope(final, trusted_target_id=gate.target), "BLOCK_REGRESSION"))
        self.assertEqual(local["value"], final["value"])

    def test_candidate_cannot_borrow_numeric_value_elsewhere_in_clause(self):
        event = self.events["late/historical/ProgressiveWitness:2"]
        gate = ScopedPointGate(self.contract, self.inventory)
        forged = {**event, "value": 9, "clause": event["clause"] + " The digit 9 is valid.",
                  "clause_char_span": [event["clause_char_span"][0], event["clause_char_span"][1] + 22]}
        self.assertEqual(bind_event_scope(forged, trusted_target_id=gate.target).role, "UNKNOWN")
        self.assertEqual(bind_event_scope(event, trusted_target_id="foreign").role, "UNKNOWN")

    def test_authentic_witness_can_refute_global_claim_with_exhausted_point_budget(self):
        trajectory = "early/s20261111/ProgressiveWitness"
        gate = ScopedPointGate(self.contract, self.inventory, point_budget=2)
        for n in (0, 1):
            self.assertEqual(gate.step(f"{trajectory}:{n}")["authority"], "RAISE_FEASIBLE_BOUND_ONLY")
        outside = gate.step(f"{trajectory}:15")
        self.assertIsNone(outside["point"])
        final = gate.step(f"{trajectory}:17")
        self.assertEqual(final["authority"], "REFUTE_GLOBAL_MAXIMUM")
        self.assertEqual(final["witness"]["value"], 1011235)
        self.assertIsNone(final["point"])
        self.assertEqual(gate.checker.report()["point_calls"], 2)

    def test_zero_budget_or_reordered_source_grants_no_authority(self):
        trajectory = "early/s20261111/ProgressiveWitness"
        gate = ScopedPointGate(self.contract, self.inventory, point_budget=0)
        first, last = (f"{trajectory}:{n}" for n in (0, 17))
        self.assertEqual(gate.step(first)["authority"], "NONE")
        self.assertEqual(gate.step(last)["authority"], "NONE")
        with self.assertRaisesRegex(ValueError, "out of order"):
            gate.step(first)

    def test_fabricated_event_cannot_create_bound(self):
        gate = ScopedPointGate(self.contract, self.inventory)
        with self.assertRaises(TypeError):
            gate.step({"id": "synthetic:0", "phase": "checkpoint_operand", "value": 10112369})
        with self.assertRaises(KeyError):
            gate.step("synthetic:0")
        self.assertIsNone(gate.bound)
        self.assertIsNone(gate.trajectory)
        with self.assertRaisesRegex(ValueError, "verified D3.6 reconstruction"):
            FrozenEventInventory(b'{"events": []}')

    def test_point_check_and_scope_are_independent(self):
        role = classify_scope("Therefore, 10112357 is valid.", "thinking", 10112357)
        self.assertTrue(role.may_refute_feasibility_claim)
        self.assertFalse(role.may_refute_global_maximum)
        result = check_candidate(self.contract, 10112357)
        self.assertEqual(result["status"], "INVALID_CANDIDATE")
        self.assertEqual(result["proof_scope"], "FULL_ORIGINAL_CONSTRAINTS")


if __name__ == "__main__":
    unittest.main()
