"""CPU-only D0 retrospective scoring after a generic parser freeze.

Gold joins only after all fixed selections have been made. Identical semantic
queries may share a CPU result; no candidate is chosen using that result.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import time

from d0_math_grade import grade_selected


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    ap.add_argument('--evaluation-file',type=Path,required=True);ap.add_argument('--output',type=Path);args=ap.parse_args();root=args.root.resolve()
    os.environ['CUDA_VISIBLE_DEVICES']='';started=time.monotonic()
    contract=json.loads((root/'D0_parser_contract.json').read_text(encoding='utf-8'))
    prep=json.loads((root/'D0_PREPARATION.json').read_text(encoding='utf-8'))
    if sha(root/'d0_answer_extract.py')!=contract['extractor_sha256'] or sha(root/'d0_math_grade.py')!=contract['semantic_grader_sha256']:raise ValueError('Frozen D0 source mismatch')
    if sha(root/'D0_SELECTIONS.jsonl')!=prep['selections_sha256'] or sha(root/'D0_parser_contract.json')!=prep['contract_sha256']:raise ValueError('Selections/contract mismatch')
    selected=[json.loads(v) for v in (root/'D0_SELECTIONS.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(selected)!=1024 or len({v['selection_id'] for v in selected})!=1024:raise ValueError('Expected1024 fixed selections')
    binding=json.loads((root/'D0_EVALUATION_BINDING.json').read_text(encoding='utf-8'))
    if sha(args.evaluation_file)!=binding['evaluation_sha256']:raise ValueError('Original evaluation file byte hash mismatch')
    evaluation=[json.loads(v) for v in args.evaluation_file.read_text(encoding='utf-8').splitlines() if v.strip()]
    gold={v['bank_id']:v['gold'] for v in evaluation}
    if len(evaluation)!=32 or len(gold)!=32 or set(v['bank_id'] for v in selected)!=set(gold):raise ValueError('Evaluation IDs must match fixed32')
    out=args.output.resolve() if args.output else root/'d0_scoring';out.mkdir(parents=True,exist_ok=False)
    unique={};row_keys={}
    for row in selected:
        if row['selection']['status']!='ok':continue
        payload={'surface':row['selection']['surface'],'gold':str(gold[row['bank_id']])}
        key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        unique[key]=(row['selection'],gold[row['bank_id']]);row_keys[row['selection_id']]=key
    grades={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(grade_selected,extraction,answer):key for key,(extraction,answer) in unique.items()}
        for future in as_completed(futures):
            grades[futures[future]]=future.result()
            if len(grades)%16==0:(out/'progress.json').write_text(json.dumps({'semantic_queries_done':len(grades),'semantic_queries_planned':len(unique),'wall_seconds':time.monotonic()-started})+'\n')
    rows=[]
    for row in selected:
        key=row_keys.get(row['selection_id'])
        grade=grades[key] if key else {'status':'selection_abstained','correct':False,'mathematical_correctness':None}
        rows.append({**row,'grade':grade,'semantic_cache_key':key})
    with (out/'D0_scores.jsonl').open('x',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    groups={}
    for method in sorted({r['method'] for r in rows}):
        groups[method]={}
        for policy in contract['policies']:
            rr=[r for r in rows if r['method']==method and r['policy']==policy]
            if len(rr)!=32:raise ValueError('Each condition/policy must retain32 cases')
            groups[method][policy]={'n':32,'selected':sum(r['selection']['status']=='ok' for r in rr),
                'abstained':sum(r['selection']['status']!='ok' for r in rr),
                'selected_correct':sum(r['grade'].get('correct') is True for r in rr),
                'selected_wrong':sum(r['selection']['status']=='ok' and r['grade'].get('correct') is False for r in rr),
                'backend_unknown':sum(r['grade'].get('correct') is None for r in rr),
                'policy_success_over32':sum(r['grade'].get('correct') is True for r in rr)/32,
                'surface_disagreement_flagged':sum(r['selection']['signals']['distinct_surface_count']>1 for r in rr)}
    result={'status':'COMPLETE','scope':'Retrospective fixed textual readout policies on32thinking+224oldgenerated outputs. No new model call; old main scores unchanged.',
        'individual_problem_IDs':32,'input_texts':256,'selection_rows':1024,'semantic_queries_deduplicated':len(unique),'groups':groups,
        'wall_seconds':time.monotonic()-started,'grader_source_sha256':sha(root/'d0_math_grade.py'),'extractor_source_sha256':sha(root/'d0_answer_extract.py'),
        'selection_sha256':sha(root/'D0_SELECTIONS.jsonl'),'evaluation_sha256':sha(args.evaluation_file),'scores_sha256':sha(out/'D0_scores.jsonl'),
        'evaluation_binding_sha256':sha(root/'D0_EVALUATION_BINDING.json'),
        'source_sha256':sha(__file__),'Gold_used_to_select_candidate':False,'oracle_best_candidate_score_computed':False,
        'limitations':['A fixed LastBox policy is not a mathematical upper bound on all possible readout.',
            'First/last text positions have no truth certificate. Surface disagreement is not proven logical conflict.',
            'Full historical thinking contains future text relative to earlier checkpoints; these policies must not select online checkpoint/action using future markers.',
            'All four selections from one text and all seven readouts from one problem are correlated. Do not report1024independent tasks.',
            'Abstention is policy non-delivery, not proof that the model mathematics is false. Backendunknown remains unresolved.']}
    (out/'D0_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='groups'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
