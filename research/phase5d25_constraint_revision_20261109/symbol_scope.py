"""Persistent bindings over exact observed token slices. No implicit premise promotion."""

from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
import json
import re


NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
ROLES = {"PROBLEM_GIVEN", "LOCAL_DEFINITION", "TEMPORARY_ASSUMPTION", "CASE_ASSUMPTION", "LEXICAL_BOUNDARY"}
MAX_VARIABLES = 4
MAX_PREMISES = 16
MAX_DEPTH = 8


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _ids(values):
    values = tuple(values)
    if any(type(token) is not int or token < 0 for token in values):
        raise ValueError("Token IDs must be nonnegative integers")
    return values


def _decode(tokenizer, values):
    return tokenizer.decode(list(values), skip_special_tokens=False)


@dataclass(frozen=True)
class EvidenceRef:
    source: str
    role: str
    token_span: tuple[int, int]
    char_span: tuple[int, int]
    observed_length: int
    source_prefix_sha256: str
    token_sha256: str
    excerpt_sha256: str

    @property
    def evidence_id(self):
        return "ev_" + digest(self.as_dict())[:32]

    def as_dict(self):
        return {**vars(self), "token_span": list(self.token_span), "char_span": list(self.char_span)}


@dataclass(frozen=True)
class Binding:
    name: str
    binding_id: str
    version: int
    scope_id: str
    role: str
    evidence: EvidenceRef
    domain_json: str | None

    @property
    def symbol(self):
        return self.name

    @property
    def domain(self):
        return None if self.domain_json is None else json.loads(self.domain_json)

    @property
    def trusted_problem_given(self):
        return self.role == "PROBLEM_GIVEN"

    def as_dict(self):
        return {"name": self.name, "binding_id": self.binding_id, "version": self.version,
                "scope_id": self.scope_id, "role": self.role, "evidence": self.evidence.as_dict(),
                "domain": self.domain}


@dataclass(frozen=True)
class BoundAssumption:
    premise_id: str
    scope_id: str
    role: str
    evidence: EvidenceRef
    bindings: tuple[Binding, ...]
    predicate_json: str

    @property
    def predicate(self):
        return json.loads(self.predicate_json)

    def as_dict(self):
        return {"premise_id": self.premise_id, "scope_id": self.scope_id, "role": self.role,
                "predicate": self.predicate, "evidence": self.evidence.as_dict(),
                "binding_refs": [[b.name, b.binding_id, b.version] for b in self.bindings]}


@dataclass(frozen=True)
class Frame:
    scope_id: str
    parent_id: str | None
    kind: str
    evidence: EvidenceRef | None
    ambiguity: str | None = None
    case_index: int | None = None
    restart_cue: EvidenceRef | None = None


@dataclass(frozen=True)
class Resolution:
    status: str
    reason: str | None
    scope_id: str
    scope_version: int
    bindings: tuple[Binding, ...] = ()
    assumptions: tuple[BoundAssumption, ...] = ()
    unresolved_symbols: tuple[str, ...] = ()
    observed_prefix_sha256: str = ""
    branch_scopes: tuple[tuple[str, str, str | None], ...] = ()
    problem_qualification: str = "EXPLICIT_DECLARATION"

    @property
    def authority(self):
        if self.status != "BOUND":
            return "UNKNOWN"
        if (self.problem_qualification == "EXPLICIT_DECLARATION" and len(self.branch_scopes) <= 1
                and all(b.trusted_problem_given for b in self.bindings) and all(
                    a.role == "PROBLEM_GIVEN" for a in self.assumptions)):
            return "PROBLEM"
        return "CONDITIONAL"

    def checker_inputs(self):
        """Return a fresh D2 domain and premise packet; callers must retain authority."""
        if self.status != "BOUND":
            raise ValueError("Unbound symbols do not furnish checker premises")
        scope = {"id": self.scope_id, "version": self.scope_version, "coefficient_domain": "Q",
                 "domains": {binding.name: binding.domain for binding in self.bindings}}
        premises = [{"id": a.premise_id, "version": 0, "scope_id": self.scope_id,
                     "scope_version": self.scope_version, "predicate": a.predicate,
                     "evidence_id": a.evidence.evidence_id} for a in self.assumptions]
        required = [{key: premise[key] for key in ("id", "version", "scope_id", "scope_version")}
                    for premise in premises]
        return scope, premises, required


