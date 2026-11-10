"""Question-only review bindings and D4.4-style weak necessary conditions."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from math import gcd
from pathlib import Path

from d45_arithmetic_checker import check
from d45_problem_specs import PROBLEMS
from feasible_witness import ObjectiveBinding, ReviewedContract, checker_source_sha256

HERE = Path(__file__).resolve().parent
PROOF = {
    "2009-I-14": "A length-four histogram with nonnegative integer counts encodes exactly a multiset on 1 through 4. Verify the length and weighted first/fourth moments; compute the second moment separately.",
    "2009-II-4": "With m children and winner n, the given step-two progression is nonnegative iff its last count is nonnegative. Its sum is m(n+1-m).",
    "2010-I-14": "Exact decimal digit divisions compute floor(log10(k*n)) for every one of the 100 required positive terms.",
    "2010-II-6": "Both factor degrees must be positive. Integer coefficient convolution in ascending powers must equal the prescribed quartic coefficient vector.",
    "2015-I-8": "Decimal quotient/remainder division computes both required digit sums exactly on n and n+864.",
    "2016-I-12": "Validate positive m, four or more factors, primality of each listed factor, multiplicity and equality of their product.",
    "2020-I-3": "The shared digits must belong to base eight. The leading digit in base eleven must be nonzero. Horner evaluation checks equality, with the fixed leading 1 in base eight.",
    "2020-I-10": "For positive integers, prime valuations characterize the power divisibility. Also verify the coprime sum and the ordinary nondivisibility.",
    "2021-II-13": "Exact modular products test the required expression modulo 1000 at a positive integer index.",
    "2022-II-1": "Integral original adult count, bus occupancy and exact final proportion bind the final number of adults.",
    "2023-I-15": "Verify p prime below the bound, integer norm a^2+b^2, positive real/imaginary cubic components and all strict triangle inequalities.",
}
WEAK_DESCRIPTION = {
    "2009-I-14": "Square and value have the same residue modulo 2, so the second moment is odd.",
    "2009-II-4": "The quadratic in the number of children is at most (n+1)^2/4, which must cover the given total.",
    "2010-I-14": "At n=1000, each term is at least 3 and k=10 already exceeds 3. Monotonicity excludes every larger input.",
    "2010-II-6": "Only the original positive-integer domain is used as the weak control here.",
    "2015-I-8": "Decimal digit sum has the same residue as the original integer modulo 9.",
    "2016-I-12": "The polynomial is odd; four prime factors have product at least 3^4, so m must be at least 9.",
    "2020-I-3": "The base-eight value is at least 512. The three shared digits are at most 7, giving base-eleven value at most 931.",
    "2020-I-10": "The positive sum is at least 2 and coprime to 210 by the original constraints.",
    "2021-II-13": "For positive n the divisibility expression modulo 2 forces n odd.",
    "2022-II-1": "Integrality of the final adult count forces it to be a positive multiple of 11.",
    "2023-I-15": "An odd prime representable as a sum of two squares is 1 modulo 4 by the residues of squares.",
}


def hash_json(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def weak_satisfied(cid: str, n: int) -> bool:
    if cid == "2009-I-14":
        return n % 2 == 1
    if cid == "2009-II-4":
        return n > 0 and (n + 1)**2 >= 4 * 2009
    if cid == "2010-I-14":
        return 1 <= n < 1000
    if cid == "2010-II-6":
        return n > 0
    if cid == "2015-I-8":
        return n > 0 and n % 9 == 2
    if cid == "2016-I-12":
        return n >= 9
    if cid == "2020-I-3":
        return 512 <= n <= 931
    if cid == "2020-I-10":
        return n >= 2 and gcd(n, 210) == 1
    if cid == "2021-II-13":
        return n > 0 and n % 2 == 1
    if cid == "2022-II-1":
        return n > 0 and n % 11 == 0
    if cid == "2023-I-15":
        return 2 <= n < 1000 and (n == 2 or n % 4 == 1)
    raise ValueError(f"Unknown frozen weak control: {cid}")


def contract_record(cohort_row: dict) -> dict:
    cid = cohort_row["case_id"]
    spec = PROBLEMS[cid]
    bound_spec = {key: cohort_row[key] for key in spec}
    if bound_spec != spec:
        raise ValueError(f"Different reviewed objective or constraints for {cid}")
    scope = {key: spec[key] for key in ("direction", "objective_id", "description", "role_patterns")}
    binding = ObjectiveBinding(cohort_row["question_sha256"], spec["objective_id"], hash_json(scope),
                               hash_json({"fields": spec["fields"], "constraints": spec["constraints"], "proof": PROOF[cid]}),
                               spec["direction"])
    note = {"case_id": cid, "question_sha256": binding.question_sha256, "review": "Independent of witness authors",
            "scope": scope, "checker": checker_source_sha256(check), "original_constraints": PROOF[cid]}
    contract = ReviewedContract(binding, tuple(spec["constraints"]), "d45.arithmetic.checker", 1,
                                check.__name__, checker_source_sha256(check),
                                hash_json(PROOF[cid]), hash_json(note))
    return {"case_id": cid, "contract": asdict(contract), "contract_sha256": contract.sha256,
            "scope": scope, "question_only_review": note,
            "weak_necessary": WEAK_DESCRIPTION[cid]}


def reconstruct(record: dict) -> ReviewedContract:
    data = record["contract"]
    contract = ReviewedContract(**{**data, "binding": ObjectiveBinding(**data["binding"]),
                                    "required_constraints": tuple(data["required_constraints"])})
    if record["contract_sha256"] != contract.sha256:
        raise ValueError("Reviewed contract digest changed")
    return contract
