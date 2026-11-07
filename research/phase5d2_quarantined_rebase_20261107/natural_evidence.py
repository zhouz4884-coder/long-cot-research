"""Extract candidate relations from observed text and retain unsupported cases."""

import ast
from fractions import Fraction
import hashlib
import re

from restricted_math_checker import make_request, verify

MATH = re.compile(r"\$\$(?P<dd>.*?)\$\$|(?<!\$)\$(?!\$)(?P<d>[^$\n]+)\$|"
                  r"\\\[(?P<b>.*?)\\\]|\\\((?P<p>.*?)\\\)", re.S)
TOKEN = re.compile(r"\d+(?:\.\d+)?|[A-Za-z_][A-Za-z_0-9]*|[()+*/^\-]")
RISK = re.compile(r"\b(if|suppose|assuming|hypothetical|instead|would|could|might|"
                  r"wrong|incorrect|invalid|contradiction|not|unless|case|example|"
                  r"check|checking|whether|try|test|want|need|solve|denote|let)\b|\?", re.I)
ASSERTION_PREFIX = re.compile(r"^\s*(?:(?:so|thus|therefore|hence|then|we get|this gives|"
                              r"this equals|we have|it follows that)\s*[:,]?\s*)?$", re.I)
UNIVERSAL = re.compile(
    r"^\s*(?:(?:thus|therefore)\s*,?\s*)?for (?:all|every)\s+"
    r"(?:(positive|nonnegative|nonzero)\s+)?(real|rational|integer)(?:s| numbers?)?\s+"
    r"\$?([A-Za-z])\$?\s*[:,]?\s*$", re.I,
)


def group(text, start):
    if start >= len(text) or text[start] != "{":
        raise ValueError("Expected a braced expression")
    depth = 1
    for end in range(start + 1, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:end], end + 1
    raise ValueError("Unclosed TeX group")


def translate(text, depth=0):
    if len(text) > 512 or depth > 10:
        raise ValueError("Expression extraction bound")
    text = text.replace(r"\left", "").replace(r"\right", "").replace(r"\cdot", "*")
    text = text.replace(r"\times", "*").replace(r"\div", "/").replace("−", "-")
    if re.search(r"[\d.]\s+[\d.]", text):
        raise ValueError("Space inside a numeral")
    text = re.sub(r"\s+|\\[,;!]", "", text)
    pieces, cursor = [], 0
    while cursor < len(text):
        frac = re.match(r"\\(?:dfrac|tfrac|frac)", text[cursor:])
        if frac:
            numerator, after = group(text, cursor + len(frac.group()))
            denominator, cursor = group(text, after)
            pieces.append(f"(({translate(numerator, depth+1)})/({translate(denominator, depth+1)}))")
        else:
            pieces.append(text[cursor])
            cursor += 1
    return "".join(pieces).replace("{", "(").replace("}", ")")


def parse_expression(text):
    translated = translate(text)
    tokens = TOKEN.findall(translated)
    if not tokens or "".join(tokens) != translated or len(tokens) > 120:
        raise ValueError("Unsupported mathematical surface")
    joined = []
    for index, token in enumerate(tokens):
        if index:
            prev = tokens[index-1]
            if (prev == ")" or prev[-1].isalnum()) and (token == "(" or token[0].isalnum()):
                joined.append("*")
        joined.append("**" if token == "^" else token)
    source = "".join(joined)
    tree = ast.parse(source, mode="eval")

    def convert(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            surface = ast.get_source_segment(source, node)
            value = Fraction(surface)
            if value.denominator == 1:
                return int(value)
            return {"op": "rat", "num": value.numerator, "den": value.denominator}
        if isinstance(node, ast.Name) and re.fullmatch(r"[A-Za-z]", node.id):
            return {"op": "var", "name": node.id}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = convert(node.operand)
            return {"op": "neg", "arg": value} if isinstance(node.op, ast.USub) else value
        operators = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow"}
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            op = operators[type(node.op)]
            left, right = convert(node.left), convert(node.right)
            if op == "pow":
                if type(right) is not int:
                    raise ValueError("Nonliteral exponent")
                return {"op": op, "base": left, "exp": right}
            if op in ("sub", "div"):
                return {"op": op, "lhs": left, "rhs": right}
            return {"op": op, "args": [left, right]}
        raise ValueError("Unsupported expression node")

    variables = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)})
    return convert(tree.body), variables, source


