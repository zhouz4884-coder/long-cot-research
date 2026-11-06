"""New D0 selected-surface semantics, isolated CPU Math-Verify0.9.0.

Extraction has already occurred without Gold. Gold is used only here, never to
select among candidates. A subprocess hard deadline bounds semantic parsing.
"""
from __future__ import annotations
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from d0_answer_extract import normalize_surface, peel, split_top

VERSION="phase5d_d0_selected_surface_v1"
BACKEND="0.9.0"


def _surface(s):
    s=normalize_surface(peel(str(s))).replace("∞",r"\infty")
    if s.startswith(r"\boxed{") and s.endswith("}"):s=s[7:-1]
    return re.sub(r"\\(?:left|right)\s*","",s).strip()


def _vector(s):
    m=re.fullmatch(r"\\begin\{(pmatrix|bmatrix|matrix)\}([\s\S]*)\\end\{\1\}",s)
    if not m:return None
    rows=re.split(r"(?<!\\)\\\\(?!\\)",m[2])
    if rows and not rows[-1].strip():rows.pop()
    cells=[split_top(v,"&") for v in rows]
    if not cells or any(v is None or any(not c for c in v) for v in cells):return None
    widths={len(v) for v in cells}
    if len(widths)!=1 or (len(cells)!=1 and next(iter(widths))!=1):return None
    return [v for row in cells for v in row]


def _tuple(s):
    if s.startswith("(") and s.endswith(")"):
        values=split_top(s[1:-1])
        if values and len(values)>1 and all(values):return values
    return None


def _interval(s):
    if s[0:1] in ("(","[") and s[-1:] in (")","]"):
        values=split_top(s[1:-1])
        if values and len(values)==2 and all(values):return (s[0],s[-1],values)
    return None


def _impl(surface,gold):
    try:version=importlib.metadata.version('math-verify')
    except importlib.metadata.PackageNotFoundError:return {'status':'backend_unavailable','correct':None}
    if version!=BACKEND:return {'status':'backend_version_mismatch','correct':None,'found':version}
    from math_verify import parse,verify,LatexExtractionConfig,ExprExtractionConfig
    from sympy import Interval
    config=(LatexExtractionConfig(),ExprExtractionConfig())
    a,b=_surface(surface),_surface(gold)
    def parsed(v):
        result=parse(r'\boxed{'+v+'}',extraction_config=config,parsing_timeout=5)
        return result if result and not isinstance(result[0],str) else None
    def equal(x,y):
        pa,pb=parsed(x),parsed(y)
        if pa is None or pb is None:return None
        return bool(verify(pb,pa,timeout_seconds=5))
    ia,ib=_interval(a),_interval(b)
    # Mixed/closed square brackets explicitly encode endpoint closure. An open
    # pair is otherwise left as an ordered-object ambiguity for the backend.
    interval_mode=bool(ia and ib and any(c in '[]' for c in (ia[0],ia[1],ib[0],ib[1])))
    if interval_mode:
        if ia[:2]!=ib[:2]:return {'status':'ok','correct':False,'comparison':'interval_endpoint_closure_mismatch'}
        values=[equal(x,y) for x,y in zip(ia[2],ib[2])]
        return {'status':'ok' if None not in values else 'math_parse_unknown','correct':all(values) if None not in values else None,'comparison':'ordered_interval_endpoints','component_results':values}
    va,vb=_vector(a),_vector(b)
    ta,tb=_tuple(a),_tuple(b)
    if vb is not None:
        ca=va if va is not None else ta
        if ca is None or len(ca)!=len(vb):return {'status':'ok','correct':False,'comparison':'vector_shape_mismatch'}
        values=[equal(x,y) for x,y in zip(ca,vb)]
        return {'status':'ok' if None not in values else 'math_parse_unknown','correct':all(values) if None not in values else None,'comparison':'ordered_vector_coordinates','component_results':values}
    if tb is not None:
        if ta is None or len(ta)!=len(tb):return {'status':'ok','correct':False,'comparison':'tuple_shape_mismatch'}
        values=[equal(x,y) for x,y in zip(ta,tb)]
        return {'status':'ok' if None not in values else 'math_parse_unknown','correct':all(values) if None not in values else None,'comparison':'ordered_tuple_components','component_results':values}
    pa,pb=parsed(a),parsed(b)
    if pb is None:return {'status':'gold_parse_unknown','correct':None}
    if pa is None:return {'status':'candidate_math_parse_unknown','correct':None}
    return {'status':'ok','correct':bool(verify(pb,pa,timeout_seconds=5)),'comparison':'math_verify_whole_object','parsed_candidate':str(pa),'parsed_gold':str(pb)}


def grade_selected(extraction,gold):
    if extraction.get('status')!='ok':return {'status':'selection_abstained','correct':False,'mathematical_correctness':None,'selection_status':extraction.get('status')}
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    try:
        proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--math-worker'],
            input=json.dumps({'surface':extraction['surface'],'gold':str(gold)}),text=True,capture_output=True,env=env,timeout=20,check=False)
        if proc.returncode:return {'status':'backend_error','correct':None,'return_code':proc.returncode,'stderr_tail':proc.stderr[-1200:]}
        result=json.loads(proc.stdout);result['grader_version']=VERSION;result['backend_version']=BACKEND;return result
    except subprocess.TimeoutExpired:return {'status':'backend_timeout','correct':None,'timeout_seconds':20}
    except (ValueError,OSError) as exc:return {'status':'backend_error','correct':None,'error_type':type(exc).__name__}


if __name__=='__main__':
    if sys.argv[1:]!=['--math-worker']:raise SystemExit('Use grade_selected or explicit --math-worker')
    payload=json.load(sys.stdin)
    try:answer=_impl(payload['surface'],payload['gold'])
    except BaseException as exc:answer={'status':'backend_error','correct':None,'error_type':type(exc).__name__}
    print(json.dumps(answer,ensure_ascii=False))
