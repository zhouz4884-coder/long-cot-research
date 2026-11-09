"""Measure recurring decision and receipt overhead on the exact frozen pilot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter_ns, process_time_ns

from freeze_cohort import digest, write_exclusive
from run_selection import bind_reviewed, ordinary_filter, scoped_filter


BLOCKS = 10


def profile(selection: dict, proofs: dict, repeats_per_block: int) -> dict:
    proof_rows = {r["problem_id"]: r for r in proofs["rows"]}
    inputs = []
    for row in selection["rows"]:
        binding, approved = bind_reviewed(proof_rows[row["problem_id"]])
        values = tuple(row["pool"]["inclusive_ranked"])
        expected = row["scoped"]["eliminated"]
        if row["ordinary"]["eliminated"] != expected:
            raise ValueError("Expected identical pilot elimination under approved inputs")
        inputs.append((values, binding, approved, expected))

    def run_block(arm):
        calls = evaluations = 0
        began_wall, began_cpu = perf_counter_ns(), process_time_ns()
        for _ in range(repeats_per_block):
            for values, binding, approved, expected in inputs:
                if arm == "ordinary":
                    result = ordinary_filter(values, approved)
                else:
                    result = scoped_filter(values, binding, approved)
                if result["eliminated"] != expected:
                    raise ValueError("Replayed decision changed")
                calls += result["paid_predicate_calls"]
                evaluations += result["paid_candidate_evaluations"]
        return {
            "wall_ns": perf_counter_ns() - began_wall,
            "process_cpu_ns": process_time_ns() - began_cpu,
            "paid_predicate_calls": calls, "paid_candidate_evaluations": evaluations,
        }

    blocks = []
    for index in range(BLOCKS):
        order = ("ordinary", "scoped") if index % 2 == 0 else ("scoped", "ordinary")
        blocks.append({"order": order, **{arm: run_block(arm) for arm in order}})
    summary = {}
    for arm in ("ordinary", "scoped"):
        measures = [block[arm] for block in blocks]
        summary[arm] = {
            "median_wall_ns_per_full_32_problem_replay": median(r["wall_ns"] for r in measures) / repeats_per_block,
            "median_process_cpu_ns_per_full_32_problem_replay": median(r["process_cpu_ns"] for r in measures) / repeats_per_block,
            "total_paid_predicate_calls": sum(r["paid_predicate_calls"] for r in measures),
            "total_paid_candidate_evaluations": sum(r["paid_candidate_evaluations"] for r in measures),
        }
    return {
        "status": "FROZEN_INPUTS_REPLAYED_WITHOUT_GOLD",
        "scope": "Separate CPU profiling only; no new selection evidence or online budget. Receipt verbosity differs by design.",
        "full_cohort_repeats_per_arm": BLOCKS * repeats_per_block,
        "blocks": blocks, "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection", "proofs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--repeats-per-block", type=int, default=80)
    args = parser.parse_args()
    if args.repeats_per_block < 1:
        parser.error("Repeat count must be positive")
    selection_bytes, proof_bytes = args.selection.read_bytes(), args.proofs.read_bytes()
    selection, proofs = json.loads(selection_bytes), json.loads(proof_bytes)
    if selection["input_sha256"]["proofs"] != digest(proof_bytes):
        raise ValueError("Profile source changed from the frozen selection")
    out = profile(selection, proofs, args.repeats_per_block)
    out["selection_sha256"] = digest(selection_bytes)
    out["proofs_sha256"] = digest(proof_bytes)
    out["profiler_sha256"] = digest(Path(__file__).read_bytes())
    write_exclusive(args.output, out)
    print(out["summary"])


if __name__ == "__main__":
    main()
