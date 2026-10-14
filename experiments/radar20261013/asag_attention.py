"""Window-only Qwen3 attention measurement for a controlled ASAG adaptation.

Does not replace SDPA, change model weights, or implement the four-action policy.
Reconstructs eager-style QK probabilities in the last four layers on a scratch
probe forward. The measured probability matrix is not claimed to be SDPA's
unmaterialized internal matrix bit for bit.
"""
import math


def window_probabilities(query, key, scaling, past_length, attention_mask=None):
    """Query positions are the appended window; keys include its past prefix.

All query heads must already be aligned to GQA keys, and RoPE applied upstream.
Use actual additive mask when supplied; otherwise construct the causal mask.
"""
    import torch
    assert query.ndim == key.ndim == 4
    assert query.shape[:2] == key.shape[:2] and query.shape[-1] == key.shape[-1]
    batch, heads, q, _ = query.shape
    k = key.shape[-2]
    assert past_length >= 0 and k == past_length + q and k > 1
    scores = torch.matmul(query, key.transpose(-2, -1)) * scaling
    if attention_mask is not None:
        assert attention_mask.ndim == 4 and attention_mask.shape[-2] in [1, q]
        assert attention_mask.shape[-1] >= k
        if attention_mask.dtype == torch.bool:
            scores = scores.masked_fill(~attention_mask[..., :k], float('-inf'))
        else:
            scores = scores + attention_mask[..., :k]
    else:
        positions = past_length + torch.arange(q, device=query.device)
        future = torch.arange(k, device=query.device).unsqueeze(0) > positions.unsqueeze(1)
        scores = scores.masked_fill(future.unsqueeze(0).unsqueeze(0), float('-inf'))
    probabilities = torch.softmax(scores, dim=-1, dtype=torch.float32)
    assert probabilities.shape == (batch, heads, q, k)
    assert torch.isfinite(probabilities).all()
    return probabilities


def summarize_window(layer_probabilities, previous_span=None, current_span=None):
    """Eq2/6 sum over queries, heads, last four layers, normalized by log(k).

Eq8 averages layers and heads. Trap statistics also average query rows and
divide by each thought action's number of keys, keeping sum/mean distinct.
"""
    import torch
    assert len(layer_probabilities) == 4
    shapes = {tuple(p.shape) for p in layer_probabilities}
    assert len(shapes) == 1
    batch, heads, queries, keys = next(iter(shapes))
    assert batch == 1 and queries > 0 and keys > 1
    entropies = [float((-(p * p.clamp_min(torch.finfo(p.dtype).tiny).log()).sum()
                        / math.log(keys)).item()) for p in layer_probabilities]
    global_row = torch.stack(layer_probabilities).mean(dim=(0, 1, 2, 3))
    assert global_row.shape == (keys,)
    def mass(span):
        if span is None:
            return None
        start, stop = span
        assert 0 <= start <= stop <= keys
        return float(global_row[start:stop].mean().item()) if start < stop else None
    previous, current = mass(previous_span), mass(current_span)
    return {'entropy_sum': sum(entropies), 'entropy_by_layer': entropies,
            'query_rows': queries, 'key_tokens': keys, 'heads_per_layer': heads,
            'previous_action_mean_token_attention': previous,
            'current_action_mean_token_attention': current,
            'trap': previous is not None and current is not None and previous > current,
            'scope': 'Eager-style measured QK window; entropy is summed across query rows, not averaged.'}


class Qwen3WindowMonitor:
    """Temporary read-only pre-hooks on a scratch-cache forward, HF4.55 API."""
    def __init__(self, model, expected_past_length):
        assert model.config.model_type == 'qwen3'
        assert len(model.model.layers) >= 4
        assert model.config._attn_implementation == 'sdpa'
        self.model = model
        self.expected_past_length = expected_past_length
        self.layers = list(range(len(model.model.layers) - 4, len(model.model.layers)))
        self.records = {}
        self.handles = []

    def _capture(self, module, args, kwargs):
        import torch
        from transformers.models.qwen3.modeling_qwen3 import apply_rotary_pos_emb, repeat_kv
        hidden = kwargs.get('hidden_states', args[0] if args else None)
        assert hidden is not None and hidden.shape[0] == 1
        assert module.sliding_window is None, 'Sliding-window models need a separate admitted measurement'
        assert not module.training
        shape = (*hidden.shape[:-1], -1, module.head_dim)
        with torch.inference_mode():
            query = module.q_norm(module.q_proj(hidden).view(shape)).transpose(1, 2)
            new_key = module.k_norm(module.k_proj(hidden).view(shape)).transpose(1, 2)
            cos, sin = kwargs['position_embeddings']
            query, new_key = apply_rotary_pos_emb(query, new_key, cos, sin)
            cache = kwargs.get('past_key_value')
            old_key = (cache.layers[module.layer_idx].keys
                       if cache is not None and module.layer_idx < len(cache.layers) else None)
            if old_key is not None:
                assert old_key.shape[-2] == self.expected_past_length
                key = torch.cat([old_key, new_key], dim=-2)
            else:
                assert self.expected_past_length == 0
                key = new_key
            repeated_key = repeat_kv(key, module.num_key_value_groups)
            probabilities = window_probabilities(query, repeated_key, module.scaling,
                                                   self.expected_past_length, kwargs.get('attention_mask'))
        assert module.layer_idx not in self.records, 'One forward only per monitor context'
        self.records[module.layer_idx] = probabilities
        # Returning None leaves all original forward arguments unchanged.

    def __enter__(self):
        for index in self.layers:
            attention = self.model.model.layers[index].self_attn
            self.handles.append(attention.register_forward_pre_hook(self._capture, with_kwargs=True))
        return self

    def __exit__(self, exception_type, exception, traceback):
        for handle in self.handles:
            handle.remove()
        self.handles.clear()

    def probabilities(self):
        assert set(self.records) == set(self.layers), 'Not all four layers were observed'
        return [self.records[index] for index in self.layers]