def _validate_domain(domain):
    if domain is None:
        return None
    if type(domain) is not dict or domain.get("kind") not in {"integer", "rational", "real"}:
        raise ValueError("Explicit supported variable domain required")
    if set(domain) - {"kind", "lower", "upper", "lower_closed", "upper_closed", "exclude", "values"}:
        raise ValueError("Unsupported domain field")
    def scalar(value):
        if type(value) is int:
            return Fraction(value)
        if (type(value) is dict and set(value) == {"op", "num", "den"} and value["op"] == "rat"
                and type(value["num"]) is int and type(value["den"]) is int and value["den"]):
            return Fraction(value["num"], value["den"])
        raise ValueError("Unsupported exact domain endpoint")
    for key in ("lower", "upper"):
        if key in domain:
            scalar(domain[key])
        if key + "_closed" in domain and (type(domain[key + "_closed"]) is not bool or key not in domain):
            raise ValueError("Invalid domain closure")
    if "lower" in domain and "upper" in domain and scalar(domain["lower"]) > scalar(domain["upper"]):
        raise ValueError("Inconsistent domain bounds")
    for key in ("exclude", "values"):
        if key in domain:
            if type(domain[key]) is not list or not 0 < len(domain[key]) <= 16:
                raise ValueError("Unsupported domain list")
            for value in domain[key]:
                scalar(value)
    return _json(domain)


def _variables(value):
    if type(value) is dict:
        if value.get("op") == "var":
            name = value.get("name")
            if set(value) != {"op", "name"} or type(name) is not str or not NAME.fullmatch(name):
                raise ValueError("Invalid variable node")
            return {name}
        return set().union(*(_variables(child) for child in value.values()))
    if type(value) in (tuple, list):
        return set().union(*map(_variables, value))
    return set()


