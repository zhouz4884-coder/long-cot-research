"""Four-action controlled ASAG decoder; not an executable author reproduction.

Declarations: common FP16/SDPA sampling and boxed reader; observed Wait included
in prefix; scratch replay of recent thought tokens; mean full-vocabulary answer
distributions for Eq7 between ATPs; one jump per textual maximum; paraphrased J;
logical thought cap counts forced jump tokens. All auxiliary work is charged.
"""
import copy
import hashlib
import json
import re
import time

from reason_transition.core import digest_ids, brace_balance, stable_seed
from reason_transition.text_decoder import RollingTextDecoder
from asag_attention import Qwen3WindowMonitor, summarize_window
from asag_policy import ASAGState, injected_probabilities

ATP = re.compile(r'(?<![A-Za-z])wait(?![A-Za-z])', re.I)
JUMP_PROMPT = 'Wait, reassess the previous steps. Try a different, shorter solution path.\n\n'


def public_asag(result):
    return {k: v for k, v in result.items() if k not in ['cache', 'logits', 'inject_distribution']}


def probe_asag(engine, prompt, thought_ids, cache, seed, previous_span=None, current_span=None):
    """Recompute a bounded recent window on a copied/cropped cache, then probe.

Restored tail is a new numerical forward, not historical incremental query
states. Its answer is the actual candidate eligible for this policy's STOP.
"""
    torch = engine.torch
    torch.cuda.synchronize()
    started = time.perf_counter()
    before = engine.model_ms
    prefix = prompt + thought_ids
    assert cache.get_seq_length() == len(prefix)
    original_length = cache.get_seq_length()
    scratch = copy.deepcopy(cache)
    recent = min(len(thought_ids), len(engine.suffix))
    scratch.crop(len(prefix) - recent)
    replay = thought_ids[-recent:] if recent else []
    with Qwen3WindowMonitor(engine.model, len(prefix) - recent) as monitor:
        scratch, logits = engine.forward(replay + engine.suffix, scratch)
    summary = summarize_window(monitor.probabilities(), previous_span, current_span)
    del monitor
    context = prefix + engine.suffix
    ids, chosen_probabilities = [], []
    distribution_sum = None
    decoder = RollingTextDecoder(engine.tok)
    text = ''
    reason = 'limit'
    for offset in range(192):
        probability = logits.float().softmax(-1)
        token, _ = engine.sample(logits, seed, 'answer', offset, stats=False)
        chosen_probabilities.append(float(probability[token].item()))
        distribution_sum = probability.clone() if distribution_sum is None else distribution_sum + probability
        ids.append(token)
        text = decoder.append(token)
        scratch, logits = engine.forward([token], scratch)
        if 1 + brace_balance(text) <= 0:
            reason = 'answer_box_complete'
            break
        if token in engine.eos:
            reason = 'eos'
            break
    assert cache.get_seq_length() == original_length
    average = distribution_sum / len(ids)
    average = average / average.sum()
    confidence = sum(chosen_probabilities) / len(chosen_probabilities)
    identity = hashlib.sha256(json.dumps({'prefix_sha256': digest_ids(context), 'seed': seed,
                                         'generated_ids': ids}, sort_keys=True).encode()).hexdigest()
    torch.cuda.synchronize()
    return {'ids': ids, 'tokens': len(ids), 'text': r'\boxed{' + text, 'generated_text': text,
            'stop_reason': reason, 'length_censored': reason == 'limit',
            'confidence_arithmetic_mean_raw_chosen_token_probability': confidence,
            'chosen_raw_token_probabilities': chosen_probabilities,
            'attention': summary, 'recent_recomputed_tokens': recent,
            'actual_probe_forward_input_tokens': recent + len(engine.suffix),
            'control_prefix_input_tokens': len(engine.suffix), 'answer_prefix_hash': digest_ids(context),
            'candidate_identity_sha256': identity, 'readout_seed': seed,
            'parent_cache_length_preserved': True,
            'ms': 1000 * (time.perf_counter() - started), 'model_ms': engine.model_ms - before,
            'quality_labels_used': False, 'inject_distribution': average,
            'cache': scratch, 'logits': logits,
            'scope': 'Actual scratch replay/probe. Mean vocabulary vector over all sampled answer steps, including boundary tokens; not historical SDPA attention.'}


