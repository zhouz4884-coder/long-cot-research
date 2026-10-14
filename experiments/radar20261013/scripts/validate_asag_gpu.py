"""Finite learned-model scratch-probe identity/cache/memory admission.

Run after measured native workers have exited. Select saved pilot prefixes by
actual length only; no correctness-based choice or blind-test data is read.
"""
import argparse
import copy
import inspect
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from reason_transition.core import Engine, stable_seed
from asag_adapter import probe_asag, decode_asag, public_asag
from protocol_guard import package_snapshot, sha256
from run_native_pilot import verify_live_model


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    args = p.parse_args()
    native = json.loads((ROOT / 'provenance/native_pilot_protocol.json').read_text())
    hashes = verify_live_model(args.model, native)
    engine = Engine(args.model)
    by_id = {q['problem_id']: q for q in [json.loads(s) for s in
             (ROOT / 'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()]}
    saved = [json.loads(s) for file in sorted((ROOT / 'results').glob('budget_pilot_[01].jsonl'))
             for s in file.read_text(encoding='utf-8').splitlines()]
    checks = []
    used = set()
    for length in [128, 8192, 16384]:
        eligible = [r for r in saved if r['model_path'] == args.model and r['problem_id'] in by_id
                    and len(r['trace']['ids']) >= length
                    and not any(t == engine.endthink or t in engine.eos for t in r['trace']['ids'][:length])]
        assert eligible, 'No actual same-model saved prefix at requested length'
        unused = [r for r in eligible if r['problem_id'] not in used]
        row = min(unused or eligible, key=lambda r: (r['problem_id'], r['budget']))
        used.add(row['problem_id'])
        prompt = engine.prompt(by_id[row['problem_id']]['question'])
        ids = row['trace']['ids'][:length]
        engine.torch.cuda.reset_peak_memory_stats()
        cache, logits = engine.forward(prompt + ids)
        parent = copy.deepcopy(cache)
        seed = stable_seed('asag-admission', row['problem_id'], length)
        split = len(prompt) + length // 2
        previous, current = (len(prompt), split), (split, len(prompt) + length)
        a = probe_asag(engine, prompt, ids, cache, seed, previous, current)
        b = probe_asag(engine, prompt, ids, cache, seed, previous, current)
        unchanged = all(engine.torch.equal(x.keys, y.keys) and engine.torch.equal(x.values, y.values)
                        for x, y in zip(parent.layers, cache.layers))
        check = {'problem_id': row['problem_id'], 'actual_thought_prefix_tokens': length,
                 'actual_query_window_tokens': a['attention']['query_rows'],
                 'probe_control_input_tokens': a['control_prefix_input_tokens'],
                 'recent_recomputed_tokens': a['recent_recomputed_tokens'],
                 'same_repeated_probe_ids': a['ids'] == b['ids'],
                 'same_repeated_candidate_identity': a['candidate_identity_sha256'] == b['candidate_identity_sha256'],
                 'attention_entropy_repetition_abs_error': abs(a['attention']['entropy_sum'] - b['attention']['entropy_sum']),
                 'raw_confidence_repetition_abs_error': abs(a['confidence_arithmetic_mean_raw_chosen_token_probability'] -
                                                           b['confidence_arithmetic_mean_raw_chosen_token_probability']),
                 'all_parent_KV_unchanged': unchanged,
                 'peak_allocated_bytes': engine.torch.cuda.max_memory_allocated(),
                 'sample_probe': public_asag(a)}
        assert unchanged and check['same_repeated_probe_ids'] and check['same_repeated_candidate_identity']
        assert check['attention_entropy_repetition_abs_error'] < 1e-6
        assert check['raw_confidence_repetition_abs_error'] < 1e-8
        assert check['actual_query_window_tokens'] == 2 * check['probe_control_input_tokens']
        checks.append(check)
        print(json.dumps({k: v for k, v in check.items() if k != 'sample_probe'}), flush=True)
        del a, b, parent, cache, logits
    # A real bounded decoder request for integration only; no Gold is passed.
    question = by_id[sorted(by_id)[0]]
    prompt = engine.prompt(question['question'])
    trace, committed = decode_asag(engine, prompt, 512, stable_seed('asag-decoder-admission', question['problem_id']))
    assert trace['tokens'] == trace['sampled_thinking_tokens'] + trace['forced_think_input_tokens']
    assert trace['tokens'] <= 512
    decoder_check = {'problem_id': question['problem_id'], 'trace': public_asag(trace),
                     'committed': committed, 'scope': 'One actual 512 logical-token integration run, not task success.'}
    from transformers.models.qwen3.modeling_qwen3 import Qwen3Attention
    source_names = ['asag_attention.py', 'asag_policy.py', 'asag_adapter.py', 'scripts/validate_asag_gpu.py',
                    'reason_transition/core.py', 'reason_transition/text_decoder.py', 'scripts/run_native_pilot.py']
    report = {'passed': True, 'model_path': args.model, 'model_revision': native['model_revision'],
              'live_model_file_sha256': hashes, 'package_versions': package_snapshot(), 'checks': checks,
              'decoder_integration_check': decoder_check,
              'source_sha256': {name: sha256(ROOT / name) for name in source_names},
              'upstream_qwen3_implementation_sha256': sha256(inspect.getsourcefile(Qwen3Attention)),
              'scope': 'Three actual saved-prefix scratch/repetition/cache controls and one decoder integration. Not accuracy, four-action coverage on learned tasks, risk certification or runtime benefit.'}
    (ROOT / 'provenance/asag_finite_gpu_admission.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
