"""Gold-blind retrospective answer policies; not a truth or checkpoint selector.

LastBox/LastFinalAnswer are fixed textual position policies, never gold-best
selection. Surface disagreement is flagged, not equated to logical falsity.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import re

VERSION = "phase5d_d0_answer_policies_v1"
POLICIES = ("LastBox", "LastFinalAnswer", "FirstCompleteAnswer", "ConservativeFinal")
MAX_SURFACE = 12000
_FINAL = re.compile(r"(?:final\s+answer|最终答案|最后答案)(?:\s*\*\*)?\s*(?:(?:is\b|是|为)\s*)?[:：=]?", re.I)
_ALT = re.compile(r"(?<![A-Za-z\\])(?:or|either|possibly|perhaps|maybe|probably|uncertain|unsure)(?=\s|[+\-\d]|$)|\bnot\s+sure\b|或者|不确定|也许|可能是", re.I)


def digest(text): return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _escaped(text, i):
    n=0
    while i>0 and text[i-1]=="\\": n+=1;i-=1
    return bool(n%2)


def _brace_end(text, start, opening="{", closing="}"):
    depth=1
    for i in range(start,len(text)):
        if _escaped(text,i):continue
        if text[i]==opening:depth+=1
        elif text[i]==closing:depth-=1
        if depth==0:return i+1
    return None


def normalize_surface(text):
    text=text.strip().replace("−","-").replace("π",r"\pi").replace("×",r"\cdot ").replace("÷",r"\div ")
    commands=r"(?:dfrac|tfrac|frac|sqrt|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|log|ln|pi|left|right|begin|end|infty|cup)"
    text=re.sub(r"(?<!\\)\\\\(?="+commands+r"\b)",lambda _:"\\",text)
    functions=r"(?:arcsin|arccos|arctan|sinh|cosh|tanh|sin|cos|tan|cot|sec|csc|log|ln)"
    text=re.sub(r"(?<![A-Za-z\\])("+functions+r")(?=\s|\^|[_({])",lambda m:"\\"+m[1],text)
    return text


def peel(text):
    text=text.strip()
    for marker in ("</think>","<|im_end|>","<|endoftext|>"):
        if text.endswith(marker):text=text[:-len(marker)].rstrip()
    text=text.rstrip("。.!！").strip()
    for _ in range(8):
        for left,right in (("**","**"),("`","`"),("$$","$$"),("$","$"),(r"\[",r"\]"),(r"\(",r"\)")):
            if text.startswith(left) and text.endswith(right) and len(text)>len(left)+len(right):
                text=text[len(left):-len(right)].strip();break
        else:break
    return text.rstrip("。.!！").strip()


def split_top(text, delimiter=","):
    # Used only inside an outer tuple/interval/vector; braces and nested pairs
    # protect internal commas. Mismatched outer interval ends are handled later.
    out=[];start=0;stack=[]
    pairs={"}":"{",")":"(","]":"["}
    for i,c in enumerate(text):
        if _escaped(text,i):continue
        if c in "{([":stack.append(c)
        elif c in "})]":
            if not stack or stack.pop()!=pairs[c]:return None
        elif c==delimiter and not stack:out.append(text[start:i].strip());start=i+1
    if stack:return None
    out.append(text[start:].strip());return out


def structural_status(surface):
    text=re.sub(r"\\(?:left|right)\s*","",normalize_surface(peel(surface)))
    if not text or len(text)>MAX_SURFACE:return "unknown","empty_or_oversize"
    if _ALT.search(text):return "ambiguous","explicit_uncertainty_or_alternatives"
    # A single bracketed pair may be an interval (mixed ends are legal), an
    # ordered pair, or a row-vector notation. Do not invent its semantic role.
    if text[0:1] in ("(","[") and text[-1:] in (")","]"):
        parts=split_top(text[1:-1])
        if parts and len(parts)>=2 and all(parts):return "ok","bracketed_object"
    if text.startswith(r"\{") and text.endswith(r"\}"):
        parts=split_top(text[2:-2])
        if parts and all(parts):return "ok","explicit_finite_set_surface"
    if split_top(text) is None:return "incomplete","unbalanced_object"
    parts=split_top(text)
    if parts and len(parts)>1:return "ambiguous","unbracketed_components"
    begins=list(re.finditer(r"\\begin\{([^}]+)\}",text));ends=list(re.finditer(r"\\end\{([^}]+)\}",text))
    if [m[1] for m in begins]!=[m[1] for m in ends]:return "incomplete","unclosed_environment"
    return "ok","math_surface_not_truth_checked"


def scan_boxes(text):
    complete=[];unclosed=[]
    for m in re.finditer(r"\\boxed\s*\{",text):
        end=_brace_end(text,m.end())
        if end is None:unclosed.append(m.start())
        else:complete.append({"kind":"boxed","start":m.start(),"end":end,"surface":text[m.end():end-1]})
    return complete,unclosed


def _payload(text, start):
    """Read an explicitly labelled object, not an arbitrary last number."""
    cursor=start
    while cursor<len(text) and text[cursor] in " \t\r\n:*`":cursor+=1
    if cursor>=len(text):return None,"empty_final_label"
    tail=text[cursor:]
    box=re.match(r"\\boxed\s*\{",tail)
    if box:
        end=_brace_end(tail,box.end())
        if end is None:return None,"unclosed_label_box"
        return {"kind":"final_label","start":start,"end":cursor+end,"surface":tail[box.end():end-1]},None
    for left,right in (("$$","$$"),("$","$"),(r"\[",r"\]"),(r"\(",r"\)")):
        if tail.startswith(left):
            at=tail.find(right,len(left))
            if at<0:return None,"unclosed_math_wrapper"
            return {"kind":"final_label","start":start,"end":cursor+at+len(right),"surface":tail[len(left):at]},None
    matrix=re.match(r"\\begin\{(pmatrix|bmatrix|matrix)\}",tail)
    if matrix:
        closing=r"\end{"+matrix[1]+"}";at=tail.find(closing,matrix.end())
        if at<0:return None,"unclosed_matrix"
        end=at+len(closing);return {"kind":"final_label","start":start,"end":cursor+end,"surface":tail[:end]},None
    line=tail.splitlines()[0].strip()
    # Plain final-labelled scalar followed by a natural-language unit is legal.
    # A competing mathematical alternative is never silently stripped.
    numeric=re.match(r"[+-]?\d+(?:\.\d+)?(?:\s*/\s*[+-]?\d+)?%?",line)
    if numeric:
        suffix=line[numeric.end():]
        if _ALT.search(suffix):return None,"alternative_label_payload"
        if not suffix.strip(" .。!！") or re.fullmatch(r"\s+[A-Za-z][A-Za-z -]*[.!]?",suffix):
            return {"kind":"final_label","start":start,"end":cursor+numeric.end(),"surface":numeric[0]},None
    # General explicitly labelled expression. Restrict prose and delimiters;
    # mathematical interpretation remains the independent backend's job.
    line=peel(line)
    if not line:return None,"empty_final_object"
    words=re.findall(r"(?<!\\)\b[A-Za-z]{2,}\b",line)
    allowed={"sin","cos","tan","cot","sec","csc","log","ln","sqrt","exp","pi","infty","infinity"}
    tex_commands=set(re.findall(r"\\([A-Za-z]+)",line))
    if any(w.lower() not in allowed and w not in tex_commands for w in words):return None,"unsupported_prose_payload"
    return {"kind":"final_label","start":start,"end":cursor+len(line),"surface":line},None


def scan_final_labels(text):
    found=[];unresolved=[]
    for m in _FINAL.finditer(text):
        item,reason=_payload(text,m.end())
        if item:
            item["label_start"]=m.start();found.append(item)
        else:unresolved.append({"start":m.start(),"reason":reason})
    return found,unresolved


def fingerprint(surface):
    text=re.sub(r"\\(?:left|right)\s*","",normalize_surface(peel(surface)))
    compact=re.sub(r"\s+","",text)
    frac=re.fullmatch(r"\\(?:dfrac|tfrac|frac)\{([+-]?\d+)\}\{([+-]?\d+)\}",compact)
    try:
        if frac:return "rational:"+str(Fraction(int(frac[1]),int(frac[2])))
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:/[+-]?\d+)?",compact):return "rational:"+str(Fraction(compact))
    except (ValueError,ZeroDivisionError):pass
    return "surface:"+compact


def extract_policy(text, policy="LastBox"):
    if policy not in POLICIES:raise ValueError("Unknown selection policy")
    if not isinstance(text,str):raise TypeError("Only output text is accepted; no evaluator dictionary")
    boxes,unclosed=scan_boxes(text);labels,bad_labels=scan_final_labels(text)
    candidates=boxes+labels
    # A label and its wrapped box identify one object, not two independent answers.
    uniq={}
    for c in candidates:uniq[(c["end"],fingerprint(c["surface"]))]=c
    candidates=sorted(uniq.values(),key=lambda c:(c.get("label_start",c["start"]),c["end"]))
    signals={"boxed_count":len(boxes),"final_label_count":len(labels),"unclosed_box_starts":unclosed,
             "unresolved_final_labels":bad_labels,"distinct_surface_count":len({fingerprint(c["surface"]) for c in candidates}),
             "surface_disagreement_is_not_certified_logical_conflict":True}
    base={"version":VERSION,"policy":policy,"text_sha256":digest(text),"signals":signals,
          "selection_uses_gold":False,"truth_certified":False}
    if policy=="LastBox":selected=boxes[-1] if boxes else None
    elif policy=="LastFinalAnswer":selected=labels[-1] if labels else None
    elif policy=="FirstCompleteAnswer":selected=candidates[0] if candidates else None
    else:
        if len({fingerprint(c["surface"]) for c in candidates})>1:return {**base,"status":"ambiguous","reason":"different_explicit_candidate_surfaces"}
        selected=candidates[-1] if candidates else None
    if selected is None:return {**base,"status":"unknown","reason":"no_complete_candidate"}
    if policy!="FirstCompleteAnswer" and any(at>=selected["end"] for at in unclosed):
        return {**base,"status":"incomplete","reason":"later_box_is_unclosed"}
    if policy in ("LastFinalAnswer","ConservativeFinal") and any(v["start"]>=selected["end"] for v in bad_labels):
        return {**base,"status":"incomplete","reason":"later_final_label_unresolved"}
    # Adjacent independent boxes are an incomplete multi-object delivery, not a
    # license to return just the final coordinate of an unwrapped tuple.
    if policy=="LastBox" and len(boxes)>1:
        gap=text[boxes[-2]["end"]:selected["start"]]
        if not gap.strip(" ,，;；$*`\\()[]\n\t"):
            return {**base,"status":"ambiguous","reason":"adjacent_boxed_components_need_complete_object"}
    suffix_line=text[selected["end"]:].splitlines()[0] if text[selected["end"]:] else ""
    if _ALT.search(suffix_line):return {**base,"status":"ambiguous","reason":"explicit_alternative_after_selected_object"}
    status,reason=structural_status(selected["surface"])
    if status!="ok":return {**base,"status":status,"reason":reason}
    return {**base,"status":"ok","surface":peel(selected["surface"]),"normalized_surface":normalize_surface(peel(selected["surface"])),
            "selected_span":[selected["start"],selected["end"]],"selected_kind":selected["kind"],
            "reason":"fixed_position_policy_not_gold_best"}
