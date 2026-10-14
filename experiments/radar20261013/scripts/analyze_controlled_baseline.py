"""Complete actual controlled baseline analysis; no partial-result selection."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from baseline_analysis import complete_scope, quality_cost_summary, asag_diagnostics, prefix_control
from reason_transition.core import stable_seed, grade
from risk_policy import problem_shard
from protocol_guard import sha256


def read_completed(file):
    marker = file.with_suffix('.complete.json')
    assert marker.exists(), f'Incomplete actual run: {file.name}'
    raw = file.read_bytes()
    assert raw.endswith(b'\n'), 'Incomplete trailing output record'
    return [json.loads(line) for line in raw.splitlines()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', choices=['dtsr', 'refrain', 'asag'], required=True)
    p.add_argument('--split', choices=['selection', 'calibration', 'test'], required=True)
    p.add_argument('--out-tag', required=True)
    p.add_argument('--full-tag', help='DTSR only: complete actual M1-style full reference output tag')
    p.add_argument('--full-policy-file', help='DTSR only: frozen policy plan that generated its actual FULL comparator')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    formal_path = ROOT / 'provenance/formal_protocol.json'
    formal = json.loads(formal_path.read_text())
    formal_hash = sha256(formal_path)
    protocol_path = ROOT / f'provenance/{args.baseline}_protocol.json'
    spec = json.loads(protocol_path.read_text())
    protocol_hash = sha256(protocol_path)
    assert spec['formal_protocol_sha256'] == formal_hash
    for name, digest in spec['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    freeze = json.loads((ROOT / 'provenance/data_freeze.json').read_text())
    ids = freeze['splits'][args.split]['ids']
    admission_path = ROOT / spec['admission_file']
    assert sha256(admission_path) == spec['admission_sha256']
    admission = json.loads(admission_path.read_text())
    assert admission['passed']
    model = admission['model_path']
    if args.baseline == 'refrain':
        files = [ROOT / f'results/online_{args.out_tag}_ordered.jsonl']
    else:
        files = [ROOT / f'results/online_{args.out_tag}_{shard}.jsonl' for shard in range(formal['gpu_shards'])]
    records = []
    for shard, file in enumerate(files):
        rows = read_completed(file)
        if args.baseline != 'refrain':
            assert all(r['assigned_shard'] == shard and r['visible_gpu'] == str(shard) for r in rows)
        records += rows
    method = args.baseline + '_controlled'
    complete_scope(records, ids, method, args.split, protocol_hash, formal_hash, model, formal['gpu_shards'])
    rows = {r['problem_id']: r for r in records}
    reference_files = []
    if args.baseline == 'dtsr':
        assert args.full_tag and args.full_policy_file, 'DTSR needs separately measured actual FULL and its policy plan'
        full_policy_path = Path(args.full_policy_file)
        full_policy = json.loads(full_policy_path.read_text())
        full_policy_hash = sha256(full_policy_path)
        assert full_policy['formal_protocol_sha256'] == formal_hash
        assert full_policy['methods']['full']['kind'] == 'full'
        assert full_policy['methods']['full'].get('budget', formal['max_think_tokens']) == formal['max_think_tokens']
        reference_files = [ROOT / f'results/online_{args.full_tag}_{g}.jsonl' for g in range(formal['gpu_shards'])]
        reference_rows = []
        for shard, file in enumerate(reference_files):
            for r in read_completed(file):
                if r['method'] != 'full':
                    continue
                assert r['split'] == args.split and r['formal_protocol_sha256'] == formal_hash and r['model_path'] == model
                assert r['policy_file_sha256'] == full_policy_hash and r['visible_gpu'] == str(shard)
                assert r['assigned_shard'] == shard == problem_shard(r['problem_id'], formal['gpu_shards'])
                reference_rows.append(r)
        assert len(reference_rows) == len(ids) and {r['problem_id'] for r in reference_rows} == set(ids)
        full = {r['problem_id']: r for r in reference_rows}
        timing_reference_scope = 'Separate actual full run with the same formal protocol/physical GPU/seed. Not an interleaved matched pair; schedule/thermal differences remain.'
    else:
        key = 'matched_serial_full' if args.baseline == 'refrain' else 'matched_full'
        full = {pid: {**r[key], 'seed': r['seed']} for pid, r in rows.items()}
        order_seed = 'refrain-pair-order' if args.baseline == 'refrain' else 'asag-pair-order'
        for pid, row in rows.items():
            label = args.baseline
            order = ['full', label] if stable_seed(order_seed, pid) % 2 else [label, 'full']
            assert row['paired_request_order'] == order
            assert abs(row['paired_backend_wall_ms'] - row['wall_ms'] - full[pid]['wall_ms']) < 1e-6
            if args.baseline == 'refrain':
                assert row['visible_gpus'] == '0,1'
        timing_reference_scope = 'Newly executed same-worker/GPU matched FULL; order predeclared by independent ID hash.'
    for pid in ids:
        assert rows[pid]['seed'] == stable_seed(formal['seed'], pid, 0)
        prefix_control(rows[pid], full[pid], method)
    # Read Gold only once complete expected outputs have been proven present.
    data = ROOT / f'data/{args.split}.jsonl'
    assert sha256(data) == freeze['splits'][args.split]['sha256']
    questions = {q['problem_id']: q for q in [json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()]}
    for pid in ids:
        assert grade(rows[pid]['answer']['text'], questions[pid]['gold'])['correct'] == rows[pid]['correct']
        assert grade(full[pid]['answer']['text'], questions[pid]['gold'])['correct'] == full[pid]['correct']
    details = {}
    if args.baseline == 'asag':
        details = asag_diagnostics(rows, spec['entropy_change_threshold'])
    elif args.baseline == 'refrain':
        from refrain_adapter import SlidingWindowUCB
        bandit = SlidingWindowUCB(spec['arms'], spec['window'], spec['exploration'], spec['length_penalty'])
        ordered_ids = [json.loads(s)['problem_id'] for s in data.read_text(encoding='utf-8').splitlines()]
        assert [r['problem_id'] for r in records] == ordered_ids
        for index, r in enumerate(records):
            assert r['bandit_reward_uses_gold'] is False and r['risk_guarantee_claimed'] is False
            assert r['stream_index'] == index and r['chosen_threshold'] == bandit.choose()
            assert r['compute_generated_tokens'] == r['trace']['tokens'] + r['answer']['tokens']
            assert bandit.update(r['chosen_threshold'], r['answer']['answer_score'], r['delivered_tokens']) == r['bandit_feedback']
            assert bandit.snapshot() == r['bandit_state_after']
        details = {'ordered_bandit_replay_passed': True, 'ordinary_iid_tests_applied': False}
    elif args.baseline == 'dtsr':
        decisions = [d for r in records for d in r['trace']['decisions']]
        for r in records:
            assert r['compute_generated_tokens'] == r['trace']['tokens'] + r['answer']['tokens'] + r['trace']['rating_generated_tokens']
            assert r['trace']['rating_generated_tokens'] == sum(d['rating_response']['tokens'] for d in r['trace']['decisions'])
        details = {'rating_calls': len(decisions), 'unparsed_rating_calls': sum(d['rating_response']['rating'] is None for d in decisions),
                   'rating_100_calls': sum(d['rating_response']['rating'] == 100 for d in decisions)}
    report = {'baseline': method, 'split': args.split, 'formal_protocol_sha256': formal_hash,
              'protocol_sha256': protocol_hash, 'statistics': quality_cost_summary(rows, full, args.baseline == 'refrain'),
              'timing_reference_scope': timing_reference_scope, 'method_diagnostics': details,
              'complete_scope_and_prefix_and_regrade_passed': True, 'independent_risk_certification_performed': False,
              'scope': 'Complete actual controlled method/default operating point only; selection is exploratory, calibration is not itself certification, and no author/serving performance is inferred.',
              'raw_source_sha256': {f.relative_to(ROOT).as_posix(): sha256(f) for f in files + reference_files},
              'analysis_source_sha256': {n: sha256(ROOT / n) for n in ['baseline_analysis.py', 'scripts/analyze_controlled_baseline.py']}}
    output = Path(args.output)
    assert not output.exists(), 'Preserve prior completed analyses'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['raw_source_sha256', 'method_diagnostics']}, indent=2))


if __name__ == '__main__':
    main()