@dataclass(frozen=True)
class ScopeState:
    prompt_ids: tuple[int, ...]
    problem_token_span: tuple[int, int] | None
    generated_ids: tuple[int, ...]
    frames: tuple[Frame, ...]
    binding_history: tuple[Binding, ...] = ()
    assumption_history: tuple[BoundAssumption, ...] = ()
    revision: int = 0
    problem_sealed: bool = False
    diagnostics: tuple[tuple[int, str], ...] = ()
    problem_qualification: str = "EXPLICIT_DECLARATION"
    restart_cue: tuple[int, EvidenceRef] | None = None

    @classmethod
    def create(cls, prompt_ids, problem_token_span=None):
        prompt = _ids(prompt_ids)
        if not prompt:
            raise ValueError("Original prompt token IDs required")
        if problem_token_span is not None:
            start, end = problem_token_span
            if not (type(start) is type(end) is int and 0 <= start < end <= len(prompt)):
                raise ValueError("Problem source is outside original prompt")
            problem_token_span = (start, end)
        root = Frame("s_" + digest((prompt, problem_token_span))[:32], None, "MAINLINE", None)
        return cls(prompt, problem_token_span, (), (root,))

    @property
    def observed_prefix_sha256(self):
        return digest(self.prompt_ids + self.generated_ids)

    @property
    def frame(self):
        return self.frames[-1]

    def advance_prefix(self, observed_generated_ids):
        generated = _ids(observed_generated_ids)
        if generated[:len(self.generated_ids)] != self.generated_ids:
            raise ValueError("Observed token history changed or moved backwards")
        return replace(self, generated_ids=generated, problem_sealed=True)

    def evidence(self, source, role, token_span, tokenizer, *, char_span=None):
        tokens = self._source_tokens(source, token_span)
        text = _decode(tokenizer, tokens)
        chars = (0, len(text)) if char_span is None else tuple(char_span)
        start, end = chars
        if not (type(start) is type(end) is int and 0 <= start < end <= len(text)):
            raise ValueError("Evidence excerpt is outside decoded source tokens")
        if role not in ROLES:
            raise ValueError("Unsupported source role")
        observed = len(self.generated_ids) if source == "GENERATED" else 0
        prefix = self.observed_prefix_sha256 if source == "GENERATED" else digest(self.prompt_ids)
        return EvidenceRef(source, role, tuple(token_span), chars, observed, prefix,
                           digest(tokens), sha256(text[start:end].encode("utf-8")).hexdigest())

    def _source_tokens(self, source, token_span):
        start, end = token_span
        if not (type(start) is type(end) is int and 0 <= start < end):
            raise ValueError("Invalid evidence token span")
        if source == "PROBLEM" and self.problem_token_span is not None:
            first, last = self.problem_token_span
            if first <= start < end <= last:
                return self.prompt_ids[start:end]
        elif source == "GENERATED" and end <= len(self.generated_ids):
            return self.generated_ids[start:end]
        raise ValueError("Evidence is outside its observed source")

    def _validate_evidence(self, evidence, roles):
        if not isinstance(evidence, EvidenceRef) or evidence.role not in roles:
            raise ValueError("Missing source evidence or role mismatch")
        tokens = self._source_tokens(evidence.source, evidence.token_span)
        if evidence.source == "PROBLEM":
            if evidence.role != "PROBLEM_GIVEN" or self.problem_sealed or len(self.frames) != 1:
                raise ValueError("Original-problem facts can only enter the original root")
            expected = (0, digest(self.prompt_ids))
        else:
            if evidence.role == "PROBLEM_GIVEN":
                raise ValueError("A model statement cannot become a problem given")
            if evidence.token_span[1] != len(self.generated_ids):
                raise ValueError("New scope evidence must end at the current observed boundary")
            required_frame = {"CASE_ASSUMPTION": "CASE", "TEMPORARY_ASSUMPTION": "ASSUMPTION"}.get(evidence.role)
            if required_frame is not None and self.frame.kind != required_frame:
                raise ValueError("Conditional evidence requires the corresponding active child scope")
            expected = (len(self.generated_ids), self.observed_prefix_sha256)
        if (evidence.observed_length, evidence.source_prefix_sha256) != expected or evidence.token_sha256 != digest(tokens):
            raise ValueError("Evidence belongs to a different observed token prefix")

    def enter(self, kind, evidence, *, ambiguity=None, case_index=None):
        self._validate_evidence(evidence, {"LEXICAL_BOUNDARY"})
        if kind not in {"CASE", "ASSUMPTION", "AMBIGUOUS"} or len(self.frames) >= MAX_DEPTH:
            raise ValueError("Unsupported scope nesting")
        frame = Frame("s_" + digest((self.frame.scope_id, evidence.evidence_id, self.revision,
                                     kind, ambiguity, case_index))[:32],
                      self.frame.scope_id, kind, evidence, ambiguity, case_index)
        return replace(self, frames=self.frames + (frame,), revision=self.revision + 1)

    def exit(self, kind, evidence):
        self._validate_evidence(evidence, {"LEXICAL_BOUNDARY"})
        if len(self.frames) == 1 or self.frame.kind != kind:
            raise ValueError("Scope exit does not match the active child")
        return replace(self, frames=self.frames[:-1], revision=self.revision + 1)

    def visible(self, name, *, prior=None):
        active = {frame.scope_id for frame in self.frames}
        restarted = any(frame.kind == "RESTART" for frame in self.frames)
        root_id = self.frames[0].scope_id
        return next((b for b in reversed(self.binding_history) if b.name == name and b.scope_id in active
                     and (not restarted or b.scope_id != root_id or b.trusted_problem_given)
                     and (prior is None or prior(b.evidence))), None)

    def declare(self, name, domain, evidence, *, replaces=None):
        self._validate_evidence(evidence, ROLES - {"LEXICAL_BOUNDARY"})
        if type(name) is not str or not NAME.fullmatch(name):
            raise ValueError("Unsupported symbol name")
        current = self.visible(name)
        if current is not None and current.scope_id == self.frame.scope_id:
            if replaces != current.binding_id or current.trusted_problem_given:
                raise ValueError("Same-scope rebinding requires explicit current local version")
        elif replaces is not None:
            raise ValueError("Revision source binding is stale or in another scope")
        version = max((b.version for b in self.binding_history if b.name == name), default=-1) + 1
        payload = _validate_domain(domain)
        binding = Binding(name, "b_" + digest((self.frame.scope_id, name, version, evidence.evidence_id, payload))[:32],
                          version, self.frame.scope_id, evidence.role, evidence, payload)
        return replace(self, binding_history=self.binding_history + (binding,), revision=self.revision + 1)

    def assume(self, predicate, evidence):
        self._validate_evidence(evidence, ROLES - {"LEXICAL_BOUNDARY"})
        if type(predicate) is not dict or set(predicate) != {"op", "lhs", "rhs"} or predicate["op"] not in {
                "eq", "ne", "lt", "le", "gt", "ge"}:
            raise ValueError("Unsupported scope predicate")
        names = sorted(_variables(predicate))
        bindings = tuple(self.visible(name) for name in names)
        if not bindings or any(binding is None or binding.domain is None for binding in bindings):
            raise ValueError("Premise has no completely bound scope")
        if evidence.source == "PROBLEM" and not all(b.trusted_problem_given for b in bindings):
            raise ValueError("Problem predicate has model-local premises")
        value = _json(predicate)
        identifier = "p_" + digest((self.frame.scope_id, evidence.evidence_id, value,
                                    tuple(b.binding_id for b in bindings)))[:32]
        if any(a.premise_id == identifier for a in self.assumption_history):
            return self
        record = BoundAssumption(identifier, self.frame.scope_id, evidence.role, evidence, bindings, value)
        return replace(self, assumption_history=self.assumption_history + (record,), revision=self.revision + 1)

    def resolve_expression(self, symbols, *, target_token_span=None, target_char_span=None):
        """Resolve at a checkpoint, or before a specific generated relation's source."""
        names = set(symbols)
        if any(type(name) is not str or not NAME.fullmatch(name) for name in names):
            raise ValueError("Invalid expression symbol")
        prefix = self.observed_prefix_sha256
        branch_scopes = tuple((frame.scope_id, frame.kind, frame.parent_id) for frame in self.frames)
        def unknown(reason, missing=()):
            return Resolution("UNBOUND", reason, self.frame.scope_id, self.revision,
                              unresolved_symbols=tuple(sorted(missing)), observed_prefix_sha256=prefix,
                              branch_scopes=branch_scopes, problem_qualification=self.problem_qualification)
        if target_token_span is not None:
            target_token_span = tuple(target_token_span)
            self._source_tokens("GENERATED", target_token_span)
            if target_char_span is not None:
                a, b = target_char_span
                if not (type(a) is type(b) is int and 0 <= a < b):
                    raise ValueError("Invalid target character interval")
                target_char_span = (a, b)
        elif target_char_span is not None:
            raise ValueError("Target character coordinates require a token span")

        def prior(evidence):
            if evidence.source == "PROBLEM" or target_token_span is None:
                return True
            if evidence.token_span[1] <= target_token_span[0]:
                return True
            return (evidence.token_span == target_token_span and target_char_span is not None
                    and evidence.char_span[1] <= target_char_span[0])

        if names and any(frame.evidence is not None and not prior(frame.evidence) for frame in self.frames):
            return unknown("scope_boundary_not_prior_to_target", names)
        if names and any(frame.ambiguity for frame in self.frames):
            return unknown(next(frame.ambiguity for frame in reversed(self.frames) if frame.ambiguity), names)
        active = {frame.scope_id for frame in self.frames}
        restarted = any(frame.kind == "RESTART" for frame in self.frames)
        premises = [a for a in self.assumption_history if a.scope_id in active and prior(a.evidence)
                    and (not restarted or a.scope_id != self.frames[0].scope_id or a.role == "PROBLEM_GIVEN")]
        guarded = {a.scope_id for a in premises if a.role in {"CASE_ASSUMPTION", "TEMPORARY_ASSUMPTION"}}
        if names and any(frame.kind in {"CASE", "ASSUMPTION"} and frame.scope_id not in guarded
                         for frame in self.frames):
            return unknown("active_scope_guard_missing", names)
        local, stale = [], []
        for premise in premises:
            target = local if all(self.visible(b.name, prior=prior) == b for b in premise.bindings) else stale
            target.append(premise)
        chosen = []
        # Close over linked premises. Projection must not silently forget a required condition.
        for _ in range(len(local) + 1):
            found = [a for a in local if a.role in {"CASE_ASSUMPTION", "TEMPORARY_ASSUMPTION"}
                     or any(b.name in names for b in a.bindings)]
            if found == chosen:
                break
            chosen = found
            names |= {b.name for a in chosen for b in a.bindings}
        for premise in stale:
            # The checker has one slot per surface name. It cannot represent an older
            # hidden binding in a still-relevant condition, or a stale definition input.
            predicate = premise.predicate
            live = {b.name for b in premise.bindings if self.visible(b.name, prior=prior) == b}
            if premise.role in {"CASE_ASSUMPTION", "TEMPORARY_ASSUMPTION"} and names:
                return unknown("conditional_guard_has_shadowed_binding", names)
            if premise.role == "PROBLEM_GIVEN" and live & names:
                return unknown("required_problem_premise_has_shadowed_binding", live & names)
            if (premise.role == "LOCAL_DEFINITION" and predicate["op"] == "eq"
                    and type(predicate["lhs"]) is dict and predicate["lhs"].get("op") == "var"
                    and predicate["lhs"]["name"] in live & names):
                return unknown("definition_dependency_has_stale_binding", (predicate["lhs"]["name"],))
        if len(names) > MAX_VARIABLES or len(chosen) > MAX_PREMISES:
            return unknown("checker_scope_limit", names)
        bindings = tuple(self.visible(name, prior=prior) for name in sorted(names))
        missing = [name for name, b in zip(sorted(names), bindings) if b is None or b.domain is None]
        if missing:
            return unknown("symbol_missing_domain_or_binding", missing)
        # Versions are branch-local counters. Prefix identity separates sibling histories.
        scope_id = "s_" + digest((self.frame.scope_id, prefix, self.revision, self.problem_qualification,
                                  target_token_span, target_char_span,
                                  tuple(b.binding_id for b in bindings), tuple(a.premise_id for a in chosen)))[:32]
        return Resolution("BOUND", None, scope_id, self.revision, bindings, tuple(chosen),
                          observed_prefix_sha256=prefix, branch_scopes=branch_scopes,
                          problem_qualification=self.problem_qualification)


