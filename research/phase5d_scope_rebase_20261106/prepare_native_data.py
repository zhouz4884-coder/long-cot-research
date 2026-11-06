"""Offline deterministic replay of the already frozen D1 eight-question bank."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    manifest=json.loads((ROOT/'D1_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    raw=(ROOT/'gsm8k_source_test.jsonl').read_bytes();assert sha(raw)==manifest['source_sha256']
    rows=[json.loads(v) for v in raw.splitlines() if v.strip()];assert len(rows)==1319
    oldpath=REPO/'data/test.jsonl';oldraw=oldpath.read_bytes()
    old={sha(json.loads(line)['question'].strip().encode()) for line in oldraw.splitlines() if line.strip()}
    salt=manifest['salt'];ranking=[]
    for line,row in enumerate(rows,1):
        question=row['question']
        if sha(question.strip().encode()) in old:continue
        ranking.append((sha((salt+'\0'+str(line)+'\0'+question).encode()),line,question))
    selected=sorted(ranking)[:8];visible=[];evaluation=[];cases=[]
    for rank,(key,line,question) in enumerate(selected,1):
        cid=f'D1_{rank:02}';visible.append({'case_id':cid,'question':question})
        answer=rows[line-1]['answer']  # Evaluation enters only AFTER selection.
        evaluation.append({'case_id':cid,'gold':answer.split('####')[-1].strip(),'original_solution':answer})
        cases.append({'case_id':cid,'rank':rank,'source_line':line,'selection_hash':key,'question_sha256':sha(question.encode())})
    assert cases==manifest['cases']
    for filename,values,expected in [('native_visible.jsonl',visible,manifest['visible_sha256']),('native_eval_only.jsonl',evaluation,manifest['eval_sha256'])]:
        # The initial bank was frozen by Windows write_text with CRLF rows.
        # Reproduce exact archived bytes across platforms, not merely JSON values.
        content=''.join(json.dumps(v,ensure_ascii=False)+'\r\n' for v in values).encode()
        assert sha(content)==expected and (ROOT/filename).read_bytes()==content,filename
    audit={'status':'PASS','cases':8,'source_rows':1319,'source_commit':manifest['source_commit'],
        'selection_formula':'SHA256(UTF8(salt+NUL+str(source_line_1based)+NUL+original_question)), sort(hash,line)',
        'old_question_source_sha256':sha(oldraw),'selection_does_not_receive_answers':True,'visible_and_eval_bytes_reproduced':True}
    (ROOT/'D1_SELECTION_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(audit,indent=2))


if __name__=='__main__':main()
