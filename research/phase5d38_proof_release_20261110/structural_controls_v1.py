"""Kernel-checked structural repair controls under a common finite verifier budget."""

import argparse
from dataclasses import dataclass
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent
FOUNDATIONAL_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
NATIVE_TACTICS = ("exact?", "omega", "grind", "simp_all", "decide")
IDENTITY = "∀ z : Nat, z + 0 = z"
IDENTITY_PROOF = "by intro z; exact Nat.add_zero z"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name):
    return json.loads((ROOT / name).read_bytes())


def certificate_axioms(output):
    if "does not depend on any axioms" in output:
        return []
    found = re.search(r"depends on axioms:\s*\[([^]]*)\]", output)
    if found:
        names = [value.strip() for value in found[1].split(",") if value.strip()]
        return names if set(names) <= FOUNDATIONAL_AXIOMS else None
    return None


@dataclass(frozen=True)
class Control:
    id: str
    limit: int
    formula: str
    old: tuple[int, int]
    xs: tuple[int, ...]
    ys: tuple[int, ...]
    draft: str

    @property
    def target(self):
        return f"∃ x y : Nat, x ≤ {self.limit} ∧ y ≤ {self.limit} ∧ ({self.formula}) ∧ ({IDENTITY})"

    def prefix(self, pair):
        x, y = pair
        return [f"have identity : {IDENTITY} := {IDENTITY_PROOF}",
                f"let x : Nat := {x}", f"let y : Nat := {y}",
                f"have hx : x ≤ {self.limit} := by decide", f"have hy : y ≤ {self.limit} := by decide"]

    def patch(self, pair, tactic="decide"):
        return self.prefix(pair) + ["refine ⟨x, y, hx, hy, ?_, identity⟩", tactic]

    def rebuilt(self, pair):
        x, y = pair
        return [f"exact ⟨{x}, {y}, by decide, by decide, by decide, {IDENTITY_PROOF}⟩"]

    def fixed_target(self, keep):
        clauses = [f"x ≤ {self.limit}", f"y ≤ {self.limit}", f"({self.formula})"]
        clauses.extend(f"{('x', 'y')[i]} = {self.old[i]}" for i in keep)
        return "¬ (∃ x y : Nat, " + " ∧ ".join(clauses) + ")"

    def fixed_refutation(self, keep):
        vars_ = ["x", "y", "hx", "hy", "hClaim"] + [f"fixed{('X', 'Y')[i]}" for i in keep]
        body = ["intro candidate", "rcases candidate with ⟨" + ", ".join(vars_) + "⟩"]
        body.extend("subst " + ("x", "y")[i] for i in keep)
        body.append("first | (omega; done) | (simp_all; done) | (grind; done)")
        return body

    def support(self):
        return product(self.xs, self.ys)


class Kernel:
    def __init__(self, exe, directory, protocol):
        self.exe = exe
        self.directory = directory
        self.timeout = protocol["process_timeout_seconds"]
        self.heartbeats = protocol["heartbeat_limit"]
        self.records = []

    def prove(self, target, tactics, stage):
        source = (f"import Lean\nset_option autoImplicit false\nset_option warningAsError true\n"
                  f"set_option maxHeartbeats {self.heartbeats}\n"
                  f"theorem d38_obligation : {target} := by\n"
                  + "\n".join("  " + line for line in tactics)
                  + "\n#print axioms d38_obligation\n")
        path = self.directory / f"obligation_{len(self.records):04d}.lean"
        path.write_bytes(source.encode())
        began = time.perf_counter()
        try:
            completed = subprocess.run([str(self.exe), "--json", str(path)], cwd=self.directory,
                                       capture_output=True, encoding="utf-8", errors="replace", timeout=self.timeout)
            status = "REJECTED"
            lines = []
            for line in completed.stdout.splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    lines.append({"raw": line.replace(str(self.directory), "$CASE_DIR")})
                    continue
                if isinstance(item, dict):
                    lines.append({k: v for k, v in item.items() if k != "fileName"})
            axioms = certificate_axioms(completed.stdout)
            if completed.returncode == 0 and axioms is not None:
                status = "KERNEL_ACCEPTED"
            elif completed.returncode == 0:
                status = "AXIOM_AUDIT_NOT_ACCEPTED"
            elif not any(item.get("severity") == "error" for item in lines):
                status = "PROCESS_OR_ENVIRONMENT_ERROR"
            if any("maximum number of heartbeats" in str(item.get("data", "")) for item in lines):
                status = "HEARTBEAT_LIMIT"
            stderr = completed.stderr.replace(str(self.directory), "$CASE_DIR")
        except subprocess.TimeoutExpired:
            status, axioms, lines, stderr = "TIMEOUT", None, [], ""
        row = {"stage": stage, "status": status, "wall_seconds": time.perf_counter() - began,
               "input_sha256": digest(source.encode()), "source": source, "accepted_axioms": axioms,
               "messages": lines, "stderr": stderr}
        self.records.append(row)
        return row


class Arm:
    def __init__(self, kernel, control, budget):
        self.kernel = kernel
        self.case = control
        self.budget = budget
        self.start = len(kernel.records)
        self.found = None
        self.release = None
        self.scopes = []

    def check(self, tactics, stage, target=None):
        if len(self.kernel.records) - self.start >= self.budget:
            return None
        return self.kernel.prove(self.case.target if target is None else target, tactics, stage)

    def accept(self, trial, pair, release):
        if trial is not None and trial["status"] == "KERNEL_ACCEPTED":
            self.found = trial
            self.release = release
            self.pair = pair
            return True
        return False

    def result(self):
        ledger = self.kernel.records[self.start:]
        return {"accepted": self.found is not None, "accepted_source_sha256": self.found["input_sha256"] if self.found else None,
                "witness_in_shared_support": getattr(self, "pair", None), "released_slots": self.release,
                "verified_prefix_cells_preserved": (0 if self.release == "FULL_REBUILD" else 5 - 2 * len(self.release))
                if self.found else None,
                "calls": len(ledger), "total_seconds": sum(row["wall_seconds"] for row in ledger),
                "first_certificate_seconds": sum(row["wall_seconds"] for row in ledger) if self.found else None,
                "scopes": self.scopes, "verifier_calls": ledger}


