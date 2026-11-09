"""Strong CPU baseline with the same preserved cells and exact minimum certificate."""

import argparse
from itertools import product
import json
from pathlib import Path
import tempfile
import time

from run_structural_controls import ARITHMETIC, Control, Kernel, digest, load


def select(case, domain):
    predicate = ARITHMETIC[case.formula]
    ordered = sorted(domain, key=lambda pair: (sum(x != old for x, old in zip(pair, case.old)), pair))
    for checked, pair in enumerate(ordered, 1):
        if all(0 <= x <= case.limit for x in pair) and predicate(*pair):
            return pair, checked
    return None, len(ordered)


def conjunction(case, chosen):
    release = tuple(i for i in range(2) if chosen[i] != case.old[i])
    smaller = [keep for keep in ((0, 1), (0,), (1,)) if 2 - len(keep) < len(release)]
    statements = [case.target] + [case.fixed_target(keep) for keep in smaller]
    proofs = [case.patch(chosen)] + [case.fixed_refutation(keep) for keep in smaller]
    if not smaller:
        return release, smaller, case.target, proofs[0]
    tactics = ["refine ⟨" + ", ".join("?_" for _ in proofs) + "⟩"]
    for proof in proofs:
        tactics.append("· " + proof[0])
        tactics.extend("  " + line for line in proof[1:])
    target = " ∧ ".join(f"({part})" for part in statements)
    return release, smaller, target, tactics


def run(exe, destination):
    protocol = load("D38_STRUCTURAL_CONTROL_FREEZE.json")
    rows = []
    with tempfile.TemporaryDirectory(prefix="d38_batched_") as temp:
        kernel = Kernel(exe, Path(temp), protocol)
        for raw in protocol["cases"]:
            case = Control(**{key: tuple(value) if isinstance(value, list) else value for key, value in raw.items()})
            for mode in ("matched_finite_support", "whole_bounded_domain"):
                start = time.perf_counter()
                domain = case.support() if mode == "matched_finite_support" else product(range(case.limit + 1), repeat=2)
                chosen, checked = select(case, domain)
                record = {"case": case.id, "scope": mode, "candidate": chosen, "arithmetic_candidates_checked": checked}
                if chosen is None:
                    record.update(status="FINITE_SUPPORT_NO_CERTIFICATE", lean_calls=0)
                else:
                    release, smaller, target, tactics = conjunction(case, chosen)
                    proof = kernel.prove(target, tactics, f"bundle_{case.id}_{mode}")
                    if proof["status"] != "KERNEL_ACCEPTED":
                        raise ValueError(f"{case.id} has no kernel-checked bundled certificate: {proof['messages']}")
                    record.update(status="KERNEL_ACCEPTED", lean_calls=1, released_slots=release,
                                  independently_refuted_smaller_lock_sets=smaller, kernel=proof)
                record["end_to_end_seconds"] = time.perf_counter() - start
                rows.append(record)
    report = {"status": "PASS", "scope": "Exact arithmetic baseline over the same finite controls. All returned witnesses and all smaller protection-set contradictions are checked in one Lean kernel invocation. Full bounded domain and the shared proposal set stay separate. No claim of support exhaustion beyond the named domain.",
              "input_freeze_sha256": digest(Path(__file__).with_name("D38_STRUCTURAL_CONTROL_FREEZE.json").read_bytes()),
              "gpu_seconds": 0, "rows": rows}
    with destination.open("xb") as out:
        out.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": report["status"], "accepted": {mode: sum(r["scope"] == mode and r["status"] == "KERNEL_ACCEPTED" for r in rows)
                                                              for mode in ("matched_finite_support", "whole_bounded_domain")}}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lean", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    run(args.lean.resolve(), args.output)
