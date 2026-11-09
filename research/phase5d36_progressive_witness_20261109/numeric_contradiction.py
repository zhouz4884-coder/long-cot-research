"""Extract bounded, exact numerical assertions without assuming problem semantics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import operator
import re
import unicodedata


_MATH = re.compile(r"\$\$([^$]{1,500})\$\$|\\\[([\s\S]{1,500}?)\\\]|"
                   r"(?<!\$)\$([^$\n]{1,500})\$(?!\$)|\\\(([^\n]{1,500}?)\\\)")
_NUM = r"(?<![\w.])[-+]?(?:[0-9]{1,32}(?:\.[0-9]{1,24})?|\.[0-9]{1,24})(?![\w]|\.[0-9]|,[0-9])"
_OPS = r"(?:<=|>=|!=|[=<>≤≥≠]|\\(?:leq?|geq?|neq?|lt|gt)(?![a-z]))"
_PARTS = re.compile(rf"({_OPS})")
_ASCII = re.compile(r"(?m)^[ \t]*(?:(?:therefore|thus|hence|so),?[ \t]+)?"
                    r"(?P<relation>[+\-0-9().][0-9.()+\-*/^ <>=!≤≥≠\t]{1,498})[ \t]*$", re.I)
_WORD_OPERATOR = r"(?:strictly\s+)?(?:less|smaller|greater|larger)\s+than|equal\s+to|at\s+(?:least|most)"
_PROSE = re.compile(rf"(?P<left>{_NUM})\s+(?:is|was)\s+(?P<operator>{_WORD_OPERATOR})\s+"
                    rf"(?P<right>{_NUM})(?=$|\s|[.!?,;)\]])", re.I)
_COREFERENCE = re.compile(
    r"\b(?:the|this|that)\s+(?:(?:[\w-]+\s+){0,3}(?:number|value|candidate))"
    rf"\s+is\s+(?P<left>{_NUM})[.!]\s+(?:(?:but|however),?\s+)?"
    rf"(?:that|this|it)(?:['’]s|\s+is)\s+(?P<operator>{_WORD_OPERATOR})\s+"
    rf"(?P<right>{_NUM})(?=$|\s|[.!?,;)\]])", re.I)
_SENTENCE = re.compile(r"[.!?](?=\s+[A-Z]|\s*$)")
_CONDITIONAL = re.compile(r"\b(?:if|unless|suppose|assuming|assume|hypothetical|"
                          r"for example|would be|could be|might be|maybe|either)\b", re.I)
_NEGATED = re.compile(r"\b(?:wrong|incorrect|false|not true|not correct|"
                      r"contradiction|mistake|erroneous|erroneously|invalid|"
                      r"not possible|not the case|I wrote|we wrote|I said|we said)\b", re.I)
_APPROXIMATE = re.compile(r"\b(?:approximate(?:ly)?|round(?:ed|ing)|estimate)\b|[≈≃≅∼~]", re.I)
_QUOTE = re.compile(r'(?m)^\s*>[^\n]*|"""[\s\S]*?"""|“[^”\n]*”|"[^"\n]*"|'
                    r"```[\s\S]*?(?:```|\Z)|`[^`\n]+`")
_TEX_OPERATORS = {r"\le": "<=", r"\leq": "<=", "≤": "<=", r"\ge": ">=", r"\geq": ">=",
                  "≥": ">=", r"\lt": "<", r"\gt": ">", r"\ne": "!=", r"\neq": "!=", "≠": "!="}
_OPERATORS = {"=": operator.eq, "!=": operator.ne, "<": operator.lt, ">": operator.gt,
              "<=": operator.le, ">=": operator.ge}
_WORD_OPERATORS = {"less than": "<", "smaller than": "<", "greater than": ">",
                   "larger than": ">", "equal to": "=", "at least": ">=", "at most": "<="}
_FRACTION = re.compile(r"\\(?:dfrac|tfrac|frac)\s*\{([+-]?\d{1,32})\}\s*\{([+-]?\d{1,32})\}")
_NUMBERS = re.compile(r"(?:[0-9]{1,32}(?:\.[0-9]{1,24})?|\.[0-9]{1,24})")


@dataclass(frozen=True)
class Relation:
    start: int
    end: int
    source: str
    left: str
    operator: str
    right: str
    exact_truth: bool
    scope: str
    extraction: str


def _number(source: str) -> Fraction:
    """Evaluate a small closed arithmetic grammar, with no Python execution."""
    import ast

    source = unicodedata.normalize("NFC", source)
    source = _FRACTION.sub(r"((\1)/(\2))", source)
    source = re.sub(r"\\(?:times|cdot)\b|[×·]", "*", source)
    source = re.sub(r"\\div\b|÷", "/", source)
    source = source.replace("−", "-").replace("^", "**").strip()
    if not source or len(source) > 240 or not re.fullmatch(r"[0-9. +*/()\t\r\n\-]+", source):
        raise ValueError("non-numeric arithmetic")
    source = re.sub(r"[\t\r\n]+", " ", source)
    source = re.sub(r"(?<![0-9.])0+(?=[0-9])", "", source)
    tree = ast.parse(source, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 48:
        raise ValueError("arithmetic node limit")

    def visit(node):
        if isinstance(node, ast.Constant):
            literal = ast.get_source_segment(source, node) or ""
            if not _NUMBERS.fullmatch(literal):
                raise ValueError("unsupported numeric literal")
            value = Fraction(literal)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = visit(node.operand)
            value = -operand if isinstance(node.op, ast.USub) else operand
        elif isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            match node.op:
                case ast.Add():
                    value = a + b
                case ast.Sub():
                    value = a - b
                case ast.Mult():
                    value = a * b
                case ast.Div():
                    value = a / b
                case ast.Pow():
                    if b.denominator != 1 or abs(b) > 12 or (a == 0 and b == 0):
                        raise ValueError("unsupported exponent")
                    value = a ** int(b)
                case _:
                    raise ValueError("unsupported arithmetic")
        else:
            raise ValueError("unsupported arithmetic")
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > 256:
            raise ValueError("arithmetic bit limit")
        return value

    return visit(tree.body)


def _context(text: str, start: int, end: int, quotes: list[tuple[int, int]]) -> str:
    if any(a < end and start < b for a, b in quotes):
        return "QUOTED_OR_CODE"
    separator = text.rfind("\n\n", 0, start)
    paragraph_start = separator + 2 if separator >= 0 else 0
    paragraph_end = text.find("\n\n", end)
    if paragraph_end < 0:
        paragraph_end = len(text)
    before = text[max(paragraph_start, start - 220):start]
    after = text[end:min(paragraph_end, end + 160)]
    sentence_before = _SENTENCE.split(before)[-1]
    sentence_after = re.split(r"[.!?](?=\s|$)", after, maxsplit=1)[0]
    local = sentence_before + text[start:end] + sentence_after
    if after.lstrip().startswith("?"):
        return "QUESTION_OR_UNCERTAIN"
    if _CONDITIONAL.search(before + text[start:end] + sentence_after):
        return "CONDITIONAL_OR_UNCERTAIN"
    if _NEGATED.search(local):
        return "REPORTED_OR_REJECTED"
    if _APPROXIMATE.search(local):
        return "APPROXIMATE_CONTEXT"
    return "ASSERTED_EXACT"


def _math_relations(body: str) -> list[tuple[Fraction, str, Fraction]]:
    parts = _PARTS.split(body.strip().rstrip("."))
    if not 3 <= len(parts) <= 15 or len(parts) % 2 == 0:
        return []
    values = [_number(piece) for piece in parts[::2]]
    ops = [_TEX_OPERATORS.get(symbol, symbol) for symbol in parts[1::2]]
    return list(zip(values[:-1], ops, values[1:], strict=True))


def scan_numeric_relations(text: str) -> list[dict]:
    """Return literal or closed-arithmetic facts with scope and exact source spans."""
    quotes = [match.span() for match in _QUOTE.finditer(text)]
    records = []
    occupied = []
    math_delimiters = list(_MATH.finditer(text))

    def add(start, end, values, extraction):
        scope = _context(text, start, end, quotes)
        for left, op, right in values:
            records.append(Relation(start, end, text[start:end], str(left), op, str(right),
                                    _OPERATORS[op](left, right), scope, extraction))
        occupied.append((start, end))

    for match in math_delimiters:
        body, = (group for group in match.groups() if group is not None)
        try:
            values = _math_relations(body)
        except (ArithmeticError, SyntaxError, ValueError):
            continue
        if values:
            add(*match.span(), values, "WHOLE_DELIMITED_RELATION")
    for match in _ASCII.finditer(text):
        start, end = match.span("relation")
        if any(item.start() < end and start < item.end() for item in math_delimiters):
            continue
        try:
            values = _math_relations(match["relation"])
        except (ArithmeticError, SyntaxError, ValueError):
            continue
        if values:
            add(start, end, values, "WHOLE_NUMERIC_LINE")
    for pattern, method in ((_COREFERENCE, "BOUNDED_ADJACENT_COREFERENCE"), (_PROSE, "EXPLICIT_NUMERIC_PROSE")):
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(a < end and start < b for a, b in occupied):
                continue
            label = re.sub(r"\s+", " ", match["operator"].lower()).removeprefix("strictly ")
            add(start, end, [(Fraction(match["left"]), _WORD_OPERATORS[label], Fraction(match["right"]))], method)
    return [asdict(row) for row in sorted(records, key=lambda row: (row.start, row.end))]
