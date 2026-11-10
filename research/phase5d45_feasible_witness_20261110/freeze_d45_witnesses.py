"""Independently certify question-only proposals and adversarial mutations."""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d45_arithmetic_checker import check
from d45_contracts import contract_record, reconstruct
from feasible_witness import FeasibleWitnessVerifier
from freeze_d45_intake import HERE, load, sha, write_exclusive


def verifier(row: dict, rules: dict) -> FeasibleWitnessVerifier:
    contract = reconstruct(row)
    budget = rules["witness_verification"]
    return FeasibleWitnessVerifier(
        contract, row["contract_sha256"], check,
        call_budget=budget["checker_calls_max_per_arm_per_question"],
        work_budget=budget["named_work_units_max_per_arm_per_question"],
        comparison_budget=budget["comparison_operations_max_per_arm_per_question"],
    )


def check_attempts(row: dict, witnesses: list[dict], rules: dict):
    contract = reconstruct(row)
    engine = verifier(row, rules)
    receipts = [engine.verify(contract.binding, item["witness"]) for item in witnesses]
    valid = [(index, receipt) for index, receipt in enumerate(receipts) if receipt.status == "CERTIFIED_FEASIBLE_BOUND"]
    selected = None
    if valid:
        sign = -1 if contract.binding.direction == "MAX" else 1
        selected = min(valid, key=lambda item: (sign * Fraction(item[1].objective), item[0]))
    return engine, receipts, selected


def adversarial(cid: str, accepted: dict) -> tuple[dict, str]:
    changed = deepcopy(accepted)
    if cid == "2009-I-14":
        changed["counts"][0] -= 1
        changed["counts"][1] += 1
        return changed, "first_moment"
    if cid == "2009-II-4":
        changed["winner"] += 1
        return changed, "total_grapes"
    if cid == "2010-I-14":
        return {"n": 1000}, "complete_floor_log_sum"
    if cid == "2010-II-6":
        changed["n"] += 1
        return changed, "exact_factor_product"
    if cid == "2015-I-8":
        changed["n"] += 1
        return changed, "original_digit_sum"
    if cid == "2016-I-12":
        changed["primes"][0] = 9
        return changed, "prime_factors"
    if cid == "2020-I-3":
        changed["b"] = 8
        return changed, "base_eight_digit_domain"
    if cid == "2020-I-10":
        return {"m": 3, "n": 8}, "power_divisibility"
    if cid == "2021-II-13":
        changed["n"] += 1
        return changed, "residue_zero"
    if cid == "2022-II-1":
        changed["bus_adults"] = (changed["bus_adults"] + 1) % 51
        return changed, "exact_final_adult_ratio"
    if cid == "2023-I-15":
        changed["a"], changed["b"] = -changed["a"], -changed["b"]
        return changed, "positive_cubic_components"
    raise ValueError(f"Unknown adversarial contract: {cid}")


def require_author_bound(cohort: dict, document: dict) -> None:
    if (
        document["question_scope_audit_sha256"] != cohort["scope_audit_sha256"]
        or document["specs_sha256"] != cohort["problem_specs_sha256"]
        or document["source_shard_sha256"] != cohort["source_shards"][0]["sha256"]
    ):
        raise ValueError("Witness author did not use the reviewed question-only source")


