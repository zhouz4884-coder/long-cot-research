"""Postscore diagnosis of wrong-side optima and an early target-binding false read."""
from __future__ import annotations

import argparse
from collections import Counter
from math import gcd, isqrt
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d45_arithmetic_checker import floor_log_sum, powmod
from freeze_d45_intake import digest, load, sha, write_exclusive


class Meter:
    def __init__(self):
        self.charges = Counter()

    def charge(self, key: str, n: int = 1) -> None:
        self.charges[key] += n


def audit(results_path: Path, readout_path: Path, blind_path: Path) -> dict:
    begin, cpu = perf_counter_ns(), thread_time_ns()
    result, strict, blind = map(load, (results_path, readout_path, blind_path))
    if strict["blind_input_sha256"] != sha(blind_path):
        raise ValueError("Postscore diagnostic used the wrong raw observations")
    keyed = {row["sample_id"]: row for row in result["blind_scope_sensitivity"]["trace_rows"]}
    claims = {row["sample_id"]: row for row in strict["rows"]}
    texts = {row["sample_id"]: row["response"] for row in blind["rows"]}
    binding_error = "2010-I-14:draw-02"
    sum_wrong = "2020-I-10:draw-03"
    modulus_wrong = "2021-II-13:draw-07"
    wrong = {(row["sample_id"], point) for row in keyed.values() for point, entry in row["points"].items()
             if entry.get("wrong_claim_side") == "MORE_OPTIMISTIC_THAN_OPTIMUM"}
    if wrong != {(binding_error, "early"), (sum_wrong, "late"), (modulus_wrong, "late")}:
        raise ValueError("Unexpected wrong-side observations in the frozen sensitivity block")

    early = claims[binding_error]["early"]
    a, b = early["char_span_in_response"]
    phrase = texts[binding_error][a:b]
    if digest(phrase.encode()) != early["source_excerpt_sha256"] or early["value"] != 300:
        raise ValueError("Early source span changed")
    if "where f(n) <= 300" not in phrase:
        raise ValueError("Expected an objective threshold, not an asserted candidate")
    if keyed[binding_error]["native_status"] != "NATIVE_CORRECT":
        raise ValueError("Unexpected delivery for the binding-error trajectory")
    early_work = Meter()
    early_value_if_wrongly_typed = floor_log_sum(300, early_work)
    assert early_value_if_wrongly_typed > 300

    sum_point = keyed[sum_wrong]["points"]["late"]
    modulo_point = keyed[modulus_wrong]["points"]["late"]
    assert sum_point["value"] == 23 and modulo_point["value"] == 397
    assert sum_point["same_candidate_in_eligible_wrong_native_final"]
    assert modulo_point["same_candidate_in_eligible_wrong_native_final"]
    sum_work = Meter()
    prime = True
    for d in range(2, isqrt(23) + 1):
        sum_work.charge("prime_trial_divisions")
        prime = prime and 23 % d != 0
    feasible_pairs = 0
    for n in range(1, 23):
        m = 23 - n
        sum_work.charge("fixed_sum_pair_attempts")
        modulus = n**n
        sum_work.charge("fixed_sum_modular_pow_calls")
        divisible = pow(m, m, modulus) == 0
        feasible_pairs += gcd(m + n, 210) == 1 and m % n != 0 and divisible
    assert prime and feasible_pairs == 0

    residue_work = Meter()
    a2, a5 = (powmod(base, 397, 1000, residue_work) for base in (2, 5))
    residue = (a2 + a5 - 397) % 1000
    assert (a2, a5, residue) == (672, 125, 400)
    return {
        "status": "POSTSCORE_POINT_DIAGNOSIS_ONLY",
        "results_sha256": sha(results_path), "strict_readout_sha256": sha(readout_path),
        "not_a_preregistered_intervention_or_gate_change": True,
        "early_false_binding": {
            "sample_id": binding_error, "span": early["char_span_in_response"],
            "source_excerpt_sha256": early["source_excerpt_sha256"], "numeric_read": 300,
            "semantic_role": "THRESHOLD_ON_FLOOR_LOG_SUM_NOT_AN_ASSERTED_INPUT",
            "native_delivery_remained_correct": True, "frozen_controls_authorized": False,
            "if_300_were_wrongly_typed_as_input_its_floor_log_sum": early_value_if_wrongly_typed,
            "paid_diagnostic_work": dict(early_work.charges),
        },
        "true_persistent_wrong_candidates": [
            {"sample_id": sum_wrong, "value": 23, "status": "NO_FEASIBLE_PAIR_AT_THIS_SUM",
             "proof": "Any prime dividing n also divides m and therefore divides prime sum 23. Since n<23 this forces n=1, which violates ordinary nondivisibility.",
             "independent_fixed_sum_enumeration_feasible_pairs": feasible_pairs,
             "paid_diagnostic_work": dict(sum_work.charges)},
            {"sample_id": modulus_wrong, "value": 397, "status": "VIOLATES_MODULAR_EQUALITY",
             "residue_two_power": a2, "residue_five_power": a5, "residue_full_expression": residue,
             "paid_diagnostic_work": dict(residue_work.charges)},
        ],
        "wall_ns": perf_counter_ns() - begin, "cpu_ns": thread_time_ns() - cpu,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "readout", "blind", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    result = audit(args.results, args.readout, args.blind)
    write_exclusive(args.output, result)
    print(result["status"], [row["status"] for row in result["true_persistent_wrong_candidates"]])


if __name__ == "__main__":
    main()
