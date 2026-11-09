"""Dispatch typed, source-bound mathematical checks and witness proposals."""

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from typed_math_events import MathEvent, canonical_json, digest
from symbol_scope import ScopeState
import restricted_math_checker as exact


CHECKER_ID = "d25-typed-math-v1"
FROZEN_CHECKER_SHA256 = "2a3147db9d621ca77c911574149b6343ef49c1be7be55757d5fa1ca1ed91f38a"
if sha256(Path(exact.__file__).read_bytes()).hexdigest() != FROZEN_CHECKER_SHA256:
    raise RuntimeError("D2 exact checker bytes differ from the frozen dependency")
CHECKER_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
MAX_PROPOSAL_CHARACTERS = 4096


@dataclass(frozen=True)
class RoleAuthority:
    """The trusted caller supplies reviewed role evidence, outside model text."""

    event_id: str
    observed_prefix_sha256: str
    role: str
    authority_id: str
    scope_id: str | None = None
    scope_version: int | None = None


@dataclass(frozen=True)
class ConstraintSet:
    """A caller-owned complete conjunction, with independent source provenance."""

    variables: tuple[str, ...]
    scope_id: str
    scope_version: int
    observed_prefix_sha256: str
    evidence_id: str
    predicates_json: str
    complete: bool

    @classmethod
    def create(cls, *, variables, scope_id, scope_version, observed_prefix_sha256,
               evidence_id, predicates, complete):
        return cls(tuple(sorted(variables)), scope_id, scope_version, observed_prefix_sha256,
                   evidence_id, canonical_json(list(predicates)), complete)

    @property
    def predicates(self):
        return json.loads(self.predicates_json)


class _InvalidAssignment(ValueError):
    pass


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise _InvalidAssignment("duplicate_json_key")
        obj[key] = value
    return obj


def _reject_nonfinite(_value):
    raise _InvalidAssignment("nonfinite_json_number")


def _bounded_integer(value):
    return type(value) is int and abs(value).bit_length() <= exact.LIMITS["input_integer_bits"]


def _exact_value(value):
    if _bounded_integer(value):
        return True
    return (type(value) is dict and set(value) == {"op", "num", "den"} and value["op"] == "rat"
            and _bounded_integer(value["num"]) and _bounded_integer(value["den"]) and value["den"] != 0)


def parse_counterexample(text, variables):
    """Parse one whole JSON object with exactly the bound scope variables."""
    if not variables or len(variables) > exact.LIMITS["variables"] or len(set(variables)) != len(variables):
        return {"status": "UNKNOWN", "reason": "no_applicable_counterexample_variables"}
    if type(text) is not str or not 0 < len(text) <= MAX_PROPOSAL_CHARACTERS:
        return {"status": "UNKNOWN", "reason": "counterexample_text_bound"}
    try:
        value = json.loads(text.strip(), object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)
    except _InvalidAssignment as error:
        return {"status": "UNKNOWN", "reason": str(error)}
    except (ValueError, RecursionError):
        return {"status": "UNKNOWN", "reason": "one_complete_json_object_required"}
    if type(value) is not dict or set(value) != {"assignment"}:
        return {"status": "UNKNOWN", "reason": "assignment_object_required"}
    assignment = value["assignment"]
    if type(assignment) is not dict or set(assignment) != set(variables):
        return {"status": "UNKNOWN", "reason": "exact_variable_coverage_required"}
    if not all(_exact_value(entry) for entry in assignment.values()):
        return {"status": "UNKNOWN", "reason": "bounded_exact_rational_required"}
    return {"status": "PARSED", "reason": None, "assignment": assignment}


def _assert_scope_source(event, scope):
    prefix = event.source.observed_prefix_sha256
    if scope is not None and (not isinstance(scope, ScopeState) or scope.observed_prefix_sha256 != prefix
                              or event.source.token_span[1] > len(scope.generated_ids)):
        raise exact.Unresolved("scope_source_prefix_mismatch")


def resolve_event_scope(event, scope):
    """Resolve sources preceding the exact event span, including within a paragraph."""
    _assert_scope_source(event, scope)
    if scope is None:
        raise exact.Unresolved("scope_required")
    return scope.resolve_expression(event.variables, target_token_span=event.source.token_span,
                                    target_char_span=event.source.char_span)


