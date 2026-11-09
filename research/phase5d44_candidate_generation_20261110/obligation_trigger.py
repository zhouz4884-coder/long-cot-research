"""Find a committed thinking-channel integer that violates a reviewed necessity."""
from __future__ import annotations

import hashlib
import re


HEADING = re.compile(r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:[✅✓][ \t]*)?(?:\*\*)?"
                     r"final[ \t]+answer\b(?:[ \t]*:)?(?:\*\*)?(?:[ \t]*:)?[ \t]*")
BOX = re.compile(r"\\boxed\s*\{\s*(?P<integer>[+-]?[0-9]{1,18})\s*\}")
END = re.compile(r"(?:\s|[.$!。*]|\\[\]\)])*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
WINDOW = 720
SCOPE_WINDOW = 3000
SCOPE_PATTERNS = {
    "2012-I-4": [r"\bn\s*\+[\s$\\]*t\b|(?:distance|milepost).{0,110}(?:minutes|elapsed)|(?:minutes|elapsed).{0,110}(?:distance|milepost)"],
    "2009-II-12": [r"(?:max(?:imum)?|most|largest|greatest).{0,90}(?:\bk\b|pair)|(?:\bk\b|pairs).{0,90}(?:maximum|optimal)"],
    "2023-II-2": [r"\bpalindrome", r"\b(?:greatest|largest|maximum)\b"],
    "2016-I-9": [r"\b(?:rectangle|AQRS)\b", r"(?:max(?:imum)?|greatest|largest).{0,100}area|area.{0,100}(?:max(?:imum)?|greatest|largest)"],
    "2012-I-10": [r"\b(?:tenth|10th)\b", r"\b(?:remainder|mod(?:ulo)?)\b.{0,45}(?:1[ ,]?000|10\^3)"],
    "2018-I-11": [r"\b(?:143|suffix)\b", r"\b(?:least|smallest|min(?:imum)?)\b.{0,70}\b(?:exponent|n)\b"],
    "2012-II-8": [r"zw\b|modulus|magnitude|\|\s*u\s*\|", r"\b(?:smallest|min(?:imum)?|smaller)\b"],
    "2019-I-5": [r"\bm\s*\+[\s$\\]*n\b", r"\borigin\b|\(0\s*,\s*0\)"],
    "2017-I-9": [r"\b(?:99|divisib\w*)\b", r"\b(?:least|smallest|first|min(?:imum)?)\b"],
    "2009-II-8": [r"\bm\s*\+[\s$\\]*n\b", r"\b(?:rolls?|stopping)\b"],
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def valid_sha(value) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def approved_obligation(case: dict) -> dict | None:
    item = case.get("obligation")
    if not isinstance(item, dict):
        return None
    if (
        case.get("problem_kind") not in {"EXTREMUM", "FIRST_EVENT"}
        or item.get("question_sha256") != case.get("question_sha256")
        or not valid_sha(case.get("question_sha256"))
        or not valid_sha(item.get("review_sha256"))
        or not valid_sha(item.get("proof_sha256"))
        or not isinstance(item.get("cue"), str) or not item["cue"].strip()
        or len(item["cue"]) > 480 or "<|" in item["cue"] or "<think>" in item["cue"] or "</think>" in item["cue"]
    ):
        return None
    kind, args = item.get("kind"), item.get("args")
    if not item.get("scope_patterns") or item["scope_patterns"] != SCOPE_PATTERNS.get(case.get("case_id")):
        return None
    if not isinstance(args, list) or not all(type(value) is int and abs(value) < 10**18 for value in args):
        return None
    if kind == "congruence" and len(args) == 2 and args[0] >= 2 and 0 <= args[1] < args[0]:
        return item
    if kind == "closed_interval" and len(args) == 2 and args[0] < args[1] and args != [0, 999]:
        return item
    if kind == "finite_exclusions" and 1 <= len(args) <= 16 and args == sorted(set(args)):
        return item
    return None


def check(value: int, item: dict) -> tuple[bool, dict]:
    kind, args = item["kind"], item["args"]
    if kind == "congruence":
        modulus, residue = args
        observed = value % modulus
        return observed != residue, {"modulus": modulus, "expected_residue": residue, "observed_residue": observed}
    if kind == "closed_interval":
        lo, hi = args
        return not lo <= value <= hi, {"lo": lo, "hi": hi}
    return value in args, {"excluded_values": args}


def claim_at_frontier(thinking_text: str) -> tuple[int, int, int] | None:
    start = max(0, len(thinking_text) - WINDOW)
    headings = list(HEADING.finditer(thinking_text, start))
    if not headings:
        return None
    heading = headings[-1]
    boxes = list(BOX.finditer(thinking_text, heading.end()))
    if len(boxes) != 1:
        return None
    box = boxes[0]
    if not END.fullmatch(thinking_text, box.end()) or r"\boxed" in thinking_text[heading.end():box.start()]:
        return None
    return int(box["integer"]), heading.start(), box.end()


def detect(case: dict, thinking_text: str) -> dict | None:
    """Return evidence tied to a candidate at the currently observed open frontier."""
    item = approved_obligation(case)
    if item is None or "</think>" in thinking_text[-WINDOW:]:
        return None
    claim = claim_at_frontier(thinking_text)
    if claim is None:
        return None
    value, start, end = claim
    scope_start = max(0, start - SCOPE_WINDOW)
    scoped = thinking_text[scope_start:end]
    scope_anchors = []
    for pattern in item["scope_patterns"]:
        matches = list(re.finditer(pattern, scoped, flags=re.I | re.S))
        if not matches:
            return None
        match = matches[-1]
        scope_anchors.append({"source_char_span": [scope_start + match.start(), scope_start + match.end()],
                              "source_excerpt_sha256": digest(match.group())})
    violated, arithmetic = check(value, item)
    if not violated:
        return None
    return {
        "status": "COMMITTED_INTEGER_REFUTED",
        "question_sha256": case["question_sha256"],
        "proof_sha256": item["proof_sha256"], "review_sha256": item["review_sha256"],
        "observed_candidate": value, "predicate_kind": item["kind"], "predicate_args": item["args"],
        "source_char_span": [start, end], "source_excerpt_sha256": digest(thinking_text[start:end]),
        "scope_anchors": scope_anchors, "arithmetic": arithmetic, "cue": item["cue"],
    }
