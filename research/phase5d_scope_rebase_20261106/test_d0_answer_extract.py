"""Generic, non-bank D0 contracts. Optional pinned CPU semantic smoke."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import d0_answer_extract as ex
from d0_math_grade import grade_selected


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--require-backend',action='store_true');ap.add_argument('--output',type=Path,default=Path(__file__).with_name('D0_LOCAL_CPU_TEST.json'));args=ap.parse_args()
    tests=[];issues=[];started=time.monotonic()
    def check(name,condition,detail=None):
        tests.append({'name':name,'pass':bool(condition),'detail':detail})
        if not condition:issues.append(name)
    positives=[(r'\boxed{7} apples.','7'),(r'$\boxed{7}$ square units.','7'),
        (r'\boxed{\frac{2}{7}} units.',r'\frac{2}{7}'),
        (r'\boxed{(2, 7, -4)} widgets.','(2, 7, -4)'),
        (r'\boxed{[0,1)}','[0,1)'),(r'\boxed{(-1,2]}','(-1,2]'),
        (r'\boxed{\begin{pmatrix}2\\7\end{pmatrix}} meters.',r'\begin{pmatrix}2\\7\end{pmatrix}'),
        (r'\boxed{cot x}',r'cot x'),(r'\boxed{\{1,2\}}',r'\{1,2\}')]
    for n,(text,surface) in enumerate(positives):
        r=ex.extract_policy(text,'LastBox');check(f'boxed_unit_object_{n}',r.get('status')=='ok' and r.get('surface')==surface,r)
    final_cases=[('Final answer: 7 apples.','7'),('**Final Answer**\n'+r'\boxed{7} meters.','7'),
        (r'Final answer: $\frac{2}{7}$ units.',r'\frac{2}{7}'),('最终答案：(2,7,-4)','(2,7,-4)'),
        (r'Final answer: \begin{pmatrix}2\\7\end{pmatrix}',r'\begin{pmatrix}2\\7\end{pmatrix}'),
        (r'Final answer: [0,1)','[0,1)'),(r'Final answer: cot x','cot x')]
    for n,(text,surface) in enumerate(final_cases):
        r=ex.extract_policy(text,'LastFinalAnswer');check(f'explicit_final_object_{n}',r.get('status')=='ok' and r.get('surface')==surface,r)
    negatives=[(r'No final object; first2 then7.','LastBox'),('I computed7 after2.','LastFinalAnswer'),
        (r'\boxed{\frac{2}{7}','LastBox'),(r'\boxed{2} then \boxed{','LastBox'),
        (r'Final answer: \boxed{2} later Final answer:','LastFinalAnswer'),
        (r'\boxed{2}\boxed{7}','LastBox'),(r'\boxed{2 or 7}','LastBox'),
        (r'\boxed{2} or7','LastBox'),('Final answer: 2 or 7','LastFinalAnswer'),
        (r'\boxed{(2,7}','LastBox'),(r'\boxed{2,7}','LastBox'),
        (r'Final answer: \begin{pmatrix}2\\7','LastFinalAnswer'),
        (r'Final answer: perhaps7','LastFinalAnswer')]
    for n,(text,policy) in enumerate(negatives):
        r=ex.extract_policy(text,policy);check(f'abstain_incomplete_or_ambiguous_{n}',r.get('status')!='ok',r)
    text=r'\boxed{2} Earlier attempt. Final answer: \boxed{7} widgets.'
    r=ex.extract_policy(text,'LastBox');check('LastBox_fixed_last_not_gold',r.get('surface')=='7' and r['signals']['distinct_surface_count']==2)
    r=ex.extract_policy(text,'FirstCompleteAnswer');check('First_fixed_first_not_gold',r.get('surface')=='2')
    r=ex.extract_policy(text,'ConservativeFinal');check('Conservative_surface_disagreement_unknown',r.get('status')=='ambiguous')
    r=ex.extract_policy(r'Final answer: \boxed{1/2} Then final answer: \boxed{0.5}','ConservativeFinal');check('Exact_rational_surface_equivalence',r.get('status')=='ok')
    r=ex.extract_policy(r'Final answer: \boxed{2} Final answer: 7','LastFinalAnswer');check('LastFinal_fixed_last_label',r.get('surface')=='7')
    for policy in ex.POLICIES:
        try:ex.extract_policy({'gold':'7','text':'7'},policy)
        except TypeError:check('no_evaluator_dict_'+policy,True)
        else:check('no_evaluator_dict_'+policy,False)
    check('no_hardcoded_benchmark_names',all(s not in Path(ex.__file__).read_text(encoding='utf-8') for s in ['C006','representatives','24313','1742']))
    semantic=[(r'\boxed{7} apples.','7',True),(r'\boxed{\frac{2}{7}} units.','2/7',True),
        (r'\boxed{0.5}','1/2',True),(r'\boxed{cot x}',r'\cot x',True),
        (r'\boxed{(2,7,-4)}','(2,7,-4)',True),(r'\boxed{(2,7,-4)}','(7,2,-4)',False),
        (r'\boxed{2}','(2,7,-4)',False),
        (r'\boxed{\begin{pmatrix}2\\7\end{pmatrix}}',r'\begin{pmatrix}2\\7\end{pmatrix}',True),
        (r'\boxed{(2,7)}',r'\begin{pmatrix}2\\7\end{pmatrix}',True),
        (r'\boxed{\begin{pmatrix}7\\2\end{pmatrix}}',r'\begin{pmatrix}2\\7\end{pmatrix}',False),
        (r'\boxed{[0,1)}',r'\left[0,1\right)',True),(r'\boxed{(0,1]}',r'\left(0,1\right]',True),
        (r'\boxed{[0,1]}','[0,1)',False),(r'\boxed{[0,0.5]}',r'[0,\frac{1}{2}]',True),
        (r'\boxed{0}','0',True),(r'\boxed{1}','1',True),
        (r'\boxed{7}','8',False),(r'\boxed{\{1,2\}}',r'\{2,1\}',True)]
    math_checks=[]
    if args.require_backend:
        for i,(text,gold,wanted) in enumerate(semantic):
            extraction=ex.extract_policy(text,'LastBox');result=grade_selected(extraction,gold)
            good=result.get('correct') is wanted
            math_checks.append({'name':f'math_{i}','pass':good,'text':text,'gold':gold,'expected':wanted,'extraction':extraction,'result':result})
            if not good:issues.append(f'math_{i}')
    report={'status':'PASS' if not issues else 'FAIL','scope':'Generic non-bank contracts; Gold appears only in offline semantic smoke.',
        'extractor_sha256':hashlib.sha256(Path(ex.__file__).read_bytes()).hexdigest(),
        'semantic_grader_sha256':hashlib.sha256(Path(__file__).with_name('d0_math_grade.py').read_bytes()).hexdigest(),
        'structural_passed':sum(t['pass'] for t in tests),'structural_total':len(tests),'math_executed':len(math_checks),'math_planned':len(semantic),
        'seconds':time.monotonic()-started,'issues':issues,'tests':tests,'math_tests':math_checks}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ['tests','math_tests']},ensure_ascii=False,indent=2))
    return 0 if not issues else 2


if __name__=='__main__':raise SystemExit(main())
