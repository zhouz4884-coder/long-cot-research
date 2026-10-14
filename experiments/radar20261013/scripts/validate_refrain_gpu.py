"""Finite live solver/cache/answer-identity admission, after measured jobs exit."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from reason_transition.core import Engine, stable_seed
from refrain_adapter import MiniLMEncoder, Discriminator, decode_refrain, answer_refrain
from protocol_guard import package_snapshot, sha256
from run_native_pilot import verify_live_model


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--encoder', required=True)
    p.add_argument('--encoder-manifest', required=True)
    args = p.parse_args()
    native = json.loads((ROOT / 'provenance/native_pilot_protocol.json').read_text())
    hashes = verify_live_model(args.model, native)
    encoder = MiniLMEncoder(args.encoder, args.encoder_manifest)
    engine = Engine(args.model)
    questions = [json.loads(s) for s in (ROOT / 'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:3]
    checks = []
    for question, limit in zip(questions, [128, 512, 2048]):
        seed = stable_seed('refrain-admission', question['problem_id'])
        prompt = engine.prompt(question['question'])
        state = engine.decode(prompt, limit, seed, until='think')
        parent = copy.deepcopy(state['cache'])
        discriminator = Discriminator(encoder, .8)
        discriminator.observe(state['text'])
        unchanged = all(engine.torch.equal(a.keys, b.keys) and engine.torch.equal(a.values, b.values)
                        for a, b in zip(parent.layers, state['cache'].layers))
        original = engine.answer(prompt + state['ids'], seed, natural_closed=state['stop_reason'] == 'natural_end',
                                 initial=(state['cache'], state['logits']))
        scored = answer_refrain(engine, prompt + state['ids'], seed,
                                natural_closed=state['stop_reason'] == 'natural_end',
                                initial=(parent, state['logits']))
        controlled = decode_refrain(engine, encoder, prompt, limit, seed, .8)
        check = {'problem_id': question['problem_id'], 'requested_prefix_tokens': limit,
                 'actual_prefix_tokens': state['tokens'], 'all_parent_kv_unchanged_after_encoder': unchanged,
                 'actual_controlled_think_tokens': controlled['tokens'],
                 'actual_controlled_stop_reason': controlled['stop_reason'],
                 'controlled_think_ids_match_common_prefix': controlled['ids'] == state['ids'][:controlled['tokens']],
                 'actual_controlled_checks': len(controlled['decisions']),
                 'answer_token_ids_equal_common_reader': original['ids'] == scored['ids'],
                 'answer_context_equal_common_reader': original['answer_prefix_hash'] == scored['answer_prefix_hash'],
                 'raw_answer_score': scored['answer_score'],
                 'score_token_indices': scored['answer_score_token_indices'],
                 'boundary_overlap_indices': scored['answer_boundary_overlap_indices']}
        assert unchanged and check['answer_token_ids_equal_common_reader'] and check['answer_context_equal_common_reader']
        assert check['controlled_think_ids_match_common_prefix']
        checks.append(check)
        print(json.dumps(check), flush=True)
        del state, parent, original, scored, controlled
    report = {'passed': True, 'model_path': args.model, 'model_revision': native['model_revision'],
              'live_model_file_sha256': hashes, 'encoder_revision': encoder.revision,
              'encoder_manifest_sha256': sha256(args.encoder_manifest), 'package_versions': package_snapshot(),
              'checks': checks, 'source_sha256': {name: sha256(ROOT / name) for name in
              ['refrain_adapter.py', 'scripts/validate_refrain_gpu.py', 'reason_transition/core.py',
               'reason_transition/text_decoder.py', 'scripts/run_native_pilot.py']},
              'scope': 'Three actual-prefix cache and common-answer identity controls only; no task accuracy, risk certificate or latency benefit.'}
    assert any(c['score_token_indices'] for c in checks), 'No valid boxed score in finite admission'
    (ROOT / 'provenance/refrain_finite_gpu_admission.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
