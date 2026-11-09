"""Frozen v1 plus a gold-blind exact boxed-RHS delivery rule."""
from __future__ import annotations

import ast
from fractions import Fraction
import re

import complete_answer as v1

VERSION = "phase5d25_complete_answer_v2"
backend_status = v1.backend_status
grade_final_answer = v1.grade_final_answer

_MAX_EXPRESSION = 240
_MAX_NODES = 48
_MAX_BITS = 256
_FINAL_ANCHOR = re.compile(r"(?:the\s+)?final\s+(?:answer|conclusion)|最终答案|最后答案", re.I)
_APPROX = re.compile(
    r"\\(?:approx|simeq|sim|cong|thickapprox)\b|[≈≃≅∼]|~\s*=|"
    r"\b(?:approx(?:imately|imation)?|round(?:ed|ing)|estimate(?:d)?)\b",
    re.I,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if|unless|suppose|assum(?:e|ed|ing)|hypothetical|for example|candidate|"
    r"reject(?:ed)?|discard(?:ed)?|would|could|might|not)\b|假设|例如|假如",
    re.I,
)
_MATH = re.compile(
    r"(?P<display>\$\$[^$]*\$\$|\\\[[\s\S]*?\\\])|"
    r"(?P<inline>\$[^$\n]+\$|\\\([^\n]*?\\\))",
)
_ASSIGNMENT = re.compile(r"\s*([A-Za-z])\s*=\s*(.+)\s*", re.S)
_TEX_FRACTION = re.compile(r"\\(?:dfrac|tfrac|frac)\s*\{([+-]?\d+)\}\s*\{([+-]?\d+)\}")


def _tree(surface):
    source = v1._normalize(surface)
    source = _TEX_FRACTION.sub(r"((\1)/(\2))", source)
    source = re.sub(r"\\(?:times|cdot)\b", "*", source)
    source = re.sub(r"\\div\b", "/", source)
    source = " ".join(source.split())
    if len(source) > _MAX_EXPRESSION or not re.fullmatch(r"[A-Za-z0-9 .+*/^()\-]+", source):
        raise ValueError("unsupported arithmetic")
    source = re.sub(r"(?<![A-Za-z0-9.])0+(?=\d)", "", source)
    source = source.replace("^", "**")
    expression = ast.parse(source, mode="eval").body
    if sum(1 for _ in ast.walk(expression)) > _MAX_NODES:
        raise ValueError("arithmetic node limit")
    return expression, source


def _number(expression, source, bindings):
    if isinstance(expression, ast.Constant):
        literal = ast.get_source_segment(source, expression)
        if not re.fullmatch(r"\d{1,32}(?:\.\d{1,32})?|\.\d{1,32}", literal or ""):
            raise ValueError("unsupported numeric literal")
        value = Fraction(literal)
    elif isinstance(expression, ast.Name) and expression.id in bindings:
        value = bindings[expression.id]
    elif isinstance(expression, ast.UnaryOp) and isinstance(expression.op, (ast.UAdd, ast.USub)):
        value = _number(expression.operand, source, bindings)
        if isinstance(expression.op, ast.USub):
            value = -value
    elif isinstance(expression, ast.BinOp):
        left = _number(expression.left, source, bindings)
        right = _number(expression.right, source, bindings)
        match expression.op:
            case ast.Add():
                value = left + right
            case ast.Sub():
                value = left - right
            case ast.Mult():
                value = left * right
            case ast.Div():
                value = left / right
            case ast.Pow():
                if right.denominator != 1 or abs(right) > 12 or (left == 0 and right == 0):
                    raise ValueError("unsupported exponent")
                value = left ** int(right)
            case _:
                raise ValueError("unsupported operator")
    else:
        raise ValueError("unbound name or unsupported expression")
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > _MAX_BITS:
        raise ValueError("arithmetic bit limit")
    return value


def _unwrap_math(match):
    text = match.group()
    delimiter_size = 2 if match.group("display") or text.startswith(r"\(") else 1
    return text[delimiter_size:-delimiter_size]


def _bind(prelude, names, source_start):
    bindings, spans = {}, {}
    # Only explicit, closed assignments inside local math wrappers are trusted
    # for this formatting rule. Other inline formulas carry no binding.
    for match in _MATH.finditer(prelude):
        surface = _unwrap_math(match)
        assignment = _ASSIGNMENT.fullmatch(surface)
        if match.group("display") and not assignment:
            raise ValueError("competing standalone display")
        if not assignment or assignment[1] not in names:
            continue
        tree, source = _tree(assignment[2])
        value = _number(tree, source, {})
        name = assignment[1]
        if name in bindings and value != bindings[name]:
            raise ValueError("conflicting local assignments")
        bindings[name] = value
        spans.setdefault(name, [source_start + match.start(), source_start + match.end()])
    prose = _MATH.sub(" ", prelude)
    if "$" in prose or re.search(r"\\[\[\]()]", prose):
        raise ValueError("unclosed local math delimiter")
    if _HYPOTHETICAL.search(prose):
        raise ValueError("hypothetical or negated local assignment")
    if any(v1._rational(v1._trim_sentence(line)) is not None for line in prose.splitlines()):
        raise ValueError("competing unboxed answer")
    for paragraph in re.split(r"\n\s*\n", prelude):
        matches = list(_MATH.finditer(paragraph))
        if len(matches) == 1 and not _MATH.sub("", paragraph).strip():
            body = _unwrap_math(matches[0])
            if not _ASSIGNMENT.fullmatch(body):
                raise ValueError("competing isolated math object")
    if names != set(bindings):
        raise ValueError("incomplete local assignments")
    return bindings, spans