_MATH = r"(?:\$\$(?P<display>.+?)\$\$|\$(?P<inline>[^$\n]+)\$|\\\[(?P<bracket>.+?)\\\]|\\\((?P<paren>.+?)\\\))"
_SYMBOL = r"(?:\$[A-Za-z][A-Za-z0-9_]{0,31}\$|[A-Za-z])"
_NAMES = rf"{_SYMBOL}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+){_SYMBOL})*"
_DOMAIN = r"(?:(?P<qualifier>positive|nonnegative|nonzero|negative|nonpositive)\s+)?(?P<kind>integer|rational|real)(?:s|\s+numbers?)?"
_DECLARATION = re.compile(rf"\s*let\s+(?P<names>{_NAMES})\s+be\s+(?:an?\s+)?{_DOMAIN}\b", re.I)
_PROBLEM_CONDITION = re.compile(rf"\s*(?:such that|satisfying|subject to|where)\s+{_MATH}", re.I | re.S)
_POSITIVE_SOLUTION = re.compile(rf"\s*find the positive solution (?:to|of)\s+(?:the equation\s+)?{_MATH}\s*[.]?\s*$",
                                re.I | re.S)
_PARTIAL_DOMAIN = re.compile(r",\s*and\s+\$(?P<name>[A-Za-z])\$\s+is\s+"
                             r"(?P<qualifier>positive|nonzero|negative|nonnegative|nonpositive)\s*,\s*"
                             r"(?=what\b|find\b|determine\b|compute\b)", re.I)