def _predecessor_binding(event, scope, predecessor_scope, resolved):
    if len(event.dependencies) != 1:
        raise exact.Unresolved("transition_requires_one_predecessor")
    source, = event.dependencies
    if (not isinstance(predecessor_scope, ScopeState) or source.step + 1 != event.source.step
            or source.token_span[1] != event.source.token_span[0]
            or len(predecessor_scope.generated_ids) != source.token_span[1]
            or predecessor_scope.prompt_ids != scope.prompt_ids
            or scope.generated_ids[:source.token_span[1]] != predecessor_scope.generated_ids):
        raise exact.Unresolved("transition_predecessor_scope_snapshot_required")
    if (predecessor_scope.revision != scope.revision or predecessor_scope.frames != scope.frames
            or predecessor_scope.binding_history != scope.binding_history
            or predecessor_scope.assumption_history != scope.assumption_history
            or predecessor_scope.problem_qualification != scope.problem_qualification):
        raise exact.Unresolved("transition_scope_changed_between_paragraphs")
    prior = predecessor_scope.resolve_expression(event.variables, target_token_span=source.token_span,
                                                 target_char_span=source.char_span)
    if prior.status != "BOUND" or prior.bindings != resolved.bindings or prior.assumptions != resolved.assumptions:
        raise exact.Unresolved("transition_predecessor_evidence_differs")
    packet, premises, _ = prior.checker_inputs()
    return {"source": source.as_dict(), "scope": packet, "premises": premises,
            "prefix_sha256": predecessor_scope.observed_prefix_sha256}


def _scope_inputs(event, scope, unscoped, predecessor_scope):
    prefix = event.source.observed_prefix_sha256
    cross_paragraph = event.kind == "EQUATION_TRANSITION" and bool(event.dependencies)
    if not event.variables and not cross_paragraph:
        literal = {"id": "s_literal_" + prefix[:32], "version": 0, "coefficient_domain": "Q", "domains": {}}
        return literal, [], [], {"authority": "LITERAL", "bindings": [], "observed_prefix_sha256": prefix}
    resolved = resolve_event_scope(event, scope)
    if resolved.status != "BOUND":
        raise exact.Unresolved(resolved.reason or "scope_unbound")
    packet, premises, required = resolved.checker_inputs()
    authority = resolved.authority
    if unscoped:
        packet = {**packet, "id": packet["id"] + "_unscoped",
                  "domains": {name: {"kind": "real"} for name in packet["domains"]}}
        premises, required, authority = [], [], "UNSCOPED_CONTROL"
    provenance = {"authority": authority, "observed_prefix_sha256": prefix,
                  "bindings": [binding.as_dict() for binding in resolved.bindings],
                  "assumptions": [assumption.as_dict() for assumption in resolved.assumptions],
                  "branch_scopes": list(resolved.branch_scopes),
                  "problem_qualification": getattr(resolved, "problem_qualification", None)}
    if cross_paragraph:
        provenance["transition_predecessor"] = _predecessor_binding(event, scope, predecessor_scope, resolved)
    return packet, premises, required, provenance


def _polynomial(node):
    if type(node) is int:
        return True
    if type(node) is not dict:
        return False
    op = node.get("op")
    if op in ("rat", "var"):
        return True
    if op == "neg":
        return _polynomial(node["arg"])
    if op in ("add", "mul"):
        return all(_polynomial(arg) for arg in node["args"])
    if op == "sub":
        return _polynomial(node["lhs"]) and _polynomial(node["rhs"])
    return op == "pow" and type(node["exp"]) is int and node["exp"] >= 0 and _polynomial(node["base"])


def _formal_statement(event):
    if event.kind == "EQUATION_TRANSITION" and event.dependencies:
        return None
    source = event.statement
    if event.kind == "EQUATION_TRANSITION" and source:
        source = {"lhs": {"op": "sub", **source["antecedent"]}, "rhs": {"op": "sub", **source["consequent"]}}
    if (event.kind in ("EQUATION", "SYMBOLIC_IDENTITY", "EQUATION_TRANSITION") and source
            and all(_polynomial(source.get(side)) for side in ("lhs", "rhs"))):
        return {**source, "semantics": "formal"}
    return None


