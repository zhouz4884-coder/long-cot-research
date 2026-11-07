"""Parse an exact counterexample assignment and check its bound relation."""
import hashlib
import json

from natural_evidence import check_relation
from restricted_math_checker import LIMITS, VARIABLE


MAX_PROPOSAL_CHARACTERS = 4096


class RejectedProposal(ValueError):
    pass


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RejectedProposal("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise RejectedProposal("nonfinite_json_number")


def _bounded_integer(value):
    return type(value) is int and abs(value).bit_length() <= LIMITS["input_integer_bits"]


def _exact_value(value):
    if _bounded_integer(value):
        return True
    if type(value) is not dict or set(value) != {"op", "num", "den"} or value["op"] != "rat":
        return False
    return _bounded_integer(value["num"]) and _bounded_integer(value["den"]) and value["den"] != 0


def parse_counterexample(text, variables):
    """Accept one whole JSON assignment with exact complete variable coverage."""
    text_hash = None

    def unresolved(reason):
        return {"status": "UNKNOWN", "reason": reason, "assignment": None, "proposal_sha256": text_hash}

    if type(variables) not in (list, tuple) or not variables:
        return unresolved("no_applicable_counterexample_variables")
    if (len(variables) > LIMITS["variables"] or any(type(name) is not str or not VARIABLE.fullmatch(name) for name in variables)
            or len(set(variables)) != len(variables)):
        return unresolved("invalid_counterexample_variables")
    if type(text) is not str or not 0 < len(text) <= MAX_PROPOSAL_CHARACTERS:
        return unresolved("counterexample_text_bound")
    try:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return unresolved("invalid_unicode_text")
    try:
        proposal = json.loads(text.strip(), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_json_constant)
    except RejectedProposal as error:
        return unresolved(str(error))
    except (ValueError, RecursionError):
        return unresolved("one_complete_json_object_required")
    if type(proposal) is not dict or set(proposal) != {"assignment"}:
        return unresolved("assignment_object_required")
    assignment = proposal["assignment"]
    if type(assignment) is not dict or set(assignment) != set(variables):
        return unresolved("exact_variable_coverage_required")
    if any(not _exact_value(value) for value in assignment.values()):
        return unresolved("bounded_exact_rational_required")
    return {"status": "parsed", "reason": None, "assignment": assignment, "proposal_sha256": text_hash}


def check_proposal(relation, text, *, unscoped=False):
    """Keep parse coverage and mathematical result available as separate fields."""
    variables = relation.get("variables", []) if type(relation) is dict else []
    parser = parse_counterexample(text, variables)
    if type(unscoped) is not bool:
        checker = {"status": "UNKNOWN", "reason": "explicit_scope_mode_required"}
    elif type(relation) is not dict or relation.get("status") != "parsed":
        checker = {"status": "UNKNOWN", "reason": "relation_scope_unresolved"}
    elif parser["status"] != "parsed":
        checker = {"status": "UNKNOWN", "reason": parser["reason"]}
    else:
        try:
            checker = check_relation(relation, assignment=parser["assignment"], unscoped=unscoped)
        except (ValueError, KeyError, TypeError, RecursionError):
            checker = {"status": "UNKNOWN", "reason": "relation_not_checkable"}
    return {"status": checker["status"], "parser": parser, "checker_result": checker,
            "unscoped": unscoped if type(unscoped) is bool else None}
