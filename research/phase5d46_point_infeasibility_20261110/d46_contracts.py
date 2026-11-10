"""Question-only proof review, weak controls and exact point contract freezing."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from d46_point_domains import check
from d46_problem_specs import PROBLEMS
from freeze_d46_intake import HERE, load, sha, write_exclusive
from point_verifier import (
    COMPLETE_FIXED_VALUE_FIBER, EXACT_NECESSARY_PREDICATE, ObjectiveBinding, ReviewedPointContract,
    checker_source_sha256,
)


PROOF = {
    "2009-I-7": "The original product telescopes exactly to 5^a_k=3k+2. The term is integral precisely when that integer is a power of five.",
    "2010-II-3": "Difference d occurs 20-d times. Multiplying all factors modulo 2^n decides divisibility. The crude strict bit bound covers very large exponents.",
    "2010-II-12": "Coprime bases imply bases 8t and 7t. Equality of squared Heron areas gives 15P=338t. Check the resulting integer lateral sides and both strict triangle constraints.",
    "2011-I-12": "Every nonempty men-run has size at least two. Six men can occupy one, two or three selected gaps, with run-count multiplicities 1,3,1. The favorable counts have multiplicities 1,2,0.",
    "2013-II-6": "The smallest integer square at or above the closed left endpoint completely decides whether the block has a square.",
    "2015-I-11": "For base b and common side a, BI^2=b^2a/P=b^2(P-b)/(2P). Positivity and P>2b imply 128<b^2<256, leaving four original integer bases. Check all four at the fixed perimeter.",
    "2015-II-3": "The original candidate must be positive, divisible by 17 and have exactly the specified decimal digit sum.",
    "2015-II-5": "Count the 2n(n-1) adjacent unordered pairs and divide by the total unordered pairs. For n>=2 the probability is 4/[n(n+1)].",
    "2017-II-5": "For total vertex sum S=(1030+x+y)/3, opposite edge weights sum to S. Enumerate each assignment of four known weights. If both missing edges are opposite, S must be 515 but no given pair sums to 515. Otherwise infer both missing weights and check the uniquely reconstructed four distinct vertices.",
    "2019-I-14": "Only an odd prime may be the claimed factor. Trial primality and modular powering decide that single candidate.",
    "2021-II-15": "The +1 recurrence reaches the least square at or above n. The +2 recurrence reaches the least square of the same parity. The recurrences add the respective gaps exactly before the integer square root.",
}
WEAK = {
    "2009-I-7": "k>1 and odd, since 3k+2 must be an odd power.",
    "2010-II-3": "The product is strictly below 2^950, so a dividing exponent is positive and below 950.",
    "2010-II-12": "The even base 8t with two integer lateral sides forces an even perimeter.",
    "2011-I-12": "The original count of women is positive.",
    "2013-II-6": "For N<=249, the next integer square is less than 1000 integers away.",
    "2015-I-11": "BI=8 and strict triangle inequalities imply b>=12 and P>2b.",
    "2015-II-3": "Digit sum gives the necessary residue 8 modulo 9.",
    "2015-II-5": "At least two squares must be selectable, so n>=2.",
    "2017-II-5": "At least one opposite edge pair is fully given; the possible total vertex sum is bounded by the smallest and largest sums of two known edges.",
    "2019-I-14": "The residue multiplicative order is 16, so the odd prime is 1 modulo 16.",
    "2021-II-15": "The original recurrence index must be positive.",
}
STRUCTURAL_FULL_CONTROL = {
    "2009-I-7": "The same telescoping reduces the entire minimum to the first allowed odd power exponent.",
    "2010-II-3": "Summing the 19 multiplicities times their 2-adic valuations yields the exact maximum directly.",
    "2010-II-12": "The one point's equality and integrality relations solve the first admissible scale globally.",
    "2011-I-12": "The same exact count simplifies to one quadratic threshold in the gap count.",
    "2015-I-11": "The complete optimum also uses just the four reviewed base possibilities.",
    "2015-II-5": "The point inequality itself is monotone and gives the first admissible integer by an exact square-root threshold.",
    "2017-II-5": "Six known-pair sums suffice for the entire target range, with constructive opposite-pair realization.",
}


def canonical(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def weak_satisfied(cid: str, value: Fraction) -> bool | None:
    if value.denominator != 1:
        return None
    n = value.numerator
    if cid == "2009-I-7":
        return n > 1 and n % 2 == 1
    if cid == "2010-II-3":
        return 1 <= n < 950
    if cid == "2010-II-12":
        return n > 0 and n % 2 == 0
    if cid == "2011-I-12":
        return n > 0
    if cid == "2013-II-6":
        return n >= 250
    if cid == "2015-I-11":
        return n > 24
    if cid == "2015-II-3":
        return n > 0 and n % 9 == 8
    if cid == "2015-II-5":
        return n >= 2
    if cid == "2017-II-5":
        return 3*(189+234)-1030 <= n <= 3*(320+287)-1030
    if cid == "2019-I-14":
        return n > 2 and n % 16 == 1
    if cid == "2021-II-15":
        return n > 0
    raise ValueError(f"Unreviewed weak control for {cid}")


def contract_record(row: dict) -> dict:
    cid = row["case_id"]
    spec = PROBLEMS[cid]
    if {k: row[k] for k in spec} != spec:
        raise ValueError(f"Different reviewed point scope for {cid}")
    scope = {k: spec[k] for k in ("direction", "objective_id", "description", "subject_patterns")}
    binding = ObjectiveBinding(row["question_sha256"], spec["objective_id"], canonical(scope),
                               canonical({"constraints": spec["constraints"], "proof": PROOF[cid]}), spec["direction"])
    kind = COMPLETE_FIXED_VALUE_FIBER if spec["point_mode"] == "FIXED_FIBER_EXHAUSTION" else EXACT_NECESSARY_PREDICATE
    review = {"case_id": cid, "question_sha256": row["question_sha256"], "scope": scope,
              "point_proof": PROOF[cid], "checker_sha256": checker_source_sha256(check)}
    contract = ReviewedPointContract(binding, tuple(spec["constraints"]), "d46.exact.point", 1, check.__name__,
                                     checker_source_sha256(check), kind, canonical(PROOF[cid]), canonical(review))
    return {
        "case_id": cid, "contract": asdict(contract), "contract_sha256": contract.sha256,
        "question_only_review": review, "weak_necessity": WEAK[cid],
        "structural_full_control": STRUCTURAL_FULL_CONTROL.get(cid),
    }


def reconstruct(row: dict) -> ReviewedPointContract:
    data = row["contract"]
    contract = ReviewedPointContract(**{**data, "binding": ObjectiveBinding(**data["binding"]),
                                      "required_constraints": tuple(data["required_constraints"])})
    if contract.sha256 != row["contract_sha256"]:
        raise ValueError("Reviewed point contract digest changed")
    return contract


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cohort", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    cohort = load(args.cohort)
    if cohort["problem_specs_sha256"] != sha(HERE / "d46_problem_specs.py") or cohort["point_domain_sha256"] != checker_source_sha256(check):
        raise ValueError("Point code differs from the question freeze")
    out = {"status": "D46_REVIEWED_POINT_CONTRACTS_FROZEN_BEFORE_HELDOUT",
           "cohort_sha256": sha(args.cohort), "contract_source_sha256": sha(Path(__file__)),
           "verifier_source_sha256": sha(HERE / "point_verifier.py"), "rows": [contract_record(r) for r in cohort["rows"]]}
    write_exclusive(args.output, out)
    print(out["status"], len(out["rows"]), sha(args.output))


if __name__ == "__main__":
    main()
