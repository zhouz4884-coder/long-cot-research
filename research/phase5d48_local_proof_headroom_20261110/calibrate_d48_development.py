"""D47-derived development-only scope cases. No archive or final labels needed."""
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from local_implication import (
    AssertionReceipt, ImplicationBinding, LocalImplicationVerifier, Predicate,
    ReviewedImplication, Variable, REFUTE_THIS_LOCAL_ASSERTION_ONLY, UNKNOWN,
)

HERE = Path(__file__).resolve().parent
D47 = HERE.parent / "phase5d47_delivery_preservation_20261110"


def digest(text):
    return sha256(text.encode()).hexdigest()


def run(contract, sample, assertion):
    receipt = AssertionReceipt(contract.binding, contract.statement_sha256, sample,
                               digest("development paraphrase: " + assertion), digest(assertion),
                               (0, len(assertion)), digest(assertion), digest("development fixture author"))
    trial = replace(receipt, role="TRIAL")
    other = replace(receipt, binding=replace(receipt.binding, scope_sha256=digest("other scope")))
    engine = LocalImplicationVerifier(contract, contract.sha256,
                                     approved_assertion_sha256=[r.sha256 for r in (receipt, trial, other)],
                                     call_budget=1, work_budget=128, wall_budget_ns=500_000_000)
    for unauthorized in (trial, other):
        outcome = engine.check(unauthorized, assertion)
        if outcome.status != UNKNOWN or outcome.work:
            raise AssertionError("Invalid role or changed object authorized")
    outcome = engine.check(receipt, assertion)
    if outcome.status != REFUTE_THIS_LOCAL_ASSERTION_ONLY or not engine.authorizes_refutation(receipt, outcome):
        raise AssertionError("Expected a valid counterexample")
    return engine.report()


def ellipse(binding, review_sha):
    def square(x):
        return ("POW", x, 2)

    def squared_dist(x, y, a, b):
        return ("ADD", square(("SUB", x, a)), square(("SUB", y, b)))

    dims = tuple(Variable(name, "RATIONAL") for name in ("x", "y", "u", "v", "a", "b", "r", "s", "t", "w"))
    domain = (Predicate("GT", "a", 4), Predicate("GT", "b", 1),
              *(Predicate("GE", name, 0) for name in ("r", "s", "t", "w")))
    premise = (
        Predicate("EQ", square("r"), squared_dist("x", "y", -4, 0)),
        Predicate("EQ", square("s"), squared_dist("x", "y", 4, 0)),
        Predicate("EQ", square("t"), squared_dist("u", "v", 20, 10)),
        Predicate("EQ", square("w"), squared_dist("u", "v", 20, 12)),
        Predicate("EQ", ("ADD", "r", "s"), ("MUL", 2, "a")),
        Predicate("EQ", ("ADD", "t", "w"), ("MUL", 2, "b")),
    )
    conclusion = Predicate("EQ", squared_dist("x", "y", "u", "v"), 0)
    values = (0, 3, 20, 14, 5, 3, 5, 5, 4, 2)
    return ReviewedImplication(binding, dims, domain, premise, conclusion,
                               tuple((v.name, value) for v, value in zip(dims, values)),
                               digest("Separate ellipse membership does not identify the two witnesses."), review_sha)


def hexagon(binding, review_sha):
    dims = tuple(Variable(name, "RATIONAL") for name in ("x", "Y", "d2"))
    line = ("ADD", ("SUB", "x", "Y"), 16)
    contract = ReviewedImplication(
        binding, dims, (Predicate("GT", "d2", 0),),
        (Predicate("EQ", line, 0), Predicate("GE", "x", -8), Predicate("LE", "x", -7)),
        Predicate("GE", ("MUL", 3, ("POW", line, 2)), "d2"),
        (("x", Fraction(-15, 2)), ("Y", Fraction(17, 2)), ("d2", 3)),
        digest("The radius squared must not exceed squared distance to supporting line EF."), review_sha,
    )
    return contract


def schur_scope_development():
    endpoint = 36
    red = frozenset(range(3, 9))
    blue = frozenset(range(9, endpoint + 1))
    checks = 0
    if red & blue or red | blue != frozenset(range(3, endpoint + 1)):
        raise AssertionError("Invalid partition")
    for color in (red, blue):
        for x in sorted(color):
            for y in sorted(color):
                checks += 1
                if x * y in color:
                    raise AssertionError("The witness contains a monochromatic product")
    return {
        "case_id": "2010-I-12", "endpoint": endpoint,
        "reviewed_quantifier": "all valid colorings of the fixed endpoint",
        "counterexample": {"red": [3, 8], "blue": [9, 36], "intervals_inclusive": True},
        "products_checked": checks, "separate_fixed_branch": "UNKNOWN_FOR_A_DIFFERENT_FIXED_COLORING",
        "scope": "This finite check refutes the universal claim for endpoint 36 only.",
    }


def main():
    cohort = json.loads((D47 / "D47_COHORT_FREEZE.json").read_bytes())
    ids = {r["case_id"]: r["question_sha256"] for r in cohort["rows"]}
    anchors = (D47 / "D47_POSTSCORE_CONTEXT_ANCHORS.json").read_bytes()
    review_sha = sha256(anchors).hexdigest()
    ellipse_binding = ImplicationBinding(ids["2022-II-12"], "ellipse-common-point",
                                         digest("two distinct focal pairs; distinct strict axes"), "MIN")
    hex_binding = ImplicationBinding(ids["2018-I-8"], "hexagon-disk-config",
                                      digest("specific center on supporting line EF"), "MAX")
    output = {
        "status": "OLD_DEVELOPMENT_PARAPHRASES_AND_FINITE_PROOFS_ONLY",
        "original_d47_context_sha256": review_sha,
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "schur": schur_scope_development(),
        "ellipse": run(ellipse(ellipse_binding, review_sha), "development:2022-II-12",
                       "Two separately witnessed memberships imply these are the same point."),
        "hexagon": run(hexagon(hex_binding, review_sha), "development:2018-I-8",
                        "The fixed center on EF has the needed positive disk clearance from EF."),
        "new_independent_questions": 0,
        "actual_native_assertion_coverage": None,
        "global_answer_authority": False,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
