"""Bind the public statement, replay the observed elaboration failure, and check the fix."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

from run_structural_controls import FOUNDATIONAL_AXIOMS, Kernel, NATIVE_TACTICS, ROOT, certificate_axioms, digest, load


COMMIT = "f0a20e14c1eeccd859d51bb4c2b3ee487889c303"
STATEMENT = "theorem numbertheory_4x3m7y3neq2003 (x y : ℤ) : 4 * x ^ 3 - 7 * y ^ 3 ≠ 2003 := by\n  sorry"
TARGET = "∀ x y : Int, 4 * x ^ 3 - 7 * y ^ 3 ≠ 2003"
EDIT = "    change (4 * x ^ 3 - 7 * y ^ 3) % 7 = (2003 : Int) % 7 at reduced\n"


def download(path):
    url = f"https://raw.githubusercontent.com/google-deepmind/miniF2F/{COMMIT}/{path}"
    with urlopen(Request(url, headers={"User-Agent": "Long-CoT-D38-CPU"}), timeout=20) as response:
        return response.read(), url


def exact_file(exe, source, directory, name):
    path = directory / f"{name}.lean"
    path.write_bytes(source)
    began = time.perf_counter()
    proc = subprocess.run([str(exe), "--json", str(path)], cwd=directory, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=15)
    diagnostics = [{k: v for k, v in json.loads(line).items() if k != "fileName"}
                   for line in proc.stdout.splitlines() if line.strip()]
    axioms = certificate_axioms(proc.stdout)
    return {"source_sha256": digest(source), "exit_code": proc.returncode,
            "axioms": axioms, "kernel_accepted": proc.returncode == 0 and axioms is not None,
            "wall_seconds": time.perf_counter() - began, "diagnostics": diagnostics}


def run(exe, out):
    test, url = download("MiniF2F/Test.lean")
    license_raw, license_url = download("LICENSE")
    if STATEMENT not in test.decode() or "Apache License" not in license_raw.decode():
        raise ValueError("Pinned public theorem or license differs")
    fixed = (ROOT / "competition_residue_control.lean").read_bytes().replace(b"\r\n", b"\n")
    if fixed.count(EDIT.encode()) != 1 or "(x y : Int) : 4 * x ^ 3 - 7 * y ^ 3 ≠ 2003" not in fixed.decode():
        raise ValueError("Declared exact statement or single checked repair differs")
    first = fixed.replace(EDIT.encode(), b"")
    protocol = load("D38_STRUCTURAL_CONTROL_FREEZE.json")
    with tempfile.TemporaryDirectory(prefix="d38_competition_") as scratch:
        directory = Path(scratch)
        rejected = exact_file(exe, first, directory, "first_attempt")
        accepted = exact_file(exe, fixed, directory, "one_line_repair")
        kernel = Kernel(exe, directory, protocol)
        automatic = [kernel.prove(TARGET, [tactic], f"whole_{tactic}") for tactic in NATIVE_TACTICS]
    if rejected["kernel_accepted"] or not any("Tactic `rewrite` failed" in x["data"] for x in rejected["diagnostics"]):
        raise ValueError("Observed first failure did not reproduce")
    if not accepted["kernel_accepted"] or not set(accepted["axioms"]) <= FOUNDATIONAL_AXIOMS:
        raise ValueError("Final exact proof did not pass kernel and axiom checks")
    report = {"status": "PASS", "source": {"commit": COMMIT, "theorem_file": url, "theorem_file_sha256": digest(test),
                                          "license": "Apache-2.0", "license_url": license_url, "license_sha256": digest(license_raw)},
              "scope": "Public competition statement and independently authored proof. The published `sorry` body is never imported. The first failure arose during CPU authoring, not from a model. Only Lean core is loaded, not the official Mathlib build.",
              "statement": TARGET, "first_attempt": rejected, "one_line_repair": accepted,
              "automatic_whole_proof": automatic, "model_tokens": 0, "gpu_seconds": 0}
    with out.open("xb") as f:
        f.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": report["status"], "accepted_axioms": accepted["axioms"],
                      "automatic_status": [r["status"] for r in automatic]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.lean.resolve(), args.output)
