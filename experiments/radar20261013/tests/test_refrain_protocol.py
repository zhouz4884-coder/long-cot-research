"""CPU controls for consequential REFRAIN protocol invariants, not benchmark tests."""
import math
import unittest
import numpy as np
from refrain_adapter import Discriminator, SlidingWindowUCB, decode_refrain, answer_refrain


class FiniteEncoder:
    def encode(self, texts):
        return np.asarray([[0., 1.] if 'unrelated' in t else [1., 0.] for t in texts])


class FakeTokenizer:
    def decode(self, ids, **kwargs):
        return ''.join(chr(i) for i in ids)


class FakeEngine:
    def __init__(self, text):
        from types import SimpleNamespace
        self.torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None))
        self.tok = FakeTokenizer()
        self.eos = {0}
        self.endthink = 1
        self.model_ms = 0.
        self.tape = list(map(ord, text))

    def forward(self, ids, cache=None):
        count = 0 if cache is None else cache + len(ids)
        return count, count

    def sample(self, logits, seed, phase, offset, stats=False):
        return self.tape[offset], None


class RefrainControls(unittest.TestCase):
    def test_prior_cue_and_all_history(self):
        d = Discriminator(FiniteEncoder(), .8)
        a = d.observe('Wait, the answer is seven.')
        self.assertEqual(a['action'], 'CONTINUE')
        self.assertFalse(a['prior_provisional_answer'])
        self.assertEqual(d.observe('An unrelated new step.')['action'], 'CONTINUE')
        b = d.observe('Wait, recheck the first step.')
        self.assertEqual(b['action'], 'STOP')
        self.assertEqual(b['max_prior_cosine'], 1.)  # Last step was orthogonal.

    def test_redundancy_without_reflection_continues(self):
        d = Discriminator(FiniteEncoder(), .6)
        d.observe('The answer should be seven.')
        b = d.observe('The calculation still gives seven.')
        self.assertEqual(b['max_prior_cosine'], 1.)
        self.assertEqual(b['action'], 'CONTINUE')

    def test_bandit_cold_start_cost_and_window(self):
        b = SlidingWindowUCB(arms=(.6, .8), window=2)
        self.assertEqual(b.choose(), .6)
        r = b.update(.6, .8, 100)
        self.assertAlmostEqual(r['reward'], .79)
        self.assertEqual(b.choose(), .8)
        r = b.update(.8, .8, 200)
        self.assertAlmostEqual(r['penalty'], .4)
        self.assertEqual(r['prior_mean_output_tokens'], 100)
        # UCB exploration uses actual pulls, with per-arm eviction, and no labels.
        for score in (.2, .4, .6):
            b.update(.6, score, 100)
        self.assertEqual(len(b.buffers[.6]), 2)
        self.assertEqual(b.completed, 5)
        self.assertEqual(b.total_length, 600)
        self.assertTrue(math.isfinite(b.buffers[.6][0]))
        self.assertFalse(r['gold_used'])

    def test_blank_line_checks_before_128_and_preserves_no_stop(self):
        text = 'The answer is seven.\n\nWait, the answer is seven.\n\nMore details.'
        engine = FakeEngine(text)
        stopped = decode_refrain(engine, FiniteEncoder(), [99], len(text), 42, .8)
        self.assertEqual(stopped['stop_reason'], 'policy_stop')
        self.assertLess(stopped['tokens'], 128)
        self.assertEqual(stopped['ids'], engine.tape[:stopped['tokens']])
        self.assertEqual(len(stopped['decisions']), 2)
        text = 'The answer is seven.\n\nA calculation gives seven.\n\nMore details.'
        engine = FakeEngine(text)
        full = decode_refrain(engine, FiniteEncoder(), [99], len(text), 42, .8)
        self.assertEqual(full['stop_reason'], 'limit')
        self.assertEqual(full['ids'], engine.tape)

    def test_answer_likelihood_excludes_brace_only_tokens(self):
        import torch
        from types import SimpleNamespace
        class Tokenizer:
            def __init__(self, pieces): self.pieces = pieces
            def encode(self, text, **kwargs): return [99]
            def convert_tokens_to_ids(self, text): return 99
            def decode(self, ids, **kwargs): return ''.join(self.pieces[i] for i in ids if i in self.pieces)
        class AnswerEngine:
            def __init__(self, pieces):
                self.torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None))
                self.tok = Tokenizer(pieces)
                self.model_ms = 0.
                self.suffix = [99]
                self.answer_cue = r'Final answer: \boxed{'
                self.eos = {0}
                self.tape = list(pieces)
            def forward(self, ids, cache=None): return 1, torch.zeros(256)
            def sample(self, logits, seed, phase, offset, stats=False):
                return (self.tape[offset] if offset < len(self.tape) else 0), None
        separated = answer_refrain(AnswerEngine({10:'7', 11:'}'}), [99], 42)
        self.assertEqual(separated['answer_score_token_indices'], [0])
        self.assertEqual(separated['answer_boundary_overlap_indices'], [])
        self.assertAlmostEqual(separated['answer_score'], 1 / 256, places=6)
        joined = answer_refrain(AnswerEngine({10:'7}'}), [99], 42)
        self.assertEqual(joined['answer_score_token_indices'], [0])
        self.assertEqual(joined['answer_boundary_overlap_indices'], [0])
        nested = answer_refrain(AnswerEngine({10:r'\frac{1}', 11:'{2}', 12:'}'}), [99], 42)
        self.assertEqual(nested['answer_score_token_indices'], [0, 1])
        invalid = answer_refrain(AnswerEngine({10:'unclosed'}), [99], 42)
        self.assertEqual(invalid['answer_score'], 0.)


if __name__ == '__main__':
    unittest.main()
