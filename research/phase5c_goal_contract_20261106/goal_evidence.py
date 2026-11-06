"""Question-only goal hints and unverified, provenance-preserving trace excerpts.

This is a deterministic heuristic input selector, not a truth gate, dependency
parser, or certified parent-boundary extractor. It never reads files or Gold.
Both full-history and projected arms must reuse the SAME returned packet.
"""
from __future__ import annotations

import hashlib
import re

VERSION = "goal_evidence_heuristic_v1"
DEFAULT_MAX_CHARS = 1800
DEFAULT_MAX_SPANS = 8
_QUERY = re.compile(r"\b(?:find|compute|determine|evaluate|enter|what\s+is|what\s+are|how\s+many|which\s+vector)\b", re.I)
_CONCLUSION = re.compile(r"\b(?:therefore|thus|hence|conclusion|answer|we\s+get|it\s+follows)\b|最终答案|所以|因此|结论", re.I)
_DISCOURSE = re.compile(r"\b(?:wait|hold\s+on|mistake|incorrect|wrong|reconsider|correction)\b|不对|等等|有误|纠正|重新计算", re.I)
_ANSWER = re.compile(r"\b(?:final\s+answer|the\s+answer|answer\s+is)\b|\banswer\s*[:=]|最终答案", re.I)
_STOP = frozenset("the a an of to in on and or is are be this that these those with by for from as at it its has have let such which what how find compute determine evaluate enter value values answer following given problem then all each any one two three".split())


def _check_text(value, name):
    if not isinstance(value, str):
        raise TypeError(name + " must be a string; evaluator dictionaries are not accepted")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derive_contract(question: str) -> dict:
    """Extract soft target/type hints from question text only, never solve it."""
    _check_text(question, "question")
    # Diagram source after the query is not a later mathematical goal.
    stop = question.lower().find("[asy]")
    stop = len(question) if stop < 0 else stop
    ordinary = question[:stop]
    queries = list(_QUERY.finditer(ordinary))
    start = queries[-1].start() if queries else 0
    end = stop
    while start < end and question[start].isspace(): start += 1
    while end > start and question[end-1].isspace(): end -= 1
    clause = question[start:end]
    target_status = "SOURCE_QUERY_CLAUSE" if queries else "UNKNOWN_TARGET_FULL_QUESTION"
    if len(clause) > 1200:
        # The original P remains available to every arm. Never pretend a cut
        # clause contains a complete extracted mathematical target.
        clause = clause[:1200]
        end = start + len(clause)
        target_status = "UNKNOWN_TARGET_TRUNCATED"
    low = clause.lower()
    arity = None
    representation = "unspecified"
    if re.search(r"\bhow\s+many\b|\b(?:find|determine|compute)\s+(?:the\s+)?(?:total\s+)?number\s+of\b", low):
        kind, hint = "count", "交付题目所问的数量；被计数对象的坐标/分量不是数量本身。"
    elif re.search(r"\bprobability\b", low):
        kind = "probability"
        representation = "percentage" if re.search(r"\bpercent(?:age)?\b|%", low) else "equivalent_numeric_forms"
        hint = "交付概率而非仅有利情况计数；0和1合法，分数与等价小数均可，遵从题目要求的比例尺度。"
    elif re.search(r"\bordered\s+(?:pair|triple|quadruple|tuple)\b", low):
        kind = "ordered_tuple"
        arity = next((n for word, n in (("pair", 2), ("triple", 3), ("quadruple", 4))
                      if re.search(r"\bordered\s+" + word + r"\b", low)), None)
        hint = "交付完整有序对象并保持分量次序；单个分量不自动构成完整答案。"
    elif re.search(r"\bwhich\s+vector\b|\b(?:find|determine|compute)\b[\s\S]{0,70}\bvector\b", low):
        kind, hint = "vector", "交付题目要求的整个向量；不能仅交一个坐标。"
    else:
        kind, hint = "unknown", "类型/终局映射未被规则可靠识别；依据完整原题交付所问对象。"
    return {
        "version": VERSION, "status": target_status, "target_quote": clause,
        "target_span": [start, end], "question_sha256": _sha(question),
        "answer_type_hint": kind, "tuple_arity_hint": arity,
        "representation_hint": representation, "instruction": hint,
        "semantic_certification": "UNVERIFIED_QUESTION_PATTERN_HINT",
        "terminal_map": "NOT_AUTOMATICALLY_DERIVED",
        "forbidden_intermediate_values": [],
        "notes": "Hints do not certify a solution. No numeric blacklist or truth claim is created.",
    }


