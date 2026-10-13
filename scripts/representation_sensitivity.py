"""Post-hoc representation audit; never overwrite the frozen primary scores."""
from collections import defaultdict
import json,re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import grade,last_box

assert json.loads(Path('results/analysis/study_integrity.json').read_text())['passed']
questions={r['problem_id']:r for r in (json.loads(s) for s in Path('data/test.jsonl').read_text(encoding='utf-8').splitlines())}
models=defaultdict(lambda:defaultdict(dict));changes=[]
for p in Path('results/online').glob('*.jsonl'):
 for s in p.read_text(encoding='utf-8').splitlines():
  r=json.loads(s);boxed=last_box(r['answer']['text']);normalized=boxed;rules=[]
  if boxed is not None:
   fixed=re.sub(r'(?<![A-Za-z\\])cot(?=\s+[A-Za-z\\(])',lambda m:r'\cot',boxed)
   if fixed!=boxed:rules.append('standalone_cot_function_command')
   match=re.fullmatch(r'\s*(\d+)\s*\^\{\\(?:mathrm|text)\{(?:st|nd|rd|th)\}\}\s*(?:grade)?\s*',fixed)
   if match:fixed=match.group(1);rules.append('whole_answer_ordinal_surface')
   normalized=fixed
  corrected=r['correct']
  if normalized!=boxed:
   new=grade(r'\boxed{'+normalized+'}',questions[r['problem_id']]['gold']);corrected=new['correct']
   changes.append({'model':r['model_path'].split('/')[-1],'method':r['method'],'problem_id':r['problem_id'],
    'before':r['correct'],'after':corrected,'original_boxed':boxed,'normalized_boxed':normalized,'rules':rules,
    'question':questions[r['problem_id']]['question'],'gold':questions[r['problem_id']]['gold'],'new_grade':new})
  models[r['model_path'].split('/')[-1]][r['method']][r['problem_id']]={'primary':r['correct'],'sensitivity':corrected}
summary={}
for model,methods in models.items():
 item={'methods':{},'controller_vs_full':{}}
 for method,by_id in methods.items():
  item['methods'][method]={'n':len(by_id),'primary_correct':sum(r['primary'] for r in by_id.values()),
   'sensitivity_correct':sum(r['sensitivity'] for r in by_id.values())}
 full=methods['full'];candidate=methods['transition'];ids=sorted(set(full)&set(candidate))
 for mode in ['primary','sensitivity']:
  item['controller_vs_full'][mode]={'n':len(ids),'accuracy_delta':sum(candidate[k][mode]-full[k][mode] for k in ids)/len(ids),
   'harms':sum(full[k][mode]==1 and candidate[k][mode]==0 for k in ids),
   'fixes':sum(full[k][mode]==0 and candidate[k][mode]==1 for k in ids)}
 summary[model]=item
out=Path('results/analysis/representation_sensitivity.json')
out.write_text(json.dumps({'is_primary_analysis':False,'scope':'Uniform post-hoc surface rules applied to all 1648 outputs; frozen primary scores and policy unchanged. Every changed answer requires case review.',
 'rules':['standalone cot function gains TeX command','whole-answer ordinal suffix canonicalized to its numeral'],
 'changes':changes,'models':summary},indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({'changes':[{k:r[k] for k in ['model','method','problem_id','before','after','rules']} for r in changes],'models':summary},indent=2))
