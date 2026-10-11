"""Export every paired accuracy reversal after the complete frozen evaluation."""
from collections import defaultdict
import json
from pathlib import Path

assert json.loads(Path('results/analysis/study_integrity.json').read_text())['passed']
questions={r['problem_id']:r for r in (json.loads(s) for s in Path('data/test.jsonl').read_text(encoding='utf-8').splitlines())}
models=defaultdict(lambda:defaultdict(dict))
for p in Path('results/online').glob('*.jsonl'):
 for s in p.read_text(encoding='utf-8').splitlines():
  r=json.loads(s);models[r['model_path'].split('/')[-1]][r['method']][r['problem_id']]=r
cases=[];md=['# 在线配对修正与改错：全量复核材料','',
 '全部最终评估完成后导出。原因需结合原始输出人工判断；以下标签只描述观测结果，不是已证明机制。','']
for model,methods in sorted(models.items()):
 for problem in sorted(set(methods['full'])&set(methods['transition'])):
  a,b=methods['full'][problem],methods['transition'][problem]
  if a['correct']==b['correct']:continue
  direction='修正' if b['correct'] else '改错';q=questions[problem]
  case={'model':model,'problem_id':problem,'direction':direction,'full_correct':a['correct'],'controller_correct':b['correct'],
        'full_censored':a['length_censored'],'controller_censored':b['length_censored'],'full_answer':a['answer']['text'],
        'controller_answer':b['answer']['text'],'gold':q['gold'],'last_decision':b['decisions'][-1] if b['decisions'] else None}
  cases.append(case)
  md.extend([f'## {model} / {problem} / {direction}','',q['question'],'',f"标准答案：`{q['gold']}`",'',
   f"FULL：`{a['answer']['text']}`",'',f"控制器：`{b['answer']['text']}`",'',
   f"FULL / 控制器思考 token：{a['think_tokens']} / {b['think_tokens']}；触顶：{a['length_censored']} / {b['length_censored']}。",'',
   'FULL 最后 800 字符：','',a['trace']['text'][-800:],'','控制器最后 800 字符：','',b['trace']['text'][-800:] if b['trace'] else '(零思考)','',
   '控制器最后决策：','', '```json',json.dumps(case['last_decision'],indent=2,ensure_ascii=False),'```',''])
out=Path('results/audit');out.mkdir(exist_ok=True)
(out/'ONLINE_CASES_ZH.md').write_text('\n'.join(line.rstrip() for line in '\n'.join(md).splitlines())+'\n',encoding='utf-8')
(out/'online_reversals.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False),encoding='utf-8')
print('EXPORTED_ALL_ONLINE_REVERSALS',len(cases))
