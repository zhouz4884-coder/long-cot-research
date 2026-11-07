"""Closed arithmetic evaluation facts with separately reviewed proof roles.

The adapter gives a synthetic subject to an observed arithmetic expression.
The caller supplies full observed token provenance and pre-Gold role reviews.
Named mathematical variables and question modelling remain outside this scope.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys

try:
    import scope_rebase_hardened as support
except ModuleNotFoundError:
    _SUPPORT_PATH = Path(__file__).resolve().parents[1] / "phase5d_scope_rebase_20261106" / "support_engine"
    sys.path.insert(0, str(_SUPPORT_PATH))
    import scope_rebase_hardened as support

from natural_evidence import parse_expression
from restricted_math_checker import make_request, verify


_SUPPORT_SHA = "9b1847f7d8d031cc7a786e82ed9da4eba44e262bcad4f5a3f0b90b9dc5ed946d"
if hashlib.sha256(Path(support.__file__).read_bytes()).hexdigest() != _SUPPORT_SHA:
    raise ValueError("Frozen evidence kernel source differs")

ROLE_SCHEMA = "D2_ASSERTED_ARITHMETIC_PROOF_V1"
ROLE_VERDICT = "ASSERTED_ARITHMETIC_PROOF"
ROLE_PHASE = "PRE_GOLD_FULL_OBSERVED_PREFIX"
_SOURCE_FIELDS = ("surface", "token_span", "char_span_in_step", "step", "equation_index",
                  "statement", "normalized", "variables", "certificate_type", "observed_prefix_sha256")


def relation_sha256(relation):
    """Hash mathematical text, source position, and the structured extraction."""
    if not isinstance(relation, dict):
        raise TypeError("Expected an observed relation dictionary")
    return support.digest({key: relation.get(key) for key in _SOURCE_FIELDS})


def _ids(value):
    ids = tuple(value)
    if any(type(token) is not int or token < 0 for token in ids):
        raise ValueError("Observed source needs integer token IDs")
    return ids


def make_observed_relations(prompt_ids, generated_ids, boundary_offsets, relations):
    prompt, generated = _ids(prompt_ids), _ids(generated_ids)
    if not prompt:
        raise ValueError("Observed source prompt is empty")
    bounds = tuple(sorted(set(boundary_offsets)))
    if any(type(offset) is not int or not 0 <= offset <= len(generated) for offset in bounds):
        raise ValueError("Source boundary is unobserved")
    return {"prompt_ids": list(prompt), "generated_ids": list(generated), "boundary_offsets": list(bounds),
            "source_prefix_sha256": support.digest(prompt + generated), "relations": list(relations)}


def make_role_certificate(relation, source_prefix_sha256, reviewers):
    receipt = {"schema": ROLE_SCHEMA, "relation_sha256": relation_sha256(relation),
               "source_prefix_sha256": source_prefix_sha256, "reviewers": list(reviewers),
               "verdict": ROLE_VERDICT, "review_phase": ROLE_PHASE}
    receipt["receipt_sha256"] = support.digest(receipt)
    return receipt


def _role_status(receipt, relation, prefix_sha):
    if not isinstance(receipt, dict):
        return "MISSING"
    if not prefix_sha:
        return "SOURCE_IDS_MISSING"
    if (receipt.get("schema") != ROLE_SCHEMA or receipt.get("verdict") != ROLE_VERDICT
            or receipt.get("review_phase") != ROLE_PHASE):
        return "ROLE_OR_REVIEW_PHASE_MISMATCH"
    if receipt.get("relation_sha256") != relation_sha256(relation) or receipt.get("source_prefix_sha256") != prefix_sha:
        return "RELATION_OR_SOURCE_MISMATCH"
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != support.digest(unsigned):
        return "RECEIPT_DIGEST_MISMATCH"
    reviewers = receipt.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) < 2:
        return "INSUFFICIENT_REVIEWERS"
    identities = []
    for review in reviewers:
        if (not isinstance(review, dict) or set(review) != {"id", "verdict"}
                or not isinstance(review["id"], str) or review["verdict"] != ROLE_VERDICT):
            return "REVIEWER_DISAGREEMENT_OR_SCHEMA"
        identities.append(review["id"])
    if (len(identities) != len(set(identities)) or "/root" not in identities
            or not any(name.startswith("/root/") and len(name) > len("/root/") for name in identities)):
        return "REVIEWER_IDENTITIES_NOT_INDEPENDENT"
    return "UNANIMOUS_PRE_GOLD_REVIEW"


def _closed_relation(relation, observed_length, prefix_sha):
    if relation.get("certificate_type") != "ARITHMETIC_EQ" or relation.get("variables") != []:
        raise ValueError("Only closed literal arithmetic is supported")
    surface = relation.get("surface")
    if not isinstance(surface, str) or surface.count("=") != 1:
        raise ValueError("Expected one observed equality")
    span = relation.get("token_span")
    if (not isinstance(span, (list, tuple)) or len(span) != 2
            or any(type(offset) is not int for offset in span) or not 0 <= span[0] < span[1] <= observed_length):
        raise ValueError("Relation token span lies outside observed generation")
    for field in ("source_prefix_sha256", "observed_prefix_sha256"):
        if relation.get(field, prefix_sha) != prefix_sha:
            raise ValueError("Relation source prefix differs")
    left, right = surface.split("=")
    lhs_ast, lhs_variables, lhs_expression = parse_expression(left)
    rhs_ast, rhs_variables, rhs_expression = parse_expression(right)
    if lhs_variables or rhs_variables:
        raise ValueError("Arithmetic contains named variables")
    statement = {"lhs": lhs_ast, "rhs": rhs_ast}
    if relation.get("statement") != statement or relation.get("normalized") != [lhs_expression, rhs_expression]:
        raise ValueError("Surface/AST/normalized expression binding differs")
    lhs_value = support.exact(lhs_expression)
    rhs_value = support.exact(rhs_expression)
    identifier = "literal_" + relation_sha256(relation)[:24]
    target = {"id": identifier, "version": 0, "kind": "justification",
              "scope": {"id": "closed_rational_eval", "version": 0, "coefficient_domain": "Q", "domains": {}},
              "certificate_type": "ARITHMETIC_EQ", "statement": statement, "required_premises": []}
    request = make_request(target, (), mode="verify")
    checked = verify(request, target=target, premises=())
    if checked["status"] not in ("VERIFIED", "INVALID_JUSTIFICATION") or checked["truth"] != (lhs_value == rhs_value):
        raise ValueError("Independent literal check is undecided or disagrees")
    expression_key = ast.dump(ast.parse(lhs_expression, mode="eval"), include_attributes=False)
    return {"span": tuple(span), "lhs_expression": lhs_expression, "rhs_value": rhs_value,
            "subject": "expr_" + support.digest(expression_key)[:24], "checked": checked,
            "relation_sha256": relation_sha256(relation)}


@dataclass(frozen=True)
class NaturalLedgerResult:
    status: str
    ledger: object = field(repr=False)
    challenge: object = field(repr=False)
    metadata: dict


def build_natural_ledger(relations_from_observed_prefix, observed_length, candidate_relation, role_certificate):
    """Build expression facts, with an actionable challenge only after role review.

    The envelope from make_observed_relations supplies actual prefix IDs.
    A plain relation list remains usable for non-actionable arithmetic metadata.
    """
    if type(observed_length) is not int or observed_length < 0:
        raise ValueError("Observed length must be a nonnegative integer")
    if isinstance(relations_from_observed_prefix, dict):
        envelope = relations_from_observed_prefix
        prompt, generated = _ids(envelope["prompt_ids"]), _ids(envelope["generated_ids"])
        if not prompt or len(generated) != observed_length:
            raise ValueError("Observed prefix length differs")
        prefix_sha = support.digest(prompt + generated)
        if envelope.get("source_prefix_sha256") != prefix_sha:
            raise ValueError("Observed prefix SHA differs")
        bounds = tuple(sorted(set(envelope["boundary_offsets"])))
        if any(type(offset) is not int or not 0 <= offset <= observed_length for offset in bounds):
            raise ValueError("Observed boundary lies outside generation")
        relations = list(envelope["relations"])
    else:
        relations = list(relations_from_observed_prefix)
        prefix_sha = None
        bounds = (0,)
    ledger = support.EvidenceLedger(
        [support.Scope("literal_eval", "rational", ("Each expr_HASH subject denotes only the exact rational evaluation of its registered LHS expression.",))],
        legal_token_boundaries=tuple(sorted({0, *bounds})), observed_token_length=observed_length,
    )
    candidate_sha = relation_sha256(candidate_relation) if isinstance(candidate_relation, dict) else None
    processed, skipped, claims, rules, seen = [], [], {}, {}, set()
    candidate_proof = None
    candidate_checked = None
    for relation in relations:
        try:
            relation_hash = relation_sha256(relation)
            if relation_hash in seen:
                raise ValueError("Duplicate observed relation identity")
            seen.add(relation_hash)
            literal = _closed_relation(relation, observed_length, prefix_sha)
        except (ValueError, TypeError, KeyError, SyntaxError, ZeroDivisionError, RecursionError) as error:
            skipped.append({"relation_sha256": relation_sha256(relation) if isinstance(relation, dict) else None,
                            "reason": str(error), "status": "UNKNOWN"})
            continue
        key = (literal["subject"], literal["rhs_value"])
        if key not in claims:
            claim_id = "claim_" + support.digest((literal["subject"], str(literal["rhs_value"])))[:24]
            ledger.add_claim(support.Claim(claim_id, literal["subject"], literal["rhs_value"], "literal_eval", 0, *literal["span"]))
            claims[key] = claim_id
        claim_id = claims[key]
        proof_id = "proof_" + relation_hash[:24]
        correct = literal["checked"]["status"] == "VERIFIED"
        rule_id = None
        if correct:
            if literal["subject"] not in rules:
                rule_id = "definition_" + literal["subject"]
                ledger.trust_constraint(rule_id, "literal_eval", literal["subject"], literal["lhs_expression"])
                rules[literal["subject"]] = rule_id
            rule_id = rules[literal["subject"]]
        outcome = ledger.prove_arithmetic(proof_id, claim_id, literal["lhs_expression"], (), constraint_id=rule_id,
                                           token_start=literal["span"][0], token_end=literal["span"][1])
        if correct and outcome.verdict != "PASS":
            raise ValueError("A verified expression failed its registered exact evaluation definition")
        record = {"relation_sha256": relation_hash, "claim_id": claim_id, "proof_id": proof_id,
                  "expression_subject": literal["subject"], "literal_result": literal["checked"],
                  "ledger_verdict": outcome.verdict, "source_token_span": list(literal["span"])}
        processed.append(record)
        if relation_hash == candidate_sha:
            candidate_proof, candidate_checked = proof_id, literal["checked"]
    role_status = _role_status(role_certificate, candidate_relation, prefix_sha) if candidate_sha else "CANDIDATE_MISSING"
    challenge = None
    if role_status == "UNANIMOUS_PRE_GOLD_REVIEW" and candidate_proof and candidate_checked["status"] == "INVALID_JUSTIFICATION":
        checked_challenge = ledger.check_arithmetic_invalidation("reviewed_" + candidate_sha[:24], candidate_proof)
        if isinstance(checked_challenge, support.Challenge) and ledger.verify_challenge(checked_challenge).verdict == "PASS":
            challenge = checked_challenge
    status = "ACTIONABLE_LITERAL_INVALIDATION" if challenge is not None else "NO_ACTIONABLE_CHALLENGE"
    return NaturalLedgerResult(status, ledger, challenge, {
        "source_prefix_sha256": prefix_sha, "observed_length": observed_length,
        "candidate_relation_sha256": candidate_sha, "candidate_proof_id": candidate_proof,
        "role_status": role_status, "processed_relations": processed, "skipped_relations": skipped,
        "role_certificate_sha256": support.digest(role_certificate) if role_certificate is not None else None,
        "support_scope": "Closed expression evaluation only. Source-role approval concerns use as an asserted proof step.",
        "role_review_authority": "Trusted caller review receipt with local identities and byte bindings.",
        "boundaries_need_native_token_validation": True,
        "trusted_given_calls": 0,
    })
