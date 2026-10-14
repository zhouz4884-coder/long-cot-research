"""Independent read-only audits/statistics for controlled online baselines."""
from collections import Counter
import math
import numpy as np
from scipy.stats import binomtest
from reason_transition.core import stable_seed
from risk_policy import problem_shard


def complete_scope(rows, expected_ids, method, split, protocol_hash, formal_hash, model, shards):
    expected = set(expected_ids)
    assert expected, 'Empty scopes are not completed evaluations'
    seen = set()
    for row in rows:
        pid = row['problem_id']
        assert pid in expected and pid not in seen, 'Unexpected or duplicate problem'
        seen.add(pid)
        assert row['method'] == method and row['split'] == split
        assert row['protocol_sha256'] == protocol_hash and row['formal_protocol_sha256'] == formal_hash
        assert row['model_path'] == model and row['assigned_shard'] == problem_shard(pid, shards)
        assert row['quality_labels_available_during_decisions'] is False
        assert row['correct'] in [0, 1] and row['grade']['correct'] == row['correct']
        assert math.isfinite(row['wall_ms']) and row['wall_ms'] > 0
        assert row['compute_generated_tokens'] > 0
        assert row['trace']['tokens'] == len(row['trace']['ids'])
        assert row['answer']['tokens'] == len(row['answer']['ids'])
    assert seen == expected, 'Full expected question scope is required'


def quality_cost_summary(rows, full_rows, ordered_adaptation=False):
    ids = sorted(rows)
    assert ids and set(ids) == set(full_rows)
    y = np.array([rows[i]['correct'] for i in ids])
    reference_y = np.array([full_rows[i]['correct'] for i in ids])
    wall = np.array([rows[i]['wall_ms'] for i in ids])
    full_wall = np.array([full_rows[i]['wall_ms'] for i in ids])
    assert np.isfinite(wall).all() and np.isfinite(full_wall).all() and (wall > 0).all() and (full_wall > 0).all()
    harmful = int(((reference_y == 1) & (y == 0)).sum())
    beneficial = int(((reference_y == 0) & (y == 1)).sum())
    delta = y - reference_y
    result = {'n': len(ids), 'correct': int(y.sum()), 'reference_correct': int(reference_y.sum()),
              'accuracy_delta': float(delta.mean()), 'harmful': harmful, 'beneficial': beneficial,
              'mean_backend_wall_s': float(wall.mean() / 1000),
              'mean_reference_backend_wall_s': float(full_wall.mean() / 1000),
              'aggregate_wall_saving': float(1 - wall.sum() / full_wall.sum()),
              'wall_saving_on_reference_correct': float(1 - wall[reference_y == 1].sum() / full_wall[reference_y == 1].sum())
                  if (reference_y == 1).any() else None,
              'mean_compute_generated_tokens': float(np.mean([r['compute_generated_tokens'] for r in rows.values()])),
              'parse_non_success': sum(r['grade']['parse_status'] != 'ok' for r in rows.values()),
              'thinking_cap_reached': sum(r['trace']['stop_reason'] == 'limit' for r in rows.values()),
              'maximum_peak_allocated_bytes': max(r['peak_allocated_bytes'] for r in rows.values()),
              'independent_risk_certification_performed': False, 'serving_performance_proven': False}
    if ordered_adaptation:
        result['uncertainty_scope'] = 'Descriptive fixed ordered stream only. Cross-question adaptation invalidates the unqualified per-problem IID bootstrap/McNemar and main fixed-potential-outcome risk family.'
        result['accuracy_delta_iid_bootstrap95ci'] = None
        result['conditional_iid_mcnemar_two_sided_p'] = None
        result['wall_saving_iid_bootstrap95ci'] = None
    else:
        rng = np.random.default_rng(20261014)
        index = rng.integers(0, len(ids), (4000, len(ids)))
        result['accuracy_delta_iid_bootstrap95ci'] = np.quantile(delta[index].mean(1), [.025, .975]).tolist()
        result['wall_saving_iid_bootstrap95ci'] = np.quantile(1 - wall[index].sum(1) / full_wall[index].sum(1), [.025, .975]).tolist()
        n = harmful + beneficial
        result['conditional_iid_mcnemar_two_sided_p'] = float(binomtest(beneficial, n, .5).pvalue) if n else 1.
        result['uncertainty_scope'] = 'Conditional IID/exchangeable-pair diagnostics only, not the stratified finite-pool risk certificate or a latency guarantee.'
    return result


