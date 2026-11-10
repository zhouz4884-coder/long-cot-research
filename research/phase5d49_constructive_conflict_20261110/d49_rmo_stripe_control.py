"""Audit the direct periodic stripe identified by the independent RMO solver."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter_ns, process_time_ns
import json

from d49_rmo_knight import CASE_ID, COHORT_SHA, HERE, N, ROOT, check_timed, digest, neighbors, require, write_once


DISCOVERY_SHA = "131734c6c62c969b6078d637d82f1da91de924bea312121a3d0ff5a08fc00d66"


def label(row, col):
    return (col + (row + 1) // 3) % 2


def main():
    original = (HERE / "D49_RMO_KNIGHT_ORDINARY.json").read_bytes()
    require(digest(original) == DISCOVERY_SHA, "Independent construction discovery receipt differs")
    prior = json.loads(original)
    witness_path = ROOT / "outputs/d49_rmo_knight_20261110/ordinary_witnesses.json"
    witness_raw = witness_path.read_bytes()
    require(digest(witness_raw) == prior["private_witness_sha256"], "Private RMO witness hash differs")
    witness = json.loads(witness_raw)
    wall, cpu = perf_counter_ns(), process_time_ns()
    grid = [[int(row % 3 == 1)] * N for row in range(N)]
    construction_cost = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    require(witness["witnesses"][0]["grid"] == grid, "Direct stripe does not reproduce the exact solver witness")
    wall, cpu = perf_counter_ns(), process_time_ns()
    endpoints = label(N - 1, 0), label(0, N - 1)
    paid_white_edges = 0
    for row in range(N):
        for col in range(N):
            if grid[row][col]:
                continue
            for rr, cc in neighbors((row, col), N):
                if (row, col) < (rr, cc) and not grid[rr][cc]:
                    require(label(row, col) == label(rr, cc), "White knight edge breaks the invariant")
                    paid_white_edges += 1
    require(endpoints[0] != endpoints[1], "Endpoints have the same invariant")
    invariant_cost = {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}
    checked, cost = check_timed(grid)
    require(checked["valid"], "Independent full checker rejects the direct stripe")
    output = {
        "status": "D49_RMO_DIRECT_STRIPE_CONSTRUCTION_VERIFIED",
        "case_id": CASE_ID, "cohort_sha256": COHORT_SHA,
        "question_sha256": prior["question_sha256"], "instruction_sha256": prior["instruction_sha256"],
        "independent_solver_discovery_receipt_sha256": DISCOVERY_SHA,
        "same_local_witness_sha256": prior["private_witness_sha256"],
        "ordinary_stripe_code_sha256": digest(Path(__file__).read_bytes()),
        "construction_cost": construction_cost, "invariant_audit_cost": invariant_cost,
        "independent_full_check_cost": cost, "white_knight_edges_checked_for_invariance": paid_white_edges,
        "independent_full_check": checked,
        "proof": "Paint exactly rows of index 1 mod 3. A length-three diagonal uses three consecutive rows, "
                 "so it contains one black cell. White-to-white knight moves of row length one keep "
                 "floor((row+1)/3) and column parity. Moves of row length two change both parities. "
                 "Thus (column+floor((row+1)/3)) mod 2 is invariant on every white knight path. "
                 "The two fixed white corners have different invariants.",
        "boundary": "The direct rule was identified from our question-only CP-SAT witness. Its executable cost "
                    "is separate from the charged discovery run. Neither method used author references or code.",
    }
    sha = write_once(HERE / "D49_RMO_STRIPE_CONTROL.json", output)
    print("D49 RMO direct stripe receipt", sha, "checked_white_edges", paid_white_edges)


if __name__ == "__main__":
    main()
