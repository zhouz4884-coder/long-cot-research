"""Synthetic decision tests, with no model outputs or task text loaded."""

from collections import Counter
from copy import deepcopy
import unittest

from score_d50_controlled_gate import HERE, RULES_SHA256, STAGES, evaluate, read_json


RULES = read_json(HERE / "D50_GATE_RULES.json", RULES_SHA256)


def fixture():
    roles = RULES["expected_independent_problems_by_role"]
    rows = [{"case_id": f"{r}{i}", "problem_id": f"{r}{i}", "role": r,
             "partition": "H", "pair_candidate_tokens": 16} for r, count in roles.items() for i in range(count)]
    packet = {"token_packet_sha256": "combined", "rows": rows}
    seal = {"combined_packet_sha256": "combined", "parts": {"main": {"sha256": "b"}, "holdout": {"sha256": "h"}}}

    def scores(changes=None):
        result = {r: {"cases": []} for r in roles}
        for row in rows:
            case_id, role = row["case_id"], row["role"]
            correct = -16 + (changes or {}).get(case_id, 0) * 16
            margin = correct + 16
            result[role]["cases"].append({"case_id": case_id, "problem_id": case_id, "role": role,
                                         "correct_target_tokens": 16, "alternative_target_tokens": 16,
                                         "correct_logprob": correct, "alternative_logprob": -16,
                                         "margin": margin, "per_target_token_margin": margin / 16})
        return result

    def step(changes=None):
        base, after = scores(), scores(changes)
        return {"status": "EVALUATED", "step_scale": 0.02, "actual_update_norm": 0.1,
                "by_role": {r: {"before": base[r], "after": after[r]} for r in roles}}

    origin = "a" * 64
    ledger = [{"kind": "FORWARD", "stage": stage, "branch": branch, "case_id": row["case_id"],
               "role": row["role"], "teacher_targets": 16, "grad_enabled": key == "baseline"}
              for key, stage in STAGES.items() for row in rows for branch in ("correct", "alternative")]
    result = {"status": "COMPLETE", "input_sha256": "b", "separate_holdout_sha256": "h",
              "heldout_matched_pairs_by_role": dict(Counter(row["role"] for row in rows)),
              "parameter_base_sha256": origin, "parameter_final_sha256": origin,
              "heldout_initial_parameter_sha256": dict.fromkeys(STAGES, origin),
              "paid_work": {"rows": ledger}, "settings": {"eta": 0.02, "kl": 0.15},
              "matched_target_parameter_norm": 0.1,
              "reference_anchors": {a: {"status": "READY"} for a in ("U", "A", "T")}, "branches": {}}
    result.update({key: scores() for key in RULES["noise"]["readouts"]})
    for arm in ("uniform", "U", "A", "T"):
        changes = {"E0": 0.005, "E1": 0.005} if arm == "T" else {"E0": 0.002, "E1": 0.002}
        result["branches"][arm] = {"status": "ATTEMPTED", "weight_summary": {"kl_from_uniform": 0 if arm == "uniform" else 0.15},
                                   "raw_sgd": step(changes), "matched_norm": step(changes)}
    return result, packet, seal, scores, step


class TestControlledGate(unittest.TestCase):
    def test_two_same_cases_and_protected_roles(self):
        result, packet, seal, _, _ = fixture()
        decision = evaluate(result, RULES, packet, seal)
        self.assertEqual(decision["status"], "PASS_CONTROLLED_GATE")
        self.assertEqual(decision["joint_e_wins"], ["E0", "E1"])

    def test_disjoint_mode_winners_fail(self):
        result, packet, seal, _, step = fixture()
        result["branches"]["T"]["matched_norm"] = step({"E2": 0.005, "E3": 0.005})
        decision = evaluate(result, RULES, packet, seal)
        self.assertEqual(decision["status"], "NO_GO_CONTROLLED_GATE")
        self.assertEqual(decision["joint_e_wins"], [])

    def test_single_harm_veto_and_comparative_missed_gain(self):
        result, packet, seal, _, step = fixture()
        result["branches"]["U"]["raw_sgd"] = step({"E0": 0.002, "E1": 0.002, "W0": 0.002})
        self.assertEqual(evaluate(result, RULES, packet, seal)["status"], "PASS_CONTROLLED_GATE")
        result["branches"]["T"]["raw_sgd"] = step({"E0": 0.005, "E1": 0.005, "C3": -0.002})
        decision = evaluate(result, RULES, packet, seal)
        self.assertEqual(decision["status"], "NO_GO_CONTROLLED_GATE")
        self.assertEqual(decision["absolute_wc_harms"]["C"]["raw_sgd"], ["C3"])

    def test_measured_noise_and_all_control_requirements(self):
        result, packet, seal, scores, step = fixture()
        result["heldout_repeat_initial_by_role"] = scores({"E0": 0.0005})
        result["branches"]["A"]["raw_sgd"] = step({"E0": 0.002, "E1": 0.0045})
        decision = evaluate(result, RULES, packet, seal)
        self.assertEqual(decision["status"], "NO_GO_CONTROLLED_GATE")
        self.assertEqual(decision["joint_e_wins"], [])

    def test_incomplete_is_not_failure_or_pass(self):
        result, packet, seal, _, _ = fixture()
        unpaid = deepcopy(result)
        unpaid["paid_work"]["rows"].pop()
        self.assertEqual(evaluate(unpaid, RULES, packet, seal)["status"], "INCOMPLETE_CONTROLLED_GATE")
        result["branches"]["T"]["matched_norm"]["actual_update_norm"] = 0.101
        self.assertEqual(evaluate(result, RULES, packet, seal)["status"], "INCOMPLETE_CONTROLLED_GATE")


if __name__ == "__main__":
    unittest.main()