def freeze(cohort_path: Path, author_path: Path, strengthened_path: Path, rules_path: Path) -> dict:
    start, cpu = perf_counter_ns(), thread_time_ns()
    cohort, author, reinforced, rules = map(load, (cohort_path, author_path, strengthened_path, rules_path))
    if sha(HERE / "d45_problem_specs.py") != cohort["problem_specs_sha256"]:
        raise ValueError("Reviewed problem specifications changed")
    if sha(HERE / "d45_arithmetic_checker.py") != cohort["checker_sha256"]:
        raise ValueError("Reviewed checker source changed")
    require_author_bound(cohort, author)
    require_author_bound(cohort, reinforced)
    if (
        reinforced["v1_author_sha256"] != sha(author_path)
        or reinforced["cohort_freeze_sha256"] != sha(cohort_path)
        or reinforced["question_only_sha256"] != cohort["question_only_sha256"]
    ):
        raise ValueError("Strengthening did not preserve the original blind handoff")
    initial = {row["case_id"]: row for row in author["rows"]}
    more = {row["case_id"]: row for row in reinforced["rows"]}
    if len(initial) != 11 or set(more) != {"2009-II-4", "2010-I-14", "2016-I-12", "2023-I-15"}:
        raise ValueError("Unexpected proposal policy cohort")
    records = []
    for question in cohort["rows"]:
        cid = question["case_id"]
        reviewed = contract_record(question)
        chosen_proposals = [initial[cid]] + ([more[cid]] if cid in more else [])
        witnessed = []
        reported = []
        for pass_id, proposal in enumerate(chosen_proposals, 1):
            if proposal["question_sha256"] != question["question_sha256"] or proposal["objective_id"] != question["objective_id"]:
                raise ValueError(f"Author used a different target for {cid}")
            attempts = proposal["attempts"]
            if len(attempts) != proposal["paid_attempts"] or (pass_id == 2 and len(attempts) > 2):
                raise ValueError(f"Proposal work did not match the frozen budget for {cid}")
            witnessed.extend({**item, "proposal_pass": pass_id} for item in attempts if item.get("witness") is not None)
            reported.append({
                "proposal_pass": pass_id, "status": proposal["status"],
                "paid_attempts": proposal["paid_attempts"],
                "construction_and_audit_subwork": proposal["construction_and_audit_subwork"],
                "executable_wall_ns": proposal["executable_wall_ns"],
                "executable_cpu_ns": proposal["executable_cpu_ns"],
                "derivation_sha256": sha256(proposal["derivation"].encode()).hexdigest(),
            })
        _, receipts, selected = check_attempts(reviewed, witnessed, rules)
        if selected is None:
            raise ValueError(f"No independently certified proposal on {cid}")
        idx, bound = selected
        mutation, expected = adversarial(cid, witnessed[idx]["witness"])
        other = verifier(reviewed, rules)
        contract = reconstruct(reviewed)
        bad = other.verify(contract.binding, mutation)
        if bad.status != "WITNESS_INFEASIBLE" or dict(bad.constraints).get(expected) is not False:
            raise ValueError(f"Exact negative control did not reject {cid}")
        records.append({
            **reviewed, "author_reported": reported, "verified_attempts": witnessed,
            "independent_witness_receipts": [r.as_dict() for r in receipts],
            "chosen_attempt_index": idx, "best_bound": bound.objective, "bound_direction": bound.bound_direction,
            "adversarial_control": {"witness": mutation, "required_rejected_constraint": expected, "receipt": bad.as_dict()},
        })
    return {
        "status": "D45_PROPOSAL_BOUNDS_INDEPENDENTLY_CERTIFIED_BEFORE_TRACE_AND_GOLD",
        "cohort_freeze_sha256": sha(cohort_path), "author_sha256": sha(author_path), "strengthened_sha256": sha(strengthened_path),
        "rules_sha256": sha(rules_path), "contract_source_sha256": sha(HERE / "d45_contracts.py"),
        "verifier_source_sha256": sha(HERE / "feasible_witness.py"), "rows": records,
        "source_cost_scope": "Executable proposal audits are timed separately; author reading and manual derivation are not instrumented.",
        "wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for option in ("cohort", "author", "strengthened", "rules", "output"):
        cli.add_argument("--" + option, type=Path, required=True)
    args = cli.parse_args()
    result = freeze(args.cohort, args.author, args.strengthened, args.rules)
    write_exclusive(args.output, result)
    print(result["status"], len(result["rows"]), sha(args.output))


if __name__ == "__main__":
    main()
