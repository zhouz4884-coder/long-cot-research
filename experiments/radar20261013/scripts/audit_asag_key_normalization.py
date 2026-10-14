"""Finite QK/casual-window counterexample control; not learned-model evidence."""
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from asag_attention import window_probabilities, summarize_window
from asag_policy import ASAGState


def main():
    import torch
    torch.set_num_threads(1)
    rows = []
    for keys in [256, 512]:
        # Finite, norm-sqrt(128) Q/K rows with ordinary head scaling. The four
        # active keys are in the past; the appended 32 queries are causal.
        query = torch.ones(1, 32, 32, 128)
        key = -torch.ones(1, 32, keys, 128)
        key[..., :4, :] = 1.
        probabilities = window_probabilities(query, key, 1 / math.sqrt(128), keys - 32)
        summary = summarize_window([probabilities] * 4)
        rows.append({'key_tokens': keys, 'query_rows': 32, 'active_past_keys': 4,
                     'finite_raw_attention_scores': [math.sqrt(128), -math.sqrt(128)],
                     'each_active_key_probability': float(probabilities[..., :4].mean()),
                     'maximum_inactive_allowed_key_probability': float(probabilities[..., 4:].max()),
                     'normalized_entropy_sum': summary['entropy_sum'],
                     'unnormalized_entropy_sum': summary['entropy_sum'] * math.log(keys)})
    delta = (rows[1]['normalized_entropy_sum'] - rows[0]['normalized_entropy_sum']) / rows[0]['normalized_entropy_sum']
    unnormalized_delta = (rows[1]['unnormalized_entropy_sum'] - rows[0]['unnormalized_entropy_sum']) / rows[0]['unnormalized_entropy_sum']
    state = ASAGState()
    state.decide(.8, rows[0]['normalized_entropy_sum'], False)
    decision = state.decide(.8, rows[1]['normalized_entropy_sum'], False)
    assert delta < -.1 and abs(unnormalized_delta) < 1e-5
    assert decision['action'] == 'INJECT'
    report = {'kind': 'synthetic_finite_QK_causal_window_control', 'rows': rows,
              'relative_normalized_entropy_delta': delta, 'relative_unnormalized_entropy_delta': unnormalized_delta,
              'default_threshold': -.1, 'unchanged_synthetic_confidence': .8,
              'state_action': decision['action'], 'learned_model_data': False,
              'source_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in
                                ['scripts/audit_asag_key_normalization.py', 'asag_attention.py', 'asag_policy.py']},
              'claim': 'Finite causal QK windows with nearly unchanged unnormalized attention entropy cross the relative normalized threshold solely to dominant precision through changing log(key_count). This establishes a possible mechanism, not its occurrence or error rate on learned-model tasks.'}
    (ROOT / 'provenance/asag_key_normalization_algebra_control.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
