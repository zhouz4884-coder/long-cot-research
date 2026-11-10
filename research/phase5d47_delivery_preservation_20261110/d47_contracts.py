"""Exact point scope and question-only proof records for D4.7."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from freeze_d47_intake import HERE, load, sha, write_exclusive
from d47_point_domains import check
from d47_problem_specs import PROBLEMS
from point_verifier import EXACT_NECESSARY_PREDICATE, ObjectiveBinding, ReviewedPointContract, checker_source_sha256

PROOFS = {
    "2009-I-13": "The integer error a_i*a_(i+1)-2009 contracts by the denominator 1+a_(i+1). "
                 "It must be zero, and product 2009 conversely gives a period-two valid sequence. "
                 "At a fixed sum verify the exact positive integer roots of the product quadratic.",
    "2010-I-12": "Below 243 color 3..8 and 81..242 red, others blue; verify every product triple at the fixed endpoint. "
                 "At or above 243 verify all 32 two-colorings of the five powers 3,9,27,81,243. "
                 "The subproblem alone forces a monochromatic product with equality allowed for the factors.",
    "2016-II-4": "Green counts force a=5k and b=3k; all color counts give volume 180k and kc=12. "
                 "For k dividing 12, distribute a fixed sequence of 3R+4G+5Y using k equal contiguous slices "
                 "indexed by row-plus-column residue, checking every original layer.",
    "2018-I-13": "With B=(0,0), C=(32,0), A=(12,6sqrt(21)), X=(t,0), put u=AX. "
                 "The original incenter barycentric determinant simplifies to area sqrt(21)*u. "
                 "A right-side interior witness exists exactly for 0<=area²/21-756<400; it uses t=12+sqrt(radicand).",
    "2018-I-8": "Equiangular convex closure fixes the two omitted edges as 2 and 16. "
                "Opposite CD/FA have distance 7sqrt(3), giving d²<=147. The center (5/2,9sqrt(3)/2) "
                "meets the radius constraints at all six sides for every 0<d²<=147.",
    "2019-I-11": "The base excenter forces omega radius r+2r_A. With common side a, base b and altitude h, "
                 "the side excenter has coordinates (a,h) and radius h. Its external tangency gives "
                 "2a=9b. Integer sides give a=9k,b=2k; verify exact radius ratios and both tangencies.",
    "2020-II-8": "The recurrence zero sets are contiguous step-two progressions centered at n, "
                 "with largest zero n(n+1)/2 and smallest n-n(n-1)/2. "
                 "Induct using n plus/minus the nonnegative preceding roots. Test the exact sum n*(n(n-1)/2+1).",
    "2022-II-12": "Pair the two focal segments to get distance sum at least 26+20=46. "
                  "Both equalities hold at the intersection (14,15/2) with strict original semiaxes. "
                  "A vertical ray from there avoids both focal segments and continuously reaches all sums a+b>=23.",
}


def canonical(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record(row: dict) -> dict:
    cid = row["case_id"]
    spec = PROBLEMS[cid]
    if {key: row[key] for key in spec} != spec:
        raise ValueError("Different reviewed original objective")
    scope = {key: spec[key] for key in ("direction", "unit", "objective_id", "description", "subject_patterns")}
    binding = ObjectiveBinding(row["question_sha256"], spec["objective_id"], canonical(scope),
                               canonical({"constraints": spec["constraints"], "proof": PROOFS[cid]}), spec["direction"])
    review = {"case_id": cid, "question_sha256": row["question_sha256"], "scope": scope,
              "proof": PROOFS[cid], "checker_sha256": checker_source_sha256(check)}
    contract = ReviewedPointContract(
        binding, tuple(spec["constraints"]), "d47.exact.point", 1, check.__name__, checker_source_sha256(check),
        EXACT_NECESSARY_PREDICATE, canonical(PROOFS[cid]), canonical(review),
    )
    return {"case_id": cid, "unit": spec["unit"], "contract": asdict(contract), "contract_sha256": contract.sha256,
            "question_only_review": review}


def reconstruct(row: dict) -> ReviewedPointContract:
    data = row["contract"]
    contract = ReviewedPointContract(**{**data, "binding": ObjectiveBinding(**data["binding"]),
                                      "required_constraints": tuple(data["required_constraints"])})
    if contract.sha256 != row["contract_sha256"]:
        raise ValueError("Point contract changed")
    return contract


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cohort", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    cohort = load(args.cohort)
    if cohort["problem_specs_sha256"] != sha(HERE / "d47_problem_specs.py") or cohort["point_domain_sha256"] != checker_source_sha256(check):
        raise ValueError("Point code differs from question freeze")
    result = {"status": "D47_POINT_AND_UNIT_CONTRACTS_FROZEN_BEFORE_HELDOUT", "cohort_sha256": sha(args.cohort),
              "contract_source_sha256": sha(Path(__file__)),
              "preservation_source_sha256": sha(HERE / "delivery_preservation.py"),
              "gate_rules_sha256": sha(HERE / "D47_GATE_RULES.json"),
              "rows": [record(r) for r in cohort["rows"]]}
    write_exclusive(args.output, result)
    print(result["status"], len(result["rows"]), sha(args.output))


if __name__ == "__main__":
    main()
