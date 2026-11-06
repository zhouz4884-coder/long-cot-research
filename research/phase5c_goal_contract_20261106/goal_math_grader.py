"""Gold-blind final-object extraction and version-pinned mathematical grading.

This is a new contract. It neither imports nor changes the historical grader.
Only grade_final receives gold. Math-Verify runs in a fresh CPU subprocess with
a hard deadline, avoiding fork of a live CUDA process and unbounded parsing.
"""
from __future__ import annotations

import importlib.metadata
import json
from decimal import Decimal
from pathlib import Path
import re
import subprocess
import sys
import time

VERSION = "goal_math_final_v1"
BACKEND_VERSION = "0.9.0"
PARSE_TIMEOUT_SECONDS = 5
GRADE_PROCESS_TIMEOUT_SECONDS = 20
MAX_SURFACE_CHARACTERS = 12000


def _escaped(text, at):
    n = 0
    while at > 0 and text[at - 1] == "\\": n += 1; at -= 1
    return n % 2 == 1


def _balanced(text):
    stack = []
    pairs = {"}": "{", ")": "(", "]": "["}
    for i, c in enumerate(text):
        if _escaped(text, i): continue
        if c in "{([": stack.append(c)
        elif c in "})]":
            if not stack or stack.pop() != pairs[c]: return False
    return not stack


def _peel(text):
    text = text.strip()
    for token in ("<|im_end|>", "<|endoftext|>"):
        if text.endswith(token): text = text[:-len(token)].rstrip()
    # Closing sentence punctuation is not part of the mathematical object.
    text = text.rstrip("。.!！").strip()
    changed = True
    while changed:
        changed = False
        for left, right in (("**", "**"), ("`", "`"), ("$$", "$$"), ("$", "$"), (r"\[", r"\]"), (r"\(", r"\)")):
            if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
                text = text[len(left):-len(right)].strip(); changed = True; break
        text = text.rstrip("。.!！").strip()
    return text


def normalize_math_surface(text):
    text = str(text).strip().replace("−", "-").replace("π", r"\pi")
    text = text.replace("×", r"\cdot ").replace("÷", r"\div ")
    # Repair JSON/source-style doubled TeX command escapes, not matrix row breaks.
    commands = r"(?:dfrac|tfrac|frac|sqrt|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|log|ln|pi|boxed|left|right|begin|end)"
    text = re.sub(r"(?<!\\)\\\\(?=" + commands + r"\b)", lambda _: "\\", text)
    functions = r"(?:arcsin|arccos|arctan|sinh|cosh|tanh|sin|cos|tan|cot|sec|csc|log|ln)"
    text = re.sub(r"(?<![A-Za-z\\])(" + functions + r")(?=\s|\^|[_({])", lambda m: "\\" + m[1], text)
    number = r"\([+-]?\d+(?:\.\d+)?\)"
    text = re.sub("(" + number + r")\s*(?=" + number + ")", lambda m: m[1] + r"\cdot ", text)
    return text


def _split_top(text, delimiter=","):
    result, start, stack = [], 0, []
    pairs = {"}": "{", ")": "(", "]": "["}
    for i,c in enumerate(text):
        if _escaped(text,i): continue
        if c in "{([": stack.append(c)
        elif c in "})]":
            if not stack or stack.pop()!=pairs[c]: return None
        elif c == delimiter and not stack: result.append(text[start:i].strip()); start=i+1
    if stack: return None
    result.append(text[start:].strip())
    return result


def _shape(surface):
    text = re.sub(r"\\(?:left|right)\s*", "", surface).strip()
    match = re.fullmatch(r"\\begin\{(pmatrix|bmatrix|matrix)\}([\s\S]*)\\end\{\1\}", text)
    if match:
        rows = re.split(r"(?<!\\)\\\\(?!\\)",match[2])
        if rows and not rows[-1].strip(): rows.pop()
        cells=[_split_top(row,"&") for row in rows]
        if not cells or any(row is None or any(not x for x in row) for row in cells): return {"answer_kind":"invalid_vector","components":None}
        widths={len(row) for row in cells}
        if len(widths)!=1: return {"answer_kind":"invalid_vector","components":None}
        if len(cells)==1 or next(iter(widths))==1:
            return {"answer_kind":"vector","components":[x for row in cells for x in row],"shape":[len(cells),next(iter(widths))]}
        return {"answer_kind":"matrix","components":None,"shape":[len(cells),next(iter(widths))]}
    if text.startswith("(") and text.endswith(")"):
        parts=_split_top(text[1:-1])
        if parts and len(parts)>1:
            if parts[-1]=="": parts.pop()
            if parts and all(parts): return {"answer_kind":"ordered_tuple","components":parts,"arity":len(parts)}
            return {"answer_kind":"invalid_tuple","components":None}
    return {"answer_kind":"scalar_or_expression","components":None}


