from copy import deepcopy
from types import SimpleNamespace
import unittest

import torch
from torch import nn
from torch.nn import functional as F

from d50_gradient_runner import (
    ANCHORS, ROLES, Diagnostic, Settings, attach_qv_lora, load_packet, match_kl,
    run_diagnostic, vector_summary,
)


class TinyCausal(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(13, 6)
        self.out = nn.Linear(6, 13)

    def forward(self, input_ids, use_cache=False):
        hidden = self.embed(input_ids).cumsum(dim=1)
        return SimpleNamespace(logits=self.out(hidden))


class TinyQV(nn.Module):
    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(num_hidden_layers=1)
        self.embed = nn.Embedding(13, 6)
        self.q_proj, self.v_proj = nn.Linear(6, 6), nn.Linear(6, 6)
        self.out = nn.Linear(6, 13)

    def forward(self, input_ids, use_cache=False):
        hidden = self.embed(input_ids).cumsum(dim=1)
        return SimpleNamespace(logits=self.out(self.q_proj(hidden) + self.v_proj(hidden)))


def packet():
    result = {name: [] for name in ("B", "Bprime", "H")}
    for split_index, (name, rows) in enumerate(result.items()):
        for i, role in enumerate(ROLES):
            row = {"case_id": f"{name}:{role}", "problem_id": f"problem:{name}:{role}", "role": role}
            if name != "H":
                row.update(input_ids=[1, i+2, split_index+5, i+6, 9+i], target_start=2, answer_positions=[4])
            if name != "B":
                row["pair"] = {"prefix_ids": [1, i+2, split_index+3],
                               "correct_ids": [i+6, i+9], "alternative_ids": [i+9, i+7]}
            rows.append(row)
    return result


class GradientRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        torch.manual_seed(901)
        self.model = TinyCausal().double()
        self.splits, self.mismatches = load_packet(packet())

    def test_causal_shift_and_answer_reference_index(self):
        example = self.splits["Bprime"][0]
        seq = example.teacher
        d = Diagnostic(self.model)
        actual = d.token_losses(example, seq, "alignment")
        ids = torch.tensor(seq.ids).unsqueeze(0)
        logits = self.model(input_ids=ids).logits
        independent = torch.stack([-F.log_softmax(logits[0, j-1], dim=0)[seq.ids[j]]
                                   for j in range(seq.target_start, len(seq.ids))])
        self.assertTrue(torch.allclose(actual, independent, atol=1e-12))
        self.assertEqual(d.ce_direction(self.splits["Bprime"], "A")[1], 3)
        self.assertEqual(d.ce_direction(self.splits["Bprime"], "U")[1], 9)

    def test_symmetric_probes_match_every_tiny_token_gradient_and_restore(self):
        d = Diagnostic(self.model)
        before = d.p.sha256()
        direction, _ = d.ce_direction(self.splits["Bprime"], "U")
        oracle = d.token_oracle(self.splits["B"], direction)
        for step in (1e-5, 2e-5):
            score, proof = d.probe(self.splits["B"], direction, step, "test_fd", 1e-12)
            self.assertTrue(torch.allclose(score, oracle, rtol=2e-7, atol=2e-8))
            self.assertLess(proof["perturbation_asymmetry_norm"], 1e-14)
        self.assertEqual(before, d.p.sha256())
        self.assertEqual(d.p.restores, 4)

    def test_margin_sign_and_exact_direction_vs_manual_derivative(self):
        d = Diagnostic(self.model)
        values, directions, counts = d.pair_roles(self.splits["Bprime"], "test_T", gradients=True)
        self.assertEqual(counts, {role: 1 for role in ROLES})
        losses = []
        for example in self.splits["Bprime"]:
            a, b = example.pair.correct, example.pair.alternative
            nll_a = d.token_losses(example, a, "manual", "correct").sum()
            nll_b = d.token_losses(example, b, "manual", "alternative").sum()
            losses.append(nll_a-nll_b)
            self.assertAlmostEqual(values[example.role]["cases"][0]["margin"], float((nll_b-nll_a).detach()), places=12)
        manual = torch.autograd.grad(torch.stack(losses).mean(), d.p.params)
        self.assertTrue(torch.allclose(d.p.flatten(manual), torch.stack(list(directions.values())).mean(dim=0), atol=1e-12))

    def test_matched_kl_keeps_support_and_detects_unattainable_ties(self):
        x = torch.tensor([1., 4., 7., 0.], dtype=torch.float64)
        q, info = match_kl(x, 0.12)
        rescale, _ = match_kl(x*17+9, 0.12)
        self.assertTrue(torch.allclose(q, rescale, atol=1e-12))
        self.assertAlmostEqual(info["actual"], 0.12, places=12)
        self.assertAlmostEqual(float(q.sum()), 1.0, places=12)
        self.assertFalse(q.requires_grad)
        self.assertIsNone(match_kl(torch.ones(3), 0.01)[0])
        self.assertIsNone(match_kl(torch.tensor([2., 2., 1.]), 0.5)[0])
        self.assertTrue(torch.equal(match_kl(torch.ones(3), 0)[0], torch.full((3,), 1/3, dtype=torch.float64)))

    def test_end_to_end_all_arms_actual_work_noise_and_linear_residual(self):
        r = run_diagnostic(self.model, self.splits, self.mismatches, Settings((1e-5, 2e-5), eta=0.02, kl=0.12))
        self.assertEqual(r["status"], "COMPLETE")
        self.assertEqual(r["parameter_base_sha256"], r["parameter_final_sha256"])
        self.assertEqual(set(r["heldout_initial_parameter_sha256"].values()), {r["parameter_base_sha256"]})
        self.assertEqual(r["heldout_baseline_by_role"], r["heldout_zero_step_by_role"])
        self.assertEqual(r["heldout_baseline_by_role"], r["heldout_repeat_initial_by_role"])
        self.assertEqual((r["paid_work"]["forward_calls"], r["paid_work"]["backward_calls"]), (126, 30))
        self.assertEqual(r["bitwise_restore_count"], 20)
        for name, arm in r["branches"].items():
            self.assertEqual(arm["status"], "ATTEMPTED")
            self.assertAlmostEqual(arm["weight_summary"]["kl_from_uniform"], 0.0 if name == "uniform" else 0.12)
            self.assertAlmostEqual(arm["matched_norm"]["actual_update_norm"], r["matched_target_parameter_norm"], places=12)
            for step in (arm["raw_sgd"], arm["matched_norm"]):
                self.assertEqual(step["status"], "EVALUATED")
                for role in ROLES:
                    row = step["by_role"][role]
                    self.assertAlmostEqual(row["delta_loss"], row["linear_delta_loss"]+row["residual"], places=13)
                    self.assertAlmostEqual(row["delta_margin"], -row["delta_loss"], places=13)

    def test_bad_split_and_pair_length_abstention(self):
        source = packet()
        broken = deepcopy(source)
        broken["H"][0]["problem_id"] = broken["B"][0]["problem_id"]
        with self.assertRaisesRegex(ValueError, "problem-isolated"):
            load_packet(broken)
        broken = deepcopy(source)
        broken["H"][0]["pair"]["alternative_ids"].append(7)
        splits, mismatch = load_packet(broken)
        r = run_diagnostic(self.model, splits, mismatch, Settings((1e-5, 2e-5), eta=0.02, kl=0.12))
        self.assertEqual(r["status"], "INSUFFICIENT_MATCHED_ROLE_PAIRS")
        self.assertEqual(r["missing_roles"], [("H", "E")])
        self.assertEqual(r["excluded_length_mismatches"][0]["alternative_tokens"], 3)
        with self.assertRaisesRegex(ValueError, "without H"):
            load_packet(source, probe_only=True)

    def test_zero_B_initialization_gives_exact_zero_A_direction(self):
        qv = TinyQV()
        modules = attach_qv_lora(qv, seed=5)
        self.assertEqual(modules, ["q_proj", "v_proj"])
        d = Diagnostic(qv)
        direction, _ = d.ce_direction(self.splits["Bprime"], "U")
        norms = vector_summary(d.p, direction)["group_norms"]
        self.assertEqual(norms["adapter_A"], 0.0)
        self.assertGreater(norms["adapter_B"], 0.0)
        self.assertTrue(all(p.dtype == torch.float32 for p in d.p.params))

    def test_nonfinite_scores_retain_failed_run_without_update(self):
        with torch.no_grad():
            self.model.out.bias[0] = float("nan")
        r = run_diagnostic(self.model, self.splits, self.mismatches, Settings((1e-5, 2e-5), eta=0.02, kl=0.12))
        self.assertEqual(r["status"], "NUMERICAL_FAILURE_RETAINED")
        self.assertEqual(r["paid_work"]["forward_calls"], 1)
        self.assertEqual(r["parameter_base_sha256"], r["parameter_final_sha256"])


if __name__ == "__main__":
    unittest.main()
