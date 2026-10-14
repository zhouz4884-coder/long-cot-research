"""Actual pinned CPU encoder checks; neither GPU nor task success is claimed."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from refrain_adapter import MiniLMEncoder, Discriminator


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--encoder', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    import numpy as np
    import torch
    torch.set_num_threads(1)
    encoder = MiniLMEncoder(args.encoder, args.manifest)
    texts = ['The answer is seven.', 'The answer is seven.',
             'Wait, the answer is seven.', 'An unrelated bird is flying.']
    started = time.perf_counter()
    vectors = encoder.encode(texts)
    batch_ms = 1000 * (time.perf_counter() - started)
    alone = encoder.encode([texts[0]])[0]
    padding_error = float(np.max(np.abs(alone - vectors[0])))
    long = 'number ' * 1000
    clipped = encoder.tokenizer(long, truncation=True, max_length=256)
    d = Discriminator(encoder, .8)
    first = d.observe('Wait, the answer is seven.')
    next_step = d.observe('Wait, the answer is seven.')
    checks = {'shape_384': vectors.shape == (4, 384), 'finite': bool(np.isfinite(vectors).all()),
              'normalized': bool(np.allclose(np.linalg.norm(vectors, axis=1), 1., atol=1e-6)),
              'identical_similarity': float(vectors[0] @ vectors[1]),
              'reflective_similarity': float(vectors[0] @ vectors[2]),
              'unrelated_similarity': float(vectors[0] @ vectors[3]),
              'batch_padding_max_abs_error': padding_error, 'actual_long_input_tokens': len(clipped['input_ids']),
              'current_cue_does_not_stop': first['action'] == 'CONTINUE',
              'prior_cue_and_redundancy_stop': next_step['action'] == 'STOP',
              'cpu_device': str(encoder.model.device), 'model_dtype': str(next(encoder.model.parameters()).dtype)}
    passed = (checks['shape_384'] and checks['finite'] and checks['normalized']
              and checks['identical_similarity'] > .99999 and padding_error < 1e-5
              and checks['actual_long_input_tokens'] == 256 and checks['current_cue_does_not_stop']
              and checks['prior_cue_and_redundancy_stop'] and checks['cpu_device'] == 'cpu')
    report = {'passed': bool(passed), 'encoder_revision': encoder.revision,
              'encoder_loading_info': encoder.loading_info,
              'manifest_sha256': hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
              'package_versions': {n: importlib.metadata.version(n) for n in ['torch', 'transformers', 'numpy']},
              'source_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                for n in ['refrain_adapter.py', 'scripts/validate_refrain_encoder.py']},
              'checks': checks, 'four_sentence_batch_wall_ms': batch_ms,
              'scope': 'Finite CPU FP32 encoder/protocol checks. No model-task accuracy, GPU cache safety or online latency gain.'}
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    assert passed


if __name__ == '__main__':
    main()