def automation(arm):
    for tactic in NATIVE_TACTICS:
        trial = arm.check([tactic], f"automatic_{tactic}")
        if arm.accept(trial, None, "FULL_REBUILD"):
            break


def whole_rebuild(arm):
    for pair in arm.case.support():
        trial = arm.check(arm.case.rebuilt(pair), "whole_proposal")
        if trial is None or arm.accept(trial, pair, "FULL_REBUILD"):
            break


def single_failed_step(arm):
    for tactic in NATIVE_TACTICS:
        trial = arm.check(arm.case.patch(arm.case.old, tactic), f"single_step_{tactic}")
        if arm.accept(trial, arm.case.old, ()):
            break


def repair_search(arm, certify):
    examined = set()
    case = arm.case
    proven_smaller = True
    for release in ((), (1,), (0,), (0, 1)):
        keep = tuple(i for i in range(2) if i not in release)
        scope = {"release": release, "keep": keep, "status": "UNEXPLORED", "kernel_refutation": None}
        arm.scopes.append(scope)
        if certify and keep:
            refuted = arm.check(case.fixed_refutation(keep), "prove_no_extension_with_locks", case.fixed_target(keep))
            if refuted is None:
                scope["status"] = "VERIFIER_BUDGET"
                return
            scope["kernel_refutation"] = refuted["status"]
            if refuted["status"] == "KERNEL_ACCEPTED":
                scope["status"] = "FIXED_SCOPE_CONTRADICTION"
                continue
        if not certify:
            # The first rejected source offset belongs to the final obligation. Start there,
            # then try edits to the most recent binding before releasing the full local block.
            scope["diagnostic_order"] = "final_step_then_last_binding_then_earlier_binding"
        prior_smaller = [r for r in arm.scopes if len(r["release"]) < len(release)]
        proven_smaller = all(r["status"] == "FIXED_SCOPE_CONTRADICTION" for r in prior_smaller)
        for pair in case.support():
            if pair in examined or any(pair[i] != case.old[i] for i in keep):
                continue
            examined.add(pair)
            actual = tuple(i for i in range(2) if pair[i] != case.old[i])
            trial = arm.check(case.patch(pair), "recheck_remaining_proof")
            if trial is None:
                scope["status"] = "VERIFIER_BUDGET"
                return
            if arm.accept(trial, pair, actual):
                scope["status"] = "KERNEL_ACCEPTED"
                scope["minimal_release_certified"] = certify and proven_smaller
                return
        scope["status"] = "FINITE_SUPPORT_NO_CERTIFICATE"


METHODS = {"automation": automation, "whole_rebuild": whole_rebuild, "single_failed_step": single_failed_step,
           "diagnostic_local": lambda arm: repair_search(arm, False), "scoped_release": lambda arm: repair_search(arm, True)}


def run(exe, output):
    protocol = load("D38_STRUCTURAL_CONTROL_FREEZE.json")
    version = subprocess.check_output([str(exe), "--version"], text=True, encoding="utf-8").strip()
    if f"version {protocol['lean_version']}" not in version:
        raise ValueError(f"Unexpected Lean toolchain: {version}")
    fixtures = load("D38_CONTROL_OFFLINE_WITNESSES.json")["ground_witnesses"]
    with tempfile.TemporaryDirectory(prefix="d38_lean_") as directory:
        kernel = Kernel(exe, Path(directory), protocol)
        rows = []
        for raw in protocol["cases"]:
            case = Control(**{key: tuple(value) if isinstance(value, list) else value for key, value in raw.items()})
            truth = kernel.prove(case.target, case.rebuilt(fixtures[case.id]), "offline_truth_only")
            prefix = kernel.prove("True", case.prefix(case.old) + ["exact True.intro"], "verify_protected_prefix")
            draft = kernel.prove(case.target, case.patch(case.old, case.draft), "verify_original_failure")
            if truth["status"] != "KERNEL_ACCEPTED" or prefix["status"] != "KERNEL_ACCEPTED" or draft["status"] != "REJECTED":
                raise ValueError(f"Invalid fixture {case.id}: {truth['status']}, {prefix['status']}, {draft['status']}")
            arms = {}
            for method in protocol["arms"]:
                arm = Arm(kernel, case, protocol["verifier_calls_per_arm"])
                METHODS[method](arm)
                arms[method] = arm.result()
            rows.append({"case": case.id, "target": case.target, "dependencies": {"hx": ["x"], "hy": ["y"],
                        "identity": [], "terminal": ["x", "y", "hx", "hy", "identity"]},
                         "offline_witness": truth, "protected_prefix": prefix, "original_rejected_draft": draft, "arms": arms})
            print(case.id, {name: (arm["accepted"], arm["calls"]) for name, arm in arms.items()}, flush=True)
    report = {"status": "COMPLETE_SYNTHETIC_CPU_MATRIX", "lean_version": version, "lean_exe_sha256": digest(exe.read_bytes()),
              "input_freeze_sha256": digest((ROOT / "D38_STRUCTURAL_CONTROL_FREEZE.json").read_bytes()),
              "natural_model_failure_cases": 0, "synthetic_control_count": len(rows), "model_tokens": 0, "gpu_seconds": 0,
              "rows": rows}
    with output.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.lean.resolve(), args.output)