def _paragraphs(trace):
    result = []
    for i, match in enumerate(re.finditer(r"\S[\s\S]*?(?=\n[ \t]*\n|\Z)", trace)):
        result.append({"index": i, "start": match.start(), "end": match.end(), "text": match.group()})
    return result


def _boxes(text):
    """Find complete nested-brace boxes; their contents remain unverified text."""
    result = []
    for match in re.finditer(r"\\boxed\s*\{", text):
        depth = 1; cursor = match.end()
        while cursor < len(text) and depth:
            if text[cursor] == "{" and (cursor == 0 or text[cursor-1] != "\\"): depth += 1
            elif text[cursor] == "}" and (cursor == 0 or text[cursor-1] != "\\"): depth -= 1
            cursor += 1
        if depth == 0:
            result.append({"start": match.start(), "end": cursor, "surface": text[match.end():cursor-1]})
    return result


def _goal_words(question):
    contract = derive_contract(question)
    return {w.lower() for w in re.findall(r"[A-Za-z]{2,}", contract["target_quote"])
            if w.lower() not in _STOP}


def _quote_window(paragraph, anchor, width, trace):
    start, end = paragraph["start"], paragraph["end"]
    if end-start > width:
        center = start + anchor
        start = max(start, min(center-width//3, end-width))
        end = start + width
    return start, end, trace[start:end]


def last_tail_packet(trace: str, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    _check_text(trace, "trace")
    if type(max_chars) is not int or max_chars < 256:
        raise ValueError("max_chars must be an integer >=256")
    start = max(0, len(trace)-max_chars)
    return {"version": VERSION, "status": "TAIL_ONLY_UNVERIFIED", "trace_sha256": _sha(trace),
            "max_quote_chars": max_chars, "selected_quote_chars": len(trace)-start,
            "spans": [{"start": start, "end": len(trace), "text": trace[start:],
                       "status": "UNVERIFIED", "reason": ["fixed_last_characters"]}] if trace else [],
            "semantic_conflict_verdict": "UNKNOWN", "certified_parent_boundary": False,
            "G_status": "NOT_IMPLEMENTED_NO_TRUTH_ARBITRATION", "boxed_surface_variants_count": 0,
            "surface_conflict_signal": False,
            "notes": "Fixed tail only, may omit necessary premises and may contain wrong or rejected conclusions."}


def build_evidence_packet(question: str, trace: str, max_chars: int = DEFAULT_MAX_CHARS,
                          max_spans: int = DEFAULT_MAX_SPANS) -> dict:
    """Select source quotes, not truth. Same packet must be reused across arms.

    Priority reserves early/latest answer candidates, then target-related
    calculation/conclusion paragraphs. Exact quotations and character offsets
    are retained. Different boxed surfaces are NOT assumed mathematically
    different or assigned correct/incorrect labels.
    """
    _check_text(question, "question"); _check_text(trace, "trace")
    if type(max_chars) is not int or max_chars < 256: raise ValueError("max_chars must be integer>=256")
    if type(max_spans) is not int or max_spans < 1: raise ValueError("max_spans must be positive integer")
    contract = derive_contract(question); words = _goal_words(question); paras = _paragraphs(trace)
    candidates = []
    for p in paras:
        text = p["text"]; boxes = _boxes(text); answer = _ANSWER.search(text)
        conclusion = _CONCLUSION.search(text); discourse = _DISCOURSE.search(text)
        overlap = sorted(words & {w.lower() for w in re.findall(r"[A-Za-z]{2,}", text)})
        equation = "=" in text or "\\frac" in text
        score = min(6, len(overlap)) * 2 + bool(boxes)*12 + bool(answer)*7 + bool(conclusion)*3 + equation*2
        anchor = boxes[0]["start"] if boxes else answer.start() if answer else conclusion.start() if conclusion else 0
        candidates.append({**p, "boxes": boxes, "explicit_answer": bool(answer), "conclusion_cue": bool(conclusion),
                           "revision_discourse_cue": bool(discourse), "goal_word_overlap": overlap,
                           "equation_surface": equation, "heuristic_score": score, "anchor": anchor})
    answer_indices = [i for i,p in enumerate(candidates) if p["boxes"] or p["explicit_answer"]]
    meaningful = [p for p in candidates if p["heuristic_score"] >= 5]
    if not meaningful:
        fallback = last_tail_packet(trace, max_chars)
        fallback.update(status="UNKNOWN_NO_CANDIDATE_FALLBACK_TAIL", contract=contract,
                        question_sha256=_sha(question), max_spans=max_spans,
                        selection_uses=["question target words", "trace text only"],
                        unknown_reason="No sufficiently marked calculation/conclusion candidate; tail is not certified.")
        return fallback
    priority = []
    # Reserve both ends: do not silently prefer the last conclusion as truth.
    if answer_indices:
        priority.extend([answer_indices[0], answer_indices[-1]])
    ranked = sorted(range(len(candidates)), key=lambda i:(-candidates[i]["heuristic_score"],-i))
    priority.extend(ranked)
    selected=[];used=set();remaining=max_chars
    width=min(480,max(128,max_chars//max(3,min(max_spans,5))))
    for i in priority:
        if i in used or len(selected)>=max_spans or remaining<=0: continue
        p=candidates[i]
        if p["heuristic_score"]<5: continue
        used.add(i)
        begin,end,text=_quote_window(p,p["anchor"],min(width,remaining),trace)
        if not text: continue
        reasons=[]
        if p["boxes"]:reasons.append("complete_boxed_candidate_surface")
        if p["explicit_answer"]:reasons.append("explicit_answer_discourse")
        if p["goal_word_overlap"]:reasons.append("target_word_overlap")
        if p["equation_surface"]:reasons.append("calculation_surface")
        if p["conclusion_cue"]:reasons.append("conclusion_discourse")
        selected.append({"start":begin,"end":end,"text":text,"paragraph_index":i,
                         "status":"UNVERIFIED","reason":reasons,
                         "revision_discourse_cue":p["revision_discourse_cue"],
                         "goal_word_overlap":p["goal_word_overlap"]})
        remaining-=len(text)
    selected.sort(key=lambda p:p["start"])
    surfaces=[]
    for p in candidates:
        for box in p["boxes"]:
            surface=re.sub(r"\s+","",box["surface"])
            if surface not in surfaces:surfaces.append(surface)
    return {"version":VERSION,"status":"UNVERIFIED_CANDIDATE_QUOTES","contract":contract,
            "question_sha256":_sha(question),"trace_sha256":_sha(trace),
            "max_quote_chars":max_chars,"max_spans":max_spans,
            "selected_quote_chars":sum(len(v["text"]) for v in selected),"spans":selected,
            "boxed_surface_variants_count":len(surfaces),
            "surface_conflict_signal":len(surfaces)>1,
            "surface_conflict_meaning":"Different text surfaces only; equivalent forms and wrong candidates remain possible.",
            "semantic_conflict_verdict":"UNKNOWN","certified_parent_boundary":False,
            "G_status":"NOT_IMPLEMENTED_NO_TRUTH_ARBITRATION",
            "selection_uses":["question target words","trace conclusion/equation/boxed surfaces","source order"],
            "omitted_characters":max(0,len(trace)-sum(len(v["text"]) for v in selected)),
            "notes":"Quotes may omit necessary premises or contain wrong/rejected statements. Never label them certified parents."}


def render_contract(contract: dict) -> str:
    arity=contract.get("tuple_arity_hint")
    extra=f"；显式有序对象分量数提示={arity}" if arity is not None else ""
    return ("原题目标原文："+contract["target_quote"]+"\n"
            +"目标类型提示="+contract["answer_type_hint"]+extra+"。"+contract["instruction"]
            +"\n这只是从题干提取的目标提示，不是已验证答案；仍须依据完整原题检查。")


def render_evidence(packet: dict) -> str:
    pieces=["历史轨迹的候选摘录（全部未经核验；先后位置和多个候选本身不决定真伪）："]
    for i,span in enumerate(packet["spans"],1):
        pieces.append(f"[摘录{i}]\n"+span["text"])
    if not packet["spans"]:pieces.append("没有可用摘录；不能据此认定没有支持，依据原题处理。")
    return "\n\n".join(pieces)

