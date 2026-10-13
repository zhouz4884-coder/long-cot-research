"""Retain original scores and uniformly adjudicate mathematical representations."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import grade

bank=Path('results/bank');traces={};changes=[]
def replace(path,rows):
    temporary=path.with_suffix('.regraded')
    temporary.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    temporary.replace(path)
for path in bank.glob('*_traces_*.jsonl'):
    rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
    for row in rows:
        row.setdefault('grade_original_math_verify',row['grade'])
        scored=grade(row['answer']['text'],row['gold'])
        if scored['correct']!=row['grade']['correct']:changes.append({'problem_id':row['problem_id'],'action':'FULL','before':row['grade']['correct'],'after':scored['correct']})
        row['grade']=scored
        if 'zero_answer' in row:
            row.setdefault('zero_grade_original_math_verify',row['zero_grade'])
            row['zero_grade']=grade(row['zero_answer']['text'],row['gold'])
        traces[row['problem_id']]=row
    replace(path,rows)
for path in bank.glob('*_branches_*.jsonl'):
    if '_orphan_' in path.name:continue
    rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
    for row in rows:
        full=traces[row['problem_id']]
        for name,text_key in [('stop','stop'),('step','step_answer')]:
            row.setdefault(name+'_grade_original_math_verify',row[name+'_grade'])
            scored=grade(row[text_key]['text'],full['gold'])
            if scored['correct']!=row[name+'_correct']:changes.append({'checkpoint_id':row['checkpoint_id'],'action':name,'before':row[name+'_correct'],'after':scored['correct']})
            row[name+'_grade']=scored;row[name+'_correct']=scored['correct']
        row['end_grade']=full['grade'];row['end_correct']=full['grade']['correct']
    replace(path,rows)
for path in bank.glob('*_probes_*.jsonl'):
    if '_orphan_' in path.name:continue
    rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
    for row in rows:
        row.setdefault('grade_original_math_verify',row['grade'])
        row['grade']=grade(row['answer']['text'],traces[row['problem_id']]['gold']);row['correct']=row['grade']['correct']
        row['end_correct']=traces[row['problem_id']]['grade']['correct']
    replace(path,rows)
Path('results/analysis').mkdir(exist_ok=True)
Path('results/analysis/surface_adjudication_v3.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
print('Adjudicated changed scores',len(changes),'on completed traces',len(traces))