def relations(step):
    """Yield directly observed adjacent equality statements and their source spans."""
    text = step["text"]
    matches = [m for m in MATH.finditer(text) if "=" in m.group()]
    if not matches and re.fullmatch(r"\s*[\d()+*/^= .\-−]+[.!]?\s*", text):
        matches = [re.fullmatch(r"(?P<plain>[\s\S]*)", text)]
    for match in matches:
        surface = next(v for v in match.groupdict().values() if v is not None).strip()
        if "=" not in surface or any(op in surface for op in ("<=", ">=", "!=", "\\le", "\\ge")):
            continue
        prefix = text[:match.start()]
        suffix = text[match.end():]
        clean_suffix = re.fullmatch(r"[\s.,;:!]*", suffix) is not None
        fully_asserted = (len(matches) == 1 and clean_suffix and ASSERTION_PREFIX.fullmatch(prefix) is not None
                          and RISK.search(text) is None)
        universal = UNIVERSAL.fullmatch(prefix) if len(matches) == 1 and clean_suffix else None
        pieces = surface.rstrip(".! ").split("=")
        if len(pieces) > 7:
            yield {"status": "UNKNOWN", "reason": "equality_chain_bound", "surface": surface}
            continue
        for index, (lhs, rhs) in enumerate(zip(pieces, pieces[1:])):
            try:
                la, lv, ls = parse_expression(lhs)
                ra, rv, rs = parse_expression(rhs)
            except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
                yield {"status": "UNKNOWN", "reason": "unsupported_surface", "surface": f"{lhs}={rhs}"}
                continue
            variables = sorted(set(lv) | set(rv))
            kind = "POLYNOMIAL_IDENTITY" if variables else "ARITHMETIC_EQ"
            status = "parsed"
            reason = None
            if variables and (not universal or variables != [universal[3]]):
                status, reason = "UNKNOWN", "symbolic_scope_unbound"
            domains = {}
            if universal:
                qualifier, domain_kind, variable = universal.groups()
                domain = {"kind": domain_kind.lower()}
                if qualifier and qualifier.lower() in ("positive", "nonnegative"):
                    domain.update(lower=0, lower_closed=qualifier.lower() == "nonnegative")
                if qualifier and qualifier.lower() == "nonzero":
                    domain["exclude"] = [0]
                domains[variable] = domain
            yield {"status": status, "reason": reason, "surface": f"{lhs}={rhs}",
                   "equation_index": index, "statement": {"lhs": la, "rhs": ra},
                   "variables": variables, "certificate_type": kind, "normalized": [ls, rs],
                   "step": step["step"], "token_span": [step["start"], step["end"]],
                   "char_span_in_step": [match.start(), match.end()],
                   "scope_source": prefix.strip() if variables else "closed arithmetic",
                   "literal_check_only": not bool(universal),
                   "actionable_role_candidate": bool(universal or fully_asserted),
                   "role_certified": False,
                   "domains": domains if variables else {}}


def target_for(relation, *, unscoped=False):
    if relation["status"] != "parsed":
        raise ValueError("Unbound relation")
    identifier = hashlib.sha256(repr((relation.get("observed_prefix_sha256"), relation["step"],
                                     relation["token_span"], relation["surface"])).encode()).hexdigest()[:16]
    target = {"id": "j_" + identifier, "version": 0, "kind": "justification",
            "scope": {"id": "s_" + identifier + ("_unscoped" if unscoped else ""), "version": 0,
                      "coefficient_domain": "Q",
                      "domains": ({var: {"kind": "real"} for var in relation["variables"]}
                                  if unscoped else relation["domains"])},
            "statement": relation["statement"], "certificate_type": relation["certificate_type"],
            "required_premises": [], "source_span": relation["token_span"]}
    if "observed_prefix_sha256" in relation:
        target["observed_prefix_sha256"] = relation["observed_prefix_sha256"]
    return target


def check_relation(relation, *, assignment=None, unscoped=False):
    if relation["status"] != "parsed":
        return {"status": "UNKNOWN", "reason": relation["reason"]}
    target = target_for(relation, unscoped=unscoped)
    request = make_request(target, (), mode="verify" if assignment is None else "counterexample",
                           **({} if assignment is None else {"assignment": assignment}))
    return verify(request, target=target, premises=())
