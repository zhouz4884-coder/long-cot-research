"""Prepare exact synthetic topology controls, without model calls or GPU work.

Twelve states = two programs x two support placements x E/C/W. These are small
mechanism fixtures, not twelve independent natural questions or performance data.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


PROGRAMS = [
    {'id': 'T1', 'definitions': [('r', '6*4'), ('x', '27-9'), ('y', '3*x+2'), ('z', 'y+r')], 'offset': 1},
    {'id': 'T2', 'definitions': [('r', '13+4'), ('x', '54//6'), ('y', 'x*x'), ('z', 'y-r')], 'offset': -1},
]


def evaluate(node, values):
    if isinstance(node, ast.Expression): return evaluate(node.body, values)
    if isinstance(node, ast.Constant) and type(node.value) is int: return node.value
    if isinstance(node, ast.Name): return values[node.id]
    if isinstance(node, ast.BinOp):
        a, b = evaluate(node.left, values), evaluate(node.right, values)
        if isinstance(node.op, ast.Add): return a + b
        if isinstance(node.op, ast.Sub): return a - b
        if isinstance(node.op, ast.Mult): return a * b
        if isinstance(node.op, ast.FloorDiv):
            assert b and a % b == 0
            return a // b
    raise ValueError(ast.dump(node))


def values_for(definitions, root_override=None):
    result = {}
    for name, expression in definitions:
        result[name] = root_override if name == 'x' and root_override is not None else evaluate(ast.parse(expression, mode='eval'), result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Preserve frozen design'
    cases = []
    for program in PROGRAMS:
        definitions = program['definitions']
        correct = values_for(definitions)
        graph = {name: sorted({n.id for n in ast.walk(ast.parse(expression, mode='eval')) if isinstance(n, ast.Name)})
                 for name, expression in definitions}
        closure = {'x'}
        while True:
            expanded = closure | {name for name, parents in graph.items() if closure.intersection(parents)}
            if expanded == closure: break
            closure = expanded
        assert closure == {'x', 'y', 'z'} and graph['r'] == []
        for placement in ['support_before_fault', 'support_after_fault']:
            order = ['r', 'x', 'y', 'z'] if placement == 'support_before_fault' else ['x', 'y', 'z', 'r']
            for group in ['E', 'C', 'W']:
                old_x = correct['x'] + program['offset'] if group == 'E' else correct['x']
                revised_x = correct['x'] + program['offset'] if group == 'W' else correct['x']
                old = values_for(definitions, old_x)
                revised = values_for(definitions, revised_x)
                assignments = [{'variable': name, 'text': f'{name}={old[name]}；'} for name in order]
                question = '按整数算术，依次定义 ' + '，'.join(f'{name}={expression}' for name, expression in definitions) + '。求 z。'
                revision = f'复核记录：x={revised_x}。其他变量须按题目原始定义处理。'
                cases.append({
                    'case_id': program['id'] + '_' + placement + '_' + group,
                    'visible': {'question': question, 'old_assignment_clauses': assignments, 'revision': revision},
                    'evaluator_only': {'program_id': program['id'], 'placement': placement, 'group': group,
                        'definitions': definitions, 'dependency_graph': graph,
                        'required_final_value': correct['z'], 'old_final_value': old['z'],
                        'revision_implied_final_value': revised['z'], 'old_x_valid': old_x == correct['x'],
                        'revised_x_valid': revised_x == correct['x'],
                        'dependency_closure_for_hypothetical_x_change': sorted(closure),
                        'independent_shared_variables': ['r'],
                        'actual_root_value_changed': old_x != revised_x},
                    'fixed_mask_rules': {'whole_B': order, 'closure': [v for v in order if v in closure],
                        'same_clause_budget_sham': [v for v in order if v != 'y'],
                        'sham_retains': 'y, a dependent value; not a semantic equivalent'},
                })
    assert len(cases) == 12
    for c in cases:
        assert c['evaluator_only']['required_final_value'] == values_for(c['evaluator_only']['definitions'])['z']
        assert len(c['fixed_mask_rules']['closure']) == len(c['fixed_mask_rules']['same_clause_budget_sham']) == 3
        assert set(c['fixed_mask_rules']['closure']).isdisjoint({'r'})
    report = {
        'scope': 'CPU-prepared design fixtures; no model generations, scores or online detector',
        'unique_programs': 2, 'paired_support_placements': 2, 'groups_per_pair': ['E', 'C', 'W'],
        'case_count': 12,
        'rendering_contract': {'whitelist': ['visible.question', 'visible.old_assignment_clauses[].text', 'visible.revision'],
            'all_original_definitions_always_visible': True,
            'tokenize_each_B_clause_separately': True,
            'slot_width': 'Global maximum clause token length across these 12 states plus one; freeze with verified tokenizer before any model outputs.',
            'padding': 'Append the same fixed neutral newline token until every clause slot has the global slot width.',
            'masking': 'Mask full slots, including padding. Closure and sham must have exactly equal masked-token counts.',
            'position_ids': 'Preserve full original positions within each paired state; no compaction.',
            'late_early': 'Same tokens and readout; fresh prefill masks the same slots from the beginning.',
            'gold_is_not_a_trigger': True},
        'limitations': ['Same-budget sham matches token count only, not position/age or logical content.',
            'Two logical programs are not twelve independent natural problems.',
            'All edits are forced diagnostic interventions; C/W are stress controls, not a deployed policy.',
            'After-fault independent r is logically independent but its old KV may depend on the bad prefix.',
            'No cache slots are freed; no memory-saving claim.',
            'Exact AST dependency and local validity are privileged offline annotations, not a validated natural-language extractor.'],
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': cases,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'case_count': len(cases), 'unique_programs': 2, 'all_oracles_verified': True, 'gpu_used': False,
                      'output_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__': main()
