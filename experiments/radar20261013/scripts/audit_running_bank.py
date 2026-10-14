"""Read-only completed-record snapshot audit; never claims a full bank is done."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol_guard import validate_formal, sha256
from risk_policy import problem_shard
from reason_transition.core import digest_ids, stable_seed


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--split', choices=['development', 'selection'], required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    formal, formal_hash = validate_formal(ROOT)
    from transformers import AutoTokenizer
    model = formal['admitted_model_paths'][0]
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    data = ROOT / f'data/{args.split}.jsonl'
    freeze = json.loads((ROOT / 'provenance/data_freeze.json').read_text())
    assert sha256(data) == freeze['splits'][args.split]['sha256']
    questions = {q['problem_id']: q for q in [json.loads(s) for s in data.read_text(encoding='utf-8').splitlines()]}
    seen = set()
    summaries = []
    total_points = 0
    for shard in range(formal['gpu_shards']):
        path = ROOT / f'results/bank_{args.split}_{shard}.jsonl'
        raw = path.read_bytes() if path.exists() else b''
        lines = raw.splitlines(keepends=True)
        complete = [line for line in lines if line.endswith(b'\n')]
        partial_tail = bool(lines and not lines[-1].endswith(b'\n'))
        rows = [json.loads(line) for line in complete]
        points = 0
        for row in rows:
            pid = row['problem_id']
            assert pid in questions and pid not in seen
            seen.add(pid)
            assert row['split'] == args.split and row['model_path'] == model
            assert row['formal_protocol_sha256'] == formal_hash
            assert row['assigned_shard'] == shard == problem_shard(pid, formal['gpu_shards'])
            assert row['visible_gpu'] == str(shard)
            assert row['seed'] == stable_seed(formal['seed'], pid, 0)
            assert row['all_correctness_labels_computed_after_generation'] is True
            assert row['full']['reference_timing_is_uninstrumented_online_benchmark'] is False
            prompt = tokenizer.apply_chat_template([{'role': 'user', 'content': questions[pid]['question'] +
                    '\nPlease reason step by step, and put your final answer within \\boxed{}.'}],
                    tokenize=True, add_generation_prompt=True, enable_thinking=True)
            trace_ids = row['full']['trace']['ids']
            offsets = [point['offset'] for point in row['points']]
            assert offsets == sorted(set(offsets))
            for point in row['points']:
                offset = point['offset']
                assert 0 < offset <= len(trace_ids)
                assert point['prefix_hash'] == digest_ids(prompt + trace_ids[:offset])
                assert point['gold_used_for_collection'] is False
                points += 1
        expected = sum(problem_shard(pid, formal['gpu_shards']) == shard for pid in questions)
        summaries.append({'shard': shard, 'complete_records_observed': len(rows), 'expected_total_records': expected,
                          'checkpoint_prefixes_checked': points, 'partial_tail_excluded': partial_tail,
                          'snapshot_bytes_sha256': hashlib.sha256(raw).hexdigest()})
        total_points += points
    report = {'passed_for_observed_complete_records': True, 'split': args.split,
              'formal_protocol_sha256': formal_hash, 'complete_records_observed': len(seen),
              'expected_total_records': len(questions), 'checkpoint_prefixes_checked': total_points,
              'shards': summaries, 'full_bank_completion_claimed': False,
              'source_sha256': sha256(Path(__file__)),
              'scope': 'Snapshot of newline-complete records only: source/data binding, ID/GPU routing, seed, timing-proxy and exact checkpoint prefixes. No partial quality estimate, online speed, training, calibration or blind-test success.'}
    output = Path(args.output)
    assert not output.exists(), 'Preserve prior snapshots; choose a new output path'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
