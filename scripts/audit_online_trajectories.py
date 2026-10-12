"""Check stored common-prefix/seed controls without modifying model outputs."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--out',default='results/analysis/trajectory_consistency.json');p.add_argument('--partial',action='store_true');args=p.parse_args()
root=Path(args.root)
if not args.partial:assert json.loads((root/'results/analysis/study_integrity.json').read_text())['passed']
folder=root/'results/online' if (root/'results/online').exists() else root
models=defaultdict(lambda:defaultdict(dict))
for file in folder.glob('*.jsonl'):
 for line in file.read_text(encoding='utf-8').splitlines():
  row=json.loads(line);model=row['model_path'].split('/')[-1]
  assert row['problem_id'] not in models[model][row['method']]
  models[model][row['method']][row['problem_id']]=row
report={'is_final':not args.partial,'scope':'Direct checks of retained token IDs, seeds and answer prefixes. No output regrading or policy tuning.','models':{}}
for model,methods in models.items():
 item={}
 for method,rows in methods.items():
  if method=='full':continue
  checked=0;mismatches=[];same_context=0;answer_mismatches=[];scoring_mismatches=[];zero_think=0
  for key in sorted(set(rows)&set(methods['full'])):
   row=rows[key];reference=methods['full'][key]
   assert row['seed']==reference['seed'] and row['model_path']==reference['model_path']
   if row['trace'] is None:zero_think+=1;continue
   checked+=1;ids=row['trace']['ids'];full_ids=reference['trace']['ids']
   if ids!=full_ids[:len(ids)]:mismatches.append(key)
   if row['step']:
    continued=ids+row['step']['ids']
    if continued!=full_ids[:len(continued)] and key not in mismatches:mismatches.append(key)
   if row['answer']['answer_prefix_hash']==reference['answer']['answer_prefix_hash']:
    same_context+=1
    if row['answer']['ids']!=reference['answer']['ids']:answer_mismatches.append(key)
    elif row['correct']!=reference['correct']:scoring_mismatches.append(key)
  item[method]={'paired_thinking_rows':checked,'zero_thinking_rows':zero_think,'thinking_prefix_mismatch_ids':mismatches,
   'identical_answer_context_rows':same_context,'same_context_answer_mismatch_ids':answer_mismatches,
   'same_output_scoring_mismatch_ids':scoring_mismatches}
 report['models'][model]=item
report['all_observed_prefixes_match']=all(not r['thinking_prefix_mismatch_ids'] for methods in report['models'].values() for r in methods.values())
report['all_observed_same_context_answers_match']=all(not r['same_context_answer_mismatch_ids'] for methods in report['models'].values() for r in methods.values())
report['all_observed_identical_outputs_scored_consistently']=all(not r['same_output_scoring_mismatch_ids'] for methods in report['models'].values() for r in methods.values())
out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