def _formal_scope(event, reason):
    prefix = event.source.observed_prefix_sha256
    # These slots name indeterminates for the existing coefficient engine.
    # They make no assertion about the problem's domain.
    packet = {"id": "s_formal_" + event.event_id[2:], "version": 0, "coefficient_domain": "Q",
              "domains": {name: {"kind": "rational"} for name in event.variables}}
    return packet, [], [], {"authority": "FORMAL_POLYNOMIAL_ONLY", "observed_prefix_sha256": prefix,
                            "scope_abstention_reason": reason, "bindings": []}


def _role(event, authority, packet, provenance, unscoped):
    if (not isinstance(authority, RoleAuthority) or unscoped or not authority.authority_id
            or authority.event_id != event.event_id or authority.observed_prefix_sha256 != event.source.observed_prefix_sha256
            or authority.role not in ("ASSERTED_JUSTIFICATION", "ASSERTED_CLAIM")):
        return None
    if event.variables and (provenance["authority"] != "PROBLEM" or
                            (authority.scope_id, authority.scope_version) != (packet["id"], packet["version"])):
        return None
    return authority


class _ExactChecks:
    def __init__(self, event, packet, premises, required):
        self.event = event
        self.scope = packet
        self.premises = premises
        self.required = required
        self.calls = []

    def run(self, certificate_type, statement, *, mode="verify", assignment=None, assumed_equation=None):
        premises, required = self.premises, self.required
        if assumed_equation is not None:
            ref = {"id": "assume_" + digest(assumed_equation)[:28], "version": 0,
                   "scope_id": self.scope["id"], "scope_version": self.scope["version"]}
            premises = [*premises, {**ref, "predicate": {"op": "eq", **assumed_equation}}]
            required = [*required, ref]
        target = {"id": self.event.event_id + "_" + str(len(self.calls)), "version": 0, "kind": "claim",
                  "scope": self.scope, "certificate_type": certificate_type, "statement": statement,
                  "required_premises": required, "source_span": list(self.event.source.token_span),
                  "observed_prefix_sha256": self.event.source.observed_prefix_sha256}
        try:
            request = exact.make_request(target, premises, mode=mode, assignment=assignment)
            result = exact.verify(request, target=target, premises=premises)
        except exact.Unresolved as error:
            request = {"mode": mode, "assignment": assignment}
            result = {"status": "UNKNOWN", "truth": None, "reason": error.reason, "certificate": None, "work_units": 0}
        self.calls.append({"target": target, "premises": premises, "request": request, "result": result})
        return result


def _approximation(checks, statement):
    relation = {name: statement[name] for name in ("lhs", "rhs")}
    outcome = checks.run("ARITHMETIC_EQ", relation)
    if outcome["truth"] is None:
        return None, outcome["reason"], None
    actual = Fraction(outcome["witness"]["lhs"])
    printed = Fraction(outcome["witness"]["rhs"])
    scale = statement["decimal_places"]
    unit = Fraction(1, 10**scale)
    if (printed / unit).denominator != 1:
        return False, "printed_value_off_declared_precision_grid", {"exact": str(actual), "printed": str(printed)}
    difference = abs(actual - printed)
    return difference <= unit / 2, "display_rounding_tolerance", {
        "exact": str(actual), "printed": str(printed), "absolute_difference": str(difference),
        "tolerance": str(unit / 2), "decimal_places": scale,
    }


def _running_sum(checks, statement):
    approximate_chain = statement["approximate"] or any(row["approximate"] for row in statement["prior_chain"])
    chain = [*statement["prior_chain"], statement]
    for i, link in enumerate(chain):
        if link["approximate"]:
            truth, reason, witness = _approximation(checks, link)
        else:
            result = checks.run("ARITHMETIC_EQ", {key: link[key] for key in ("lhs", "rhs")})
            truth, reason, witness = result["truth"], result["reason"], result.get("witness")
        if truth is not True and i < len(chain) - 1:
            return "UNKNOWN", None, "prior_subtotal_not_verified", {"failed_link": i, "reason": reason}
    details = {"approximate_chain": approximate_chain, "subtotal_check": witness}
    status = "UNKNOWN" if truth is None else "VERIFIED_RUNNING_SUM" if truth else "INVALID_RUNNING_SUM"
    return status, truth, reason, details