def _result(surface, method, evidence, **extra):
    surface=_peel(surface)
    if not surface or len(surface)>MAX_SURFACE_CHARACTERS: return {"status":"unparsed","reason":"empty_or_oversize_final","method":method}
    normalized=normalize_math_surface(surface)
    uncertainty = re.search(r"\b(?:or|either|possibly|perhaps|maybe|probably|uncertain|unsure)\b|\bnot\s+sure\b|\d\s*or\s*[+\-]?\d|不确定|或者|可能是|也许", normalized, re.I)
    if uncertainty:
        return {"status":"ambiguous","reason":"uncertain_or_alternative_final_object","method":method}
    balanced=re.sub(r"\\(?:left|right)\s*", "", normalized)
    if not _balanced(balanced): return {"status":"incomplete","reason":"unbalanced_final_object","method":method}
    shape=_shape(normalized)
    if shape["answer_kind"].startswith("invalid"): return {"status":"incomplete","reason":shape["answer_kind"],"method":method}
    flat = _split_top(re.sub(r"\\(?:left|right)\s*", "", normalized))
    escaped_set = normalized.startswith(r"\{") and normalized.endswith(r"\}") and _balanced(normalized[2:-2])
    if flat and len(flat)>1 and not escaped_set and shape["answer_kind"] not in ("vector", "matrix", "ordered_tuple"):
        return {"status":"ambiguous","reason":"unbracketed_multiple_final_components","method":method}
    return {"status":"ok","surface":surface,"normalized_surface":normalized,"method":method,
            "evidence":evidence,"normalization_applied":surface!=normalized,**shape,**extra}