_RESTART = re.compile(r"(?:but\s+)?(?:wait,\s+let me think again\.\s+)?let me\s+"
                      r"(?:check with another approach|try another (?:approach|method)|"
                      r"check if there['’]s another approach)\b", re.I)
_ORIGINAL_EQUATION = re.compile(rf"\s*original equation\s*:\s*{_MATH}", re.I | re.S)
_GUARD = re.compile(rf"\s*(?:assume|assuming|suppose|if)\s+(?:that\s+)?{_MATH}", re.I | re.S)
_CASE = re.compile(rf"\s*case\s+(?P<number>[1-9][0-9]?)\s*:\s*{_MATH}", re.I | re.S)
_LET = re.compile(rf"\s*(?:(?:let(?:\s+me\s+set)?)|define)\s+{_MATH}", re.I | re.S)
_GUARD_REMAINDER = re.compile(r"\s*(?:[.:]?\s*$|(?:[.,:]\s*)?(?:then|we can|thus|so)\b)", re.I)
_LET_REMAINDER = re.compile(r"\s*\.(?:\s*$|\s+(?:then|thus|so|hence|therefore)\b)|\s*$", re.I)
_REL = re.compile(r"\\(?:neq|ne|leq|le|geq|ge)(?![A-Za-z])|!=|<=|>=|[=<>≠≤≥]")
_OPERATORS = {"=": "eq", "<": "lt", ">": "gt", "!=": "ne", "≠": "ne", "\\neq": "ne", "\\ne": "ne",
              "<=": "le", "≤": "le", "\\le": "le", "\\leq": "le",
              ">=": "ge", "≥": "ge", "\\ge": "ge", "\\geq": "ge"}
_PARSE_ERRORS = (ValueError, SyntaxError, ZeroDivisionError, RecursionError)


def _qualify(kind, qualifier):
    domain = {"kind": kind.lower()}
    if qualifier is not None:
        qualifier = qualifier.lower()
        if qualifier == "nonzero":
            domain["exclude"] = [0]
        elif qualifier in {"positive", "nonnegative"}:
            domain.update(lower=0, lower_closed=qualifier == "nonnegative")
        else:
            domain.update(upper=0, upper_closed=qualifier == "nonpositive")
    return domain


