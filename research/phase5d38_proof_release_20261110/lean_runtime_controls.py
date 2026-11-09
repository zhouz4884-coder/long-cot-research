"""Exercise only fixed trusted positive and adversarial Lean release controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter

from lean_runtime_install import ARCHIVE, PREFIX, REPO, ROOT, SHA256, URL, VERSION, file_sha, verify_required


COMMIT = "db93fe1608548721853390a10cd40580fe7d22ae"
FIXTURES = {
    "kernel_positive": """import Lean
set_option warningAsError true
theorem releaseTarget (n : Nat) : n + 0 = n := by
  exact Nat.add_zero n
#print axioms releaseTarget
""",
    "sorry_default": """import Lean
theorem releaseTarget : False := by
  sorry
#print axioms releaseTarget
""",
    "sorry_strict": """import Lean
set_option warningAsError true
theorem releaseTarget : False := by
  sorry
#print axioms releaseTarget
""",
    "indirect_sorry": """import Lean
theorem incompleteHelper : False := by
  sorry
theorem releaseTarget : False := incompleteHelper
#print axioms releaseTarget
""",
    "admit_strict": """import Lean
set_option warningAsError true
theorem releaseTarget : False := by
  admit
#print axioms releaseTarget
""",
    "custom_axiom": """import Lean
set_option warningAsError true
axiom fakeEvidence : False
theorem releaseTarget : False := fakeEvidence
#print axioms releaseTarget
""",
    "fake_statement_unbound": """import Lean
set_option warningAsError true
theorem releaseTarget : True := by
  trivial
#print axioms releaseTarget
""",
    "fake_statement_bound": """import Lean
set_option warningAsError true
theorem releaseTarget : True := by
  trivial
theorem requiredTarget : ∀ n : Nat, n + 0 = n := releaseTarget
#print axioms requiredTarget
""",
    "wrong_proof_bound": """import Lean
set_option warningAsError true
theorem releaseTarget (n : Nat) : n + 0 = n := by
  exact True.intro
#print axioms releaseTarget
""",
}


def run(argv, cwd):
    env = {key: val for key, val in os.environ.items()
           if key.upper() not in {"LEAN_PATH", "LEAN_SRC_PATH", "LEAN_SYSROOT"}}
    began = perf_counter()
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=45, check=False)
    return {"arguments": [Path(argv[0]).name, *argv[1:]], "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr, "wall_seconds": perf_counter() - began}


def controls(root):
    root = root.resolve()
    runtime = root / PREFIX
    lean, lake = runtime / "bin/lean.exe", runtime / "bin/lake.exe"
    if file_sha(root / ARCHIVE) != SHA256:
        raise ValueError("Control runtime archive differs from official release digest")
    files = verify_required(runtime)
    lean_version = run([str(lean), "--version"], runtime)
    lake_version = run([str(lake), "--version"], runtime)
    prefix = run([str(lean), "--print-prefix"], runtime)
    if (lean_version["exit_code"] != 0 or f"version {VERSION}" not in lean_version["stdout"]
            or COMMIT not in lean_version["stdout"] or lake_version["exit_code"] != 0
            or prefix["exit_code"] != 0 or Path(prefix["stdout"].strip()).resolve() != runtime):
        raise ValueError("Lean executable version or inferred sysroot differs from pinned release")
    # Publish a workspace-relative prefix without modifying the recorded check.
    prefix["stdout"] = runtime.relative_to(REPO).as_posix() + "\n"
    rows = {}
    with tempfile.TemporaryDirectory(prefix="d38-lean-controls-", dir=root) as directory:
        work = Path(directory)
        for name, source in FIXTURES.items():
            filename = name + ".lean"
            (work / filename).write_bytes(source.encode("utf-8"))
            result = run([str(lean), "--json", filename], work)
            rows[name] = {"source_sha256": hashlib.sha256(source.encode()).hexdigest(), **result}
    out = lambda name: rows[name]["stdout"] + rows[name]["stderr"]
    code = lambda name: rows[name]["exit_code"]
    expected = {
        "kernel_positive": code("kernel_positive") == 0 and "does not depend on any axioms" in out("kernel_positive"),
        "sorry_default": code("sorry_default") == 0 and "uses 'sorry'" in out("sorry_default") and "[sorryAx]" in out("sorry_default"),
        "sorry_strict": code("sorry_strict") != 0 and "uses 'sorry'" in out("sorry_strict"),
        "indirect_sorry": code("indirect_sorry") == 0 and "releaseTarget' depends on axioms: [sorryAx]" in out("indirect_sorry"),
        "admit_strict": code("admit_strict") != 0 and "uses 'sorry'" in out("admit_strict"),
        "custom_axiom": code("custom_axiom") == 0 and "[fakeEvidence]" in out("custom_axiom"),
        "fake_statement_unbound": code("fake_statement_unbound") == 0 and "does not depend on any axioms" in out("fake_statement_unbound"),
        "fake_statement_bound": code("fake_statement_bound") != 0 and "type mismatch" in out("fake_statement_bound").lower(),
        "wrong_proof_bound": code("wrong_proof_bound") != 0 and "type mismatch" in out("wrong_proof_bound").lower(),
    }
    for key, passed in expected.items():
        rows[key]["expected_behavior_observed"] = passed
    return {"status": "PASS" if all(expected.values()) else "FAIL", "scope": "Fixed trusted CPU fixtures, no Mathlib or model proof submitted.",
            "artifact": {"url": URL, "sha256": SHA256, "bytes": (root / ARCHIVE).stat().st_size},
            "runtime_files_sha256": files,
            "version": lean_version, "lake_version": lake_version, "prefix_check": prefix,
            "passed": sum(expected.values()), "total": len(expected), "controls": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = controls(args.root)
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    if args.output:
        with args.output.open("xb") as target:
            target.write(raw)
    print(json.dumps({"status": data["status"], "controls": {name: row["expected_behavior_observed"]
                     for name, row in data["controls"].items()}}))
    return 0 if data["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
