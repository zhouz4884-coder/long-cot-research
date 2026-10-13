"""Exact, legal small task oracles for pilot grading/data validity; CPU only."""
import itertools,json,math
from fractions import Fraction
from pathlib import Path
from sympy import sqrt,simplify

ROOT=Path(__file__).resolve().parents[1]
coin_values=[math.factorial(n) for n in range(1,7)]
sums={sum(n*v for n,v in zip(counts,coin_values)) for counts in itertools.product(*[range(1,n+1) for n in range(1,7)])}
coin_answer=sum(0<value<2018 for value in sums)
assert coin_answer==210

def digit_sum(t):
    t%=720;hour=t//60 or 12;minute=t%60
    return sum(map(int,f'{hour:02d}{minute:02d}'))
times=[t for t in range(720) if digit_sum(t-19)==digit_sum(t)-2]
future_sums=sorted({digit_sum(t+19) for t in times})
assert times==[69] and future_sums==[11]

vertices=[(-6,Fraction(45,4)),(0,0),(9,0),(15,8),(9,Fraction(77,4)),(0,Fraction(77,4))]
area=abs(sum(vertices[i][0]*vertices[(i+1)%6][1]-vertices[(i+1)%6][0]*vertices[i][1] for i in range(6)))/2
assert area==Fraction(1155,4)

sx=7-sqrt(142)/2;sy=5-sqrt(142)/2
assert simplify((sx-12)**2+sy**2)==121
assert simplify(sx**2+(sy-12)**2)==169
assert simplify(24+12*sqrt(2)-44)!=0

report={'scope':'Exact CPU task/data oracles; not neural-model experiments or algorithm performance.',
        'coin_problem':{'pilot_index':7,'enumerated_count_assignments':720,'distinct_valid_sums_under2018':coin_answer},
        'clock_problem':{'pilot_index':9,'all_720_times_enumerated':True,'satisfying_minutes':[69],'unique_future_digit_sum':11},
        'hexagon_problem':{'pilot_index':12,'exact_coordinate_hull_area':str(area),'reference_final_answer_supported':True,
                           'reference_intermediate_cosine_line_has_arithmetic_or_label_error':True},
        'undefined_point_problem':{'pilot_index':13,'alternative_S':str((sx,sy)),'SQ_squared':121,'SR_squared':169,
                                  'alternative_perimeter':str(24+12*sqrt(2)),'given_text_does_not_uniquely_imply44':True}}
(ROOT/'provenance/pilot_bounded_oracles.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
