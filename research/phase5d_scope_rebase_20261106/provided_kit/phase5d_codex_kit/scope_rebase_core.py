"""Phase5-D CPU reference: certificate support and conservative invalidation.

This is intentionally NOT a model-side verifier or a full Long-CoT algorithm.
PASS means a proof edge was validated in its declared scope by a trusted
checker. The module does not infer truth from LLM prose, Gold, or confidence.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Literal
import ast
from fractions import Fraction

Verdict = Literal["PASS", "FAIL", "UNKNOWN"]

@dataclass(frozen=True)
class Claim:
    id: str                 # versioned, e.g., x@0 and x@1 differ
    canonical_text: str
    scope_id: str
    token_start: int
    token_end: int

@dataclass(frozen=True)
class Justification:
    id: str
    conclusion: str
    premises: tuple[str, ...]
    scope_id: str
    verdict: Verdict
    checker: str            # "trusted_root", "exact_arithmetic", "verified_rule"
    certificate: str       # reproducible checker artifact or trusted source ID
    revoked: bool = False

@dataclass(frozen=True)
class Challenge:
    target_justification_id: str
    verdict: Verdict       # whether alleged counterevidence itself is valid
    scope_id: str
    certificate: str

@dataclass(frozen=True)
class RepairDelta:
    lost_support: frozenset[str]
    retained_support: frozenset[str]
    newly_supported: frozenset[str]
    crop_at_token: int | None
    carried_claims: tuple[str, ...]

class EvidenceLedger:
    CHECKERS = frozenset({"trusted_root", "exact_arithmetic", "verified_rule"})

    def __init__(self, claims: list[Claim], proofs: list[Justification]):
        self.claims = {c.id: c for c in claims}
        self.proofs = {p.id: p for p in proofs}
        if len(self.claims) != len(claims) or len(self.proofs) != len(proofs):
            raise ValueError("Duplicate claim or justification identifiers")
        for p in proofs:
            if p.conclusion not in self.claims or any(v not in self.claims for v in p.premises):
                raise ValueError("Undefined claim reference")
            if p.scope_id != self.claims[p.conclusion].scope_id:
                raise ValueError("Justification/claim scope mismatch")
            if p.checker not in self.CHECKERS:
                raise ValueError("Untrusted checker cannot create a certificate")
            if p.verdict == "PASS" and not p.certificate:
                raise ValueError("PASS requires independently inspectable certificate")
            # A premise with a different scope needs an explicit scope-mapping proof;
            # this deliberately conservative prototype rejects implicit mapping.
            if any(self.claims[v].scope_id != p.scope_id for v in p.premises):
                raise ValueError("Premise scope must match, or be modeled explicitly")

    def supported(self) -> frozenset[str]:
        """Least fixed point for OR-of-AND justifications; cycles self-support never pass."""
        supported: set[str] = set()
        while True:
            additions = {
                p.conclusion for p in self.proofs.values()
                if (not p.revoked and p.verdict == "PASS" and
                    p.checker in self.CHECKERS and bool(p.certificate) and
                    all(v in supported for v in p.premises))
            } - supported
            if not additions:
                return frozenset(supported)
            supported.update(additions)

    def revoke_by_challenge(self, challenge: Challenge) -> RepairDelta:
        """A valid IN-SCOPE challenge revokes a proof, never declares its claim false."""
        prior = self.supported()
        p = self.proofs[challenge.target_justification_id]
        # Both PASS and a scope match are required. UNKNOWN and FAIL are no-op.
        if (challenge.verdict == "PASS" and challenge.scope_id == p.scope_id
                and challenge.certificate):
            self.proofs[p.id] = replace(p, revoked=True)
        after = self.supported()
        lost = prior - after
        crop = min((self.claims[v].token_start for v in lost), default=None)
        # Late claims with independent, currently supported certificates can be
        # carried as CANONICAL TEXT ONLY. Their old KVs may not be grafted.
        carried = tuple(sorted(
            (v for v in after if crop is not None and self.claims[v].token_start >= crop),
            key=lambda v: (self.claims[v].token_start, v)
        ))
        return RepairDelta(frozenset(lost), frozenset(prior & after),
                           frozenset(after - prior), crop, carried)

    def bridge(self, delta: RepairDelta) -> str:
        """Untrusted for model execution until a separate bridge serialization audit."""
        if delta.crop_at_token is None:
            return ""
        lines = ["\n[Scoped evidence ledger — reconstituted facts, not original hidden states]"]
        for cid in delta.carried_claims:
            c = self.claims[cid]
            lines.append(f"- {cid} [scope={c.scope_id}]: {c.canonical_text}")
        lines.append("[Previously unsupported claims must not be reused as established facts.]\n")
        return "\n".join(lines)


class _ExactArithmetic(ast.NodeVisitor):
    """Whitelisted rational expressions only: NO arbitrary Python execution."""
    OPS = {ast.Add: lambda a,b: a+b, ast.Sub: lambda a,b: a-b,
           ast.Mult: lambda a,b: a*b, ast.Div: lambda a,b: a/b}
    def visit_Expression(self,node): return self.visit(node.body)
    def visit_Constant(self,node):
        if type(node.value) is not int or abs(node.value) > 10**9:
            raise ValueError("Only bounded integer literals are supported")
        return Fraction(node.value)
    def visit_UnaryOp(self,node):
        if isinstance(node.op, ast.USub):return -self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):return self.visit(node.operand)
        raise ValueError("Unsupported unary operator")
    def visit_BinOp(self,node):
        if type(node.op) is ast.Pow:
            base=self.visit(node.left);exp=self.visit(node.right)
            if exp.denominator != 1 or abs(exp.numerator)>12:
                raise ValueError("Unsafe exponent")
            return base ** exp.numerator
        if type(node.op) not in self.OPS: raise ValueError("Unsupported binary operator")
        return self.OPS[type(node.op)](self.visit(node.left),self.visit(node.right))
    def generic_visit(self,node): raise ValueError(f"Disallowed syntax {type(node).__name__}")


def verify_numeric_equality(lhs: str, rhs: str, *, scope_complete: bool) -> Verdict:
    """Checks arithmetic equality, NOT that a math question was modeled correctly."""
    if not scope_complete:
        return "UNKNOWN"
    try:
        l = _ExactArithmetic().visit(ast.parse(lhs, mode="eval"))
        r = _ExactArithmetic().visit(ast.parse(rhs, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return "UNKNOWN"
    return "PASS" if l == r else "FAIL"