def _predicate_at(checks, equation, assignment):
    result = checks.run("DOMAIN_PREDICATE", {"predicate": {"op": "eq", **equation}, "assignment": assignment})
    if result["reason"] == "frozen_candidate_violates_scope":
        return None, "out_of_scope"
    return result["truth"], result["reason"]


def _transition_at(checks, statement, assignment):
    first, reason = _predicate_at(checks, statement["antecedent"], assignment)
    if first is None:
        return None, reason, None
    second, reason = _predicate_at(checks, statement["consequent"], assignment)
    if second is None:
        return None, reason, None
    valid = first == second if statement["direction"] == "IFF" else not first or second
    return valid, "checked_transition_point", {"assignment": assignment, "antecedent": first, "consequent": second}


def _rational_json(number):
    if number.denominator == 1:
        return number.numerator
    return {"op": "rat", "num": number.numerator, "den": number.denominator}


def _transition(checks, statement, assignment=None):
    if assignment is not None:
        truth, reason, witness = _transition_at(checks, statement, assignment)
        if reason == "out_of_scope" or truth is True:
            return "INVALID_COUNTEREXAMPLE", None, reason if truth is None else "point_satisfies_transition", witness
        status = "CHECKED_COUNTEREXAMPLE" if truth is False else "UNKNOWN"
        return status, truth, reason, witness

    first, second = statement["antecedent"], statement["consequent"]
    first_residual, second_residual = {"op": "sub", **first}, {"op": "sub", **second}
    equal_residuals = checks.run("POLYNOMIAL_IDENTITY", {"lhs": first_residual, "rhs": second_residual})
    if equal_residuals["truth"] is True:
        return "VERIFIED_TRANSITION", True, "equal_defined_residuals", equal_residuals.get("witness")

    # A conditional identity can establish a direction when the registered
    # antecedent supplies usable exact grounding to the frozen checker.
    defined = equal_residuals["truth"] is False or all(
        checks.run("POLYNOMIAL_IDENTITY", {"lhs": residual, "rhs": residual})["truth"] is True
        for residual in (first_residual, second_residual)
    )
    if defined:
        forward = checks.run("POLYNOMIAL_IDENTITY", second, assumed_equation=first)
        reverse = checks.run("POLYNOMIAL_IDENTITY", first, assumed_equation=second) if statement["direction"] == "IFF" else None
        if forward["truth"] is True and (reverse is None or reverse["truth"] is True):
            return "VERIFIED_TRANSITION", True, "certified_directional_implications", None

    domains = {name: exact._domain(domain) for name, domain in sorted(checks.scope["domains"].items())}
    points, exhaustive = exact._ordered_points(domains, {})
    admissible, unresolved = 0, False
    for values in points:
        point = {name: _rational_json(value) for name, value in values.items()}
        truth, reason, witness = _transition_at(checks, statement, point)
        if reason == "out_of_scope":
            continue
        admissible += 1
        if truth is False:
            return "FALSE_TRANSITION", False, "checked_transition_counterexample", witness
        unresolved |= truth is None
    if exhaustive and admissible and not unresolved:
        return "VERIFIED_TRANSITION", True, "exhaustive_admissible_scope", {"admissible_points": admissible}
    return "UNKNOWN", None, "transition_not_certified_within_bound", {"admissible_points": admissible}


def _candidate(checks, event, constraints, provenance):
    prefix = event.source.observed_prefix_sha256
    packet = checks.scope
    if (not isinstance(constraints, ConstraintSet) or constraints.complete is not True or not constraints.evidence_id
            or constraints.observed_prefix_sha256 != prefix or provenance["authority"] != "PROBLEM"
            or (constraints.scope_id, constraints.scope_version) != (packet["id"], packet["version"])):
        return "UNKNOWN", None, "complete_owned_constraint_set_required", None
    assignment = event.statement.get("assignment", {})
    if set(constraints.variables) != set(assignment) or set(assignment) != set(packet["domains"]):
        return "UNKNOWN", None, "complete_constraint_assignment_required", None
    result = checks.run("SUBSTITUTION", {"assignment": assignment, "constraints": constraints.predicates})
    truth = result["truth"]
    return ("UNKNOWN" if truth is None else "VERIFIED_CANDIDATE" if truth else "INVALID_CANDIDATE",
            truth, result["reason"], result.get("witness"))


