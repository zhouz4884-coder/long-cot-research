"""Synthetic analysis controls; no learned-baseline evidence is fabricated."""
import copy
import math
import unittest
from baseline_analysis import complete_scope, quality_cost_summary, asag_diagnostics
from risk_policy import problem_shard


def row(pid, correct=1, wall=1000):
    return {'problem_id': pid, 'method': 'dtsr_controlled', 'split': 'selection',
            'protocol_sha256': 'baseline', 'formal_protocol_sha256': 'formal', 'model_path': 'model',
            'assigned_shard': problem_shard(pid, 2), 'quality_labels_available_during_decisions': False,
            'correct': correct, 'grade': {'correct': correct, 'parse_status': 'ok'},
            'wall_ms': wall, 'compute_generated_tokens': 2, 'peak_allocated_bytes': 8,
            'trace': {'ids': [1], 'tokens': 1, 'stop_reason': 'limit'}, 'answer': {'ids': [7], 'tokens': 1}}


class AnalysisControls(unittest.TestCase):
    def test_full_scope_and_identity_reject_missing_duplicate_and_wrong_protocol(self):
        items = [row('a'), row('b')]
        args = (['a', 'b'], 'dtsr_controlled', 'selection', 'baseline', 'formal', 'model', 2)
        complete_scope(items, *args)
        for invalid in [items[:1], [items[0], items[0]]]:
            with self.assertRaises(AssertionError): complete_scope(invalid, *args)
        bad = copy.deepcopy(items)
        bad[0]['protocol_sha256'] = 'changed'
        with self.assertRaises(AssertionError): complete_scope(bad, *args)

    def test_paired_quality_and_real_ratio_not_mean_of_individual_ratios(self):
        candidate = {'a': row('a', 0, 50), 'b': row('b', 1, 400)}
        full = {'a': row('a', 1, 100), 'b': row('b', 0, 900)}
        result = quality_cost_summary(candidate, full)
        self.assertEqual(result['accuracy_delta'], 0)
        self.assertEqual((result['harmful'], result['beneficial']), (1, 1))
        self.assertAlmostEqual(result['aggregate_wall_saving'], .55)
        self.assertAlmostEqual(result['wall_saving_on_reference_correct'], .5)
        self.assertFalse(result['independent_risk_certification_performed'])

    def test_ordered_adaptation_does_not_inherit_iid_statistics(self):
        candidate, full = {'a': row('a')}, {'a': row('a')}
        result = quality_cost_summary(candidate, full, ordered_adaptation=True)
        self.assertIsNone(result['conditional_iid_mcnemar_two_sided_p'])
        self.assertIsNone(result['accuracy_delta_iid_bootstrap95ci'])
        self.assertIsNone(result['wall_saving_iid_bootstrap95ci'])

    def test_asag_committed_identity_cost_and_entropy_decomposition(self):
        first = {'action': 'CONTINUE', 'offset': 1, 'probe': {'tokens': 2, 'actual_probe_forward_input_tokens': 16,
                 'attention': {'entropy_sum': 100., 'query_rows': 16, 'key_tokens': 256}}}
        second = {'action': 'STOP', 'reason': 'high_confidence_and_entropy_drop', 'offset': 2,
                  'probe': {'tokens': 2, 'ids': [7, 8], 'text': '7}', 'candidate_identity_sha256': 'same',
                            'actual_probe_forward_input_tokens': 16,
                            'attention': {'entropy_sum': 80., 'query_rows': 16, 'key_tokens': 512}}}
        item = {'compute_generated_tokens': 6, 'trace': {'tokens': 2, 'sampled_thinking_tokens': 2,
                'forced_think_input_tokens': 0, 'auxiliary_generated_tokens': 4,
                'auxiliary_forward_input_tokens': 32, 'decisions': [first, second], 'stop_reason': 'policy_stop'},
                'answer': {'ids': [7, 8], 'text': '7}', 'candidate_identity_sha256': 'same'}}
        details = asag_diagnostics({'a': item}, -.1)
        self.assertEqual(details['normalized_entropy_crossings'], 1)
        self.assertEqual(details['crossings_where_query_key_normalizer_component_alone_would_suffice'], 1)
        observed = details['entropy_decomposition'][-1]
        self.assertAlmostEqual(observed['relative_normalized_entropy_delta'], -.2)
        self.assertAlmostEqual(observed['relative_query_key_normalizer_component_if_shannon_fixed'], -1/9)
        self.assertAlmostEqual(observed['relative_unnormalized_entropy_per_query_delta'], -.1)
        bad = copy.deepcopy(item)
        bad['compute_generated_tokens'] = 8  # Incorrectly charge the reused candidate twice.
        with self.assertRaises(AssertionError): asag_diagnostics({'a': bad}, -.1)
        bad = copy.deepcopy(item)
        bad['answer']['candidate_identity_sha256'] = 'resampled'
        with self.assertRaises(AssertionError): asag_diagnostics({'a': bad}, -.1)


if __name__ == '__main__':
    unittest.main()