def _terminal_display(payload):
    terminal = v1._trim_sentence(payload)
    leading = len(payload) - len(payload.lstrip())
    for opening, closing in (("$$", "$$"), (r"\[", r"\]")):
        if terminal.endswith(closing):
            position = terminal.rfind(opening, 0, len(terminal) - len(closing))
            if position >= 0:
                return (leading + position, leading + position + len(opening),
                        leading + len(terminal) - len(closing))
    raise ValueError("terminal display required")


def _recover(text, old):
    labels = list(v1._LABEL.finditer(text))
    if len(labels) != 1 or not _FINAL_ANCHOR.fullmatch(labels[0]["label"]):
        raise ValueError("single explicit final-answer anchor required")
    label = labels[0]
    payload = text[label.end():]
    if len(payload) > 3_000 or _APPROX.search(payload) or v1._OR.search(payload) or v1._UNCERTAIN.search(payload):
        raise ValueError("approximate, alternative or oversized final section")
    if (len(v1._boxes(payload)[0]) != 1 or v1._CONCLUSION.search(payload)
            or v1._CONCLUSION.search(text[:label.start()])):
        raise ValueError("competing final delivery")
    display, start, end = _terminal_display(payload)
    body = payload[start:end]
    boxes, unfinished = v1._boxes(body)
    if unfinished or len(boxes) != 1:
        raise ValueError("one terminal box required")
    box_start, box_end, box_value = boxes[0]
    prefix = body[:box_start].rstrip()
    if not prefix.endswith("=") or body[box_end:].strip():
        raise ValueError("box is not the terminal right-hand side")
    parts = prefix[:-1].split("=")
    if not 1 <= len(parts) <= 7 or any(not part.strip() for part in parts):
        raise ValueError("incomplete equality chain")
    lead, lead_source = _tree(parts[0])
    names = {node.id for node in ast.walk(lead) if isinstance(node, ast.Name)}
    if names and len(parts) < 2:
        raise ValueError("closed arithmetic predecessor required")
    bindings, spans = _bind(payload[:display], names, label.end())
    values = [_number(lead, lead_source, bindings)]
    for part in parts[1:]:
        tree, source = _tree(part)
        values.append(_number(tree, source, {}))
    scalar = v1.extract_final_answer(r"\boxed{" + box_value + "}", "scalar")
    if scalar["status"] != "ok" or scalar["unit"] is not None:
        raise ValueError("unsupported boxed scalar")
    tree, source = _tree(scalar["components"][0])
    exact = _number(tree, source, {})
    if any(value != exact for value in values):
        raise ValueError("equality chain fails exact arithmetic")
    body_start = label.end() + start
    return {
        **old,
        "version": VERSION,
        "status": "ok",
        "reason": "single_boxed_rhs_of_exact_terminal_chain",
        "method": "exact_final_chain_boxed_rhs",
        "kind": "scalar",
        "components": scalar["components"],
        "unit": None,
        "closure": None,
        "vector_shape": None,
        "selected_span": [body_start + box_start, body_start + box_end],
        "chain_span": [body_start, label.end() + end],
        "exact_chain_value": str(exact),
        "checked_chain_terms": len(values) + 1,
        "local_bindings": {name: {"value": str(value), "span": spans[name]} for name, value in bindings.items()},
    }


def extract_final_answer(final_response: str, answer_kind: str = "auto") -> dict:
    selection = v1.extract_final_answer(final_response, answer_kind)
    if (answer_kind not in ("auto", "scalar") or selection["status"] != "ambiguous"
            or selection.get("reason") != "boxed_objects_do_not_consume_final_payload"):
        return selection
    try:
        return _recover(final_response, selection)
    except (ValueError, SyntaxError, ArithmeticError):
        return selection


def score_final_answer(final_response: str, gold: str, *, answer_kind: str = "auto",
                       eos: bool = True, think_closed: bool = True) -> dict:
    if eos is not True or think_closed is not True:
        return v1.score_final_answer(final_response, gold, answer_kind=answer_kind, eos=eos, think_closed=think_closed)
    selection = extract_final_answer(final_response, answer_kind)
    return {"selection": selection, "grade": grade_final_answer(selection, gold)}