def asag_diagnostics(rows, entropy_threshold):
    actions, applied, stop_reasons = Counter(), Counter(), Counter()
    normalized_crossings = geometry_only_crossings = 0
    details = []
    for pid, row in rows.items():
        trace = row['trace']
        assert trace['tokens'] == trace['sampled_thinking_tokens'] + trace['forced_think_input_tokens']
        probes = trace['decisions']
        assert trace['auxiliary_generated_tokens'] == sum(d['probe']['tokens'] for d in probes)
        assert trace['auxiliary_forward_input_tokens'] == sum(d['probe']['actual_probe_forward_input_tokens'] for d in probes)
        first = None
        for decision in probes:
            actions[decision['action']] += 1
            applied[decision.get('applied_action', decision['action'])] += 1
            p = decision['probe']['attention']
            h, q, k = p['entropy_sum'], p['query_rows'], p['key_tokens']
            if first is None:
                first = (h, q, k)
            if first[0] > 0 and h > 0:
                geometry = (q / first[1]) * (math.log(first[2]) / math.log(k)) - 1
                unnormalized = h * math.log(k) / q
                base_unnormalized = first[0] * math.log(first[2]) / first[1]
                actual = (h - first[0]) / first[0]
                crossed = actual < entropy_threshold
                normalized_crossings += int(crossed)
                geometry_only_crossings += int(crossed and geometry < entropy_threshold)
                details.append({'problem_id': pid, 'offset': decision['offset'], 'action': decision['action'],
                                'relative_normalized_entropy_delta': actual,
                                'relative_query_key_normalizer_component_if_shannon_fixed': geometry,
                                'relative_unnormalized_entropy_per_query_delta': unnormalized / base_unnormalized - 1})
        if trace['stop_reason'] == 'policy_stop':
            last = probes[-1]
            assert last['action'] == 'STOP'
            assert row['answer']['candidate_identity_sha256'] == last['probe']['candidate_identity_sha256']
            assert row['answer']['ids'] == last['probe']['ids'] and row['answer']['text'] == last['probe']['text']
            stop_reasons[last['reason']] += 1
            new_final = 0
        else:
            new_final = row['answer']['tokens']
        assert row['compute_generated_tokens'] == trace['sampled_thinking_tokens'] + trace['auxiliary_generated_tokens'] + new_final
    return {'actions': dict(actions), 'applied_actions': dict(applied), 'stop_reasons': dict(stop_reasons),
            'normalized_entropy_crossings': normalized_crossings,
            'crossings_where_query_key_normalizer_component_alone_would_suffice': geometry_only_crossings,
            'entropy_decomposition': details,
            'interpretation': 'A mathematical decomposition of observed scalars, not a causal attribution, task-error explanation, or prevalence estimate from the synthetic control.'}


def prefix_control(candidate, full, method):
    assert candidate['seed'] == full['seed']
    trace, reference = candidate['trace']['ids'], full['trace']['ids']
    if method == 'asag_controlled':
        changes = [d for d in candidate['trace']['decisions'] if d['action'] in ['INJECT', 'JUMP']
                   and not d.get('intervention_censored_by_context_budget')]
        length = changes[0]['offset'] if changes else len(trace)
        assert candidate['common_thinking_prefix_before_first_intervention_tokens'] == length
    else:
        length = len(trace)
    assert len(reference) >= length and trace[:length] == reference[:length]
    return length