def _dispatch(checks, event, mode, assignment, constraints, provenance):
    statement, kind = event.statement, event.kind
    if not statement or event.eligibility in ("UNSUPPORTED_PRECISION", "UNRESOLVED_EQUATION_ROLE"):
        return "UNKNOWN", None, event.eligibility.lower(), None
    if kind == "CLOSED_ARITHMETIC":
        result = checks.run("ARITHMETIC_EQ", statement)
    elif kind == "APPROX_ARITHMETIC":
        truth, reason, witness = _approximation(checks, statement)
        status = "UNKNOWN" if truth is None else "ROUNDING_COMPATIBLE" if truth else "ROUNDING_INCOMPATIBLE"
        return status, truth, reason, witness
    elif kind == "RUNNING_SUM_CONTINUATION":
        return _running_sum(checks, statement)
    elif kind == "SYMBOLIC_IDENTITY":
        result = checks.run("POLYNOMIAL_IDENTITY", statement, mode=mode, assignment=assignment)
    elif kind == "EQUATION_TRANSITION":
        return _transition(checks, statement, assignment)
    elif kind == "CANDIDATE_SOLUTION":
        return _candidate(checks, event, constraints, provenance)
    else:
        return "UNKNOWN", None, "unsupported_event_type", None
    if result["truth"] is False:
        status = "CHECKED_COUNTEREXAMPLE" if mode == "counterexample" else (
            "FALSE_LITERAL" if kind == "CLOSED_ARITHMETIC" else "FALSE_SCOPED_IDENTITY"
        )
    else:
        status = result["status"]
    return status, result["truth"], result["reason"], result.get("witness")


def _unknown(event, reason, *, parser=None):
    return {"event_id": event.event_id, "kind": event.kind, "status": "UNKNOWN", "math_status": "UNKNOWN",
            "truth": None, "action": "NONE", "reason": reason, "witness": None, "parser": parser,
            "binding": None, "certificate": None, "exact_checks": [], "work_units": 0}


