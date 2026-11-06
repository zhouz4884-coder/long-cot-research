"""Offline descriptive baseline grading; never used by native execution."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

from d0_answer_extract import extract_policy
from d0_math_grade import grade_selected


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();r=a.root;start=time.monotonic()
    for name in ('native_launcher.json','schedule_launcher.json'):assert json.loads((r/name).read_text())['status']=='FINISHED'
    manifest=json.loads((r/'D1_DATA_MANIFEST.json').read_text());raw=(r/'native_eval_only.jsonl').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==manifest['eval_sha256']
    gold={q['case_id']:q['gold'] for q in map(json.loads,raw.splitlines())}
    files=sorted((r/'native_results').glob('worker_*/D1_*/result.json'));assert len(files)==8
    results=[json.loads(f.read_text()) for f in files];assert {q['case_id'] for q in results}==set(gold)
    def score(q):
        selected=extract_policy(q['final_response'],'LastBox') if q['think_closed'] and q['EOS'] else {'status':'uncommitted'}
        grade=grade_selected(selected,gold[q['case_id']]) if selected['status']=='ok' else {'status':'not_delivered','correct':False}
        return {'case_id':q['case_id'],'selection':selected,'grade':grade,'EOS':q['EOS'],'tokens':q['new_tokens'],
            'raw_sha256':hashlib.sha256(next(f for f in files if f.parent.name==q['case_id']).read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(score,results))
    output=r/'D1_NATIVE_SCORES.json';assert not output.exists()
    output.write_text(json.dumps({'status':'COMPLETE','n':8,'correct':sum(q['grade'].get('correct') is True for q in rows),
        'unknown':sum(q['grade'].get('correct') is None for q in rows),'rows':rows,'wall_seconds':time.monotonic()-start,
        'scope':'Descriptive sampled Continue baseline only;8interfacefixtures,zeroalgorithmrepair interventions,notanaccuracygain.'},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
