"""Execute isolated pinned DEER confidence helpers on controlled CPU fixtures.

Vendor files are immutable. No module-level dataset/model initialization runs.
These are implementation interface findings, not learned-model or paper results.
"""
import ast
import contextlib
import copy
import hashlib
import io
import importlib.metadata
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]


def isolated(path, name, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def main():
    import torch
    torch.set_num_threads(1)
    vendor = ROOT / 'vendor/DEER'
    hf_path, qwen_path = vendor / 'vanilla_deer.py', vendor / 'vllm-deer-qwen3.py'
    hf = isolated(hf_path, 'calcu_max_probs_w_kv', {'torch': torch, 'F': torch.nn.functional, 'deepcopy': copy.deepcopy})
    qwen = isolated(qwen_path, 'calculate_average_max_prob_from_logprobs', {'torch': torch, 'math': math})
    class Tokenizer:
        def __call__(self, texts): return {'input_ids': [[1] for _ in texts]}
    class Model:
        def __init__(self, probabilities): self.values = iter(probabilities)
        def __call__(self, input_ids, past_key_values):
            chosen, probability = next(self.values)
            other = 1 - chosen
            logits = torch.zeros(1, 1, 2)
            logits[0, 0, chosen] = math.log(probability)
            logits[0, 0, other] = math.log(1 - probability)
            return {'logits': logits, 'past_key_values': past_key_values}
    hf_cases = []
    for label, values in [('one_closing_token', [(1, .9)]),
                          ('two_tokens_no_interior', [(0, .6), (1, .9)]),
                          ('three_tokens_one_interior', [(0, .6), (0, .7), (1, .9)])]:
        result = hf(Model(values), torch.tensor([[4]]), {}, Tokenizer(), 1)
        hf_cases.append({'fixture': label, 'generated_steps': len(values),
                         'returned_score': result if math.isfinite(result) else None,
                         'nonfinite_returned': not math.isfinite(result)})
    def item(probability, text): return SimpleNamespace(logprob=math.log(probability), decoded_token=text)
    qwen_cases = []
    fixtures = [('one_terminal_token', [{1: item(.9, '</think>')}]),
                ('three_tokens_including_terminal', [{3: item(.2, '{')}, {4: item(.4, 'answer')}, {1: item(.8, '</think>')}]),
                ('same_map_content_first', [{3: item(.8, '{')}, {7: item(.03, 'content'), 1: item(.96, '</think>')}]),
                ('same_map_terminal_first', [{3: item(.8, '{')}, {1: item(.96, '</think>'), 7: item(.03, 'content')}])]
    for label, values in fixtures:
        try:
            with contextlib.redirect_stdout(io.StringIO()): result = qwen(values, 'avg2')
            qwen_cases.append({'fixture': label, 'generated_steps': len(values), 'returned_score': result, 'exception_type': None})
        except Exception as e:
            qwen_cases.append({'fixture': label, 'generated_steps': len(values), 'returned_score': None, 'exception_type': type(e).__name__})
    tree = ast.parse(qwen_path.read_text(encoding='utf-8'))
    trial_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == 'SamplingParams' and any(k.arg == 'logprobs' for k in n.keywords)]
    calls = [{'line': n.lineno, 'explicit_keyword_names': [k.arg for k in n.keywords],
              'explicit_temperature': any(k.arg == 'temperature' for k in n.keywords),
              'explicit_seed': any(k.arg == 'seed' for k in n.keywords)} for n in trial_calls]
    assert hf_cases[1]['nonfinite_returned']
    assert qwen_cases[0]['exception_type'] == 'ZeroDivisionError'
    assert abs(qwen_cases[1]['returned_score'] - math.sqrt(.4 * .8)) < 1e-6
    assert qwen_cases[2]['returned_score'] != qwen_cases[3]['returned_score']
    assert calls and all(not c['explicit_temperature'] for c in calls)
    report = {'pinned_repository': 'iie-ycx/DEER', 'pinned_commit': 'c9dd19fbffa27f841cfe47502d015b63811b4d1b',
              'hf_cpu_fixtures': hf_cases, 'qwen_vllm_helper_cpu_fixtures': qwen_cases,
              'qwen_trial_sampling_call_metadata': calls,
              'package_versions': {'torch': importlib.metadata.version('torch')},
              'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                [hf_path, qwen_path, Path(__file__)]},
              'scope': 'Executed original isolated helper code on synthetic CPU fixtures; no weights/GPU, dataset quality, runtime gain, paper-theorem failure, or actual vLLM dictionary-reordering prevalence is demonstrated.',
              'required_next_checks': ['Inspect exact pinned available vLLM SamplingParams defaults before inferring trial sampling mode',
                                       'Use emitted token IDs to resolve terminal and probability identity in a declared repair',
                                       'Preserve original errors/omissions and compare author-setting/controlled-setting separately']}
    output = ROOT / 'provenance/deer_confidence_source_interface_audit.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