def check_proposal(event, text=None, *, mode="verify", scope=None, predecessor_scope=None, role_authority=None,
                   constraints=None, unscoped=False, _proposal_source=None):
    """Use deterministic checks by default and JSON only for a witness request."""
    if not isinstance(event, MathEvent):
        raise TypeError("Expected a typed MathEvent")
    if mode not in ("verify", "counterexample") or type(unscoped) is not bool:
        return _unknown(event, "unsupported_verification_mode")
    if mode == "counterexample" and event.kind not in ("SYMBOLIC_IDENTITY", "EQUATION_TRANSITION"):
        return _unknown(event, "witness_mode_not_applicable_to_event")
    formal = None
    try:
        _assert_scope_source(event, scope)
    except exact.Unresolved as error:
        return _unknown(event, error.reason)
    try:
        if event.kind == "EQUATION":
            raise exact.Unresolved("unresolved_equation_role")
        packet, premises, required, provenance = _scope_inputs(event, scope, unscoped, predecessor_scope)
    except exact.Unresolved as error:
        if mode == "verify" and not unscoped:
            formal = _formal_statement(event)
        if formal is None:
            return _unknown(event, error.reason)
        packet, premises, required, provenance = _formal_scope(event, error.reason)
    role = _role(event, role_authority, packet, provenance, unscoped) if formal is None else None
    parser = parse_counterexample(text, tuple(packet["domains"])) if mode == "counterexample" else None
    if parser is not None and parser["status"] != "PARSED":
        return _unknown(event, parser["reason"], parser=parser)
    checks = _ExactChecks(event, packet, premises, required)
    try:
        if formal is None:
            status, truth, reason, witness = _dispatch(checks, event, mode, parser.get("assignment") if parser else None,
                                                       constraints, provenance)
        else:
            formal_check = checks.run("POLYNOMIAL_IDENTITY", formal)
            if formal_check["truth"] is True:
                status, truth, reason, witness = "FORMAL_IDENTITY_VERIFIED", True, "equal_polynomial_coefficients", formal_check["witness"]
            else:
                status, truth, reason, witness = "UNKNOWN", None, "natural_semantics_unbound_after_formal_check", None
    except (exact.Unresolved, TypeError, KeyError, ValueError, ZeroDivisionError, RecursionError) as error:
        status, truth, reason, witness = "UNKNOWN", None, getattr(error, "reason", "unsupported_typed_input"), None
    math_status = status
    action = "NONE"
    if status == "INVALID_COUNTEREXAMPLE":
        action = "REJECT_COUNTEREXAMPLE"
    elif truth is False and role and status in ("FALSE_LITERAL", "FALSE_SCOPED_IDENTITY", "FALSE_TRANSITION", "CHECKED_COUNTEREXAMPLE"):
        status = "INVALID_JUSTIFICATION" if role.role == "ASSERTED_JUSTIFICATION" else "REFUTED_CLAIM"
        action = "INVALIDATE_JUSTIFICATION" if status == "INVALID_JUSTIFICATION" else "REFUTE_CLAIM"
    constraint_binding = vars(constraints) if isinstance(constraints, ConstraintSet) else None
    binding = {"event_id": event.event_id, "event_version": 0, "event_sha256": digest(event.as_dict()),
               "observed_prefix_sha256": event.source.observed_prefix_sha256, "scope": packet,
               "scope_provenance": provenance, "premises": premises, "role_authority": vars(role) if role else None,
               "constraint_set": constraint_binding, "mode": mode, "unscoped": unscoped,
               "proposal_text_sha256": sha256(text.encode("utf-8")).hexdigest() if type(text) is str else None,
               "proposal_source": _proposal_source.as_dict() if _proposal_source is not None else None}
    certificate = None
    if status != "UNKNOWN":
        receipt = {"checker_id": CHECKER_ID, "checker_sha256": CHECKER_SHA256, "exact_checker_sha256": FROZEN_CHECKER_SHA256,
                   "binding_sha256": digest(binding), "exact_checks_sha256": digest(checks.calls),
                   "status": status, "action": action, "truth": truth, "witness_sha256": digest(witness)}
        certificate = {**receipt, "sha256": digest(receipt)}
    return {"event_id": event.event_id, "kind": event.kind, "status": status, "math_status": math_status,
            "truth": truth, "action": action, "reason": reason, "witness": witness, "parser": parser,
            "binding": binding, "certificate": certificate, "exact_checks": checks.calls,
            "work_units": sum(call["result"].get("work_units", 0) for call in checks.calls)}


def check_event(event, *, scope=None, predecessor_scope=None, role_authority=None, constraints=None, unscoped=False,
                target_event=None, target_scope=None):
    """Check one observed relation, or a witness addressed to an owned target."""
    if not isinstance(event, MathEvent):
        raise TypeError("Expected a typed MathEvent")
    if event.kind != "COUNTEREXAMPLE":
        return check_proposal(event, scope=scope, predecessor_scope=predecessor_scope, role_authority=role_authority,
                              constraints=constraints, unscoped=unscoped)
    if (not isinstance(target_event, MathEvent) or event.statement.get("target_id") != target_event.event_id
            or not isinstance(scope, ScopeState) or not isinstance(target_scope, ScopeState)
            or scope.observed_prefix_sha256 != event.source.observed_prefix_sha256
            or scope.prompt_ids != target_scope.prompt_ids
            or scope.generated_ids[:len(target_scope.generated_ids)] != target_scope.generated_ids
            or target_event.source.token_span[1] > event.source.token_span[0]):
        return _unknown(event, "counterexample_target_not_bound_to_prior_observation")
    result = check_proposal(target_event, event.statement["proposal_text"], mode="counterexample", scope=target_scope,
                            predecessor_scope=predecessor_scope,
                            role_authority=role_authority, unscoped=unscoped, _proposal_source=event)
    return {**result, "target_event_id": target_event.event_id, "event_id": event.event_id, "kind": event.kind}


def replay_certificate(certificate, event, text=None, **verification):
    """Recompute the complete typed decision from its caller-owned inputs."""
    if not isinstance(certificate, dict):
        return False
    if event.kind == "COUNTEREXAMPLE":
        result = check_event(event, **verification)
    else:
        result = check_proposal(event, text, **verification)
    return result["certificate"] == certificate
