"""Finite semantic controls for the declared DEER score repair."""
import math
import unittest
from deer_trial_score import qwen_trial_score


class TrialScoreControls(unittest.TestCase):
    def test_empty_single_and_unaligned_are_explicit_zero(self):
        self.assertFalse(qwen_trial_score([], [], 1)['valid'])
        self.assertEqual(qwen_trial_score([1], [{1: math.log(.9)}], 1)['score'], 0.)
        self.assertEqual(qwen_trial_score([2, 1], [], 1)['reason'], 'unaligned_token_logprob_sequence')

    def test_emitted_identity_not_dictionary_order_or_alternative_stop(self):
        start = {2: math.log(.8)}
        a = {7: math.log(.03), 1: math.log(.96)}
        b = {1: math.log(.96), 7: math.log(.03)}
        self.assertEqual(qwen_trial_score([2, 7], [start, a], 1)['score'], 0.)
        self.assertEqual(qwen_trial_score([2, 7], [start, b], 1)['score'], 0.)
        self.assertEqual(qwen_trial_score([2, 1], [start, a], 1)['score'],
                         qwen_trial_score([2, 1], [start, b], 1)['score'])

    def test_preserves_actual_source_first_skip_and_terminal_inclusion(self):
        records = [{2: math.log(.2)}, {3: math.log(.4)}, {1: math.log(.8)}]
        result = qwen_trial_score([2, 3, 1], records, 1)
        self.assertAlmostEqual(result['score'], math.sqrt(.4 * .8))
        self.assertEqual(result['scored_token_indices'], [1, 2])
        self.assertTrue(result['includes_terminal_in_confidence'])
        self.assertFalse(result['gold_used'])

    def test_missing_and_nonfinite_do_not_silently_skip(self):
        records = [{2: math.log(.2)}, {3: float('nan')}, {1: math.log(.8)}]
        self.assertEqual(qwen_trial_score([2, 3, 1], records, 1)['reason'], 'invalid_emitted_token_logprob')
        records[1] = {7: math.log(.9)}
        self.assertEqual(qwen_trial_score([2, 3, 1], records, 1)['reason'], 'emitted_token_logprob_missing')


if __name__ == '__main__':
    unittest.main()
