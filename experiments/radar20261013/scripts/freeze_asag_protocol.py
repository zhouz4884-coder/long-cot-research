"""Bind all admitted controlled choices before any ASAG online request."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from protocol_guard import validate_formal, sha256
from evaluate_asag_online import SOURCES


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    args = p.parse_args()
    formal, formal_hash = validate_formal(ROOT, args.model)
    path = ROOT / 'provenance/asag_finite_gpu_admission.json'
    admission = json.loads(path.read_text())
    assert admission['passed'] and admission['model_path'] == args.model
    assert [c['actual_thought_prefix_tokens'] for c in admission['checks']] == [128, 8192, 16384]
    assert admission['package_versions'] == formal['package_versions']
    for name, digest in admission['source_sha256'].items():
        assert sha256(ROOT / name) == digest
    assert not list((ROOT / 'results').glob('online_asag_*.jsonl'))
    spec = {'method_scope': 'ASAG_controlled_four_action_HF', 'confidence_threshold': .95,
            'entropy_change_threshold': -.1, 'maximum_jumps': 1,
            'formal_protocol_sha256': formal_hash, 'data_freeze_sha256': sha256(ROOT / 'provenance/data_freeze.json'),
            'source_sha256': {name: sha256(ROOT / name) for name in SOURCES},
            'admission_file': 'provenance/asag_finite_gpu_admission.json', 'admission_sha256': sha256(path),
            'paper_reference': 'https://proceedings.mlr.press/v306/li26ev.html',
            'latency_reference': 'New matched FULL per problem, predeclared ID-hash pair order, same worker and GPU',
            'declared_differences': ['Common FP16 SDPA stochastic sampler and boxed reader, not author BF16/greedy',
                                     'Observed Wait included in parent prefix; temporary cloned-cache tail replay',
                                     'FP32 eager-style QK probabilities; no claim of internal SDPA matrix equality',
                                     'Mean full-vocabulary probe-step vector injected between ATPs',
                                     'At most one jump per textual limit; appendix <= off-by-one not followed',
                                     'Paraphrased jump instruction; logical thought cap includes forced jump tokens',
                                     'A STOP reuses the actual paid probe candidate; all rejected probe work counted',
                                     'Zero first entropy permits first confidence-only stop; undefined later ratio continues'],
            'risk_guarantee_claimed': False, 'actual_asag_records_at_freeze': 0}
    output = ROOT / 'provenance/asag_protocol.json'
    assert not output.exists(), 'Do not overwrite a baseline freeze'
    output.write_text(json.dumps(spec, indent=2) + '\n')
    print(json.dumps({'protocol_sha256': sha256(output), 'risk_guarantee_claimed': False}))


if __name__ == '__main__':
    main()
