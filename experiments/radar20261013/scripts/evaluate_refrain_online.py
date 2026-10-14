"""One ordered adaptive stream, using each problem's frozen physical GPU.

Two engines remain resident, but requests run serially. Splitting the bandit
across GPU workers would alter the algorithm. Gold is read only after updating
the unsupervised bandit; its reward never uses quality labels.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from reason_transition.core import Engine, stable_seed, public, grade, append_jsonl
from refrain_adapter import MiniLMEncoder, SlidingWindowUCB, decode_refrain, answer_refrain
from protocol_guard import validate_formal, sha256
from risk_policy import problem_shard
from run_native_pilot import verify_live_model

SOURCES = ['refrain_adapter.py', 'scripts/evaluate_refrain_online.py', 'reason_transition/core.py',
           'reason_transition/text_decoder.py', 'risk_policy.py', 'scripts/run_native_pilot.py']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--encoder', required=True)
    p.add_argument('--protocol-file', required=True)
    p.add_argument('--split', choices=['selection', 'calibration', 'test'], required=True)
    p.add_argument('--out-tag', required=True)
    p.add_argument('--n', type=int)
    args = p.parse_args()
    assert os.environ.get('CUDA_VISIBLE_DEVICES') == '0,1', 'Use the two frozen physical GPUs in order'
    formal, formal_hash = validate_formal(ROOT, args.model)
    assert formal['gpu_shards'] == 2
    protocol_path = Path(args.protocol_file)
    protocol_hash = sha256(protocol_path)
    spec = json.loads(protocol_path.read_text())
    assert spec['formal_protocol_sha256'] == formal_hash
    assert spec['method_scope'] == 'REFRAIN_controlled_global_ordered_stream'
    assert set(spec['source_sha256']) == set(SOURCES)
    for name, digest in spec['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    encoder_manifest = ROOT / spec['encoder_manifest_file']
    assert sha256(encoder_manifest) == spec['encoder_manifest_sha256']
    admission_path = ROOT / spec['admission_file']
    admission = json.loads(admission_path.read_text())
    assert sha256(admission_path) == spec['admission_sha256'] and admission['passed']
    assert admission['model_path'] == args.model and admission['package_versions'] == formal['package_versions']
    for name, digest in admission['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    if args.split == 'test':
        final = json.loads((ROOT / 'provenance/refrain_final_test_freeze.json').read_text())
        assert args.n is None and final['protocol_sha256'] == protocol_hash
        assert final['actual_test_generation_records_at_freeze'] == 0
        assert final['data_freeze_sha256'] == sha256(ROOT / 'provenance/data_freeze.json')
    freeze = json.loads((ROOT / 'provenance/data_freeze.json').read_text())
    source = ROOT / f'data/{args.split}.jsonl'
    assert sha256(source) == freeze['splits'][args.split]['sha256']
    rows = [json.loads(s) for s in source.read_text(encoding='utf-8').splitlines()]
    if args.n is not None:
        assert args.n > 0
        rows = rows[:args.n]
    assert len({q['problem_id'] for q in rows}) == len(rows)
    out = ROOT / f'results/online_{args.out_tag}_ordered.jsonl'
    previous = [json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()] if out.exists() else []
    assert len(previous) <= len(rows)
    bandit = SlidingWindowUCB(spec['arms'], spec['window'], spec['exploration'], spec['length_penalty'])
    for index, record in enumerate(previous):
        assert record['problem_id'] == rows[index]['problem_id'] and record['stream_index'] == index
        assert record['protocol_sha256'] == protocol_hash and record['formal_protocol_sha256'] == formal_hash
        assert record['model_path'] == args.model and record['split'] == args.split
        assert record['assigned_shard'] == problem_shard(record['problem_id'], 2)
        assert record['chosen_threshold'] == bandit.choose()
        expected_order = ['full', 'refrain'] if stable_seed('refrain-pair-order', record['problem_id']) % 2 else ['refrain', 'full']
        assert record['paired_request_order'] == expected_order
        assert record['trace']['ids'] == record['matched_serial_full']['trace']['ids'][:record['trace']['tokens']]
        replay = bandit.update(record['chosen_threshold'], record['answer']['answer_score'], record['delivered_tokens'])
        assert replay == record['bandit_feedback'] and bandit.snapshot() == record['bandit_state_after']
    # A fresh live identity check rather than trusting the cached admission marker.
    native = json.loads((ROOT / 'provenance/native_pilot_protocol.json').read_text())
    live_hashes = verify_live_model(args.model, native)
    import torch
    engines = {}
    for device in range(2):
        with torch.cuda.device(device):
            engine = Engine(args.model)
            for i in range(2):
                warm = engine.decode(engine.prompt('What is 2 plus 2?'), 16, stable_seed('refrain-warm', device, i))
                del warm
            engines[device] = engine
    encoder = MiniLMEncoder(args.encoder, encoder_manifest)
    for index, q in enumerate(rows[len(previous):], start=len(previous)):
        assert sha256(protocol_path) == protocol_hash and validate_formal(ROOT, args.model)[1] == formal_hash
        for name, digest in spec['source_sha256'].items():
            assert sha256(ROOT / name) == digest
        device = problem_shard(q['problem_id'], 2)
        engine = engines[device]
        seed = stable_seed(formal['seed'], q['problem_id'], 0)
        with torch.cuda.device(device):
            # Serial FULL has the same resident models/physical GPU and global
            # schedule. Compare latency here, not to the two-worker M1 timing.
            order = ['full', 'refrain'] if stable_seed('refrain-pair-order', q['problem_id']) % 2 else ['refrain', 'full']
            pair = {}
            for method in order:
                torch.cuda.reset_peak_memory_stats(device)
                torch.cuda.synchronize(device)
                started = time.perf_counter()
                prompt = engine.prompt(q['question'])
                if method == 'refrain':
                    threshold = bandit.choose()
                    trace = decode_refrain(engine, encoder, prompt, formal['max_think_tokens'], seed, threshold)
                    answer = answer_refrain(engine, prompt + trace['ids'], seed,
                                           natural_closed=trace['stop_reason'] == 'natural_end',
                                           initial=(trace['cache'], trace['logits']))
                    feedback = bandit.update(threshold, answer['answer_score'], trace['tokens'] + answer['tokens'])
                else:
                    trace = engine.decode(prompt, formal['max_think_tokens'], seed, until='think', capture=False)
                    answer = engine.answer(prompt + trace['ids'], seed,
                                           natural_closed=trace['stop_reason'] == 'natural_end',
                                           initial=(trace['cache'], trace['logits']))
                torch.cuda.synchronize(device)
                pair[method] = {'trace': public(trace), 'answer': public(answer),
                                'wall_ms': 1000 * (time.perf_counter() - started),
                                'peak_allocated_bytes': torch.cuda.max_memory_allocated(device)}
                del trace, answer  # Release the live cache before the paired request.
            rf, full = pair['refrain'], pair['full']
            assert rf['trace']['ids'] == full['trace']['ids'][:rf['trace']['tokens']], 'Paired solver prefix changed'
            # Neither method's Gold is scored before the REFRAIN bandit update.
            score = grade(rf['answer']['text'], q['gold'])
            full_score = grade(full['answer']['text'], q['gold'])
            delivered = rf['trace']['tokens'] + rf['answer']['tokens']
            record = {'problem_id': q['problem_id'], 'stream_index': index, 'method': 'refrain_controlled',
                      'split': args.split, 'seed': seed, 'model_path': args.model,
                      'formal_protocol_sha256': formal_hash, 'protocol_sha256': protocol_hash,
                      'chosen_threshold': threshold, 'bandit_feedback': feedback, 'bandit_state_after': bandit.snapshot(),
                      'trace': rf['trace'], 'answer': rf['answer'], 'grade': score, 'correct': score['correct'],
                      'wall_ms': rf['wall_ms'], 'compute_generated_tokens': delivered, 'delivered_tokens': delivered,
                      'paired_backend_wall_ms': rf['wall_ms'] + full['wall_ms'],
                      'paired_compute_generated_tokens': delivered + full['trace']['tokens'] + full['answer']['tokens'],
                      'assigned_shard': device, 'visible_gpus': os.environ['CUDA_VISIBLE_DEVICES'],
                      'actual_device': str(engine.device), 'peak_allocated_bytes': rf['peak_allocated_bytes'],
                      'matched_serial_full': {**full, 'grade': full_score, 'correct': full_score['correct']},
                      'paired_request_order': order, 'same_input_same_seed_thinking_prefix': True,
                      'encoder_revision': encoder.revision, 'live_model_file_sha256': live_hashes,
                      'quality_labels_available_during_decisions': False, 'bandit_reward_uses_gold': False,
                      'risk_guarantee_claimed': False,
                      'scope': 'Actual serial backend request including CPU encoder and bandit, with a newly executed matched serial FULL; ordered adaptation is not an exchangeable per-problem risk family or serving experiment.'}
            append_jsonl(out, record)
            print(json.dumps({'refrain': q['problem_id'], 'threshold': threshold, 'checks': len(rf['trace']['decisions']),
                              'correct': score['correct'], 'wall_s': rf['wall_ms'] / 1000,
                              'matched_full_wall_s': full['wall_ms'] / 1000}), flush=True)
            del pair, rf, full
    records = [json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()]
    assert len(records) == len(rows) and [r['problem_id'] for r in records] == [q['problem_id'] for q in rows]
    (ROOT / f'results/online_{args.out_tag}_ordered.complete.json').write_text(json.dumps({'n': len(records), 'unix': time.time()}))


if __name__ == '__main__':
    main()
