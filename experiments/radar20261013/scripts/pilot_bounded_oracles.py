"""Exact, legal small task oracles for pilot grading/data validity; CPU only."""
import itertools,json,math
from collections import Counter
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

vertices=[(-Fraction(27,5),Fraction(36,5)),(0,0),(10,0),
          (Fraction(77,5),Fraction(231,20)),(10,Fraction(75,4)),(0,Fraction(75,4))]
triangle=vertices[:3]
squared_sides=[(triangle[i][0]-triangle[j][0])**2+(triangle[i][1]-triangle[j][1])**2
               for i,j in [(0,1),(1,2),(2,0)]]
assert squared_sides==[81,100,289], 'Oracle coordinates must satisfy AB9/BC10/CA17'
center=(5,Fraction(75,8));radius_squared=Fraction(85,8)**2
assert all((x-center[0])**2+(y-center[1])**2==radius_squared for x,y in vertices)
assert all(vertices[i][0]+vertices[i+3][0]==2*center[0] and
           vertices[i][1]+vertices[i+3][1]==2*center[1] for i in range(3))
turns=[]
for i in range(6):
    a,b,c=vertices[i],vertices[(i+1)%6],vertices[(i+2)%6]
    turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
assert all(t>0 for t in turns),'Use the actual convex hull vertex order'
area=abs(sum(vertices[i][0]*vertices[(i+1)%6][1]-vertices[(i+1)%6][0]*vertices[i][1] for i in range(6)))/2
assert area==Fraction(1155,4)

sx=7-sqrt(142)/2;sy=5-sqrt(142)/2
assert simplify((sx-12)**2+sy**2)==121
assert simplify(sx**2+(sy-12)**2)==169
assert simplify(24+12*sqrt(2)-44)!=0

grid_states={tuple([0]*6):1}
for _ in range(6):
    next_states=Counter()
    for state,count in grid_states.items():
        for cols in itertools.combinations(range(6),2):
            updated=tuple(v+(i in cols) for i,v in enumerate(state))
            if max(updated)<=2:next_states[updated]+=count
    grid_states=next_states
assert grid_states[(2,)*6]==67950
seq=[1,4,2,3]
for _ in range(4):seq.append(sum(seq[-4:]))
assert seq[-1]==66
lattice=sum(x*x+2*y*y<25 for x in range(-5,6) for y in range(-4,5))
assert lattice==55
# Each of two rows has F_11=89 independent monomer/horizontal-domino tilings.
tilings=[1,1]
for n in range(2,11):tilings.append(tilings[-1]+tilings[-2])
assert tilings[10]**2==7921
cards=0
for allocation in itertools.product(range(3),repeat=6):
    if set(allocation)!={0,1,2}:continue
    owned=[i+2 for i,p in enumerate(allocation) if p==0]
    cards+=len(owned)>1 or any(c%2==0 for c in owned)
assert cards==450
binary=min(n for n in range(63,10000,63) if n.bit_count()%2)
assert binary==4221
partial_credit_exact=sum(k**(26-k) for k in range(1,26))
assert partial_credit_exact==66071772829247409

report={'scope':'Exact CPU task/data oracles; not neural-model experiments or algorithm performance.',
        'oracle_version':2,
        'geometry_correction':'Version1 used a different triangle whose hull area happened to match. Version2 verifies the original side lengths, circumcircle, antipodes and convex hull before calculating area. Version1 code/output are preserved in provenance/oracle_archive.',
        'coin_problem':{'pilot_index':7,'enumerated_count_assignments':720,'distinct_valid_sums_under2018':coin_answer},
        'clock_problem':{'pilot_index':9,'all_720_times_enumerated':True,'satisfying_minutes':[69],'unique_future_digit_sum':11},
        'hexagon_problem':{'pilot_index':12,'exact_coordinate_hull_area':str(area),'reference_final_answer_supported':True,
                           'original_squared_sides':[str(v) for v in squared_sides],
                           'circumcenter':[str(v) for v in center],'circumradius_squared':str(radius_squared),
                           'all_vertices_on_circle':True,'diametrically_opposite_pairs_verified':True,
                           'convex_order_verified':True,
                           'reference_intermediate_cosine_line_has_arithmetic_or_label_error':True},
        'undefined_point_problem':{'pilot_index':13,'alternative_S':str((sx,sy)),'SQ_squared':121,'SR_squared':169,
                                  'alternative_perimeter':str(24+12*sqrt(2)),'given_text_does_not_uniquely_imply44':True},
        'additional_exact_controls':[
            {'pilot_index':51,'answer':seq[-1],'method':'four-term recurrence'},
            {'pilot_index':52,'answer':lattice,'method':'bounded integer lattice enumeration'},
            {'pilot_index':58,'answer':grid_states[(2,)*6],'method':'all six row-pair choices with column-count DP'},
            {'pilot_index':71,'answer':tilings[10]**2,'method':'independent-row horizontal domino recurrence'},
            {'pilot_index':81,'answer':cards,'method':'all 3^6 labelled hand assignments'},
            {'pilot_index':86,'answer':partial_credit_exact,'method':'exact integer sum; original partial-credit task'},
            {'pilot_index':98,'answer':binary,'method':'all smaller positive multiples of 63'}]}
(ROOT/'provenance/pilot_bounded_oracles.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
