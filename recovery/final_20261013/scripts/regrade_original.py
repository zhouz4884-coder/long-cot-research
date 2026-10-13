"""Audit upstream smoke accuracy under symbolic grading; retain censoring."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import grade,append_jsonl
from transformers import AutoTokenizer

root=Path('.')
rows=[json.loads(x) for x in (root/'data/math500_smoke.jsonl').read_text(encoding='utf-8').splitlines()]
raw=[json.loads(x) for x in (root/'results/original_raw.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(raw)==168 and len(rows)==24
tok=AutoTokenizer.from_pretrained('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B',local_files_only=True)
end=tok.convert_tokens_to_ids('</think>');budgets=['FULL',0,128,256,512,1024,2048]
out=Path('results/p0');out.mkdir(exist_ok=True)
records=[]
for i,r in enumerate(raw):
    budget=budgets[i//24];question=rows[i%24];ids=r['generated_ids']
    closed=end in ids
    full=budget=='FULL'
    answer_ids=ids[ids.index(end)+1:] if full and closed else ids
    text=tok.decode(answer_ids,skip_special_tokens=True)
    result=grade('Final answer: '+text,question['gold']) if not full or closed else {'correct':0,'parse_status':'unfinished_thinking'}
    records.append({'problem_id':question['problem_id'],'budget':budget,'text':text,'gold':question['gold'],
        'grade':result,'length_censored':full and not closed,'tokens':len(ids),'ms':r['batch_ms']})
(out/'original_regraded.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
summary={str(b):{'n':24,'correct':sum(r['grade']['correct'] for r in records if r['budget']==b),
    'censored':sum(r['length_censored'] for r in records if r['budget']==b),
    'parse_failed':sum(r['grade'].get('parse_status') not in ['ok','unfinished_thinking'] for r in records if r['budget']==b)} for b in budgets}
(out/'original_regraded_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
