"""CPU high-level countermodels, not a claim about Qwen's internal algorithm.

Three different stories can generate the same g(new_x) signature: a stale stage,
incorrect lookup despite computing f(new_x), and a recent-number shortcut.
Only compatibility with saved output strings is counted; no semantic events or
neural mechanisms are assigned from matching a number.
"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
PRIOR = ROOT.parent / 'direction_selection_20261105'
PARSER = ROOT.parent / 'next_design_20261105/frozen_answer_extractor.py'


def evaluate(node, environment):
    if isinstance(node, ast.Expression): return evaluate(node.body, environment)
    if isinstance(node, ast.Constant) and type(node.value) is int: return node.value
    if isinstance(node, ast.Name): return environment[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -evaluate(node.operand, environment)
    if isinstance(node, ast.BinOp):
        a, b = evaluate(node.left, environment), evaluate(node.right, environment)
        if isinstance(node.op, ast.Add): return a + b
        if isinstance(node.op, ast.Sub): return a - b
        if isinstance(node.op, ast.Mult): return a * b
        if isinstance(node.op, ast.FloorDiv):
            assert b and a % b == 0
            return a // b
    raise ValueError(ast.dump(node))


def main():
    output = ROOT / 'observational_signature_control.json'
    assert not output.exists(), 'Preserve previous evidence'
    assert hashlib.sha256(PARSER.read_bytes()).hexdigest() == 'c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed'
    spec = importlib.util.spec_from_file_location('frozen_text_extractor', PARSER)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    cases = json.loads((PRIOR / 'proposed_p0_cases.json').read_text(encoding='utf-8'))['cases']
    rows = []
    for case in cases:
        assignments = re.findall(r'x\s*=\s*(-?\d+)', case['revision'])
        if assignments:
            revised_x = int(assignments[-1])
        else:
            revised_x = int(re.findall(r'-?\d+', case['revision'])[-1])
        definitions = {d['variable']: d['expression'] for d in case['definitions']}
        correct_intermediate = evaluate(ast.parse(definitions['y'], mode='eval'), {'x': revised_x})
        final_rule = ast.parse(definitions['z'], mode='eval')
        assert {n.id for n in ast.walk(final_rule) if isinstance(n, ast.Name)} == {'y'}
        stale_stage = evaluate(final_rule, {'y': revised_x})
        # This countermodel really computes the intermediate, then reads the wrong slot.
        binding_registers = {'x': revised_x, 'y_computed': correct_intermediate, 'lookup_y': revised_x}
        wrong_lookup = evaluate(final_rule, {'y': binding_registers['lookup_y']})
        recent_number = int(re.findall(r'-?\d+', case['revision'])[-1])
        text_shortcut = evaluate(final_rule, {'y': recent_number})
        assert stale_stage == wrong_lookup == text_shortcut
        actual = json.loads((PRIOR / 'p0_qwen3_4b_fp16_01' / (case['case_id'] + '.json')).read_text(encoding='utf-8'))
        matches = []
        for arm, row in actual['arms'].items():
            text = row['greedy']['text']; parsed = module.extract_answer(text)['value']
            if parsed == stale_stage:
                matches.append({'arm': arm, 'text': text, 'parsed_value': parsed})
        rows.append({'case_id': case['case_id'], 'new_root_from_visible_revision': revised_x,
                     'intermediate_computed_by_binding_countermodel': correct_intermediate,
                     'g_new_x_signature': stale_stage, 'three_countermodels_agree': True,
                     'compatible_saved_outputs': matches})
    report = {'scope': 'Constructive observational ambiguity of three high-level programs; not neural identification or new task performance',
              'passed': True, 'case_count': len(rows), 'countermodels_agree_cases': len(rows),
              'compatible_saved_output_count': sum(len(r['compatible_saved_outputs']) for r in rows),
              'correctness_or_mechanism_assigned_from_match': False, 'gpu_used': False,
              'limitation': 'The countermodels cover one signature, not all 80 outputs. A model may combine several mechanisms.',
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': rows}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['passed', 'case_count', 'countermodels_agree_cases', 'compatible_saved_output_count', 'gpu_used']}))


if __name__ == '__main__': main()
