"""Exact legal controls for all five observed 8192 -> 16384 pilot repairs."""
from collections import Counter,deque
from fractions import Fraction
import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    # Label symmetry predicts a uniform final permutation; enumerate every
    # independently uniform draw order and left/right history to check it.
    permutation_counts=Counter()
    for order in itertools.permutations(range(7)):
        for choices in itertools.product([0,1],repeat=6):
            beads=deque([order[0]])
            for color,right in zip(order[1:],choices):
                if right:beads.append(color)
                else:beads.appendleft(color)
            permutation_counts[tuple(beads)]+=1
    assert len(permutation_counts)==math.factorial(7)
    assert set(permutation_counts.values())=={64}
    probability=Fraction(permutation_counts[tuple(range(7))],sum(permutation_counts.values()))
    assert probability==Fraction(1,5040)
    # A degree<=2012 polynomial has zero finite difference of order2013:
    # P(2013)=P(0)+D. Minimizing x^2+(x+D)^2 gives x=-D/2.
    D=sum((-1)**i*math.comb(2013,i)*2**i for i in range(1,2013))
    assert D==2**2013-2 and -D//2==1-2**2012
    oracles=json.loads((ROOT/'provenance/pilot_bounded_oracles.json').read_text())
    assert oracles['oracle_version']==2 and oracles['coin_problem']['distinct_valid_sums_under2018']==210
    assert oracles['clock_problem']['satisfying_minutes']==[69]
    assert oracles['hexagon_problem']['original_squared_sides']==['81','100','289']
    assert oracles['hexagon_problem']['exact_coordinate_hull_area']=='1155/4'
    expected={'omni/13d1e8d14ff7cfc12d52':{'answer':'210','method':'all720 legal coin-count assignments'},
              'omni/54df3d59ca31803f13eb':{'answer':'1/5040','method':'all322560 equally weighted bead histories'},
              'omni/b8197137d3c433518e43':{'answer':'1-2^2012','method':'exact order2013 binomial finite difference and convex quadratic minimization'},
              'omni/b8561fe9b6549c3bd703':{'answer':'1155/4','method':'exact triangle side/circle/antipode/hull constraints and shoelace area'},
              'omni/d0adc4d143b1e663d23c':{'answer':'11','method':'all720 possible12-hour clock times'}}
    raw={r['problem_id']:r for g in [0,1] for r in map(json.loads,(ROOT/f'results/pilot_full_{g}.jsonl').read_text(encoding='utf-8').splitlines())}
    extended={r['problem_id']:r for g in [0,1] for r in map(json.loads,(ROOT/f'results/budget_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines()) if r['budget']==16384}
    repairs={pid for pid,row in extended.items() if not raw[pid]['correct'] and row['correct']}
    regrets={pid for pid,row in extended.items() if raw[pid]['correct'] and not row['correct']}
    assert repairs==set(expected) and not regrets
    cases=[{'problem_id':pid,**control,'old_answer':raw[pid]['answer']['text'],
            'extended_answer':extended[pid]['answer']['text'],'old_thought_censored':raw[pid]['length_censored'],
            'extended_thought_censored':extended[pid]['length_censored'],
            'final_answer_supported_by_exact_control':True,'trace_semantic_correctness_proven':False}
           for pid,control in expected.items()]
    result={'scope':'Complete five-case pilot answer audit with independent finite/exact CPU controls; no learned-policy or blind-test result.',
            'repairs':len(cases),'regressions':len(regrets),'bead_histories':sum(permutation_counts.values()),
            'cases':cases,'prior_geometry_oracle_withdrawn_and_replaced':True,
            'oracle_source_sha256':hashlib.sha256((ROOT/'scripts/pilot_bounded_oracles.py').read_bytes()).hexdigest()}
    (ROOT/'results/budget_repair_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'repairs':len(cases),'regressions':len(regrets),'all_five_gold_answers_have_exact_controls':True,
                      'bead_histories':result['bead_histories']},indent=2))


if __name__=='__main__':main()