def _names(match):
    return tuple(word.strip("$") for word in re.split(r"(?:\s*,\s*(?:and\s+)?|\s+and\s+)",
                                                       match["names"], flags=re.I))


def _math(match):
    return next(match[field] for field in ("display", "inline", "bracket", "paren") if match[field] is not None)


def _predicate(surface, parse_expression, state):
    surface = surface.rstrip().removesuffix(".")
    operators = list(_REL.finditer(surface))
    if len(operators) != 1:
        raise ValueError("Expected one explicit predicate")
    operator = operators[0]
    # In the supported algebra grammar, two adjacent declared one-letter symbols may be juxtaposed.
    def expression(raw):
        raw = re.sub(r"(\\(?:dfrac|tfrac|frac))\s*([0-9A-Za-z])\s*(?=\{)",
                     lambda match: match[1] + "{" + match[2] + "}", raw)
        try:
            return parse_expression(raw)[0]
        except _PARSE_ERRORS:
            def product(match):
                pair = match.group()
                if state.visible(pair) is None and all(state.visible(name) is not None for name in pair):
                    return "*".join(pair)
                return pair
            expanded = re.sub(r"(?<![A-Za-z_\\])[A-Za-z]{2}(?![A-Za-z_])", product, raw)
            if expanded == raw:
                raise
            return parse_expression(expanded)[0]
    return {"op": _OPERATORS[operator.group()], "lhs": expression(surface[:operator.start()]),
            "rhs": expression(surface[operator.end():])}


def _note(state, step, reason, *, block=False):
    frames = state.frames
    if block:
        frames = frames[:-1] + (replace(frames[-1], ambiguity=reason),)
    return replace(state, frames=frames, diagnostics=state.diagnostics + ((step, reason),),
                   revision=state.revision + int(block))


def _problem_position(prompt, question, tokenizer):
    full = _decode(tokenizer, prompt)
    marker = "<|im_start|>user\n"
    if full.count(marker) != 1 or any(mark in question for mark in ("<|im_start|>", "<|im_end|>")):
        raise ValueError("Original user question is not uniquely delimited")
    first = full.index(marker) + len(marker)
    last = first + len(question)
    if not question or full[first:last] != question or not full[last:].startswith(("\n", "<|im_end|>")):
        raise ValueError("Question text differs from actual original prompt")
    offsets = []
    for index in range(len(prompt) + 1):
        prefix = _decode(tokenizer, prompt[:index])
        if full.startswith(prefix):
            offsets.append((len(prefix), index))
    left, start = max(pair for pair in offsets if pair[0] <= first)
    right, end = min(pair for pair in offsets if pair[0] >= last)
    if start >= end or _decode(tokenizer, prompt[start:end]) != full[left:right]:
        raise ValueError("Question has no verified covering token span")
    return (start, end), first - left


