"""Complete unrestricted E15 solver by monotone suffix feasibility."""

import json
import sys
import time

from prepare_d36_checkpoints import ROOT, prepare, write_once

sys.path.append(str(ROOT.parent / "phase5d35_witness_gated_revision_20261109"))
from witness_contract import DIGITS, compile_contract


def minimal_suffix(prefix, length):
    digits = list(prefix)
    steps = 0
    while len(digits) < length:
        digits.append(digits[-1] + digits[-2])
        steps += 1
        if digits[-1] > 9:
            break
    return digits, steps


def solve(question):
    contract = compile_contract(question)
    if contract is None or contract.template_id != DIGITS:
        raise ValueError("Question is outside the exact recurrence contract")
    first_overflow, work = minimal_suffix((1, 0), 20)
    if first_overflow[-1] <= 9:
        raise AssertionError("Expected finite digit length")
    length = len(first_overflow) - 1
    prefix = []
    considered = []
    for position in range(length):
        for digit in range(9, int(position == 0) - 1, -1):
            trial = prefix + [digit]
            if position >= 2 and digit < prefix[-1] + prefix[-2]:
                feasible, completion, spent = False, None, 1
            else:
                partial = trial + [0] if position == 0 else trial
                completion, spent = minimal_suffix(partial, length)
                feasible = len(completion) == length and completion[-1] <= 9
                spent += int(position >= 2)
            work += spent
            considered.append({"prefix": trial, "feasible_completion": feasible, "minimal_completion": completion})
            if feasible:
                prefix.append(digit)
                break
        else:
            raise AssertionError("Previously feasible prefix lost every completion")
    value = int("".join(map(str, prefix)))
    return {"contract_id": contract.contract_id, "question_sha256": contract.question_sha256,
            "scope": "FULL_OBJECTIVE", "value": value, "max_length": length,
            "componentwise_minimum_first_overflow": first_overflow,
            "prefix_trials": considered, "digit_trials": len(considered), "arithmetic_operations": work}


def run():
    prepare()
    packet = json.loads((ROOT / "prepared/early_checkpoint.json").read_bytes())
    question = packet["question"]
    started = time.perf_counter()
    result = solve(question)
    replay_ok = solve(question) == result
    elapsed = time.perf_counter() - started
    previous = json.loads((ROOT / "D36_POINT_BASELINES.json").read_bytes())["separate_unrestricted_solver"]
    if not replay_ok or result["value"] != previous["certified_value"]:
        raise ValueError("Independent complete solver receipts disagree")
    report = {"status": "PASS", "method": "unrestricted_lexicographic_monotone_suffix",
              "certificate": result, "replay_agrees": replay_ok,
              "previous_complete_enumerator_checks": previous["paid_check_count"],
              "previous_complete_enumerator_value": previous["certified_value"],
              "proof": "Every valid sequence dominates the (1,0) minimal recurrence, and cannot extend to its first overflowing digit. For any legal prefix the componentwise minimal suffix fits iff any suffix fits. At maximum length, choose the largest next digit admitting a suffix, preserving the lexicographic optimum by induction.",
              "cpu_seconds_including_replay": elapsed, "model_input_tokens": 0,
              "timing_scope": "This process's two CPU solves, including contract compilation, excludes file I/O."}
    path = ROOT / "D36_DIRECT_SOLVER_COMPARISON.json"
    if path.exists():
        original = json.loads(path.read_bytes())
        if {k: v for k, v in report.items() if k != "cpu_seconds_including_replay"} != {
                k: v for k, v in original.items() if k != "cpu_seconds_including_replay"}:
            raise ValueError("Complete solver result changed on replay")
        return original
    write_once(path, report)
    return report


if __name__ == "__main__":
    result = run()
    print({"status": result["status"], "value": result["certificate"]["value"],
           "digit_trials": result["certificate"]["digit_trials"],
           "arithmetic_operations": result["certificate"]["arithmetic_operations"],
           "cpu_seconds_including_replay": result["cpu_seconds_including_replay"]})