def decode_asag(engine, prefix, max_think_tokens, seed, confidence_threshold=.95,
                entropy_change_threshold=-.1, maximum_jumps=1):
    """Actual token-level four-action decoder; the caller reuses committed answer."""
    assert max_think_tokens > 0
    torch = engine.torch
    torch.cuda.synchronize()
    started = time.perf_counter()
    before = engine.model_ms
    cache, logits = engine.forward(prefix)
    prefill_ms = engine.model_ms - before
    state = ASAGState(confidence_threshold, entropy_change_threshold, maximum_jumps)
    decoder = RollingTextDecoder(engine.tok)
    ids = []
    text = ''
    sampled = forced_tokens = auxiliary_generated = auxiliary_inputs = 0
    probe_ms = 0.
    decisions = []
    boundaries = [0]
    last_marker_end = 0
    injection = None
    committed = None
    reason = 'limit'
    while len(ids) < max_think_tokens:
        sampling_logits = logits if injection is None else injected_probabilities(logits.float().softmax(-1), injection)
        token, _ = engine.sample(sampling_logits, seed, 'think', sampled, stats=False)
        sampled += 1
        ids.append(token)
        text = decoder.append(token)
        cache, logits = engine.forward([token], cache)
        if token in engine.eos:
            reason = 'eos'
            break
        if token == engine.endthink:
            reason = 'natural_end'
            break
        markers = [m for m in ATP.finditer(text) if m.end() > last_marker_end]
        if not markers:
            continue
        last_marker_end = markers[-1].end()
        n = len(ids)
        previous = (len(prefix) + boundaries[-2], len(prefix) + boundaries[-1]) if len(boundaries) > 1 else None
        current = (len(prefix) + boundaries[-1], len(prefix) + n)
        probe = probe_asag(engine, prefix, ids, cache, stable_seed(seed, 'asag-probe', n, sampled), previous, current)
        auxiliary_generated += probe['tokens']
        auxiliary_inputs += probe['actual_probe_forward_input_tokens']
        probe_ms += probe['ms']
        decision = state.decide(probe['confidence_arithmetic_mean_raw_chosen_token_probability'],
                                probe['attention']['entropy_sum'], probe['attention']['trap'])
        decision.update({'offset': n, 'sampled_thinking_tokens': sampled, 'observed_marker': markers[-1].group(),
                         'prefix_sha256': digest_ids(prefix + ids), 'probe': public_asag(probe)})
        boundaries.append(n)
        if decision['action'] == 'STOP':
            # Deliver the same paid candidate, never silently resample it.
            committed = public_asag(probe)
            reason = 'policy_stop'
            decisions.append(decision)
            del probe
            break
        if decision['action'] == 'INJECT':
            injection = probe['inject_distribution']
        else:
            injection = None
        if decision['action'] == 'JUMP':
            jump_ids = engine.tok.encode(JUMP_PROMPT, add_special_tokens=False)
            if len(ids) + len(jump_ids) > max_think_tokens:
                decision['applied_action'] = 'CONTINUE'
                decision['intervention_censored_by_context_budget'] = True
            else:
                cache, logits = engine.forward(jump_ids, cache)
                ids.extend(jump_ids)
                forced_tokens += len(jump_ids)
                for forced in jump_ids:
                    text = decoder.append(forced)
                last_marker_end = len(text)  # Do not treat forced Wait as a new ATP.
                decision['jump_input_tokens'] = len(jump_ids)
                decision['jump_prompt_variant'] = 'declared_paraphrase'
        decisions.append(decision)
        del probe
    torch.cuda.synchronize()
    trace = {'ids': ids, 'text': text, 'tokens': len(ids), 'sampled_thinking_tokens': sampled,
             'forced_think_input_tokens': forced_tokens, 'stop_reason': reason, 'length_censored': reason == 'limit',
             'ms': 1000 * (time.perf_counter() - started), 'model_ms': engine.model_ms - before,
             'prefill_model_ms': prefill_ms, 'decisions': decisions,
             'auxiliary_generated_tokens': auxiliary_generated, 'auxiliary_forward_input_tokens': auxiliary_inputs,
             'auxiliary_wall_ms': probe_ms, 'quality_labels_available_during_decisions': False,
             'cache': cache, 'logits': logits,
             'scope': 'Controlled ASAG decoder with all four actions; all scratch/candidate/injection/jump work inside wall-clock; formal GPU/runtime admission pending.'}
    return trace, committed
