"""Complete native regrade/prefix/final-allocation audit, with two legal oracles.

Pilot only. No held-out test or calibration prompt/gold is read.
"""
import hashlib
import itertools
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reason_transition.core import grade


def main():
    analysis = json.loads((ROOT / 'results/native_pilot_analysis.json').read_text())
    native = [json.loads(line) for g in [0, 1] for line in
              (ROOT / f'results/native_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(native) == 58 and analysis['matched_thinking_prefix_controls_passed']
    for name, digest in analysis['raw_source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    questions = {q['problem_id']: q for q in [json.loads(line) for line in
                 (ROOT / 'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()]}
    by_budget = {b: {r['problem_id']: r for r in native if r['nominal_budget'] == b} for b in [8192, 16384]}
    assert all(len(rows) == 29 for rows in by_budget.values())
    regrades = []
    for row in native:
        recomputed = grade(row['native_answer_text'], questions[row['problem_id']]['gold'])
        assert recomputed['correct'] == row['correct'] and recomputed['parse_status'] == row['grade']['parse_status']
        regrades.append({'problem_id': row['problem_id'], 'budget': row['nominal_budget'], 'consistent': True})
    extension_controls = []
    for pid in sorted(by_budget[8192]):
        low, high = by_budget[8192][pid], by_budget[16384][pid]
        shared = min(len(low['trace']['ids']), len(high['trace']['ids']))
        same = low['seed'] == high['seed'] and low['trace']['ids'][:shared] == high['trace']['ids'][:shared]
        assert same
        extension_controls.append({'problem_id': pid, 'shared_total_generated_tokens': shared, 'same': same})
    truncated_finals = []
    for row in native:
        if row['thinking_closed'] and row['grade']['parse_status'] != 'ok':
            high = by_budget[16384][row['problem_id']]
            truncated_finals.append({'problem_id': row['problem_id'], 'budget': row['nominal_budget'],
                                    'thinking_tokens': row['thinking_tokens'], 'actual_post_close_tokens': row['native_answer_tokens'],
                                    'total_cap': row['total_budget'], 'post_close_capacity': row['total_budget'] - row['thinking_tokens'],
                                    'native_stop_reason': row['trace']['stop_reason'],
                                    'same_trace_extended_16k_correct': high['correct'],
                                    'extended_total_tokens': high['total_tokens'],
                                    'observed_failure': 'Closed thinking then capped before a complete final answer. No retrospective regrade of partial thought.'})
    # Divisor triples: direct ordered enumeration and an independent stars-bars count.
    divisors = [n for n in range(1, 361) if 360 % n == 0]
    count = sum(360 % (a * b * c) == 0 for a, b, c in itertools.product(divisors, repeat=3))
    from math import comb
    stars_bars = comb(6, 3) * comb(5, 3) * comb(4, 3)
    assert count == stars_bars == 800
    assert questions['omni/02545ce568924ace2f79']['gold'] == '800'
    # Orthic triangle: all feet and projections in symbolic generic coordinates.
    from sympy import symbols, Matrix, simplify, factor
    u, v = symbols('u v', real=True)
    A, B, C = Matrix([0, 0]), Matrix([1, 0]), Matrix([u, v])
    def foot(point, left, right):
        direction = right - left
        return left + direction * ((point - left).dot(direction) / direction.dot(direction))
    D, E, F = foot(A, B, C), foot(B, C, A), foot(C, A, B)
    H = Matrix([u, u * (1 - u) / v])
    P, Q = foot(A, E, F), foot(H, E, F)
    R = 2 * H - Q
    cross = lambda a, b: a[0] * b[1] - a[1] * b[0]
    dp_identity = factor(simplify(cross(D - P, R - P)))
    assert dp_identity == 0 and all(simplify(x) == 0 for x in R - H + Q - H)
    assert questions['omni/13bd1b66302cc02ba173']['gold'] == '1'
    oracle = {'divisor_triples': {'divisors': len(divisors), 'ordered_assignments_enumerated': len(divisors)**3,
                                'brute_count': count, 'stars_bars_count': stars_bars},
              'orthic_triangle': {'A': '[0,0]', 'B': '[1,0]', 'C': '[u,v]',
                                  'H': str(H), 'R_definition': '2H-Q', 'cross_DP_RP_identity': str(dp_identity),
                                  'HQ_equals_HR': True,
                                  'domain': 'Given nondegenerate acute scalene triangle and the stated unique intersection/projections; v nonzero and defined foot denominators. This is a symbolic incidence proof under these premises.'}}
    native_gains = {pid for pid in by_budget[8192] if not by_budget[8192][pid]['correct'] and by_budget[16384][pid]['correct']}
    forced_by_budget = {8192: {}, 16384: {}}
    for g in [0, 1]:
        for line in (ROOT / f'results/pilot_full_{g}.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r['problem_id'] in by_budget[8192]: forced_by_budget[8192][r['problem_id']] = r
        for line in (ROOT / f'results/budget_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r['budget'] == 16384: forced_by_budget[16384][r['problem_id']] = r
    forced_gains = {pid for pid in by_budget[8192] if not forced_by_budget[8192][pid]['correct'] and forced_by_budget[16384][pid]['correct']}
    report = {'passed': True, 'native_regraded_requests': len(regrades), 'whole_generation_extension_controls': extension_controls,
              'closed_but_truncated_finals': truncated_finals, 'independent_exact_oracles': oracle,
              'native_budget_gains': sorted(native_gains), 'forced_budget_gains': sorted(forced_gains),
              'gain_overlap': sorted(native_gains & forced_gains),
              'native_gains_already_correct_under_forced8192': sorted(pid for pid in native_gains if forced_by_budget[8192][pid]['correct']),
              'native16384_missing_final_but_forced_correct': sorted(pid for pid in by_budget[8192]
                  if not by_budget[16384][pid]['correct'] and forced_by_budget[16384][pid]['correct']),
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'native_analysis_sha256': hashlib.sha256((ROOT / 'results/native_pilot_analysis.json').read_bytes()).hexdigest(),
              'scope': 'Complete diagnostic pilot and exact math controls only; observed censoring/operational readout differences, not a cue-only causal estimate, cognitive-state proof or risk certificate.'}
    (ROOT / 'results/native_readout_mechanism_audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: val for k, val in report.items() if k != 'whole_generation_extension_controls'}, indent=2))


if __name__ == '__main__':
    main()