def scope_from_problem(prompt_ids, question, tokenizer, parse_expression):
    """Register only exact declarations in the observed user-question interval."""
    prompt = _ids(prompt_ids)
    span, offset = _problem_position(prompt, question, tokenizer)
    state = ScopeState.create(prompt, span)
    declaration = _DECLARATION.match(question)
    if declaration is None:
        positive = _POSITIVE_SOLUTION.fullmatch(question)
        if positive:
            try:
                predicate = _predicate(_math(positive), parse_expression, state)
                names = _variables(predicate)
                if predicate["op"] != "eq" or len(names) != 1:
                    raise ValueError("Positive solution clause requires one equation variable")
                ref = state.evidence("PROBLEM", "PROBLEM_GIVEN", span, tokenizer,
                                     char_span=(offset + positive.start(), offset + positive.end()))
                state = state.declare(next(iter(names)), _qualify("real", "positive"), ref)
                state = state.assume(predicate, ref)
                return _note(replace(state, problem_qualification="GOAL_POSITIVE_SOLUTION"), 0,
                             "goal_specific_positive_solution_scope")
            except _PARSE_ERRORS:
                return _note(replace(state, problem_qualification="UNBOUND_PROBLEM"), 0,
                             "unsupported_positive_solution_equation")
        partial = _PARTIAL_DOMAIN.search(question)
        if (partial is not None and re.match(r"\s*given that\b", question, re.I)
                and not any(mark in question[:partial.start()] for mark in ('"', '“', '”', '`'))
                and not re.search(r"\b(?:if|or|unless|whether|not|either)\b", question[:partial.start()], re.I)):
            ref = state.evidence("PROBLEM", "PROBLEM_GIVEN", span, tokenizer,
                                 char_span=(offset + partial.start(), offset + partial.end()))
            state = state.declare(partial["name"], _qualify("real", partial["qualifier"]), ref)
            return _note(replace(state, problem_qualification="PARTIAL_PROBLEM_CONSTRAINTS"), 0,
                         "partial_problem_constraints_require_independent_completion")
        return _note(replace(state, problem_qualification="UNBOUND_PROBLEM"), 0,
                     "no_explicit_problem_domain_declaration")
    declaration_ref = state.evidence("PROBLEM", "PROBLEM_GIVEN", span, tokenizer,
                                     char_span=(offset + declaration.start(), offset + declaration.end()))
    names = _names(declaration)
    if len(set(names)) != len(names):
        return _note(state, 0, "ambiguous_problem_declaration", block=True)
    for name in names:
        state = state.declare(name, _qualify(declaration["kind"], declaration["qualifier"]), declaration_ref)
    after = question[declaration.end():]
    if re.match(r"\s*(?:such that|satisfying|subject to|where)\b", after, re.I):
        condition = _PROBLEM_CONDITION.match(after)
        if condition is None:
            return _note(state, 0, "unsupported_problem_premise", block=True)
        rest = after[condition.end():]
        # A second conjunct can change the admissible set. Do not certify a partial parse.
        if not re.match(r"\s*[.,;]?\s*(?:$|find\b|determine\b|what\b|compute\b|prove\b|show\b)",
                        rest, re.I):
            return _note(state, 0, "incomplete_problem_premises", block=True)
        a = offset + declaration.end() + condition.start()
        b = offset + declaration.end() + condition.end()
        ref = state.evidence("PROBLEM", "PROBLEM_GIVEN", span, tokenizer, char_span=(a, b))
        try:
            state = state.assume(_predicate(_math(condition), parse_expression, state), ref)
        except _PARSE_ERRORS:
            return _note(state, 0, "unsupported_problem_premise", block=True)
    elif not re.match(r"\s*[.,;]?\s*(?:$|find\b|determine\b|what\b|compute\b|prove\b|show\b)", after, re.I):
        return _note(state, 0, "incomplete_problem_premises", block=True)
    return state


