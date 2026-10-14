"""Freeze the independently admitted baseline before any controlled request."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from protocol_guard import validate_formal, sha256
from evaluate_refrain_online import SOURCES


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    args = p.parse_args()
    formal, formal_hash = validate_formal(ROOT, args.model)
    path = ROOT / 'provenance/refrain_finite_gpu_admission.json'
    admission = json.loads(path.read_text())
    assert admission['passed'] and admission['model_path'] == args.model and len(admission['checks']) == 3
    assert admission['package_versions'] == formal['package_versions']
    for name, digest in admission['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    manifest = ROOT / 'provenance/refrain_encoder_manifest.json'
    assert sha256(manifest) == admission['encoder_manifest_sha256']
    assert not list((ROOT / 'results').glob('online_refrain_*.jsonl'))
    protocol = {'method_scope': 'REFRAIN_controlled_global_ordered_stream',
                'arms': [.60, .65, .70, .75, .80], 'window': 100, 'exploration': 1., 'length_penalty': .2,
                'formal_protocol_sha256': formal_hash, 'data_freeze_sha256': sha256(ROOT / 'provenance/data_freeze.json'),
                'source_sha256': {name: sha256(ROOT / name) for name in SOURCES},
                'admission_file': 'provenance/refrain_finite_gpu_admission.json', 'admission_sha256': sha256(path),
                'encoder_manifest_file': 'provenance/refrain_encoder_manifest.json', 'encoder_manifest_sha256': sha256(manifest),
                'paper_reference': 'https://aclanthology.org/2026.acl-long.1256/',
                'stream_order': 'Frozen split-file order; each problem routed to ID-hashed physical GPU; one serial global bandit',
                'initialization': 'Reset all reward windows and total length at the start of each split',
                'latency_reference': 'Newly executed FULL per problem under the same serial two-resident-engine schedule',
                'paired_request_order': 'Independent ID hash before observing either answer; no Gold scoring until REFRAIN update',
                'declared_differences': ['Qwen3-4B FP16 SDPA with common bounded think/192-token boxed finalizer',
                                         'MiniLM FP32 on CPU; encoder time included in actual request wall-clock',
                                         'Case-insensitive literal reflection phrases; explicit answer-is/should-be prior cue',
                                         'Reward normalizes length by previous completed samples mean; first penalty .0001L',
                                         'Box-boundary overlapping sampled token included in answer likelihood',
                                         'Common fixed per-problem counter sampling seeds; two resident engines, serial requests'],
                'risk_guarantee_claimed': False, 'actual_refrain_records_at_freeze': 0}
    output = ROOT / 'provenance/refrain_protocol.json'
    assert not output.exists(), 'Do not overwrite a baseline freeze'
    output.write_text(json.dumps(protocol, indent=2) + '\n')
    print(json.dumps({'protocol_sha256': sha256(output), 'risk_guarantee_claimed': False}))


if __name__ == '__main__':
    main()
