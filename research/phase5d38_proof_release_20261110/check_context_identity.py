"""Actual Lean controls for context, goal order and unresolved witness identity."""

import argparse
import json
from pathlib import Path
import tempfile

from run_structural_controls import Kernel, digest, load


def identity(runtime_hash, target, prefix):
    """Conservative exact replay key for the pinned core environment."""
    packet = {"runtime": runtime_hash, "imports": ["Lean"], "target": target, "prefix": prefix}
    return digest(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode())


def run(exe, out):
    protocol = load("D38_STRUCTURAL_CONTROL_FREEZE.json")
    runtime = digest(exe.read_bytes())
    prop_good = "∀ P : Prop, P → P"
    prop_bad = "∀ P : Prop, (¬ P) → P"
    both = "∀ P Q : Prop, P → Q → P ∧ Q"
    witness = "∀ (P : Nat → Prop), P 2 → ∃ n : Nat, P n"
    rows = [
        ("same_surface_valid_context", prop_good, ["intro P h", "trace_state"], ["exact h"], True),
        ("same_surface_wrong_context", prop_bad, ["intro P h", "trace_state"], ["exact h"], False),
        ("ordinary_goal_order", both, ["intro P Q hp hq", "constructor", "trace_state"],
         ["exact hp", "exact hq"], True),
        ("swapped_goal_order", both, ["intro P Q hp hq", "constructor", "rotate_left", "trace_state"],
         ["exact hp", "exact hq"], False),
        ("witness_metavariable_unassigned", witness, ["intro P h", "refine ⟨?_, ?_⟩", "rotate_left", "trace_state"],
         ["exact h"], True),
        ("witness_locked_to_other_value", witness, ["intro P h", "refine ⟨3, ?_⟩", "trace_state"], ["exact h"], False),
    ]
    evidence = []
    with tempfile.TemporaryDirectory(prefix="d38_identity_") as temp:
        kernel = Kernel(exe, Path(temp), protocol)
        for name, target, prefix, suffix, expected in rows:
            checked = kernel.prove(target, prefix + suffix, name)
            matched = checked["status"] == ("KERNEL_ACCEPTED" if expected else "REJECTED")
            if not expected:
                matched = matched and any("Type mismatch" in item.get("data", "") for item in checked["messages"])
            evidence.append({"name": name, "exact_input_identity": identity(runtime, target, prefix),
                             "expected_accepted": expected, "matches": matched, "kernel": checked})
    report = {"status": "PASS" if all(item["matches"] for item in evidence) else "FAIL",
              "scope": "Real kernel source replay for three controlled mismatch pairs. Exact input keys refuse even semantically equivalent but byte-different prefixes; no claim of a general kernel state fingerprint.",
              "all_exact_identities_distinct": len({item["exact_input_identity"] for item in evidence}) == len(evidence),
              "cases": evidence}
    with out.open("xb") as output:
        output.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": report["status"], "results": [(e["name"], e["kernel"]["status"]) for e in evidence]}))
    if report["status"] != "PASS" or not report["all_exact_identities_distinct"]:
        raise SystemExit(1)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lean", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    run(args.lean.resolve(), args.output)
