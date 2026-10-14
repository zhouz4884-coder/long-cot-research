"""Finite CPU controls for interpretation-sensitive ASAG equations and actions."""
import math
import unittest
from asag_attention import window_probabilities, summarize_window
from asag_policy import ASAGState, injected_probabilities


class ASAGControls(unittest.TestCase):
    def test_first_high_confidence_and_fixed_first_entropy(self):
        self.assertEqual(ASAGState().decide(.96, 100., False)['action'], 'STOP')
        state = ASAGState()
        self.assertEqual(state.decide(.8, 100., False)['action'], 'CONTINUE')
        self.assertEqual(state.decide(.96, 95., False)['action'], 'CONTINUE')
        self.assertEqual(state.decide(.96, 89., False)['action'], 'STOP')
        self.assertEqual(state.first_entropy, 100.)
        self.assertEqual(ASAGState().decide(.96, 0., False)['action'], 'STOP')
        zero = ASAGState()
        zero.decide(.8, 0., False)
        self.assertEqual(zero.decide(.96, 5., True)['reason'], 'undefined_ratio_zero_first_entropy')

    def test_all_four_actions_and_one_jump_limit(self):
        state = ASAGState()
        state.decide(.8, 100., False)
        self.assertEqual(state.decide(.8, 89., False)['action'], 'INJECT')
        self.assertEqual(state.decide(.8, 105., True)['action'], 'JUMP')
        self.assertEqual(state.decide(.8, 110., True)['action'], 'STOP')
        self.assertEqual(state.jumps, 1)
        self.assertEqual(ASAGState().decide(None, 100., True)['action'], 'CONTINUE')

    def test_strict_boundary_and_probability_mixture(self):
        import torch
        state = ASAGState()
        state.decide(.8, 100., False)
        # Both exact equalities fail the paper's strict branch conditions.
        self.assertEqual(state.decide(.95, 90., False)['action'], 'CONTINUE')
        model = torch.tensor([.1, .9])
        answer = torch.tensor([1., 0.])
        mixed = injected_probabilities(model, answer).softmax(-1)
        self.assertTrue(torch.allclose(mixed, torch.tensor([.145, .855]), atol=1e-7))

    def test_causal_query_window_and_boolean_mask(self):
        import torch
        query = torch.zeros(1, 1, 2, 3)
        key = torch.zeros(1, 1, 4, 3)
        measured = window_probabilities(query, key, 1., 2)
        self.assertTrue(torch.allclose(measured[0, 0, 0], torch.tensor([1/3, 1/3, 1/3, 0.])))
        self.assertTrue(torch.allclose(measured[0, 0, 1], torch.tensor([.25, .25, .25, .25])))
        mask = torch.tensor([[[[True, True, True, False], [True, True, True, True]]]])
        self.assertTrue(torch.equal(measured, window_probabilities(query, key, 1., 2, mask)))
        additive = torch.where(mask, 0., float('-inf'))
        self.assertTrue(torch.equal(measured, window_probabilities(query, key, 1., 2, additive)))

    def test_entropy_query_sum_and_per_token_trap_mass(self):
        import torch
        p = torch.tensor([[[[.4, .2, .2, .2], [.4, .2, .2, .2]]]])
        report = summarize_window([p] * 4, (0, 1), (1, 4))
        expected = 8 * (-.4*math.log(.4) - 3*.2*math.log(.2)) / math.log(4)
        self.assertAlmostEqual(report['entropy_sum'], expected, places=5)
        # Previous total mass .4 is smaller than current .6, but per-token .4>.2.
        self.assertTrue(report['trap'])
        self.assertAlmostEqual(report['current_action_mean_token_attention'], .2, places=6)


if __name__ == '__main__':
    unittest.main()
