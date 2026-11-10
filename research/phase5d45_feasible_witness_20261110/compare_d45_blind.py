"""Freeze matched weak, ordinary and feasible-witness decisions before label access."""
from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d45_contracts import reconstruct, weak_satisfied
from freeze_d45_intake import HERE, load, sha, write_exclusive
from freeze_d45_witnesses import check_attempts, verifier


def replay_proposals(row: dict, rules: dict):
    engine, receipts, selected = check_attempts(row, row["verified_attempts"], rules)
    frozen = row["independent_witness_receipts"]
    if len(frozen) != len(receipts) or selected is None:
        raise ValueError("Changed number of independently verified witnesses")
    for actual, expected in zip(receipts, frozen, strict=True):
        if any(actual.as_dict()[key] != expected[key] for key in (
            "status", "work", "objective", "contract_sha256", "witness_sha256", "bound_direction",
        )):
            raise ValueError("Independently verified witness decision changed")
    if selected[0] != row["chosen_attempt_index"] or selected[1].objective != row["best_bound"]:
        raise ValueError("Independent strongest bound changed")
    return engine, selected[1]


def blind_compare(
    cohort_path: Path, claims_path: Path, witness_path: Path, ordinary_path: Path,
    ordinary_freeze_path: Path, rules_path: Path,
) -> dict:
    began, cpu = perf_counter_ns(), thread_time_ns()
    cohort, claims, proof, ordinary, ordinary_freeze, rules = map(
        load, (cohort_path, claims_path, witness_path, ordinary_path, ordinary_freeze_path, rules_path),
    )
    cohort_sha = sha(cohort_path)
    if not (
        claims["status"] == "FROZEN_D45_SCOPED_OBSERVATIONS_WITHOUT_GOLD"
        and claims["cohort_freeze_sha256"] == proof["cohort_freeze_sha256"] == cohort_sha
        and proof["rules_sha256"] == sha(rules_path)
        and proof["contract_source_sha256"] == sha(HERE / "d45_contracts.py")
        and proof["verifier_source_sha256"] == sha(HERE / "feasible_witness.py")
        and ordinary_freeze["ordinary_bounds_sha256"] == sha(ordinary_path)
        and ordinary_freeze["cohort_freeze_sha256"] == ordinary["cohort_freeze_sha256"] == cohort_sha
        and ordinary_freeze["control_source_sha256"] == sha(HERE / "d45_ordinary_controls.py")
    ):
        raise ValueError("Blind comparison inputs did not use the exact prelabel freeze")
    cases = {row["case_id"]: row for row in cohort["rows"]}
    authored = {row["case_id"]: row for row in proof["rows"]}
    ordinary_rows = {row["case_id"]: row for row in ordinary["rows"]}
    if len(cases) != 11 or set(cases) != set(authored) or set(cases) != set(ordinary_rows):
        raise ValueError("Independent question denominator changed")
    engines, records = {}, []
    for cid, question in cases.items():
        review = authored[cid]
        contract = reconstruct(review)
        control = ordinary_rows[cid]
        if (
            question["question_sha256"] != contract.binding.question_sha256
            or control["question_sha256"] != question["question_sha256"]
            or control["objective_id"] != contract.binding.objective_id or control["direction"] != contract.binding.direction
        ):
            raise ValueError("Ordinary construction or author proof used a different question")
        engine, cert = replay_proposals(review, rules)
        ordinary_engine = verifier(review, rules)
        ordinary_cert = None
        if control.get("witness") is not None:
            ordinary_cert = ordinary_engine.verify(contract.binding, control["witness"])
            if ordinary_cert.status != "CERTIFIED_FEASIBLE_BOUND":
                raise ValueError(f"Independent ordinary witness failed exact checking for {cid}")
            if Fraction(control["bound"]) != Fraction(ordinary_cert.objective) or control["bound_direction"] != ordinary_cert.bound_direction:
                raise ValueError(f"Independent ordinary objective differs for {cid}")
        engines[cid] = (contract.binding, engine, cert, ordinary_engine, ordinary_cert)
    by_sample = {sample["sample_id"]: row["case_id"] for row in cohort["rows"] for sample in row["draws"]}
    if len(by_sample) != len(claims["rows"]) or len({row["sample_id"] for row in claims["rows"]}) != 88:
        raise ValueError("Blind observation sample denominator changed")
    weak_calls, weak_cpu = 0, 0
    for row in claims["rows"]:
        cid = row["problem_id"]
        if by_sample[row["sample_id"]] != cid:
            raise ValueError("Blind observation identity changed")
        binding, engine, cert, ordinary_engine, ordinary_cert = engines[cid]
        assessments = {}
        for point in ("early", "late"):
            observation = row[point]
            value = observation["value"]
            if observation["status"] != "EXPLICIT_SCOPED_OPTIMUM" or observation["scope_status"] != "ORIGINAL_REQUESTED_OPTIMUM":
                assessments[point] = {"eligibility": "NO_BOUND_SCOPED_OPTIMUM", "observation_status": observation["status"]}
                continue
            if type(value) is not int:
                assessments[point] = {"eligibility": "NONINTEGER_CLAIM_SEPARATE", "value": value}
                continue
            t = thread_time_ns()
            weak = weak_satisfied(cid, value)
            weak_cpu += thread_time_ns() - t
            weak_calls += 1
            authored_receipt = engine.compare(binding, value, cert)
            ordinary_receipt = ordinary_engine.compare(binding, value, ordinary_cert)
            assessments[point] = {
                "eligibility": "BOUND_INTEGER_OPTIMUM", "value": value,
                "weak_condition_refuted": not weak,
                "ordinary_refuted": ordinary_receipt.status == "REFUTED_OPTIMUM_CLAIM",
                "witness_refuted": authored_receipt.status == "REFUTED_OPTIMUM_CLAIM",
                "ordinary_claim_receipt": ordinary_receipt.as_dict(), "witness_claim_receipt": authored_receipt.as_dict(),
            }
        records.append({"case_id": cid, "sample_id": row["sample_id"], "draw": row["draw_index"],
                        "termination": row["termination"], "native_final_eligible": row["native_final_eligible"],
                        "native_final_value": row["final"]["value"], **assessments})
    return {
        "status": "D45_ALL_MATCHED_COMPARISONS_FROZEN_WITHOUT_GOLD",
        "cohort_freeze_sha256": cohort_sha, "claims_sha256": sha(claims_path), "witness_freeze_sha256": sha(witness_path),
        "ordinary_bounds_sha256": sha(ordinary_path), "ordinary_freeze_sha256": sha(ordinary_freeze_path),
        "rules_sha256": sha(rules_path), "comparison_source_sha256": sha(Path(__file__)),
        "questions": [{"case_id": cid, "witness_bound": cert.objective,
                       "ordinary_bound": ordinary_cert.objective if ordinary_cert else None,
                       "witness_report": engine.report(), "ordinary_report": ordinary_engine.report()}
                      for cid, (_, engine, cert, ordinary_engine, ordinary_cert) in engines.items()],
        "rows": records,
        "work": {"weak_necessary_evaluations": weak_calls, "weak_necessary_cpu_ns": weak_cpu,
                 "wall_ns": perf_counter_ns() - began, "cpu_ns": thread_time_ns() - cpu},
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("cohort", "claims", "witness", "ordinary", "ordinary-freeze", "rules", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    result = blind_compare(args.cohort, args.claims, args.witness, args.ordinary, args.ordinary_freeze, args.rules)
    write_exclusive(args.output, result)
    print(result["status"], len(result["rows"]), sha(args.output))


if __name__ == "__main__":
    main()
