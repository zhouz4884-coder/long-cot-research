"""CPU tape/probe controls: candidate reuse, intervention application and cost."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from asag_adapter import decode_asag, JUMP_PROMPT


class Tokenizer:
    def encode(self, text, **kwargs): return list(map(ord, text))
    def decode(self, ids, **kwargs): return ''.join(chr(i) for i in ids)


class Engine:
    def __init__(self, text):
        import torch
        self.torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None))
        self.tok = Tokenizer()
        self.eos = {0}
        self.endthink = 1
        self.model_ms = 0.
        self.tape = list(map(ord, text))
        self.injection_calls = 0
    def forward(self, ids, cache=None):
        import torch
        return 1, torch.zeros(256)
    def sample(self, logits, seed, phase, offset, stats=False):
        self.injection_calls += int(float(logits.max()) < 0)
        return (self.tape[offset] if offset < len(self.tape) else 0), None


def make_probe(confidence, entropy, trap=False):
    import torch
    distribution = torch.zeros(256)
    distribution[90] = 1.
    return {'ids': [55, 125], 'text': r'\boxed{7}', 'tokens': 2,
            'candidate_identity_sha256': 'same-paid-candidate',
            'confidence_arithmetic_mean_raw_chosen_token_probability': confidence,
            'attention': {'entropy_sum': entropy, 'trap': trap},
            'actual_probe_forward_input_tokens': 10, 'ms': 2.,
            'inject_distribution': distribution}


class ASAGDecoderControls(unittest.TestCase):
    def test_stop_reuses_paid_candidate(self):
        e = Engine('Wait, continue.\n\n')
        with patch('asag_adapter.probe_asag', return_value=make_probe(.96, 100)):
            trace, committed = decode_asag(e, [99], 100, 42)
        self.assertEqual(trace['stop_reason'], 'policy_stop')
        self.assertEqual(committed['ids'], [55, 125])
        self.assertEqual(committed['candidate_identity_sha256'], 'same-paid-candidate')
        self.assertEqual(trace['auxiliary_generated_tokens'], 2)
        self.assertNotIn('inject_distribution', committed)

    def test_injection_affects_following_sampling_inputs_and_costs_all_probes(self):
        text = 'Wait, begin.\n\nWait, another step.\n\nDone.'
        e = Engine(text)
        with patch('asag_adapter.probe_asag', side_effect=[make_probe(.8, 100), make_probe(.8, 80)]):
            trace, committed = decode_asag(e, [99], 100, 42)
        self.assertIsNone(committed)
        self.assertEqual([d['action'] for d in trace['decisions']], ['CONTINUE', 'INJECT'])
        self.assertGreater(e.injection_calls, 0)
        self.assertEqual(trace['auxiliary_generated_tokens'], 4)
        self.assertEqual(trace['auxiliary_forward_input_tokens'], 20)
        self.assertEqual(trace['auxiliary_wall_ms'], 4.)

    def test_jump_is_consumed_and_forced_wait_does_not_retrigger(self):
        text = 'Wait, begin.\n\nWait, think again.\n\nDone.'
        e = Engine(text)
        with patch('asag_adapter.probe_asag', side_effect=[make_probe(.8, 100), make_probe(.8, 110, True)]):
            trace, _ = decode_asag(e, [99], 300, 42)
        self.assertEqual([d['action'] for d in trace['decisions']], ['CONTINUE', 'JUMP'])
        self.assertEqual(trace['forced_think_input_tokens'], len(JUMP_PROMPT))
        self.assertIn(JUMP_PROMPT, trace['text'])
        self.assertEqual(trace['tokens'], trace['sampled_thinking_tokens'] + trace['forced_think_input_tokens'])

    def test_jump_quota_and_context_limit_are_explicit(self):
        e = Engine('Wait, begin.\n\nWait, think again.\n\nDone.')
        with patch('asag_adapter.probe_asag', side_effect=[make_probe(.8, 100), make_probe(.8, 110, True)]):
            trace, committed = decode_asag(e, [99], 35, 42)
        self.assertIsNone(committed)
        self.assertEqual(trace['forced_think_input_tokens'], 0)
        self.assertTrue(trace['decisions'][-1]['intervention_censored_by_context_budget'])
        self.assertEqual(trace['decisions'][-1]['applied_action'], 'CONTINUE')
        e = Engine('Wait, begin.\n\nWait, think again.\n\nDone.')
        with patch('asag_adapter.probe_asag', side_effect=[make_probe(.8, 100), make_probe(.8, 110, True)]):
            trace, committed = decode_asag(e, [99], 100, 42, maximum_jumps=0)
        self.assertEqual(trace['decisions'][-1]['reason'], 'jump_budget_exhausted')
        self.assertEqual(committed['candidate_identity_sha256'], 'same-paid-candidate')


if __name__ == '__main__':
    unittest.main()
