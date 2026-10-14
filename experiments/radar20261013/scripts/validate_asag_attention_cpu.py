"""Actual random-weight tiny Qwen3 CPU controls under the frozen HF runtime.

This proves a finite measurement interface, not ASAG or learned-model results.
"""
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from asag_attention import Qwen3WindowMonitor, summarize_window


def main():
    import torch
    from transformers import Qwen3Config, Qwen3ForCausalLM
    torch.set_num_threads(1)
    torch.manual_seed(20261014)
    config = Qwen3Config(vocab_size=31, hidden_size=64, intermediate_size=128, num_hidden_layers=4,
                         num_attention_heads=4, num_key_value_heads=2, head_dim=16, attention_dropout=0.,
                         max_position_embeddings=128)
    config._attn_implementation = 'sdpa'
    model = Qwen3ForCausalLM(config).eval()
    eager = copy.deepcopy(model)
    eager.config._attn_implementation = 'eager'
    cases = []
    for prefix_length, window in [(0, 7), (5, 7), (20, 1)]:
        prefix = torch.arange(prefix_length).unsqueeze(0) % config.vocab_size
        extension = (torch.arange(window).unsqueeze(0) + 3) % config.vocab_size
        with torch.inference_mode():
            parent = model(prefix, use_cache=True).past_key_values if prefix_length else None
            original_parent = copy.deepcopy(parent)
            control = model(extension, past_key_values=copy.deepcopy(parent), use_cache=True)
            with Qwen3WindowMonitor(model, prefix_length) as monitor:
                measured = model(extension, past_key_values=copy.deepcopy(parent), use_cache=True)
            reference = eager(extension, past_key_values=copy.deepcopy(parent), use_cache=True, output_attentions=True)
        captured = monitor.probabilities()
        maximum_error = max(float((a - b.float()).abs().max().item())
                            for a, b in zip(captured, reference.attentions[-4:]))
        unchanged = parent is None or all(torch.equal(a.keys, b.keys) and torch.equal(a.values, b.values)
                                         for a, b in zip(parent.layers, original_parent.layers))
        logits_same = torch.equal(control.logits, measured.logits)
        caches_same = all(torch.equal(a.keys, b.keys) and torch.equal(a.values, b.values)
                          for a, b in zip(control.past_key_values.layers, measured.past_key_values.layers))
        summary = summarize_window(captured, (0, min(prefix_length, 2)),
                                    (prefix_length, prefix_length + window))
        row_error = max(float((p.sum(-1) - 1.).abs().max().item()) for p in captured)
        hooks_removed = all(not model.model.layers[i].self_attn._forward_pre_hooks for i in monitor.layers)
        check = {'past_tokens': prefix_length, 'query_window_tokens': window,
                 'eager_attention_max_abs_error': maximum_error, 'probability_row_sum_max_abs_error': row_error,
                 'identical_SDPA_logits_with_and_without_monitor': logits_same,
                 'all_result_KV_identical': caches_same, 'all_parent_KV_unchanged': unchanged,
                 'all_temporary_hooks_removed': hooks_removed, 'window_summary': summary}
        assert maximum_error < 2e-6 and row_error < 2e-6 and unchanged and logits_same and caches_same and hooks_removed
        cases.append(check)
    report = {'passed': True, 'cases': cases,
              'package_versions': {n: importlib.metadata.version(n) for n in ['torch', 'transformers']},
              'source_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in
                                ['asag_attention.py', 'scripts/validate_asag_attention_cpu.py']},
              'model_scope': 'Random-weight four-layer tiny Qwen3, CPU FP32; not the downloaded Qwen3-4B',
              'scope': 'Finite scratch-window GQA/RoPE/causal-mask/read-only-hook controls only. No learned-model ASAG policy, efficacy or GPU admission.'}
    (ROOT / 'provenance/asag_attention_cpu_control.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
