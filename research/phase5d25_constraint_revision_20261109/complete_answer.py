"""Gold-blind complete final-object extraction and bounded CPU grading."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys

VERSION = "phase5d25_complete_answer_v1"
BACKEND_VERSIONS = {"math-verify": "0.9.0", "latex2sympy2_extended": "1.11.0"}
KINDS = {"auto", "scalar", "set", "multiset", "tuple", "vector", "interval"}
MAX_TEXT = 150_000
MAX_OBJECT = 4_000
MAX_PARTS = 16
WORKER_TIMEOUT_SECONDS = 20

_BOX = re.compile(r"(?<!\\)\\boxed\s*\{")
_LABEL = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:step\s+\d+\s*:\s*)?"
    r"(?P<label>(?:the\s+)?final\s+(?:answer|conclusion)|conclusion|最终答案|最后答案|"
    r"(?:the\s+)?(?:complete\s+)?(?:solution\s+set|set\s+of\s+(?:solutions|roots)|"
    r"(?:real\s+)?(?:solutions|roots))\s*(?:are|is)\b)"
    r"(?=\s|:|：|=|\*|$)(?:\*\*)?\s*(?:is\b\s*)?[:：=]?\s*(?:\*\*)?",
)
_CONCLUSION = re.compile(
    r"(?im)(?:^|(?<=[.!?。])\s+)(?:\*\*)?"
    r"(?:(?:therefore|thus|hence|so|finally|in conclusion),?\s+)?"
    r"(?:the\s+)?(?:final\s+)?answer\s*(?:is\b\s*|[:：=]\s*)+",
)
_PLURAL = re.compile(
    r"\b(?:all\s+(?:(?:real|positive|integer)\s+)*(?:solutions|roots)|"
    r"(?:solutions|roots)\s+are|(?:solution|root)\s+set|set\s+of\s+(?:solutions|roots))\b|"
    r"所有(?:的)?(?:解|根)|解集",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:either|possibly|perhaps|maybe|probably|uncertain|unsure|not\s+sure)\b|"
    r"不确定|也许|可能是",
    re.I,
)
_OR = re.compile(r"\bor\b|或者|\\(?:lor|vee)\b", re.I)
_INTERMEDIATE = re.compile(
    r"\b(?:intermediate(?:\s+(?:value|result|answer))?|subtotal|temporary|candidate|"
    r"not\s+(?:the\s+)?(?:final\s+)?answer|step\s+\d+)\b|中间(?:值|结果)|暂定",
    re.I,
)
_PLURAL_INTRO = re.compile(
    r"^\s*(?:the\s+)?(?:complete\s+)?(?:all\s+)?(?:real\s+)?"
    r"(?:solutions|roots|solution\s+set|set\s+of\s+(?:solutions|roots))"
    r"\s*(?:are|is)\b\s*[:：]?\s*",
    re.I,
)
_SET_WRAPS = ((r"\{", r"\}"), ("{", "}"))
_WRAPS = (("**", "**"), ("`", "`"), ("$$", "$$"), ("$", "$"), (r"\[", r"\]"), (r"\(", r"\)"))
_TEX_SPACE = re.compile(r"\\(?:quad|qquad|enspace|thinspace)\b|\\[,;:! ]|~")
_VECTOR = re.compile(r"\\begin\{(pmatrix|bmatrix|matrix)\}([\s\S]*)\\end\{\1\}")
_COMMANDS = set((
    "frac dfrac tfrac sqrt cdot times div pi infty infinity sin cos tan cot sec csc "
    "arcsin arccos arctan sinh cosh tanh log ln exp abs floor ceil lfloor rfloor lceil rceil "
    "alpha beta gamma theta phi varphi lambda mu sigma omega i ell circ pmod mod bmod degree"
).split())
_WORDS = set("sin cos tan cot sec csc log ln exp pi infinity mod".split())
_UNIT_GROUPS = {
    "m": ("m", "meter", "meters", "metre", "metres"),
    "cm": ("cm", "centimeter", "centimeters", "centimetre", "centimetres"),
    "mm": ("mm", "millimeter", "millimeters", "millimetre", "millimetres"),
    "km": ("km", "kilometer", "kilometers", "kilometre", "kilometres"),
    "ft": ("ft", "foot", "feet"),
    "in": ("in", "inch", "inches"),
    "yd": ("yd", "yard", "yards"),
    "mi": ("mi", "mile", "miles"),
    "g": ("g", "gram", "grams"),
    "kg": ("kg", "kilogram", "kilograms"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "L": ("l", "liter", "liters", "litre", "litres"),
    "mL": ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    "s": ("s", "second", "seconds"),
    "min": ("min", "minute", "minutes"),
    "h": ("h", "hour", "hours"),
    "d": ("day", "days"),
    "USD": ("dollar", "dollars", "usd", "us dollar", "us dollars"),
    "cent": ("cent", "cents"),
    "degree": ("degree", "degrees"),
    "radian": ("radian", "radians"),
    "unit": ("unit", "units"),
    "student": ("student", "students"),
    "person": ("person", "persons", "people"),
    "item": ("item", "items"),
    "object": ("object", "objects"),
    "m/s": ("m/s", "meter per second", "meters per second", "metres per second"),
    "km/h": ("km/h", "kilometers per hour", "kilometres per hour"),
    "mi/h": ("mph", "mile per hour", "miles per hour"),
}
_UNITS = {alias: unit for unit, aliases in _UNIT_GROUPS.items() for alias in aliases}
_COUNT_LABELS = {"student", "person", "item", "object"}
_UNIT_NAME = "|".join(re.escape(alias) for alias in sorted(_UNITS, key=len, reverse=True))
_UNIT = re.compile(
    r"(?:(?P<power_word>square|cubic)\s+)?(?P<name>" + _UNIT_NAME + r")"
    r"(?:\s*(?:\^(?P<power>[23])|\^\{(?P<braced_power>[23])\}|(?P<unicode_power>[²³])))?$",
    re.I,
)
_TEX_UNIT = re.compile(r"\\(?:text|mathrm|operatorname)\{([^{}]+)\}(\s*(?:\^[23]|\^\{[23]\}|[²³]))?$")


def _trim_sentence(text):
    text = text.strip().rstrip("。！").strip()
    return text[:-1].rstrip() if text.endswith(".") and not text.endswith("..") else text


def _peel(text):
    value = _trim_sentence(text)
    for _ in range(8):
        for left, right in _WRAPS:
            if value.startswith(left) and value.endswith(right) and len(value) > len(left) + len(right):
                value = _trim_sentence(value[len(left):-len(right)])
                break
        else:
            return value
    return value


def _normalize(text):
    text = text.replace("−", "-").replace("π", r"\pi").replace("∞", r"\infty")
    text = text.replace("×", r"\cdot ").replace("÷", r"\div ")
    return _TEX_SPACE.sub(" ", re.sub(r"\\(?:left|right)(?![A-Za-z])\s*", "", text)).strip()


def _boxes(text):
    found = []
    cursor = 0
    while match := _BOX.search(text, cursor):
        depth = 1
        for end in range(match.end(), len(text)):
            if text[end] in "{}" and (end == 0 or text[end - 1] != "\\"):
                depth += 1 if text[end] == "{" else -1
                if depth == 0:
                    break
        else:
            return found, True
        value = text[match.end():end]
        if _BOX.search(value):
            return found, True
        found.append((match.start(), end + 1, value))
        if len(found) > MAX_PARTS:
            return found, True
        cursor = end + 1
    return found, False


def _split_top(text, separator=","):
    parts, stack, start = [], [], 0
    pairs = {"}": "{", ")": "(", "]": "["}
    for i, char in enumerate(text):
        if char in "{([":
            stack.append(char)
        elif char in "})]":
            if not stack or stack.pop() != pairs[char]:
                return None
        elif char == separator and not stack and (i == 0 or text[i - 1] != "\\"):
            parts.append(text[start:i].strip())
            start = i + 1
    if stack:
        return None
    return parts + [text[start:].strip()]


def _unit_tail(text):
    text = text.strip()
    match = _TEX_UNIT.search(text)
    if match:
        unit_text = match[1].strip() + (match[2] or "")
        unit = _UNIT.fullmatch(unit_text)
    else:
        unit = _UNIT.search(text)
        match = unit
    if not unit:
        return text, None
    before = text[:match.start()]
    if not _TEX_UNIT.search(text) and before and (not before[-1].isspace() and before[-1] not in "}$)]"):
        return text, None
    written_power = unit["power"] or unit["braced_power"] or unit["unicode_power"]
    power = written_power or {"square": "2", "cubic": "3"}.get((unit["power_word"] or "").lower())
    power = {"²": "2", "³": "3"}.get(power, power)
    if unit["power_word"] and written_power:
        return text, None
    name = _UNITS[unit["name"].lower()]
    return before.rstrip(), name + (f"^{power}" if power else "")


def _rational(surface):
    text = re.sub(r"\s+", "", surface)
    scale = 100 if text.endswith(r"\%") else 1
    if scale != 1:
        text = text[:-2]
    if re.fullmatch(r"[+-]?(?:\d+\.\d+|\d+|\.\d+|\d+/[+-]?\d+)", text):
        try:
            if "/" in text:
                a, b = text.split("/")
                return Fraction(int(a), int(b)) / scale
            return Fraction(text) / scale
        except (ValueError, ZeroDivisionError):
            return None
    frac = re.fullmatch(r"([+-]?)\\(?:dfrac|tfrac|frac)\{([+-]?\d+)\}\{([+-]?\d+)\}", text)
    if not frac:
        frac = re.fullmatch(r"([+-]?)\\(?:dfrac|tfrac|frac)(\d)(\d)", text)
    if frac:
        try:
            return Fraction((-1 if frac[1] == "-" else 1) * int(frac[2]), int(frac[3])) / scale
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _component(surface):
    text = _normalize(_peel(surface))
    if not text or len(text) > MAX_OBJECT or _UNCERTAIN.search(text) or _OR.search(text):
        return None
    if len(_split_top(text) or []) != 1 or not re.search(r"[0-9A-Za-z]", text):
        return None
    text = re.sub(r"(?<!\\)%$", r"\\%", text)
    if re.search(r"\d\s+\d|\.{2,}|(?:\\(?:cdot|times|div)|[+\-*/^_=])\s*$", text):
        return None
    # Ordinary equalities are not scalar expressions. One simple named answer
    # prefix is removed at object level before scalar components are parsed.
    if "=" in text or re.search(r"[<>;&:$`%?@#]", text.replace(r"\%", "")):
        return None
    commands = re.findall(r"\\([A-Za-z]+)", text)
    if any(command not in _COMMANDS for command in commands):
        return None
    word_text = re.sub(r"\\[A-Za-z]+|\\[% ]", " ", text)
    if "\\" in word_text or any(word not in _WORDS for word in re.findall(r"[A-Za-z]{2,}", word_text)):
        return None
    if re.search(r"[^0-9A-Za-z\s{}()[\].,+\-*/^_|!°%]", word_text):
        return None
    return text


def _entry(kind, components, *, unit=None, closure=None, vector_shape=None):
    return {"status": "ok", "kind": kind, "components": components, "unit": unit,
            "closure": closure, "vector_shape": vector_shape}


def _bad(status, reason):
    return {"status": status, "reason": reason}


def _vector_parts(surface):
    matrix = _VECTOR.fullmatch(surface)
    if not matrix:
        return None
    rows = re.split(r"(?<!\\)\\\\(?!\\)", matrix[2].strip())
    cells = [_split_top(row, "&") for row in rows]
    if any(not row or not all(row) for row in cells):
        return None
    width = len(cells[0])
    if any(len(row) != width for row in cells) or (len(cells) > 1 and width > 1):
        return None
    return [item for row in cells for item in row], [len(cells), width]


def _grouped_thousands(text):
    return re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text) is not None


def _object(text, kind, *, plural=False):
    if len(text) > MAX_OBJECT:
        return _bad("unparsed", "object_limit")
    # Preserve a visible TeX layout separator between separate boxes.
    text = re.sub(r"(?<=})\s*\\(?:quad|qquad)\b\s*(?=\\boxed)", ", ", text)
    text, unit = _unit_tail(_normalize(_peel(text)))
    text = _peel(text)
    if not unit:
        text, unit = _unit_tail(_normalize(text))
    if text.startswith(("$", r"\[", r"\(")):
        return _bad("incomplete", "unclosed_final_math_wrapper")
    if _UNCERTAIN.search(text):
        return _bad("ambiguous", "uncertain_final_object")
    # A one-name answer prefix, e.g. x = ..., can introduce the object.
    text = re.sub(r"^\s*[A-Za-z](?:_\{?[0-9]+\}?)?\s*=\s*(?!=)", "", text, count=1)
    boxes, unfinished = _boxes(text)
    if unfinished:
        return _bad("incomplete", "unclosed_nested_or_oversized_boxes")
    explicit_set = next(((left, right) for left, right in _SET_WRAPS if text.startswith(left) and text.endswith(right)), None)
    if _OR.search(text) and not (plural or explicit_set):
        return _bad("ambiguous", "alternative_final_objects")
    # Multiple boxes only participate if they consume the complete object.
    # A mere final heading is insufficient to infer that a list is unordered.
    if boxes:
        if len(boxes) == 1 and not text[:boxes[0][0]].strip() and not text[boxes[0][1]:].strip():
            inside = _object(boxes[0][2], kind, plural=plural)
            if inside["status"] == "ok" and unit:
                if inside["unit"] and inside["unit"] != unit:
                    return _bad("ambiguous", "conflicting_units")
                inside["unit"] = unit
            return inside
        prefix = text[:boxes[0][0]].strip()
        suffix = text[boxes[-1][1]:].strip()
        wrappers = {(r"\{", r"\}"): "set", ("{", "}"): "set", ("(", ")"): "pair",
                    ("[", "]"): "bracket", ("(", "]"): "interval", ("[", ")"): "interval"}
        bracket = wrappers.get((prefix, suffix))
        if (prefix or suffix) and not bracket:
            return _bad("ambiguous", "boxed_objects_do_not_consume_final_payload")
        gaps = [text[prev:curr] for (_, prev, _), (curr, _, _) in zip(boxes, boxes[1:])]
        if not bracket and gaps and all(gap.strip() == "=" for gap in gaps):
            forms = [_object(part, kind, plural=plural) for _, _, part in boxes]
            keys = [_fingerprint(form) for form in forms]
            if keys[0] is not None and all(key == keys[0] for key in keys):
                if unit:
                    if forms[0]["unit"] and forms[0]["unit"] != unit:
                        return _bad("ambiguous", "conflicting_units")
                    forms[0]["unit"] = unit
                return forms[0]
            return _bad("ambiguous", "unproven_equal_final_repetitions")
        for gap in gaps:
            if not re.fullmatch(r"\s*(?:(?:[,，;]\s*)?(?:and|or|或者)|[,，;])?\s*", gap, re.I):
                return _bad("ambiguous", "unrecognized_box_separator")
            if not gap.strip() and not re.search(r"\s{2,}", gap):
                return _bad("ambiguous", "missing_box_separator")
        parts = [part for _, _, part in boxes]
        if bracket == "set" or (not bracket and (plural or kind in ("set", "multiset"))):
            return _components("multiset" if kind == "multiset" else "set", parts, unit=unit)
        if bracket in ("pair", "bracket", "interval"):
            return _bracketed(prefix, suffix, parts, kind, unit)
        return _bad("ambiguous", "plural_object_without_type")
    if explicit_set:
        left, right = explicit_set
        parts = _split_top(text[len(left):-len(right)])
        if parts == [""]:
            parts = []
        return _components("multiset" if kind == "multiset" else "set", parts, unit=unit)
    if text in (r"\varnothing", r"\emptyset", "∅"):
        return _entry("multiset" if kind == "multiset" else "set", [], unit=unit)
    if text.startswith(r"\begin"):
        vector = _vector_parts(text)
        if vector is None:
            return _bad("incomplete", "unsupported_or_unclosed_vector_environment")
        parts, shape = vector
        return _components("vector", parts, unit=unit, vector_shape=shape)
    if text[:1] in ("(", "[") and text[-1:] in (")", "]"):
        parts = _split_top(text[1:-1])
        if parts is None:
            return _bad("incomplete", "unbalanced_bracket_object")
        if len(parts) > 1:
            return _bracketed(text[0], text[-1], parts, kind, unit)
    if _grouped_thousands(text) and kind not in ("set", "multiset") and not plural:
        text = text.replace(",", "")
    if plural or kind in ("set", "multiset"):
        # Explicit solution lists allow and/or between mathematical values.
        listing = re.sub(r"\\text\{\s*(and|or)\s*\}|\b(and|or)\b", ",", text, flags=re.I)
        listing = re.sub(r",\s*,", ",", listing).replace("，", ",")
        parts = _split_top(listing)
        return _components("multiset" if kind == "multiset" else "set", parts, unit=unit)
    parts = _split_top(text)
    if parts is None:
        return _bad("incomplete", "unbalanced_final_object")
    if len(parts) != 1:
        return _bad("ambiguous", "untyped_final_components")
    scalar = _component(text)
    if scalar is None:
        return _bad("unparsed", "unsupported_scalar_or_tail")
    return _entry("scalar", [scalar], unit=unit)


def _components(kind, parts, *, unit, closure=None, vector_shape=None):
    if parts is None or len(parts) > MAX_PARTS or any(not part for part in parts):
        return _bad("incomplete", "incomplete_or_oversize_components")
    expanded = []
    for part in parts:
        signs = re.findall(r"\\pm(?![A-Za-z])|±", part)
        if signs and kind in ("set", "multiset") and len(signs) == 1:
            expanded.extend(re.sub(r"\\pm(?![A-Za-z])|±", sign, part) for sign in ("+", "-"))
        else:
            expanded.append(part)
    if len(expanded) > MAX_PARTS:
        return _bad("unparsed", "component_limit")
    components = [_component(part) for part in expanded]
    if any(component is None for component in components):
        return _bad("unparsed", "unsupported_component")
    return _entry(kind, components, unit=unit, closure=closure, vector_shape=vector_shape)


def _bracketed(left, right, parts, kind, unit):
    if left == "[" or right == "]" or kind == "interval":
        if len(parts) != 2:
            return _bad("ambiguous", "interval_requires_two_endpoints")
        return _components("interval", parts, unit=unit, closure=[left == "[", right == "]"])
    if len(parts) == 2 and kind == "auto":
        return _bad("ambiguous", "open_interval_or_ordered_pair")
    return _components("vector" if kind == "vector" else "tuple", parts, unit=unit)


def _terminal_boxed(segment, kind, plural, *, allow_prose):
    """Read an isolated final boxed block with no competing answer in its prefix."""
    terminal = _trim_sentence(segment)
    start = terminal.rfind("\n") + 1
    for opening, closing in (("$$", "$$"), (r"\[", r"\]")):
        if terminal.endswith(closing):
            opening_at = terminal.rfind(opening, 0, len(terminal) - len(closing))
            if opening_at < 0:
                return None
            start = opening_at
            break
    tail = segment[start:]
    # Permit an exact anchored concluding cue on the final line.
    lead = _CONCLUSION.match(tail) or re.match(r"\s*(?:therefore|thus|hence|so|finally)\s*[:,]\s*", tail, re.I)
    if lead:
        start += lead.end()
        tail = segment[start:]
    if not _BOX.search(tail):
        return None
    before = segment[:start]
    prior_boxes, incomplete = _boxes(before)
    if incomplete or prior_boxes:
        return None
    if before.count("$$") % 2 or before.count(r"\[") != before.count(r"\]") or before.count(r"\(") != before.count(r"\)"):
        return None
    lines = [line.strip() for line in before.splitlines() if line.strip()]
    local = lines[-1] if lines else ""
    if local in ("$", "$$", r"\[", r"\(") or _UNCERTAIN.search(local) or _OR.search(local) or _INTERMEDIATE.search(local):
        return None
    if local and not allow_prose and re.search(r":\s*$", local) and not re.search(
        r"(?:answer|solutions?|roots?|therefore|thus|hence|so|result|conclusion)\b", local, re.I
    ):
        return None
    headings = [line for line in lines if line.startswith("#")]
    terminal_cue = re.match(r"^(?:therefore|thus|hence|so|finally)\b[^\n]*:\s*$", local, re.I)
    if headings and not allow_prose and not terminal_cue and _INTERMEDIATE.search(headings[-1]):
        return None
    result = _object(tail, kind, plural=plural)
    if result["status"] == "ok":
        if allow_prose:
            # A bare mathematical delivery earlier in the same final section
            # is also a candidate. No final-box priority resolves a conflict.
            key = _fingerprint(result)
            for part in re.split(r"\n\s*\n", before):
                old = _object(part, kind, plural=plural)
                if old["status"] == "ok" and old["kind"] == result["kind"] and _fingerprint(old) != key:
                    return None
        return result, start
    return None


def _fingerprint(entry):
    if entry["status"] != "ok":
        return None
    components = []
    for surface in entry["components"]:
        number = _rational(surface)
        value = ("rational", str(number)) if number is not None else ("surface", re.sub(r"\s+", "", surface))
        components.append(value)
    if entry["kind"] == "set":
        components = sorted(set(components))
    if entry["kind"] == "multiset":
        components = sorted(components)
    return entry["kind"], entry["unit"], entry["closure"], components


def extract_final_answer(final_response: str, answer_kind: str = "auto") -> dict:
    """Extract the complete terminal object using only output and public type metadata."""
    if answer_kind not in KINDS:
        raise ValueError("Unsupported answer kind")
    if not isinstance(final_response, str):
        raise TypeError("Final response must be text")
    base = {
        "version": VERSION,
        "requested_kind": answer_kind,
        "final_response_sha256": hashlib.sha256(final_response.encode()).hexdigest(),
        "selection_uses_gold": False,
    }
    text = final_response.rstrip()
    for marker in ("<|im_end|>", "<|endoftext|>"):
        if text.endswith(marker):
            text = text[:-len(marker)].rstrip()
    if not text or len(text) > MAX_TEXT:
        return {**base, **_bad("unparsed", "empty_or_oversize_response")}
    if re.search(r"</?think>", text, re.I):
        return {**base, **_bad("unparsed", "thinking_not_separated")}
    if re.search(r"```", text):
        return {**base, **_bad("unparsed", "code_fence_not_final_math")}
    boxes, unfinished = _boxes(text)
    if unfinished or re.search(r"(?<!\\)\\boxed\b(?!\s*\{)", text):
        return {**base, **_bad("incomplete", "unclosed_nested_or_oversized_boxes")}
    strong_labels = list(_LABEL.finditer(text))
    labels = strong_labels or list(_CONCLUSION.finditer(text))
    if labels:
        candidates = []
        for i, label in enumerate(labels):
            end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
            start = label.end()
            payload = text[start:end]
            if i + 1 < len(labels):
                payload = re.sub(r"\n\s*-{3,}\s*$", "", payload)
            intro = _PLURAL_INTRO.match(payload)
            plural = bool(_PLURAL.search(label.group(0)) or intro)
            if intro:
                start += intro.end()
                payload = payload[intro.end():]
            result = _object(payload, answer_kind, plural=plural)
            if result["status"] != "ok":
                fallback = _terminal_boxed(payload, answer_kind, plural, allow_prose=True)
                if fallback:
                    result, shift = fallback
                    start += shift
            candidates.append((result, start, start + len(payload) if start == label.end() else end))
        result, start, end = candidates[-1]
        if result["status"] != "ok":
            return {**base, **result, "selected_span": [start, end]}
        fingerprint = _fingerprint(result)
        for previous, old_start, old_end in candidates[:-1]:
            if previous["status"] == "ok" and _fingerprint(previous) != fingerprint:
                return {**base, **_bad("ambiguous", "different_explicit_final_deliveries")}
            if previous["status"] != "ok" and _BOX.search(text[old_start:old_end]):
                return {**base, **_bad("ambiguous", "unresolved_earlier_final_delivery")}
        method = "explicit_terminal_answer"
    else:
        start, end = 0, len(text)
        result = _object(text, answer_kind, plural=False)
        method = "whole_final_object"
        if result["status"] != "ok" and boxes:
            fallback = _terminal_boxed(text, answer_kind, False, allow_prose=False)
            if fallback:
                result, start = fallback
                method = "terminal_boxed_block"
            elif result["status"] == "unparsed" or _INTERMEDIATE.search(text[max(0, boxes[-1][0] - 90):boxes[-1][0]]):
                result = _bad("unparsed", "no_terminal_answer_delivery")
    if result["status"] == "ok" and answer_kind != "auto" and result["kind"] != answer_kind:
        return {**base, **_bad("ambiguous", "public_answer_kind_mismatch"), "observed_kind": result["kind"]}
    if result["status"] != "ok":
        return {**base, **result}
    return {**base, **result, "method": method, "selected_span": [start, end]}


def _parse_components(surfaces):
    from latex2sympy2_extended import NormalizationConfig, latex2sympy
    from sympy import Expr, Rational, oo
    config = NormalizationConfig(boxed="none", equations=False, units=False, malformed_operators=True)
    parsed = []
    for surface in surfaces:
        number = _rational(surface)
        if number is not None:
            value = Rational(number.numerator, number.denominator)
        else:
            try:
                value = latex2sympy(surface, is_real=None, normalization_config=config)
            except Exception:
                return None
        if not isinstance(value, Expr) or value.is_finite is False and value not in (oo, -oo):
            return None
        parsed.append(value)
    return parsed


def _equal(a, b):
    from sympy import Float, simplify
    if a == b:
        return True
    if not a.has(Float) and not b.has(Float):
        delta = simplify(a - b)
        if delta.is_zero is not None:
            return bool(delta.is_zero)
    from math_verify import verify
    return bool(verify(b, a, strict=True, timeout_seconds=None))


def _unique(values):
    unique = []
    for value in values:
        if not any(_equal(value, other) for other in unique):
            unique.append(value)
    return unique


def _same_unordered(candidate, gold):
    if len(candidate) != len(gold):
        return False
    edges = [[j for j, ref in enumerate(gold) if _equal(value, ref)] for value in candidate]
    matched = {}
    def augment(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in matched or augment(matched[j], seen):
                matched[j] = i
                return True
        return False
    return all(augment(i, set()) for i in range(len(candidate)))


def _grade_impl(selection, gold):
    kind = selection["kind"]
    reference = _object(gold, selection["requested_kind"])
    if reference["status"] != "ok":
        return {"status": "gold_parse_unknown", "correct": None, "reason": reference["reason"]}
    if kind != reference["kind"]:
        return {"status": "ok", "correct": False, "comparison": "object_kind_mismatch"}
    optional_count = selection["unit"] is None and reference["unit"] in _COUNT_LABELS
    if reference["unit"] is not None and reference["unit"] != selection["unit"] and not optional_count:
        return {"status": "ok", "correct": False, "comparison": "unit_mismatch"}
    if kind == "interval" and selection["closure"] != reference["closure"]:
        return {"status": "ok", "correct": False, "comparison": "interval_closure_mismatch"}
    if kind not in ("set", "multiset") and len(selection["components"]) != len(reference["components"]):
        return {"status": "ok", "correct": False, "comparison": "ordered_object_arity_mismatch"}
    if kind == "vector" and selection["vector_shape"] and reference["vector_shape"] and selection["vector_shape"] != reference["vector_shape"]:
        return {"status": "ok", "correct": False, "comparison": "explicit_vector_shape_mismatch"}
    ref = _parse_components(reference["components"])
    if ref is None:
        return {"status": "gold_parse_unknown", "correct": None, "reason": "whole_component_parse_failed"}
    candidate = _parse_components(selection["components"])
    if candidate is None:
        return {"status": "candidate_parse_unknown", "correct": None, "reason": "whole_component_parse_failed"}
    if kind == "set":
        candidate, ref = _unique(candidate), _unique(ref)
    if kind in ("set", "multiset"):
        correct = _same_unordered(candidate, ref)
        comparison = "unordered_unique_set" if kind == "set" else "unordered_multiplicity"
    else:
        correct = all(_equal(value, expected) for value, expected in zip(candidate, ref, strict=True))
        comparison = "ordered_components" if kind != "scalar" else "whole_scalar"
    return {"status": "ok", "correct": correct, "comparison": comparison,
            "candidate_arity": len(candidate), "gold_arity": len(ref),
            "candidate_unit": selection["unit"], "gold_unit": reference["unit"]}


def backend_status():
    found = {}
    for name, expected in BACKEND_VERSIONS.items():
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return {"status": "backend_unavailable", "dependency": name, "expected": expected}
        if found[name] != expected:
            return {"status": "backend_version_mismatch", "dependency": name,
                    "expected": expected, "found": found[name]}
    return {"status": "ok", "versions": found}


def grade_final_answer(selection: dict, gold: str) -> dict:
    """Score an already selected object; Gold is unavailable to extraction."""
    base = {"scorer_version": VERSION, "backend_versions": BACKEND_VERSIONS}
    if selection["status"] != "ok":
        return {**base, "status": "not_delivered", "correct": False}
    if not isinstance(gold, str):
        raise TypeError("Gold must be one reference math surface")
    backend = backend_status()
    if backend["status"] != "ok":
        return {**base, **backend, "correct": None}
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", PYTHONIOENCODING="utf-8")
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--grade-worker"],
            input=json.dumps({"selection": selection, "gold": gold}), encoding="utf-8",
            capture_output=True, timeout=WORKER_TIMEOUT_SECONDS, env=env, check=True,
        )
        return {**base, **json.loads(process.stdout)}
    except subprocess.TimeoutExpired:
        return {**base, "status": "backend_timeout", "correct": None}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {**base, "status": "backend_error", "correct": None, "error_type": type(exc).__name__}


def score_final_answer(final_response: str, gold: str, *, answer_kind: str = "auto",
                       eos: bool = True, think_closed: bool = True) -> dict:
    """Common online score entry point for frozen final responses."""
    selection = (extract_final_answer(final_response, answer_kind)
                 if eos is True and think_closed is True else _bad("uncommitted", "requires_eos_and_closed_thinking"))
    return {"selection": selection, "grade": grade_final_answer(selection, gold)}


if __name__ == "__main__":
    if sys.argv[1:] != ["--grade-worker"]:
        raise SystemExit("Import score_final_answer(final_response, gold, answer_kind=...)")
    request = json.load(sys.stdin)
    try:
        result = _grade_impl(request["selection"], request["gold"])
    except Exception as error:
        result = {"status": "backend_error", "correct": None, "error_type": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False))
