"""Descriptive final failure diagnostics, with no re-fitting or test-set tuning."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import numpy as np

assert json.loads(Path('results/analysis/study_integrity.json').read_text())['passed']
rows=defaultdict(lambda:defaultdict(dict))
for p in Path('results/online').glob('*.jsonl'):
 for s in p.read_text(encoding='utf-8').splitlines():
  r=json.loads(s);rows[r['model_path'].split('/')[-1]][r['method']][r['problem_id']]=r
report={'scope':'Descriptive audit of frozen final outputs and saved decisions. It does not identify hidden-state mechanisms or tune any policy.','models':{}}
for model,methods in rows.items():
 full=methods['full'];controller=methods['transition'];ids=sorted(set(full)&set(controller))
 harms=[k for k in ids if full[k]['correct'] and not controller[k]['correct']]
 fixes=[k for k in ids if not full[k]['correct'] and controller[k]['correct']]
 states=[]
 for k in harms:
  a,b=full[k],controller[k];decision=b['decisions'][-1] if b['decisions'] else None
  detail=decision['detail'] if decision else {}
  raw_full=detail.get('full_fix',0)-detail.get('full_harm',0)
  raw_step=detail.get('step_fix',0)-detail.get('step_harm',0)
  margin=b['policy_spec'].get('margin',0)
  states.append({'problem_id':k,'full_think_tokens':a['think_tokens'],'controller_think_tokens':b['think_tokens'],
   'full_censored':a['length_censored'],'controller_parse_status':b['grade']['parse_status'],
   'last_action':decision['action'] if decision else None,'estimated_stop_correct':detail.get('stop_correct'),
   'unpenalized_full_net':raw_full,'unpenalized_step_net':raw_step,'stop_margin':margin,
   'penalty_changed_stop_decision':max(raw_full,raw_step)>margin and decision is not None and decision['action']=='STOP',
   'full_penalized_value':detail.get('values',{}).get('FULL')})
 values=[r['estimated_stop_correct'] for r in states if r['estimated_stop_correct'] is not None]
 report['models'][model]={'n':len(ids),'harm_n':len(harms),'fix_n':len(fixes),
  'full_censored_among_harms':sum(r['full_censored'] for r in states),
  'parse_non_success_among_harms':sum(r['controller_parse_status']!='ok' for r in states),
  'stop_action_among_harms':sum(r['last_action']=='STOP' for r in states),
  'estimated_stop_correct_below_0_5_among_harms':sum(v<0.5 for v in values),
  'estimated_stop_correct_below_0_9_among_harms':sum(v<0.9 for v in values),
  'median_estimated_stop_correct_among_harms':float(np.median(values)) if values else None,
  'cost_penalty_changed_stop_choice_among_harms':sum(r['penalty_changed_stop_decision'] for r in states),
  'harm_cases':states,'fix_ids':fixes,
  'both_wrong_n':sum(not full[k]['correct'] and not controller[k]['correct'] for k in ids)}
path=Path('results/analysis/online_failure_diagnostics.json');path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({model:{k:v for k,v in r.items() if k not in ['harm_cases','fix_ids']} for model,r in report['models'].items()},indent=2))
