"""Declared repair of pinned Qwen-DEER score identity/short-trial interfaces.

This helper alone is not a full DEER or DEER-PRo baseline. The future author
runner must still execute actual ATP/chunk/probe/continue/final transitions.
"""
import math


def qwen_trial_score(emitted_ids, per_token_logprobs, endthink_id, policy='avg2'):
    """Preserve source indices [1:n], but resolve probabilities by emitted ID.

Source behavior includes the terminal token; this repair does not silently
switch to answer-content-only scoring. Empty/single/incomplete/missing/nonfinite
trials yield zero with a reason. Endthink is checked on the emitted sequence.
"""
    assert policy in ['avg1', 'avg2', 'min']
    if len(emitted_ids) != len(per_token_logprobs):
        return {'score': 0., 'valid': False, 'reason': 'unaligned_token_logprob_sequence'}
    if len(emitted_ids) < 2:
        return {'score': 0., 'valid': False, 'reason': 'no_scored_tokens_after_first'}
    if emitted_ids[-1] != endthink_id:
        return {'score': 0., 'valid': False, 'reason': 'trial_did_not_emit_endthink'}
    logs = []
    for index in range(1, len(emitted_ids)):
        token = emitted_ids[index]
        values = per_token_logprobs[index]
        value = values.get(token, values.get(str(token))) if isinstance(values, dict) else None
        if value is None:
            return {'score': 0., 'valid': False, 'reason': 'emitted_token_logprob_missing', 'index': index}
        logprob = value.logprob if hasattr(value, 'logprob') else value.get('logprob') if isinstance(value, dict) else value
        if not isinstance(logprob, (int, float)) or not math.isfinite(logprob) or logprob > 0:
            return {'score': 0., 'valid': False, 'reason': 'invalid_emitted_token_logprob', 'index': index}
        logs.append(float(logprob))
    if policy == 'avg2': score = math.exp(sum(logs) / len(logs))
    elif policy == 'avg1': score = sum(math.exp(x) for x in logs) / len(logs)
    else: score = math.exp(min(logs))
    return {'score': score, 'valid': True, 'reason': None, 'scored_token_indices': list(range(1, len(emitted_ids))),
            'terminal_identity': 'actual_emitted_token_id', 'includes_terminal_in_confidence': True,
            'gold_used': False, 'scope': 'Declared identity/short-sequence repair, not task correctness or author benchmark.'}
