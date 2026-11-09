"""Extract bounded mathematical objects from completed, observed paragraphs."""

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

_D2 = Path(__file__).resolve().parents[1] / "phase5d2_quarantined_rebase_20261107"
if _D2.is_dir() and str(_D2) not in sys.path:
    sys.path.append(str(_D2))
from natural_evidence import MATH, parse_expression


MAX_PARAGRAPH = 4096
HISTORY_STEPS = 16
HEX = re.compile(r"[a-f0-9]{64}\Z")
NAME = r"[A-Za-z][A-Za-z0-9_]{0,31}"
NUMBER = r"[+\-−]?\d{1,64}(?:\.\d{1,64})?"
PRODUCT = re.compile(rf"({NUMBER})\s*(?:\*|×|\\times|\\cdot)\s*({NUMBER})")
PAIR = re.compile(r"\\approx(?![A-Za-z])|≈|(?<![<>!=])=(?!=|>)")
ARROW = re.compile(r"\\(?:Longleftrightarrow|Leftrightarrow|Longrightarrow|Rightarrow|"
                   r"Longleftarrow|Leftarrow)(?![A-Za-z])|<=>|<->|⇔|⟺|=>|->|⇒|⟹|⇐|⟸")
EQUIVALENT = frozenset((r"\Longleftrightarrow", r"\Leftrightarrow", "<=>", "<->", "⇔", "⟺"))
REVERSE = frozenset((r"\Longleftarrow", r"\Leftarrow", "⇐", "⟸"))
SUM_ANCHOR = re.compile(r"(?:adding (?:them|these|the terms) up|running (?:sum|subtotal)|sum the terms)\s*:", re.I)
PRECISION = re.compile(r"(?:rounded\s+)?to\s+(\d{1,2})\s+decimal places\s*[:,]", re.I)
IDENTITY = re.compile(r"(?:identity\s*:|for\s+(?:all|every)\b[^:,.!?]{1,120}[:,])\s*", re.I)
CALCULATION = re.compile(r"(?:first|next|then|well|so|therefore|thus|hence)\s*,\s*", re.I)
CANDIDATE = re.compile(r"(?:candidate solution|candidate assignment|candidate)\s*:\s*", re.I)
COUNTEREXAMPLE = re.compile(r"counterexample\s+(?:for|to)\s+([A-Za-z_][\w.:@-]{0,95})\s*:\s*", re.I | re.ASCII)
FOLLOWUP_TRANSITION = re.compile(r"This\s+(is equivalent to|implies)\s+", re.I)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ObservedSource:
    step: int
    token_span: tuple[int, int]
    char_span: tuple[int, int]
    text_sha256: str
    observed_prefix_sha256: str

    def as_dict(self):
        return {**vars(self), "token_span": list(self.token_span), "char_span": list(self.char_span)}


@dataclass(frozen=True)
class MathEvent:
    kind: str
    role: str
    raw: str
    normalized: tuple[str, ...]
    variables: tuple[str, ...]
    source: ObservedSource
    dependencies: tuple[ObservedSource, ...]
    eligibility: str
    statement_json: str

    @property
    def statement(self):
        return json.loads(self.statement_json)

    @property
    def event_id(self):
        return "e_" + digest(self._body())[:40]

    def _body(self):
        return {"kind": self.kind, "role": self.role, "raw": self.raw, "normalized": list(self.normalized),
                "variables": list(self.variables), "source": self.source.as_dict(),
                "dependencies": [item.as_dict() for item in self.dependencies],
                "eligibility": self.eligibility, "statement": self.statement}

    def as_dict(self):
        return {"event_id": self.event_id, **self._body()}


def _step_valid(step):
    return (isinstance(step, dict) and type(step.get("step")) is int and step["step"] >= 0
            and type(step.get("start")) is int and type(step.get("end")) is int
            and 0 <= step["start"] < step["end"] and type(step.get("text")) is str)


def _source(step, prefix_hash, chars=None):
    return ObservedSource(step["step"], (step["start"], step["end"]),
                          (0, len(step["text"])) if chars is None else chars,
                          sha256(step["text"].encode("utf-8")).hexdigest(), prefix_hash)


