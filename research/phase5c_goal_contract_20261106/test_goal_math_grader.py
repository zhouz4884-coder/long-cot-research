"""Generic, non-bank CPU interface/semantic tests. Does not load experiment data."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import goal_math_grader as grader


EXTRACTION_CASES = [
    (r"\boxed{\frac{2}{5}}", "ok", r"\frac{2}{5}", "scalar_or_expression"),
    (r"\boxed{(5,-2,7)}", "ok", "(5,-2,7)", "ordered_tuple"),
    (r"最终答案：\boxed{(5,\frac{2}{5},7)}", "ok", r"(5,\frac{2}{5},7)", "ordered_tuple"),
    (r"Final answer: \begin{pmatrix}2\\3\end{pmatrix}", "ok", r"\begin{pmatrix}2\\3\end{pmatrix}", "vector"),
    (r"\boxed{\begin{bmatrix}2&3\end{bmatrix}}", "ok", r"\begin{bmatrix}2&3\end{bmatrix}", "vector"),
    ("Final answer is 0.4", "ok", "0.4", "scalar_or_expression"),
    ("最终答案是0", "ok", "0", "scalar_or_expression"),
    ("**最终答案：1**", "ok", "1", "scalar_or_expression"),
    (r"最终答案：$\frac{2}{5}$。", "ok", r"\frac{2}{5}", "scalar_or_expression"),
    ('{"final_answer":[5,-2,7]}', "ok", "(5,-2,7)", "ordered_tuple"),
    ('{"final_answer":[[2],[3]]}', "ok", "(2,3)", "ordered_tuple"),
    ('{"final_answer":0.4}', "ok", "0.4", "scalar_or_expression"),
    ('{"final_answer":"2/5"}', "ok", "2/5", "scalar_or_expression"),
    ('```json\n{"final_answer":1}\n```', "ok", "1", "scalar_or_expression"),
    ('{"final_answer":"\\\\boxed{5}"}', "ok", "5", "scalar_or_expression"),
    ("Some reasoning, 5 and 2.\nFinal answer: 7", "ok", "7", "scalar_or_expression"),
    (r"Reasoning gives \boxed{2}, then after recomputing: \boxed{7}.", "ok", "7", "scalar_or_expression"),
    (r"\boxed{5},\boxed{-2},\boxed{7}", "ambiguous", None, None),
    (r"Final answer: \boxed{5},\boxed{-2},\boxed{7}", "ambiguous", None, None),
    (r"\boxed{(5,-2,7)", "incomplete", None, None),
    (r"\boxed{7} Later: \boxed{", "incomplete", None, None),
    ('{"final_answer":7,"final_answer":8}', "ambiguous", None, None),
    ('{"candidate":{"v":1,"v":2},"final_answer":7}', "ambiguous", None, None),
    ('{"final_answer":', "incomplete", None, None),
    ('{"final_answer":true}', "unparsed", None, None),
    ('{"final_answer":null}', "unparsed", None, None),
    ('{"final_answer":NaN}', "ambiguous", None, None),
    ('{"final_answer":{"value":7}}', "unparsed", None, None),
    ('{"final_answer":[]}', "unparsed", None, None),
    ('{"final_answer":[[1,2],[3,4]]}', "unparsed", None, None),
    ("We computed 5, then -2, then 7", "unparsed", None, None),
    ("```json\n{\"final_answer\":7}", "incomplete", None, None),
    (r"Final answer: (5,-2,", "incomplete", None, None),
    ("Final answer: 5 or 7", "ambiguous", None, None),
    (r"\boxed{5 or 7}", "ambiguous", None, None),
    ("Final answer: either 5 or 7", "ambiguous", None, None),
    ("Final answer: possibly 7", "ambiguous", None, None),
    ("最终答案：不确定是5或者7", "ambiguous", None, None),
    ("Final answer: 5, -2, 7", "ambiguous", None, None),
    (r"\boxed{5,-2,7}", "ambiguous", None, None),
    (r"\boxed{(5),(7)}", "ambiguous", None, None),
    (r"Final answer: \begin{matrix}2\\3\end{matrix}", "ok", r"\begin{matrix}2\\3\end{matrix}", "vector"),
]

MATH_CASES = [
    {"name":"rational_decimal","output":r"\boxed{0.4}","gold":r"\frac{2}{5}","expected":True},
    {"name":"fraction_form","output":r"最终答案：\frac{2}{5}","gold":"0.4","expected":True},
    {"name":"probability_zero_legal","output":"Final answer: 0","gold":"0","expected":True},
    {"name":"probability_one_legal","output":"最终答案：1","gold":"1","expected":True},
    {"name":"ordered_tuple_all_components","output":r"\boxed{(5,-2,7)}","gold":"(5,-2,7)","expected":True},
    {"name":"ordered_tuple_not_first_component","output":r"\boxed{5}","gold":"(5,-2,7)","expected":False},
    {"name":"ordered_tuple_not_permutation","output":r"\boxed{(7,-2,5)}","gold":"(5,-2,7)","expected":False},
    {"name":"ordered_tuple_wrong_tail","output":r"\boxed{(5,-2,8)}","gold":"(5,-2,7)","expected":False},
    {"name":"JSON_list_tuple","output":'{"final_answer":[5,-2,7]}',"gold":"(5,-2,7)","expected":True},
    {"name":"column_vector","output":r"\boxed{\begin{pmatrix}2\\3\end{pmatrix}}","gold":r"\begin{pmatrix}2\\3\end{pmatrix}","expected":True},
    {"name":"JSON_coordinates_gold_vector","output":'{"final_answer":[2,3]}',"gold":r"\begin{pmatrix}2\\3\end{pmatrix}","expected":True},
    {"name":"vector_not_scalar","output":r"\boxed{2}","gold":r"\begin{pmatrix}2\\3\end{pmatrix}","expected":False},
    {"name":"plain_cot_not_letter_product","output":r"Final answer: cot y","gold":r"\frac{\cos y}{\sin y}","expected":True},
    {"name":"plain_sin_function","output":r"Final answer: sin y","gold":r"\sin y","expected":True},
    {"name":"radical_expression","output":r"\boxed{\sqrt{12}}","gold":r"2\sqrt{3}","expected":True},
    {"name":"JSON_string_fraction","output":'{"final_answer":"2/5"}',"gold":r"\frac{2}{5}","expected":True},
    {"name":"JSON_float_fraction","output":'{"final_answer":0.4}',"gold":r"\frac{2}{5}","expected":True},
    {"name":"wrong_number","output":r"\boxed{8}","gold":"7","expected":False},
    {"name":"truncated_tuple_no_first_item_rescue","output":r"\boxed{(5,-2,}","gold":"(5,-2,7)","expected":False},
    {"name":"alternatives_not_backend_number_selection","output":r"\boxed{5 or 7}","gold":"7","expected":False},
    {"name":"unbracketed_tuple_not_first_or_last","output":r"\boxed{5,-2,7}","gold":"7","expected":False},
    {"name":"invalid_gold_not_model_failure","output":r"\boxed{7}","gold":r"\frac{","expected":None},
]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--require-backend',action='store_true');args=ap.parse_args()
    started=time.monotonic();checks=[];issues=[]
    for i,(text,status,surface,kind) in enumerate(EXTRACTION_CASES):
        got=grader.extract_final(text);ok=got['status']==status and (surface is None or got.get('surface')==surface) and (kind is None or got.get('answer_kind')==kind)
        checks.append({'name':'extract_'+str(i),'pass':ok,'expected_status':status,'got':got})
        if not ok:issues.append('extract_'+str(i))
    for name,original,expected in [('cot',"cot y",r'\cot y'),('sin',"sin(y)",r'\sin(y)'),('cos',"cos^2 y",r'\cos^2 y'),('not_substring',"cost",'cost'),('already_TeX',r'\cot y',r'\cot y')]:
        ok=grader.normalize_math_surface(original)==expected;checks.append({'name':'normalization_'+name,'pass':ok})
        if not ok:issues.append('normalization_'+name)
    state=grader._backend_state();semantic=[]
    # Explicit hard-deadline routing without waiting20s or constructing pathological algebra.
    import subprocess
    from unittest.mock import patch
    with patch.object(grader,"_backend_state",return_value={"status":"ok"}), patch.object(grader.subprocess,"run",side_effect=subprocess.TimeoutExpired("mock",20)):
        timeout=grader.grade_final(r"\boxed{7}","7")
    timeout_ok=timeout['status']=='grader_timeout' and timeout['correct'] is None
    checks.append({'name':'hard_worker_timeout_mock','pass':timeout_ok})
    if not timeout_ok:issues.append('hard_worker_timeout_mock')
    if state['status']=='ok':
        for item in MATH_CASES:
            got=grader.grade_final(item['output'],item['gold']);ok=got.get('correct') is item['expected']
            semantic.append({'name':item['name'],'expected':item['expected'],'pass':ok,'result':got})
            if not ok:issues.append('math_'+item['name'])
    else:
        check=grader.grade_final(r'\boxed{7}','7')
        if check.get('correct') is not None or check['status']!=state['status']:issues.append('missing_backend_not_explicit')
        if args.require_backend:issues.append('required_backend_missing')
    report={'status':'PASS' if not issues else 'FAIL','scope':'Generic non-bank CPU extraction and optional mathematical smoke; no experimental sample/Gold rules used.',
            'source_sha256':hashlib.sha256(Path(grader.__file__).read_bytes()).hexdigest(),'backend_state':state,
            'extraction_checks':len(checks),'math_checks_executed':len(semantic),'math_checks_planned':len(MATH_CASES),'issues':issues,
            'seconds':time.monotonic()-started,'checks':checks,'semantic_checks':semantic}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','semantic_checks')},ensure_ascii=False,indent=2))
    return 0 if not issues else 2


if __name__=='__main__':raise SystemExit(main())
