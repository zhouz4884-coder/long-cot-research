"""Candidate-bound side readouts and bounded paragraph continuations.

No correctness label is used by these model-facing operations. Main-prefix
caches are copied before a readout; a committed candidate is never resampled.
"""
import copy
import hashlib
import json
import math
import time

from reason_transition.core import boundary, brace_balance, public, digest_ids


def candidate(e, prefix, cache, logits, seed, natural_closed=False):
    e.torch.cuda.synchronize()
    start = time.perf_counter()
    model_before = e.model_ms
    original_len = cache.get_seq_length()
    child = copy.deepcopy(cache)
    suffix = e.tok.encode("\n\n" + e.answer_cue, add_special_tokens=False) if natural_closed else e.suffix
    child, next_logits = e.forward(suffix, child)
    first_lp = next_logits.float().log_softmax(-1)
    first_entropy = float(-(first_lp.exp() * first_lp).sum().item())
    ids, text, logps, maxima, entropies = [], "", [], [], []
    reason = "limit"
    for i in range(192):
        lp = next_logits.float().log_softmax(-1)
        probs = lp.exp()
        token, _ = e.sample(next_logits, seed, "answer", i, stats=False)
        logps.append(float(lp[token].item()))
        maxima.append(float(probs.max().item()))
        entropies.append(float(-(probs * lp).sum().item()))
        ids.append(token)
        text += e.tok.decode([token], skip_special_tokens=False)
        child, next_logits = e.forward([token], child)
        if 1 + brace_balance(text) <= 0:
            reason = "answer_box_complete"
            break
        if token in e.eos:
            reason = "eos"
            break
    assert cache.get_seq_length() == original_len
    e.torch.cuda.synchronize()
    result = {"ids": ids, "text": r"\boxed{" + text, "generated_text": text,
              "tokens": len(ids), "stop_reason": reason, "length_censored": reason == "limit",
              "ms": 1000 * (time.perf_counter() - start), "model_ms": e.model_ms - model_before,
              "eat_entropy": first_entropy, "logprob_mean": sum(logps) / len(logps),
              "logprob_min": min(logps), "entropy_mean": sum(entropies) / len(entropies),
              "maxprob_geomean": math.exp(sum(math.log(max(x, 1e-300)) for x in maxima) / len(maxima)),
              "answer_prefix_hash": digest_ids(prefix + suffix),
              "candidate_sha256": hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest(),
              "sample_seed": seed, "parent_cache_unchanged_in_length": True,
              "cache_strategy": "copy_before_readout"}
    del child, next_logits
    return result


def decode_steps(e, prefix, cache, logits, seed, offset, steps, max_tokens):
    """Paragraphs are operational boundaries; hitting cap is a recorded outcome."""
    assert steps > 0 and max_tokens > 0
    e.torch.cuda.synchronize()
    start = time.perf_counter()
    model_before = e.model_ms
    ids, text, complete = [], "", 0
    reason = "limit"
    last_boundary = -1
    for i in range(max_tokens):
        token, _ = e.sample(logits, seed, "think", offset + i, stats=False)
        ids.append(token)
        text += e.tok.decode([token], skip_special_tokens=False)
        cache, logits = e.forward([token], cache)
        if token in e.eos:
            reason = "eos"
            break
        if token == e.endthink:
            reason = "natural_end"
            break
        # Consecutive extra newlines at one boundary count once.
        if boundary(text) and text.strip() and len(text.rstrip()) != last_boundary:
            complete += 1
            last_boundary = len(text.rstrip())
            if complete >= steps:
                reason = "step_end"
                break
    e.torch.cuda.synchronize()
    return {"ids": ids, "text": text, "tokens": len(ids), "steps_requested": steps,
            "steps_completed": complete, "stop_reason": reason, "length_censored": reason == "limit",
            "ms": 1000 * (time.perf_counter() - start), "model_ms": e.model_ms - model_before,
            "cache": cache, "logits": logits}


def candidate_features(readout):
    """Only observable answer features; never the gold or future trajectory."""
    return {"candidate_tokens": readout["tokens"],
            "candidate_complete": int(readout["stop_reason"] == "answer_box_complete"),
            "candidate_logprob_mean": readout["logprob_mean"],
            "candidate_logprob_min": readout["logprob_min"],
            "candidate_entropy_mean": readout["entropy_mean"],
            "candidate_first_entropy": readout["eat_entropy"],
            "candidate_confidence": readout["maxprob_geomean"]}