def _contiguous_history(step, history):
    result = []
    following = step
    for previous in reversed(history[-HISTORY_STEPS:]):
        if (not _step_valid(previous) or previous["step"] + 1 != following["step"]
                or previous["end"] != following["start"] or len(previous["text"]) > MAX_PARAGRAPH):
            break
        result.append(previous)
        following = previous
    return list(reversed(result))


def _body(text):
    stripped = text.strip().rstrip(".;")
    for pattern in (CALCULATION, PRECISION, IDENTITY):
        match = pattern.match(stripped)
        if match:
            stripped = stripped[match.end():].strip()
    return stripped


def _numeric(text):
    value = Fraction(text.strip().replace("−", "-"))
    if value.denominator == 1:
        return value.numerator
    return {"op": "rat", "num": value.numerator, "den": value.denominator}


def _decimal_places(text):
    if not re.fullmatch(NUMBER, text):
        return None
    return len(text.partition(".")[2])


def _equation(left, right):
    lhs, left_vars, left_normalized = parse_expression(left)
    rhs, right_vars, right_normalized = parse_expression(right)
    return ({"lhs": lhs, "rhs": rhs}, tuple(sorted(set(left_vars) | set(right_vars))),
            (left_normalized, right_normalized))


def _pair(text):
    matches = list(PAIR.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    return text[:match.start()].strip(), match.group() != "=", text[match.end():].strip()


def _approximation_basis(lhs, history):
    """An observed local multiplication block can suggest display rounding."""
    product = PRODUCT.fullmatch(lhs)
    if not product:
        return ()
    common = set(product.groups())
    used = []
    approximate = r"(?:≈|\\approx)"
    for row in reversed(history):
        text = row["text"].strip()
        used.append(row)
        cue = re.search(rf"(?<![A-Za-z0-9_.])({PRODUCT.pattern})\s*{approximate}\s*(?P<question>\?)?\s*$", text)
        if cue and (cue["question"] or re.search(rf"{approximate}\s*$", text[:cue.start()])):
            factors = PRODUCT.fullmatch(cue[1])
            return tuple(reversed(used)) if common.intersection(factors.groups()) else ()
        if re.fullmatch(r"Let me compute that\s*:", text, re.I):
            continue
        requested = re.fullmatch(rf"Compute\s+({PRODUCT.pattern})\s*:", text, re.I)
        relation = _pair(_body(text))
        previous = PRODUCT.fullmatch(requested[1]) if requested else PRODUCT.fullmatch(relation[0]) if relation else None
        if previous is None or (relation is not None and _decimal_places(relation[2]) is None):
            return ()
        common.intersection_update(previous.groups())
        if not common:
            return ()
    return ()


def _sum_context(history):
    """Require an explicit addition block and one uninterrupted subtotal chain."""
    anchor = next((i for i in range(len(history) - 1, -1, -1)
                   if SUM_ANCHOR.fullmatch(history[i]["text"].strip())), None)
    if anchor is None or anchor + 1 == len(history):
        return None, ()
    chain = []
    subtotal = None
    for row in history[anchor + 1:]:
        split = _pair(_body(row["text"]))
        if split is None:
            return None, ()
        lhs, approximate, rhs = split
        scale = _decimal_places(rhs)
        if scale is None:
            return None, ()
        if subtotal is None:
            try:
                statement, variables, _ = _equation(lhs, rhs)
            except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
                return None, ()
            if variables or lhs.startswith("+") or not isinstance(statement["lhs"], dict) or statement["lhs"]["op"] != "add":
                return None, ()
        elif lhs.startswith("+") and re.fullmatch(NUMBER, lhs[1:].strip()):
            statement = {"lhs": {"op": "add", "args": [_numeric(subtotal), _numeric(lhs[1:])]}, "rhs": _numeric(rhs)}
        else:
            return None, ()
        chain.append({**statement, "approximate": approximate, "decimal_places": scale})
        subtotal = rhs
    return {"subtotal": subtotal, "chain": chain}, tuple(history[anchor:])


def _assignment_text(text):
    assignment = {}
    for element in text.split(","):
        match = re.fullmatch(rf"\s*({NAME})\s*=\s*({NUMBER}(?:/\d{{1,64}})?)\s*", element)
        if not match or match[1] in assignment:
            raise ValueError("Expected a complete exact assignment")
        assignment[match[1]] = _numeric(match[2])
    return assignment


def _whole_exact_equation(text):
    body = text.strip().rstrip(".;")
    wrapped = MATH.fullmatch(body)
    if wrapped is not None:
        body = next(value for value in wrapped.groupdict().values() if value is not None)
    parts = _pair(body)
    if parts is None or parts[1]:
        raise ValueError("Expected one complete exact equation")
    return _equation(parts[0], parts[2])


def extract_events(step, *, observed_prefix_sha256, prior_steps=()):
    """Return typed events for one caller-validated, observed source paragraph.

    History supplies source text and spans only. Neither caller annotations in
    step dictionaries nor lexical extraction issue proof authority.
    """
    if not _step_valid(step) or not isinstance(observed_prefix_sha256, str) or not HEX.fullmatch(observed_prefix_sha256):
        raise ValueError("An observed paragraph and exact prefix hash are required")
    text = step["text"]
    source = _source(step, observed_prefix_sha256)

    def event(kind, role, statement, *, source=source, normalized=(), variables=(), dependencies=(), eligibility="CHECKABLE"):
        start, end = source.char_span
        return MathEvent(kind, role, text[start:end], tuple(normalized), tuple(variables), source,
                         tuple(_source(row, observed_prefix_sha256) for row in dependencies),
                         eligibility, canonical_json(statement))

    if len(text) > MAX_PARAGRAPH:
        return (event("UNSUPPORTED", "unresolved", {}, eligibility="PARAGRAPH_LIMIT"),)
    trimmed = text.strip().rstrip(".;")
    counterexample = COUNTEREXAMPLE.match(trimmed)
    if counterexample:
        return (event("COUNTEREXAMPLE", "counterexample_proposal", {"target_id": counterexample[1],
                       "proposal_text": trimmed[counterexample.end():]}, eligibility="REQUIRES_TARGET"),)
    candidate = CANDIDATE.match(trimmed)
    if candidate:
        body = trimmed[candidate.end():]
        wrapped = MATH.fullmatch(body)
        if wrapped is not None:
            body = next(value for value in wrapped.groupdict().values() if value is not None)
        try:
            assignment = _assignment_text(body)
        except (ValueError, ZeroDivisionError):
            return (event("CANDIDATE_SOLUTION", "candidate_assignment", {}, eligibility="INVALID_ASSIGNMENT_SURFACE"),)
        return (event("CANDIDATE_SOLUTION", "candidate_assignment", {"assignment": assignment},
                      variables=sorted(assignment), eligibility="REQUIRES_COMPLETE_CONSTRAINTS"),)

    history = _contiguous_history(step, prior_steps)
    followup = FOLLOWUP_TRANSITION.match(trimmed)
    if followup:
        previous = history[-1] if history else None
        if previous is None or any(row.get("boundary") != "paragraph" or not row["text"].endswith("\n\n")
                                   for row in (previous, step)):
            return (event("EQUATION_TRANSITION", "transition_candidate", {}, eligibility="UNBOUND_PREDECESSOR_EQUATION"),)
        try:
            first, first_vars, first_normalized = _whole_exact_equation(previous["text"])
            second, second_vars, second_normalized = _whole_exact_equation(trimmed[followup.end():])
        except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
            return (event("EQUATION_TRANSITION", "transition_candidate", {}, eligibility="UNSUPPORTED_TRANSITION_SURFACE"),)
        direction = "IFF" if followup[1].casefold() == "is equivalent to" else "IMPLIES"
        return (event("EQUATION_TRANSITION", "transition_candidate",
                      {"direction": direction, "antecedent": first, "consequent": second},
                      normalized=(*first_normalized, direction, *second_normalized),
                      variables=sorted(set(first_vars) | set(second_vars)), dependencies=(previous,),
                      eligibility="REQUIRES_PREDECESSOR_SCOPE"),)

    fragments = [(next(value for value in match.groupdict().values() if value is not None).strip(),
                  _source(step, observed_prefix_sha256, match.span()), text[:match.start()]) for match in MATH.finditer(text)]
    if not fragments:
        body = _body(text)
        start = text.rfind(body)
        fragments = [(body, _source(step, observed_prefix_sha256, (start, start + len(body))), text)]
    events = []
    for fragment, span, context in fragments:
        arrows = list(ARROW.finditer(fragment))
        if arrows:
            arrow = arrows[0]
            antecedent, consequent = _pair(fragment[:arrow.start()]), _pair(fragment[arrow.end():])
            relation = "IFF" if arrow.group() in EQUIVALENT else "IMPLIES"
            if arrow.group() in REVERSE:
                antecedent, consequent = consequent, antecedent
            try:
                if len(arrows) != 1 or antecedent is None or consequent is None or antecedent[1] or consequent[1]:
                    raise ValueError("Expected one arrow between exact equations")
                first, first_vars, first_normalized = _equation(antecedent[0], antecedent[2])
                second, second_vars, second_normalized = _equation(consequent[0], consequent[2])
            except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
                events.append(event("EQUATION_TRANSITION", "transition_candidate", {}, source=span,
                                    eligibility="UNSUPPORTED_TRANSITION_SURFACE"))
            else:
                events.append(event("EQUATION_TRANSITION", "transition_candidate",
                                    {"direction": relation, "antecedent": first, "consequent": second},
                                    source=span, normalized=(*first_normalized, relation, *second_normalized),
                                    variables=sorted(set(first_vars) | set(second_vars)), eligibility="REQUIRES_SCOPE"))
            continue

        operators = list(PAIR.finditer(fragment))
        if not operators:
            continue
        if len(operators) > 6:
            events.append(event("UNSUPPORTED", "unresolved", {}, source=span, eligibility="CHAIN_LIMIT"))
            continue
        identity = IDENTITY.match(context.strip()) is not None
        precision = PRECISION.match(CALCULATION.sub("", context.strip(), count=1))
        for i, operator in enumerate(operators):
            left = fragment[operators[i - 1].end() if i else 0:operator.start()].strip()
            right = fragment[operator.end():operators[i + 1].start() if i + 1 < len(operators) else len(fragment)].strip()
            approximate = operator.group() != "=" or precision is not None
            if len(operators) == 1 and left.startswith("+") and re.fullmatch(NUMBER, left[1:].strip()):
                subtotal, dependencies = _sum_context(history)
                scale = _decimal_places(right)
                if subtotal is None or scale is None or len(fragments) != 1 or fragment != _body(text):
                    events.append(event("RUNNING_SUM_CONTINUATION", "displayed_subtotal", {}, source=span,
                                        eligibility="UNBOUND_RUNNING_SUBTOTAL"))
                else:
                    current = {"lhs": {"op": "add", "args": [_numeric(subtotal["subtotal"]), _numeric(left[1:])]},
                               "rhs": _numeric(right)}
                    events.append(event("RUNNING_SUM_CONTINUATION", "displayed_subtotal",
                                        {**current, "prior_chain": subtotal["chain"], "approximate": approximate,
                                         "decimal_places": scale}, source=span, dependencies=dependencies,
                                        normalized=(subtotal["subtotal"], left, right)))
                continue
            try:
                statement, variables, normalized = _equation(left, right)
            except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
                events.append(event("UNSUPPORTED", "unresolved_equation", {}, source=span,
                                    eligibility="UNSUPPORTED_EQUATION_SURFACE"))
                continue
            basis = () if approximate or variables or len(operators) != 1 or len(fragments) != 1 else _approximation_basis(left, history)
            if approximate or basis:
                scale = int(precision[1]) if precision else _decimal_places(right)
                mode = "DECLARED_DECIMAL_PLACES" if precision else "EXPLICIT_APPROXIMATION" if approximate else "INFERRED_DISPLAY_PRECISION"
                events.append(event("APPROX_ARITHMETIC", "display_approximation", {**statement, "precision_mode": mode,
                                    "decimal_places": scale}, source=span, normalized=normalized, variables=variables,
                                    dependencies=basis, eligibility="CHECKABLE" if not variables and scale is not None and scale <= 64 else "UNSUPPORTED_PRECISION"))
            elif not variables:
                events.append(event("CLOSED_ARITHMETIC", "literal_expression", statement,
                                    source=span, normalized=normalized))
            elif identity:
                events.append(event("SYMBOLIC_IDENTITY", "identity_candidate", statement,
                                    source=span, normalized=normalized, variables=variables, eligibility="REQUIRES_SCOPE"))
            else:
                events.append(event("EQUATION", "unclassified_equation", statement, source=span,
                                    normalized=normalized, variables=variables, eligibility="UNRESOLVED_EQUATION_ROLE"))
    return tuple(events)
