"""CPU reference: scoped certificate replay, AND/OR support, conservative repair.

This is a restricted arithmetic/trusted-input kernel, NOT a natural-language
verifier, a theorem-prover, a model controller, a cryptographic security boundary,
or evidence that SCOPE-Rebase improves task accuracy. Trusted inputs/constraints
are explicit caller-supplied assumptions; their correctness is not inferred.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal

Verdict = Literal["PASS", "FAIL", "UNKNOWN"]
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_@.:-]{0,95}\Z")
SUBJECT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}\Z")
MAX_BITS = 4096


def _identifier(value: str):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("Invalid identifier")


def rational(value):
    if type(value) is int:
        result = Fraction(value)
    elif isinstance(value, Fraction):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+(?:/[+-]?\d+)?", value):
        result = Fraction(value)
    else:
        raise ValueError("An exact integer/rational, never bool/float, is required")
    if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise ValueError("Rational magnitude limit")
    return result


def _normal(obj):
    if isinstance(obj, Fraction): return str(obj)
    if hasattr(obj, "__dataclass_fields__"): return _normal(asdict(obj))
    if isinstance(obj, dict): return {str(k): _normal(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)): return [_normal(v) for v in obj]
    if isinstance(obj, (set, frozenset)): return sorted(_normal(v) for v in obj)
    return obj


def digest(obj):
    return hashlib.sha256(json.dumps(_normal(obj), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def exact(expr: str, values: dict[str, Fraction] | None = None) -> Fraction:
    """Bounded AST interpreter; no eval, calls, attributes, floats or floor division."""
    if not isinstance(expr, str) or not 0 < len(expr) <= 2048:
        raise ValueError("Expression length limit")
    tree = ast.parse(expr, mode="eval")
    if len(list(ast.walk(tree))) > 128: raise ValueError("AST node limit")
    values = values or {}

    def visit(node, depth=0):
        if depth > 24: raise ValueError("AST depth limit")
        if isinstance(node, ast.Constant):
            if type(node.value) is not int or abs(node.value) > 10**9:
                raise ValueError("Only bounded integer literals")
            return rational(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values: raise ValueError("Unbound variable")
            return rational(values[node.id])
        if isinstance(node, ast.UnaryOp):
            a = visit(node.operand, depth+1)
            if isinstance(node.op, ast.USub): return -a
            if isinstance(node.op, ast.UAdd): return a
            raise ValueError("Unsupported unary operator")
        if not isinstance(node, ast.BinOp): raise ValueError("Unsupported syntax")
        a, b = visit(node.left, depth+1), visit(node.right, depth+1)
        if isinstance(node.op, ast.Pow):
            if b.denominator != 1 or abs(b.numerator) > 12: raise ValueError("Exponent limit")
            if max(abs(a.numerator).bit_length(), a.denominator.bit_length()) * abs(b.numerator) > MAX_BITS:
                raise ValueError("Power resource bound")
            return rational(a ** b.numerator)
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            raise ValueError("Unsupported binary operator")
        # Conservative upper bounds prevent enormous intermediates, even if a
        # later simplification could cancel them. Such checks abstain, not FAIL.
        if max(abs(a.numerator).bit_length(), a.denominator.bit_length()) + max(abs(b.numerator).bit_length(), b.denominator.bit_length()) > MAX_BITS:
            raise ValueError("Intermediate resource bound")
        if isinstance(node.op, ast.Add): result = a+b
        elif isinstance(node.op, ast.Sub): result = a-b
        elif isinstance(node.op, ast.Mult): result = a*b
        else: result = a/b
        return rational(result)
    return visit(tree.body)


def names(expr):
    if not isinstance(expr, str) or not 0 < len(expr) <= 2048: raise ValueError("Expression length limit")
    tree = ast.parse(expr, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 128: raise ValueError("AST node limit")
    return {n.id for n in nodes if isinstance(n, ast.Name)}


@dataclass(frozen=True)
class Scope:
    id: str
    domain: str = "rational"
    assumptions: tuple[str, ...] = ()
    revision: int = 0

    def __post_init__(self):
        _identifier(self.id)
        if self.domain not in ("integer", "rational") or type(self.revision) is not int or self.revision < 0:
            raise ValueError("Unsupported or incomplete scope")
        if not isinstance(self.assumptions, tuple) or any(not isinstance(s, str) for s in self.assumptions):
            raise ValueError("Immutable explicit assumptions required")
        if len(self.assumptions) > 8 or any(len(s) > 1024 for s in self.assumptions):
            raise ValueError("Scope serialization bound")


@dataclass(frozen=True)
class Claim:
    id: str
    subject: str
    value: Fraction
    scope_id: str
    version: int = 0
    token_start: int = 0
    token_end: int = 0

    def __post_init__(self):
        _identifier(self.id); _identifier(self.scope_id)
        if not SUBJECT.fullmatch(self.subject): raise ValueError("Unscoped/unsafe subject identity")
        if type(self.version) is not int or self.version < 0: raise ValueError("Invalid version")
        if not (type(self.token_start) is int and type(self.token_end) is int and 0 <= self.token_start <= self.token_end):
            raise ValueError("Invalid token span")
        object.__setattr__(self, "value", rational(self.value))


@dataclass(frozen=True)
class ProofCertificate:
    id: str
    checker_id: str
    purpose: str
    binding_hash: str
    witness: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Justification:
    id: str
    conclusion: str
    premises: tuple[str, ...]
    scope_id: str
    expression: str | None
    bindings: tuple[tuple[str, str], ...]
    checker_id: str
    certificate: ProofCertificate | None
    verdict: Verdict
    source_id: str | None = None
    token_start: int = 0
    token_end: int = 0
    revoked: bool = False
    constraint_id: str | None = None


@dataclass(frozen=True)
class Challenge:
    id: str
    kind: str                 # invalidate_justification OR refute_claim
    target_id: str
    scope_id: str
    certificate: ProofCertificate | None = None
    asserted_verdict: Verdict = "UNKNOWN"  # untrusted input; never establishes PASS


@dataclass(frozen=True)
class Verification:
    verdict: Verdict
    reason: str
    certificate: ProofCertificate | None = None


@dataclass(frozen=True)
class SupportState:
    status: str
    supported: frozenset[str]
    raw_positive: frozenset[str]
    conflict_claims: frozenset[str]
    refuted_claims: frozenset[str]


@dataclass(frozen=True)
class RepairDelta:
    verdict: Verdict
    reason: str
    lost_support: frozenset[str]
    retained_support: frozenset[str]
    invalidated_justifications: tuple[str, ...]
    invalidated_text_spans: tuple[tuple[int, int], ...]
    proposed_cut_token: int | None
    safe_cut_token: int | None
    carried_claims: tuple[str, ...]
    claim_refuted: bool
    after_status: str
    revision: int


class EvidenceLedger:
    """Trusted scope/input registry + replayable restricted checker capabilities.

    `trust_given` and `trust_constraint` are explicit trusted-input integration
    points. They are not called by model prose. Python private members are not a
    sandbox/security boundary; serialized caller-supplied certificates are checked.
    """
    def __init__(self, scopes, *, legal_token_boundaries=(0,), observed_token_length=0):
        self._scopes = {s.id: s for s in scopes}
        if len(self._scopes) != len(scopes): raise ValueError("Duplicate scope")
        if type(observed_token_length) is not int or observed_token_length < 0: raise ValueError("Observed length")
        boundaries = tuple(sorted(set(legal_token_boundaries)))
        if any(type(v) is not int or not 0 <= v <= observed_token_length for v in boundaries):
            raise ValueError("Unobserved token boundary")
        self.boundaries, self.observed_token_length = boundaries, observed_token_length
        self._claims, self._proofs, self._certificates = {}, {}, {}
        self._givens, self._constraints, self._withdrawals, self._refutations = {}, {}, {}, {}
        self._current, self.revision = {}, 0

    @property
    def claims(self): return MappingProxyType(self._claims)
    @property
    def proofs(self): return MappingProxyType(self._proofs)
    @property
    def current_versions(self): return MappingProxyType(self._current)

    def _claim_hash(self, cid):
        c = self._claims[cid]
        return digest((c, self._scopes[c.scope_id]))

    def add_claim(self, claim):
        if claim.id in self._claims or claim.scope_id not in self._scopes: raise ValueError("Duplicate claim/unknown scope")
        if any((old.scope_id, old.subject, old.version, old.value) ==
               (claim.scope_id, claim.subject, claim.version, claim.value) for old in self._claims.values()):
            raise ValueError("Use multiple proofs of one canonical claim, not duplicate claim IDs")
        if claim.token_end > self.observed_token_length: raise ValueError("Claim reaches unobserved future")
        if self._scopes[claim.scope_id].domain == "integer" and claim.value.denominator != 1:
            raise ValueError("Integer-domain claim is not integer")
        self._claims[claim.id] = claim
        self._current.setdefault((claim.scope_id, claim.subject), claim.version)
        self.revision += 1

    def trust_given(self, source_id, claim_id):
        """Record a caller-authenticated problem premise. No truth is inferred."""
        _identifier(source_id)
        if source_id in self._givens: raise ValueError("Given source is immutable")
        self._givens[source_id] = self._claim_hash(claim_id)

    def trust_constraint(self, rule_id, scope_id, subject, expression):
        _identifier(rule_id)
        if rule_id in self._constraints or scope_id not in self._scopes or not SUBJECT.fullmatch(subject):
            raise ValueError("Immutable known constraint required")
        # AST syntax/resource shape checked independently of evaluation values.
        if not isinstance(expression, str) or len(expression) > 2048: raise ValueError("Constraint bound")
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 128: raise ValueError("Constraint AST bound")
        self._constraints[rule_id] = (scope_id, subject, expression, digest(self._scopes[scope_id]))

    def _binding(self, proof):
        return digest({"proof": replace(proof, certificate=None, verdict="UNKNOWN", revoked=False),
                       "conclusion": self._claim_hash(proof.conclusion),
                       "premises": [(p, self._claim_hash(p)) for p in proof.premises],
                       "scope": self._scopes[proof.scope_id],
                       "trusted_rule": self._constraints.get(proof.constraint_id) if proof.constraint_id else None})

    def _rule_applicable(self, proof):
        constraint = self._constraints.get(proof.constraint_id)
        if constraint is None: return False
        scope, subject, expression, scope_hash = constraint
        return (proof.scope_id == scope and self._claims[proof.conclusion].subject == subject and
                scope_hash == digest(self._scopes[scope]) and
                ast.dump(ast.parse(expression, mode="eval")) == ast.dump(ast.parse(proof.expression, mode="eval")))

    def _scope_and_values(self, conclusion, scope_id, expression, bindings):
        if conclusion not in self._claims or scope_id not in self._scopes: raise ValueError("Unknown claim/scope")
        if self._claims[conclusion].scope_id != scope_id: raise ValueError("Conclusion scope mismatch")
        d = dict(bindings)
        if len(d) != len(bindings) or set(d) != names(expression): raise ValueError("Incomplete/extra variable bindings")
        values = {}
        for variable, cid in bindings:
            c = self._claims[cid]
            if c.scope_id != scope_id or c.subject != variable: raise ValueError("Premise scope/entity mismatch")
            values[variable] = c.value
        return values

    def _issue(self, checker, purpose, binding_hash, witness):
        payload = (checker, purpose, binding_hash, tuple(sorted(witness.items())))
        cert = ProofCertificate(digest(payload), checker, purpose, binding_hash, tuple(sorted(witness.items())))
        self._certificates[cert.id] = cert
        return cert

    def _record(self, p):
        if p.id in self._proofs: raise ValueError("Duplicate proof")
        _identifier(p.id)
        if not (0 <= p.token_start <= p.token_end <= self.observed_token_length): raise ValueError("Proof token span")
        self._proofs[p.id] = p; self.revision += 1
        return Verification(p.verdict, "replayable_certificate" if p.certificate else "checker_did_not_certify", p.certificate)

    def prove_given(self, proof_id, conclusion, source_id, *, token_start=0, token_end=0):
        c = self._claims[conclusion]
        p = Justification(proof_id, conclusion, (), c.scope_id, None, (), "trusted-input-v1", None, "UNKNOWN", source_id, token_start, token_end)
        if self._givens.get(source_id) != self._claim_hash(conclusion): return self._record(p)
        cert = self._issue(p.checker_id, "justify", self._binding(p), {"source_id": source_id, "claim_hash": self._claim_hash(conclusion)})
        return self._record(replace(p, certificate=cert, verdict="PASS"))

    def prove_arithmetic(self, proof_id, conclusion, expression, bindings=(), *, constraint_id=None, token_start=0, token_end=0):
        c = self._claims[conclusion]
        premises = tuple(dict.fromkeys(cid for _, cid in bindings))
        p = Justification(proof_id, conclusion, premises, c.scope_id, expression, tuple(bindings), "exact-rational-v1", None, "UNKNOWN", None, token_start, token_end)
        p = replace(p, constraint_id=constraint_id)
        try:
            values = self._scope_and_values(conclusion, c.scope_id, expression, tuple(bindings))
            result = exact(expression, values)
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError, RecursionError): return self._record(p)
        if result != c.value: return self._record(replace(p, verdict="FAIL"))
        if not self._rule_applicable(p): return self._record(p)
        cert = self._issue(p.checker_id, "justify", self._binding(p), {"computed": str(result), "expected": str(c.value),
                           "constraint_id": constraint_id, "constraint_hash": digest(self._constraints[constraint_id])})
        return self._record(replace(p, verdict="PASS", certificate=cert))

    def ingest_justification(self, proposal):
        """Serialized/free PASS strings do not bypass certificate replay."""
        valid = self._certificate_valid(proposal)
        return self._record(proposal if valid else replace(proposal, verdict="UNKNOWN", certificate=None))

    def _certificate_valid(self, proof):
        cert = proof.certificate
        if proof.verdict != "PASS" or not isinstance(cert, ProofCertificate): return False
        if self._certificates.get(cert.id) != cert or cert.purpose != "justify" or cert.checker_id != proof.checker_id: return False
        try:
            if cert.binding_hash != self._binding(proof): return False
            if proof.checker_id == "trusted-input-v1":
                return self._givens.get(proof.source_id) == self._claim_hash(proof.conclusion)
            if proof.checker_id == "exact-rational-v1":
                if not self._rule_applicable(proof): return False
                values = self._scope_and_values(proof.conclusion, proof.scope_id, proof.expression, proof.bindings)
                if proof.premises != tuple(dict.fromkeys(cid for _, cid in proof.bindings)): return False
                return exact(proof.expression, values) == self._claims[proof.conclusion].value
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError, RecursionError): return False
        return False

    def _current_claim(self, cid):
        c = self._claims[cid]
        return self._current[(c.scope_id, c.subject)] == c.version

    def _closure(self, blocked=frozenset()):
        result = set()
        while True:
            add = {p.conclusion for p in self._proofs.values()
                   if not p.revoked and p.conclusion not in blocked and self._current_claim(p.conclusion)
                   and self._certificate_valid(p) and all(cid in result for cid in p.premises)} - result
            if not add: return frozenset(result)
            result.update(add)

    def support_state(self):
        raw = self._closure(); conflict = self._positive_conflicts(raw)
        refuted = {cid for cid, challenge in self._refutations.items() if self.verify_challenge(challenge).verdict == "PASS"}
        conflict.update(raw & refuted)
        supported = self._closure(frozenset(conflict | refuted))
        return SupportState("INCONSISTENT_CERTIFICATES" if conflict else "OK", supported, raw,
                            frozenset(conflict), frozenset(refuted))

    def _positive_conflicts(self, raw):
        groups = {}
        for cid in raw:
            c = self._claims[cid]; groups.setdefault((c.scope_id, c.subject, c.version), []).append(cid)
        conflict = set()
        for ids in groups.values():
            if len({self._claims[cid].value for cid in ids}) > 1: conflict.update(ids)
        return conflict

    def _independent_support(self, target):
        # Conservative: unresolved refutations and contradictory certificates
        # cannot become premises of a new refutation. No recursive truth call.
        blocked = {target} | self._positive_conflicts(self._closure()) | set(self._refutations)
        return self._closure(frozenset(blocked))

    def supported(self): return self.support_state().supported

    def _delta(self, before, verdict, reason, invalidated=(), *, claim_refuted=False):
        after = self.support_state(); lost = before.supported - after.supported
        spans = tuple((self._proofs[pid].token_start, self._proofs[pid].token_end) for pid in invalidated)
        starts = [a for a, _ in spans] + [self._claims[cid].token_start for cid in lost]
        proposed = min(starts) if starts else None
        cut = max((b for b in self.boundaries if proposed is not None and b <= proposed), default=None)
        carried = tuple(sorted((cid for cid in after.supported if cut is not None and self._claims[cid].token_start >= cut),
                               key=lambda cid: (self._claims[cid].token_start, cid)))
        return RepairDelta(verdict, reason, frozenset(lost), before.supported & after.supported, tuple(invalidated), spans,
                           proposed, cut, carried, claim_refuted, after.status, self.revision)

    def issue_withdrawal(self, challenge_id, proof_id, *, reason):
        """Trusted lifecycle API: withdraw THIS evidence, not declare a theorem false.

        In production the authorizing reason must come from an external checker or
        trusted source lifecycle, not an LLM. This CPU interface explicitly models
        that authority; it is NOT a natural refutation detector.
        """
        _identifier(challenge_id)
        p = self._proofs[proof_id]
        if not isinstance(reason, str) or not reason.strip(): raise ValueError("Auditable withdrawal reason")
        binding = digest((proof_id, self._binding(p), p.scope_id, digest(self._scopes[p.scope_id])))
        cert = self._issue("proof-lifecycle-v1", "invalidate_justification", binding,
                           {"target": proof_id, "reason": reason})
        self._withdrawals[cert.id] = (proof_id, binding)
        return Challenge(challenge_id, "invalidate_justification", proof_id, p.scope_id, cert)

    def check_arithmetic_invalidation(self, challenge_id, proof_id):
        """Refute this stated numerical step, without asserting its conclusion false.

        A bad argument may conclude a true claim. No trusted inference-rule
        license is needed to reject a numerically false equality as written.
        Grounded premise values and identity/scope bindings ARE still required.
        """
        _identifier(challenge_id)
        try:
            p = self._proofs[proof_id]
            if p.expression is None: raise ValueError("No arithmetic statement")
            values = self._scope_and_values(p.conclusion, p.scope_id, p.expression, p.bindings)
            independent = self._independent_support(p.conclusion)
            if not all(cid in independent for cid in p.premises): raise ValueError("Ungrounded counterevidence")
            computed = exact(p.expression, values); claimed = self._claims[p.conclusion].value
            if computed == claimed: return Verification("FAIL", "calculation_does_not_invalidate_step")
            binding = digest((p.id, self._binding(p), p.scope_id, digest(self._scopes[p.scope_id])))
            cert = self._issue("invalid-arithmetic-v1", "invalidate_justification", binding,
                               {"target": p.id, "computed": str(computed), "claimed": str(claimed)})
            return Challenge(challenge_id, "invalidate_justification", p.id, p.scope_id, cert)
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError, RecursionError):
            return Verification("UNKNOWN", "incomplete_or_out_of_scope_arithmetic_invalidation")

    def check_claim_refutation(self, challenge_id, claim_id, constraint_id, bindings=()):
        """Independent exact counterevidence for an explicitly trusted constraint."""
        _identifier(challenge_id)
        target = self._claims[claim_id]
        try:
            scope, subject, expr, scope_hash = self._constraints[constraint_id]
            if (target.scope_id, target.subject) != (scope, subject): raise ValueError("Constraint scope/entity")
            values = self._scope_and_values(claim_id, scope, expr, tuple(bindings))
            premise_ids = tuple(dict.fromkeys(cid for _, cid in bindings))
            # Must have a grounded support path that does not depend on the very
            # claim alleged to be false; OR alternatives are respected.
            independent = self._independent_support(claim_id)
            if not all(cid in independent for cid in premise_ids): raise ValueError("Counterevidence not independently grounded")
            expected = exact(expr, values)
            if expected == target.value: return Verification("FAIL", "counterexample_does_not_refute_claim")
            binding = digest((self._claim_hash(claim_id), constraint_id, self._constraints[constraint_id],
                              [(cid, self._claim_hash(cid)) for cid in premise_ids]))
            witness = {"constraint_id": constraint_id, "bindings": json.dumps(bindings), "expected": str(expected), "actual": str(target.value)}
            cert = self._issue("constraint-rational-v1", "refute_claim", binding, witness)
            challenge = Challenge(challenge_id, "refute_claim", claim_id, scope, cert)
            return challenge
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError, RecursionError):
            return Verification("UNKNOWN", "incomplete_or_out_of_scope_counterevidence")

    def verify_challenge(self, challenge):
        if not isinstance(challenge, Challenge): return Verification("UNKNOWN", "no_checked_challenge")
        cert = challenge.certificate
        if not isinstance(cert, ProofCertificate) or self._certificates.get(cert.id) != cert or cert.purpose != challenge.kind:
            return Verification("UNKNOWN", "missing_or_unissued_certificate")
        try:
            if challenge.kind == "invalidate_justification":
                p = self._proofs[challenge.target_id]
                binding = digest((p.id, self._binding(p), p.scope_id, digest(self._scopes[p.scope_id])))
                if cert.checker_id == "invalid-arithmetic-v1":
                    if challenge.scope_id != p.scope_id or cert.binding_hash != binding: raise ValueError("Statement binding")
                    values = self._scope_and_values(p.conclusion, p.scope_id, p.expression, p.bindings)
                    if not all(cid in self._independent_support(p.conclusion) for cid in p.premises): raise ValueError("Counterevidence lost support")
                    computed = exact(p.expression, values); claimed = self._claims[p.conclusion].value
                    ok = computed != claimed and dict(cert.witness).get("computed") == str(computed) and dict(cert.witness).get("claimed") == str(claimed)
                    return Verification("PASS" if ok else "UNKNOWN", "checked_invalid_arithmetic_step" if ok else "invalid_step_receipt_mismatch", cert if ok else None)
                ok = (cert.checker_id == "proof-lifecycle-v1" and challenge.scope_id == p.scope_id and
                      self._withdrawals.get(cert.id) == (p.id, binding) and cert.binding_hash == binding)
                return Verification("PASS" if ok else "UNKNOWN", "exact_proof_withdrawal_receipt" if ok else "withdrawal_binding_mismatch", cert if ok else None)
            if challenge.kind == "refute_claim":
                c = self._claims[challenge.target_id]; witness = dict(cert.witness)
                scope, subject, expr, scope_hash = self._constraints[witness["constraint_id"]]
                bindings = tuple(tuple(v) for v in json.loads(witness["bindings"]))
                if (c.scope_id, c.subject) != (scope, subject) or challenge.scope_id != scope or not self._current_claim(c.id):
                    raise ValueError("Refutation scope/version")
                vals = self._scope_and_values(c.id, scope, expr, bindings)
                premise_ids = tuple(dict.fromkeys(cid for _, cid in bindings))
                if not all(cid in self._independent_support(c.id) for cid in premise_ids): raise ValueError("Refutation lost support")
                binding = digest((self._claim_hash(c.id), witness["constraint_id"], self._constraints[witness["constraint_id"]],
                                  [(cid, self._claim_hash(cid)) for cid in premise_ids]))
                expected = exact(expr, vals)
                ok = cert.checker_id == "constraint-rational-v1" and cert.binding_hash == binding and expected != c.value
                return Verification("PASS" if ok else "UNKNOWN", "independent_exact_refutation" if ok else "refutation_mismatch", cert if ok else None)
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError, RecursionError): pass
        return Verification("UNKNOWN", "unsupported_or_incomplete_challenge")

    def apply_challenge(self, challenge):
        before = self.support_state(); verdict = self.verify_challenge(challenge)
        if verdict.verdict != "PASS": return self._delta(before, verdict.verdict, verdict.reason)
        if challenge.kind == "invalidate_justification":
            p = self._proofs[challenge.target_id]
            if p.revoked: return self._delta(before, "PASS", "already_withdrawn")
            self._proofs[p.id] = replace(p, revoked=True); self.revision += 1
            return self._delta(before, "PASS", "one_justification_withdrawn_not_claim_false", (p.id,))
        self._refutations[challenge.target_id] = challenge; self.revision += 1
        return self._delta(before, "PASS", "refuted_claim_evidence_not_arbitrary_root_deletion", claim_refuted=True)

    def activate_version(self, claim_id):
        return self.activate_versions((claim_id,))

    def activate_versions(self, claim_ids):
        before = self.support_state(); candidates = [self._claims[cid] for cid in claim_ids]
        keys = [(c.scope_id, c.subject) for c in candidates]
        if not candidates or len(set(keys)) != len(keys): raise ValueError("One new version per slot")
        eligible = all(any(p.conclusion == c.id and not p.revoked and self._certificate_valid(p)
                           and all(cid in before.supported for cid in p.premises) for p in self._proofs.values()) for c in candidates)
        if not eligible: return self._delta(before, "UNKNOWN", "new_version_has_no_current_grounded_certificate")
        if any(c.version <= self._current[key] for c, key in zip(candidates, keys)):
            return self._delta(before, "UNKNOWN", "version_must_advance")
        old_versions = dict(self._current)
        for c, key in zip(candidates, keys): self._current[key] = c.version
        prospective = self.support_state()
        if not all(c.id in prospective.supported for c in candidates) or prospective.status != "OK":
            self._current = old_versions
            return self._delta(before, "UNKNOWN", "new_version_not_grounded_after_atomic_switch")
        self.revision += 1
        return self._delta(before, "PASS", "old_version_archived_not_proved_false")

    def bridge(self, delta):
        if delta.revision != self.revision: raise ValueError("Stale repair delta")
        state = self.support_state()
        if state.status != "OK": raise ValueError("Inconsistent certificates cannot be bridged")
        if delta.safe_cut_token is None: return ""
        if not set(delta.carried_claims) <= state.supported: raise ValueError("Bridge contains unsupported claims")
        lines = ["\nChecked scoped facts retained after withdrawing an obsolete justification:"]
        for cid in delta.carried_claims:
            c = self._claims[cid]
            valid = [p for p in self._proofs.values() if not p.revoked and p.conclusion == cid and self._certificate_valid(p)
                     and all(v in state.supported for v in p.premises)]
            receipts = ",".join(p.certificate.id for p in sorted(valid, key=lambda p: p.id))
            scope = self._scopes[c.scope_id]
            assumptions = json.dumps(scope.assumptions, ensure_ascii=True).replace("<", r"\u003c").replace(">", r"\u003e")
            lines.append(f"- {c.subject} = {c.value}; scope={c.scope_id}; scope_revision={scope.revision}; "
                         f"domain={scope.domain}; assumptions_json={assumptions}; version={c.version}; evidence={receipts}.")
        lines.append("Use only the retained facts in their stated scopes; rebuild unsupported steps.\n")
        text = "\n".join(lines)
        if any(token in text for token in ("<|", "<think>", "</think>")): raise ValueError("Unsafe bridge control token")
        return text