def apply_observed_step(state, step, tokenizer, parse_expression):
    """Advance mathematical scope at a fully observed native paragraph boundary."""
    start, end = step["start"], step["end"]
    text = _decode(tokenizer, state._source_tokens("GENERATED", (start, end)))
    if text != step["text"] or end != len(state.generated_ids):
        raise ValueError("Observed scope step is not the exact current token suffix")
    if step["boundary"] != "paragraph":
        return _note(state, step["step"], "no_complete_paragraph_scope_update")
    if not text.endswith("\n\n"):
        raise ValueError("Recorded paragraph lacks its native closing boundary")
    stripped = text.strip()
    if not stripped:
        return state

    def source(role, span=None):
        return state.evidence("GENERATED", role, (start, end), tokenizer, char_span=span)

    # Restating one verified original equation after a bounded restart cue gives
    # a fresh local frame. Earlier speculative bindings remain inaccessible.
    abandoned_branch = any(frame.ambiguity is not None and frame.kind == "ASSUMPTION" for frame in state.frames)
    restart = _RESTART.match(stripped) if abandoned_branch else None
    if restart is not None:
        left = len(text) - len(text.lstrip())
        return replace(state, restart_cue=(step["step"], source("LEXICAL_BOUNDARY",
                                                                (left, left + restart.end()))))
    original = _ORIGINAL_EQUATION.match(text) if abandoned_branch else None
    if original is not None and state.restart_cue is not None:
        cue_step, cue = state.restart_cue
        if 1 <= step["step"] - cue_step <= 4:
            root = state.frames[0]
            base = replace(state, frames=(root,))
            try:
                predicate = _predicate(_math(original), parse_expression, base)
            except _PARSE_ERRORS:
                predicate = None
            if (predicate is not None and predicate["op"] == "eq"
                    and any(a.role == "PROBLEM_GIVEN" and a.scope_id == root.scope_id and a.predicate == predicate
                            for a in state.assumption_history)):
                ref = source("LEXICAL_BOUNDARY", original.span())
                identifier = "s_" + digest((root.scope_id, cue.evidence_id, ref.evidence_id, state.revision))[:32]
                frame = Frame(identifier, root.scope_id, "RESTART", ref, restart_cue=cue)
                return _note(replace(state, frames=(root, frame), restart_cue=None,
                                     revision=state.revision + 1), step["step"], "source_bound_problem_reanchor")

    exit_match = re.fullmatch(r"end (case|assumption)[.]?", stripped, re.I)
    if exit_match:
        kind = exit_match[1].upper()
        if state.frame.kind == kind:
            return state.exit(kind, source("LEXICAL_BOUNDARY"))
        return _note(state, step["step"], "unmatched_scope_exit", block=True)

    case_marker = re.match(r"case\s+([1-9][0-9]?)\s*:", stripped, re.I)
    has_case = bool(re.match(r"(?:case\b|for this case\b)", stripped, re.I))
    has_hypothesis = bool(re.match(r"(?:assume\b|assuming\b|suppose\b|if\b|without loss\b|wlog\b)", stripped, re.I))
    if has_case or has_hypothesis:
        if len(state.frames) >= MAX_DEPTH:
            return _note(state, step["step"], "scope_nesting_limit", block=True)
        kind = "CASE" if has_case else "ASSUMPTION"
        index = int(case_marker[1]) if case_marker else None
        if kind == "CASE" and state.frame.kind == "CASE":
            if index is None or state.frame.case_index is None or index != state.frame.case_index + 1:
                return _note(state, step["step"], "ambiguous_case_sibling", block=True)
            state = state.exit("CASE", source("LEXICAL_BOUNDARY"))
        match = (_CASE if has_case else _GUARD).match(text)
        parsed_guard = match is not None and _GUARD_REMAINDER.match(text[match.end():]) is not None
        state = state.enter(kind, source("LEXICAL_BOUNDARY", match.span() if parsed_guard else None),
                            case_index=index)
        if not parsed_guard:
            return _note(state, step["step"], "unsupported_scope_guard", block=True)
        try:
            role = "CASE_ASSUMPTION" if has_case else "TEMPORARY_ASSUMPTION"
            return state.assume(_predicate(_math(match), parse_expression, state), source(role, match.span()))
        except _PARSE_ERRORS:
            return _note(state, step["step"], "unbound_scope_guard", block=True)

    explicit = _DECLARATION.match(text)
    if explicit and re.fullmatch(r"\s*[.]?\s*", text[explicit.end():]):
        try:
            for name in _names(explicit):
                state = state.declare(name, _qualify(explicit["kind"], explicit["qualifier"]),
                                      source("LOCAL_DEFINITION", explicit.span()))
        except ValueError:
            return _note(state, step["step"], "ambiguous_local_declaration", block=True)
        return state

    definition = _LET.match(text)
    if definition and _LET_REMAINDER.match(text[definition.end():]):
        try:
            predicate = _predicate(_math(definition), parse_expression, state)
            lhs = predicate["lhs"]
            if predicate["op"] != "eq" or type(lhs) is not dict or lhs.get("op") != "var":
                raise ValueError("Explicit definition requires a single bound name")
            name = lhs["name"]
            inputs = _variables(predicate["rhs"])
            dependencies = tuple(state.visible(var) for var in inputs)
            ref = source("LOCAL_DEFINITION", definition.span())
            if name in inputs or any(binding is None or binding.domain is None for binding in dependencies):
                pending = state.declare(name, None, ref)
                return _note(pending, step["step"], "local_definition_has_unbound_input")
            declared = state.declare(name, {"kind": "real"}, ref)
            return declared.assume(predicate, ref)
        except _PARSE_ERRORS:
            return _note(state, step["step"], "unsupported_or_ambiguous_local_definition", block=True)
    return state


def replay_d2_scope(result, question, tokenizer, through_step, parse_expression):
    """Rebuild scope using only the exact native steps through the requested checkpoint."""
    prompt = result["prompt_ids"]
    if digest(prompt) != result["prompt_sha256"]:
        raise ValueError("Original prompt token hash changed")
    state = scope_from_problem(prompt, question, tokenizer, parse_expression)
    generated = result["generated_ids"]
    previous_end = 0
    previous_step = -1
    for step in result["steps"]:
        if step["step"] > through_step:
            break
        start, end = step["start"], step["end"]
        if not previous_end <= start < end <= len(generated) or step["step"] <= previous_step:
            raise ValueError("Nonmonotone recorded scope step")
        state = state.advance_prefix(generated[:end])
        state = apply_observed_step(state, step, tokenizer, parse_expression)
        previous_end = end
        previous_step = step["step"]
        if step["step"] == through_step:
            return state
    raise ValueError("Requested scope step is outside the observed prefix")
