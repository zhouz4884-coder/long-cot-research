"""Read-only lineage checks and event audit export for completed training banks."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import digest_ids

p=argparse.ArgumentParser();p.add_argument('--root',default='.');args=p.parse_args()
root=Path(args.root);bank=root/'results/bank';out=Path('results/audit');out.mkdir(parents=True,exist_ok=True)
report={'splits':{},'scope':'read-only completed development/engineering audit'}
markdown=['# 分支事件逐条复核材料','', '以下是实际模型输出；不是额外实验或人工修正评分。','']
for split,expected in [('development',150),('engineering',50)]:
 traces=[];branches=[]
 for kind,rows in [('traces',traces),('branches',branches)]:
  for file in sorted(bank.glob(f'{split}_{kind}_*.jsonl')):
   if '_orphan_' not in file.name:rows.extend(json.loads(line) for line in file.read_text(encoding='utf-8').splitlines())
 by_id={r['problem_id']:r for r in traces};assert len(traces)==len(by_id)==expected
 assert len({r['checkpoint_id'] for r in branches})==len(branches)
 for r in branches:
  assert digest_ids(r['prefix_ids'])==r['prefix_hash'],r['checkpoint_id']
  trace=by_id[r['problem_id']]
  assert r['prefix_ids']==(trace['prompt_ids']+trace['trace']['ids'])[:len(r['prefix_ids'])]
  assert r['end_correct']==trace['grade']['correct']
 events=[r for r in branches if r['stop_correct']!=r['step_correct']]
 report['splits'][split]={'trace_n':len(traces),'checkpoint_n':len(branches),'event_n':len(events),
  'states_without_checkpoint':[k for k in by_id if k not in {r['problem_id'] for r in branches}],
  'trace_correct':sum(r['grade']['correct'] for r in traces),'trace_censored':sum(r['trace']['length_censored'] for r in traces),
  'step_counts':dict(Counter(f"{r['stop_correct']}->{r['step_correct']}" for r in branches)),
  'all_prefixes_hash_and_parent_ids_match':True}
 for r in events:
  t=by_id[r['problem_id']]
  question=next(json.loads(line)['question'] for line in Path(f'data/{split}.jsonl').read_text(encoding='utf-8').splitlines() if json.loads(line)['problem_id']==r['problem_id'])
  markdown.extend([f"## {split}: {r['checkpoint_id']}",'',f"题目：{question}",'',f"标准答案：`{t['gold']}`",'',f"STOP ({r['stop_correct']}): `{r['stop']['text']}`",'',f"STEP ({r['step_correct']}): `{r['step_answer']['text']}`",'',f"一步续写：{r['step']['text']}",''])
(out/'bank_lineage.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
(out/'EVENTS_ZH.md').write_text('\n'.join(line.rstrip() for line in '\n'.join(markdown).splitlines())+'\n',encoding='utf-8')
print(json.dumps(report,indent=2,ensure_ascii=False))