def _json_extract(text):
    def no_duplicates(pairs):
        obj={}
        for key,value in pairs:
            if key in obj: raise ValueError("duplicate_key")
            obj[key]=value
        return obj
    try:
        obj=json.loads(text,object_pairs_hook=no_duplicates,parse_float=Decimal,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_JSON_number")))
    except (ValueError,TypeError) as exc:
        return {"status":"incomplete" if isinstance(exc,json.JSONDecodeError) else "ambiguous","reason":"invalid_JSON_final_object","error_type":type(exc).__name__}
    if not isinstance(obj,dict) or "final_answer" not in obj: return {"status":"unparsed","reason":"missing_JSON_final_answer"}
    value=obj["final_answer"]
    def scalar(v):
        if type(v) is int or isinstance(v,Decimal): return str(v)
        if isinstance(v,str) and v.strip(): return v.strip()
        raise ValueError("unsupported_JSON_answer_type")
    try:
        if isinstance(value,list):
            if not value: raise ValueError("empty_JSON_list")
            if all(isinstance(v,list) and len(v)==1 for v in value): value=[v[0] for v in value]
            elif len(value)==1 and isinstance(value[0],list): value=value[0]
            parts=[scalar(v) for v in value]
            if not parts: raise ValueError("empty_JSON_list")
            result=_result("("+",".join(parts)+("," if len(parts)==1 else "")+")","JSON_final_answer",{"field":"final_answer"})
            result.update(answer_kind="ordered_tuple",components=[normalize_math_surface(v) for v in parts],arity=len(parts),JSON_list_order_preserved=True)
            return result
        surface=scalar(value)
        if surface.startswith(r"\boxed{"):
            inside=extract_final(surface)
            if inside["status"]!="ok":return inside
            surface=inside["surface"]
        return _result(surface,"JSON_final_answer",{"field":"final_answer"})
    except ValueError as exc:return {"status":"unparsed","reason":str(exc)}


def extract_final(text):
    """Extract a complete explicitly delivered answer; has no gold argument."""
    if not isinstance(text,str): return {"status":"unparsed","reason":"output_not_text"}
    text=text.strip()
    if not text:return {"status":"unparsed","reason":"empty_output"}
    if text.startswith("```"):
        match=re.fullmatch(r"```(?:json)?\s*\n([\s\S]*)\n```",text)
        if match: text=match[1].strip()
        else:return {"status":"incomplete","reason":"incomplete_or_unsupported_code_fence"}
    if text.startswith("{"):return _json_extract(text)
    labels=list(re.finditer(r"(?:最终答案|最后答案|答案)\s*(?:(?:是|为)\s*[:：=]?|[:：=])|(?:final\s+answer|the\s+answer|answer)\s*(?:is\b\s*[:：=]?|[:：=])",text,re.I))
    boxes=[];incomplete_box=False
    for match in re.finditer(r"\\boxed\s*\{",text):
        start=match.end();depth=1;end=None
        for i in range(start,len(text)):
            if _escaped(text,i):continue
            if text[i]=="{":depth+=1
            elif text[i]=="}":depth-=1
            if depth==0:end=i;break
        if end is None:incomplete_box=True
        else:boxes.append({"start":match.start(),"content_start":start,"end":end+1,"surface":text[start:end]})
    if incomplete_box:return {"status":"incomplete","reason":"incomplete_boxed_object"}
    if labels:
        label=labels[-1];tail=_peel(text[label.end():])
        if text[:label.start()].rstrip().endswith("**") and tail.endswith("**"):
            tail=tail[:-2].strip()
        # A bold heading can close immediately before its mathematical payload.
        if tail.startswith("**"):tail=tail[2:].strip()
        candidate_boxes=[b for b in boxes if b["start"]>=label.end()]
        if len(candidate_boxes)>1:
            return {"status":"ambiguous","reason":"multiple_boxed_final_objects_after_final_label"}
        if candidate_boxes:
            b=candidate_boxes[0]
            if _peel(text[b["end"]:]).strip("$*` \\[]()"):
                return {"status":"ambiguous","reason":"nonterminal_boxed_final_object"}
            return _result(b["surface"],"label_and_boxed",{"label_start":label.start(),"span":[b["content_start"],b["end"]-1]})
        return _result(tail,"final_label",{"label_start":label.start(),"span":[label.end(),len(text)]})
    if boxes:
        b=boxes[-1]
        if _peel(text[b["end"]:]).strip("$*` \\[]()"):
            return {"status":"ambiguous","reason":"nonterminal_boxed_answer"}
        if len(boxes)>1:
            between=text[boxes[-2]["end"]:b["start"]]
            if not between.strip(" ,，;；$*`\\()[]\n\t"):
                return {"status":"ambiguous","reason":"adjacent_boxed_components_need_one_complete_object"}
        return _result(b["surface"],"terminal_boxed",{"span":[b["content_start"],b["end"]-1]})
    # Complete standalone mathematical objects are accepted, never a last-number regex.
    raw=_peel(text)
    if re.fullmatch(r"[+\-]?\d+(?:\.\d+)?(?:\s*/\s*[+\-]?\d+)?",raw) or (raw.startswith("(") and raw.endswith(")")):
        return _result(raw,"whole_math_object",{"span":[0,len(text)]})
    return {"status":"unparsed","reason":"missing_explicit_complete_final_object"}


def _backend_state():
    try: found=importlib.metadata.version("math-verify")
    except importlib.metadata.PackageNotFoundError:return {"status":"backend_unavailable","expected_version":BACKEND_VERSION}
    return {"status":"ok" if found==BACKEND_VERSION else "backend_version_mismatch","version":found,"expected_version":BACKEND_VERSION}


def _grade_impl(text,gold):
    extraction=extract_final(text)
    base={"scorer_version":VERSION,"extraction":extraction,"backend":"math_verify","backend_version":BACKEND_VERSION}
    if extraction["status"]!="ok":return {**base,"status":"output_unparsed","correct":False}
    state=_backend_state()
    if state["status"]!="ok":return {**base,**state,"correct":None}
    try:
        from math_verify import parse, verify, LatexExtractionConfig, ExprExtractionConfig
        configs=(LatexExtractionConfig(),ExprExtractionConfig())
        def parsed(surface):
            result=parse(r"\boxed{"+normalize_math_surface(surface)+"}",extraction_config=configs,parsing_timeout=PARSE_TIMEOUT_SECONDS)
            return result if result and not isinstance(result[0],str) else None
        def equal(a,b):
            pa,pb=parsed(a),parsed(b)
            if pa is None or pb is None:return None,pa,pb
            return bool(verify(pb,pa,timeout_seconds=PARSE_TIMEOUT_SECONDS)),pa,pb
        gold_surface=normalize_math_surface(str(gold));gold_surface=_peel(gold_surface)
        # Gold is normally a bare mathematical surface; a complete boxed wrapper is harmless.
        if gold_surface.startswith(r"\boxed{"):
            gg=extract_final(gold_surface)
            if gg["status"]=="ok":gold_surface=gg["normalized_surface"]
        gold_shape=_shape(gold_surface);pc=extraction.get("components");gc=gold_shape.get("components")
        if pc is not None or gc is not None:
            if pc is None or gc is None or len(pc)!=len(gc):return {**base,"status":"ok","correct":False,"comparison":"ordered_object_shape_mismatch","gold_answer_kind":gold_shape["answer_kind"]}
            # Historical vector compatibility: tuple coordinates may express a gold vector.
            if gold_shape["answer_kind"]=="ordered_tuple" and extraction["answer_kind"]=="vector":
                return {**base,"status":"ok","correct":False,"comparison":"ordered_tuple_vs_vector_kind_mismatch"}
            decisions=[];parsed_pairs=[];gold_failures=0
            for a,b in zip(pc,gc):
                ok,pa,pb=equal(a,b);decisions.append(ok);gold_failures+=int(pb is None);parsed_pairs.append({"prediction":str(pa),"gold":str(pb)})
            if gold_failures:return {**base,"status":"gold_parse_failed","correct":None,"comparison":"ordered_components","parsed_pairs":parsed_pairs}
            if any(v is None for v in decisions):return {**base,"status":"math_parse_failed","correct":False,"comparison":"ordered_components","parsed_pairs":parsed_pairs}
            return {**base,"status":"ok","correct":all(decisions),"comparison":"ordered_components","component_count":len(pc),"parsed_pairs":parsed_pairs}
        ok,pa,pb=equal(extraction["normalized_surface"],gold_surface)
        if pb is None:return {**base,"status":"gold_parse_failed","correct":None,"comparison":"scalar_or_expression","parsed":str(pa),"gold_parsed":str(pb)}
        return {**base,"status":"ok" if ok is not None else "math_parse_failed","correct":False if ok is None else ok,"comparison":"scalar_or_expression","parsed":str(pa),"gold_parsed":str(pb)}
    except Exception as exc:
        timeout="timeout" in type(exc).__name__.lower() or "timedout" in type(exc).__name__.lower()
        return {**base,"status":"grader_timeout" if timeout else "grader_error","correct":None,"error_type":type(exc).__name__,"error":str(exc)[:300]}


def grade_final(text,gold):
    """Posthoc grading only; hard CPU worker timeout is explicit, not an incorrect answer."""
    extraction=extract_final(text)
    base={"scorer_version":VERSION,"extraction":extraction,"backend":"math_verify","backend_version":BACKEND_VERSION}
    if extraction["status"]!="ok":return {**base,"status":"output_unparsed","correct":False}
    state=_backend_state()
    if state["status"]!="ok":return {**base,**state,"correct":None}
    started=time.monotonic()
    try:
        run=subprocess.run([sys.executable,"-I",str(Path(__file__).resolve()),"--grade-worker"],
            input=json.dumps({"text":text,"gold":str(gold)},ensure_ascii=False),capture_output=True,text=True,encoding="utf-8",
            timeout=GRADE_PROCESS_TIMEOUT_SECONDS,check=False)
        if run.returncode:return {**base,"status":"grader_worker_error","correct":None,"returncode":run.returncode,"stderr":run.stderr[-300:]}
        result=json.loads(run.stdout);result["grading_wall_seconds"]=time.monotonic()-started;return result
    except subprocess.TimeoutExpired:return {**base,"status":"grader_timeout","correct":None,"timeout_seconds":GRADE_PROCESS_TIMEOUT_SECONDS}
    except (ValueError,OSError) as exc:return {**base,"status":"grader_worker_error","correct":None,"error_type":type(exc).__name__}


if __name__=="__main__":
    if sys.argv[1:]==["--grade-worker"]:
        import contextlib,io
        payload=json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()):answer=_grade_impl(payload["text"],payload["gold"])
        print(json.dumps(answer,ensure_ascii=False,allow_nan=False))
    else:raise SystemExit("Import extract_final(text) or grade_final(text,gold)")
