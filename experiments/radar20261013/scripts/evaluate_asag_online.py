"""Actual controlled ASAG and newly executed matched FULL, per frozen GPU ID."""
import argparse
import inspect
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from reason_transition.core import Engine, stable_seed, public, grade, append_jsonl
from asag_adapter import decode_asag, public_asag
from protocol_guard import validate_formal, sha256
from risk_policy import problem_shard
from run_native_pilot import verify_live_model

SOURCES = ['asag_attention.py', 'asag_policy.py', 'asag_adapter.py', 'scripts/evaluate_asag_online.py',
           'reason_transition/core.py', 'reason_transition/text_decoder.py', 'risk_policy.py', 'scripts/run_native_pilot.py']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--split', choices=['selection', 'calibration', 'test'], required=True)
    p.add_argument('--protocol-file', required=True)
    p.add_argument('--out-tag', required=True)
    p.add_argument('--shard', type=int, required=True)
    p.add_argument('--shards', type=int, default=2)
    p.add_argument('--n', type=int)
    args = p.parse_args()
    assert 0 <= args.shard < args.shards and os.environ.get('CUDA_VISIBLE_DEVICES') == str(args.shard)
    formal, formal_hash = validate_formal(ROOT, args.model)
    assert formal['gpu_shards'] == args.shards
    protocol_path = Path(args.protocol_file)
    protocol_hash = sha256(protocol_path)
    spec = json.loads(protocol_path.read_text())
    assert spec['formal_protocol_sha256'] == formal_hash and spec['method_scope'] == 'ASAG_controlled_four_action_HF'
    assert set(spec['source_sha256']) == set(SOURCES)
    for name, digest in spec['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    admission_path = ROOT / spec['admission_file']
    admission = json.loads(admission_path.read_text())
    assert sha256(admission_path) == spec['admission_sha256'] and admission['passed']
    assert admission['model_path'] == args.model and admission['package_versions'] == formal['package_versions']
    for name, digest in admission['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    from transformers.models.qwen3.modeling_qwen3 import Qwen3Attention
    assert sha256(inspect.getsourcefile(Qwen3Attention)) == admission['upstream_qwen3_implementation_sha256']
    if args.split == 'test':
        final = json.loads((ROOT / 'provenance/asag_final_test_freeze.json').read_text())
        assert args.n is None and final['protocol_sha256'] == protocol_hash
        assert final['actual_test_generation_records_at_freeze'] == 0
        assert final['data_freeze_sha256'] == sha256(ROOT / 'provenance/data_freeze.json')
    data = ROOT / f'data/{args.split}.jsonl'
    freeze = json.loads((ROOT / 'provenance/data_freeze.json').read_text())
    assert sha256(data) == freeze['splits'][args.split]['sha256']
    rows = [json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()]
    if args.n is not None:
        assert args.n > 0
        rows = rows[:args.n]
    rows = [q for q in rows if problem_shard(q['problem_id'], args.shards) == args.shard]
    expected = {q['problem_id'] for q in rows}
    assert len(expected) == len(rows)
    out = ROOT / f'results/online_{args.out_tag}_{args.shard}.jsonl'
    previous = [json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    done = {r['problem_id'] for r in previous}
    assert len(done) == len(previous) and done <= expected
    for record in previous:
        assert record['protocol_sha256'] == protocol_hash and record['formal_protocol_sha256'] == formal_hash
        assert record['model_path'] == args.model and record['split'] == args.split and record['assigned_shard'] == args.shard
        assert record['paired_request_order'] == pair_order(record['problem_id'])
    native = json.loads((ROOT / 'provenance/native_pilot_protocol.json').read_text())
    live_hashes = verify_live_model(args.model, native)
    engine = Engine(args.model)
    for i in range(2):
        warm = engine.decode(engine.prompt('What is 2 plus 2?'), 16, stable_seed('asag-warm', i))
        del warm
    for q in rows:
        if q['problem_id'] in done:
            continue
        assert sha256(protocol_path) == protocol_hash and validate_formal(ROOT, args.model)[1] == formal_hash
        for name, digest in spec['source_sha256'].items():
            assert sha256(ROOT / name) == digest
        seed = stable_seed(formal['seed'], q['problem_id'], 0)
        pair = {}
        for method in pair_order(q['problem_id']):
            engine.torch.cuda.reset_peak_memory_stats()
            engine.torch.cuda.synchronize()
            started = time.perf_counter()
            prompt = engine.prompt(q['question'])
            if method == 'asag':
                trace, committed = decode_asag(engine, prompt, formal['max_think_tokens'], seed,
                                               spec['confidence_threshold'], spec['entropy_change_threshold'], spec['maximum_jumps'])
                if committed is None:
                    answer = engine.answer(prompt + trace['ids'], seed,
                                           natural_closed=trace['stop_reason'] == 'natural_end',
                                           initial=(trace['cache'], trace['logits']))
                    new_final = answer['tokens']
                else:
                    answer = committed
                    new_final = 0
                compute = trace['sampled_thinking_tokens'] + trace['auxiliary_generated_tokens'] + new_final
                trace_public = public_asag(trace)
            else:
                trace = engine.decode(prompt, formal['max_think_tokens'], seed, until='think', capture=False)
                answer = engine.answer(prompt + trace['ids'], seed,
                                       natural_closed=trace['stop_reason'] == 'natural_end', initial=(trace['cache'], trace['logits']))
                compute = trace['tokens'] + answer['tokens']
                trace_public = public(trace)
            engine.torch.cuda.synchronize()
            wall_ms = 1000 * (time.perf_counter() - started)
            pair[method] = {'trace': trace_public, 'answer': public_asag(answer), 'wall_ms': wall_ms,
                            'compute_generated_tokens': compute, 'delivered_tokens': trace['tokens'] + answer['tokens'],
                            'peak_allocated_bytes': engine.torch.cuda.max_memory_allocated()}
            del trace, answer
        controlled, full = pair['asag'], pair['full']
        interventions = [d for d in controlled['trace']['decisions'] if d['action'] in ['INJECT', 'JUMP']
                         and not d.get('intervention_censored_by_context_budget')]
        common_length = interventions[0]['offset'] if interventions else len(controlled['trace']['ids'])
        assert controlled['trace']['ids'][:common_length] == full['trace']['ids'][:common_length]
        # Probe/stop/intervention decisions are complete before either Gold score.
        score = grade(controlled['answer']['text'], q['gold'])
        full_score = grade(full['answer']['text'], q['gold'])
        record = {'problem_id': q['problem_id'], 'method': 'asag_controlled', 'split': args.split,
                  'seed': seed, 'model_path': args.model, 'formal_protocol_sha256': formal_hash,
                  'protocol_sha256': protocol_hash, **controlled, 'grade': score, 'correct': score['correct'],
                  'matched_full': {**full, 'grade': full_score, 'correct': full_score['correct']},
                  'common_thinking_prefix_before_first_intervention_tokens': common_length,
                  'same_prefix_before_first_intervention': True, 'paired_request_order': pair_order(q['problem_id']),
                  'paired_backend_wall_ms': controlled['wall_ms'] + full['wall_ms'],
                  'paired_compute_generated_tokens': controlled['compute_generated_tokens'] + full['compute_generated_tokens'],
                  'assigned_shard': args.shard, 'visible_gpu': os.environ['CUDA_VISIBLE_DEVICES'],
                  'live_model_file_sha256': live_hashes, 'quality_labels_available_during_decisions': False,
                  'risk_guarantee_claimed': False,
                  'scope': 'Actual controlled four-action request including all probes and input interventions, with newly executed matched FULL; not author BF16/greedy performance or serving latency.'}
        append_jsonl(out, record)
        print(json.dumps({'asag': q['problem_id'], 'correct': score['correct'], 'wall_s': controlled['wall_ms'] / 1000,
                          'full_wall_s': full['wall_ms'] / 1000}), flush=True)
        del pair, controlled, full
    records = [json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()]
    assert len(records) == len(expected) and {r['problem_id'] for r in records} == expected
    (ROOT / f'results/online_{args.out_tag}_{args.shard}.complete.json').write_text(json.dumps({'n': len(records), 'unix': time.time()}))


def pair_order(problem_id):
    return ['full', 'asag'] if stable_seed('asag-pair-order', problem_id) % 2 else ['asag', 'full']


if __name__ == '__main__':
    main()
