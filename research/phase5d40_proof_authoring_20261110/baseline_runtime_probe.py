"""Revalidate the D39 Lean runtime and run fixed, safe D40 automation controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter


ROOT = Path(__file__).resolve().parent
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
sys.path.insert(0, str(D39))

from author_runtime_setup import CACHE, LEAN_ROOT, PREFIX, PROJECT, REPO, clean_env, fetch_sources, file_sha, verify_toolchain
from author_runtime_verify import cached_files
from lean_resident_probe import ResidentLean


TARGET = "D40BaselineRuntime.target"
HEARTBEATS = 200_000
REQUEST_TIMEOUT_SECONDS = 120
PROOF_SLOT = "  d40_slot\n"
WRAPPER_OPTIONS = f"set_option warningAsError true\nset_option maxHeartbeats {HEARTBEATS}\n"
NORMAL = ("assumption", "rfl", "simp_all", "norm_num", "omega", "ring", "linarith", "nlinarith",
          "decide", "solve_by_elim", "aesop", "grind")
SIGNATURE_DVD = (
    ("RingSubDvdPowSubPow", "refine dvd_trans ?_ (sub_dvd_pow_sub_pow _ _ _)\nnorm_num"),
    ("NatSubDvdPowSubPow", "refine dvd_trans ?_ (Nat.sub_dvd_pow_sub_pow _ _ _)\nnorm_num"),
    ("NatSubOneDvdPowSubOne", "refine dvd_trans ?_ (Nat.sub_one_dvd_pow_sub_one _ _)\nnorm_num"),
    ("IntModEqPower", "apply Int.ModEq.dvd\napply Int.ModEq.pow\nnorm_num [Int.ModEq]"),
)
EXACT_LIBRARY = "exact?"
APPLY_LIBRARY = "apply?"


def indented(body):
    return "\n".join("  " + line for line in body.splitlines()) + "\n"


def fill_proof_slot(source, body):
    if source.splitlines().count(PROOF_SLOT.rstrip("\n")) != 1:
        raise ValueError("A reviewed proof source must contain one exact marker line")
    return source.replace(PROOF_SLOT, indented(body))


def controls():
    nat = ("(n : Nat) : n + 0 = n", "∀ n : Nat, n + 0 = n")
    trans = ("(a b c : Nat) (h₁ : a ≤ b) (h₂ : b ≤ c) : a ≤ c", "∀ a b c : Nat, a ≤ b → b ≤ c → a ≤ c")
    integer = ("(n : Nat) : (13 : Int) ∣ (11 : Int) ^ n - (-2 : Int) ^ n",
               "∀ n : Nat, (13 : Int) ∣ (11 : Int) ^ n - (-2 : Int) ^ n")
    natural = ("(n : Nat) : 4 ∣ (5 : Nat) ^ n - 1", "∀ n : Nat, 4 ∣ (5 : Nat) ^ n - 1")
    finite = (": (24 : Nat).divisors.card = 8", "(24 : Nat).divisors.card = 8")
    return (
        ("trusted_positive", nat, "exact Nat.add_zero n", "KERNEL_ACCEPTED"),
        ("wrong_body", nat, "exact True.intro", "REJECTED"),
        ("resident_positive_again", nat, "exact Nat.add_zero n", "KERNEL_ACCEPTED"),
        ("admitted_body", nat, "sorry", "REJECTED"),
        ("exact_library", trans, EXACT_LIBRARY, "KERNEL_ACCEPTED"),
        ("apply_library", trans, APPLY_LIBRARY, "KERNEL_ACCEPTED"),
        ("generic_signature_int", integer, SIGNATURE_DVD[0][1], "KERNEL_ACCEPTED"),
        ("generic_signature_nat", natural, SIGNATURE_DVD[2][1], "KERNEL_ACCEPTED"),
        ("finite_ground", finite, "decide", "KERNEL_ACCEPTED"),
    )


def trusted_source(header, expected):
    return ("import Architect\nimport Mathlib\n\n" + WRAPPER_OPTIONS + "\nnamespace D40BaselineRuntime\n"
            f"theorem target {header} := by\n" + PROOF_SLOT + "end D40BaselineRuntime\n\n"
            f"example : {expected} := {TARGET}\n#print axioms {TARGET}\n")


def verified_environment():
    smoke = json.loads((D39 / "author_runtime_smoke.json").read_bytes())
    if not PROJECT.is_dir() or not (PROJECT.parent / "source.git").is_dir() or not CACHE.is_dir():
        raise ValueError("Preserved author environment is absent; no implicit recovery requested")
    for name in smoke["sources"]["packages"]:
        if not (PROJECT / ".lake/packages" / name / ".git").is_dir():
            raise ValueError(f"Preserved package checkout missing: {name}")
    runtime = verify_toolchain()
    source = fetch_sources()
    if (smoke["status"] != "PASS_MATCHED_AUTHOR_IMPORT_POSITIVE" or runtime != smoke["runtime"]
            or any(source[key] != smoke["sources"][key] for key in source if key != "setup_wall_seconds")):
        raise ValueError("Preserved D39 toolchain or checked source differs")
    for name, check in smoke["built_imports"].items():
        p = PROJECT / name
        if p.stat().st_size != check["bytes"] or file_sha(p) != check["sha256"]:
            raise ValueError(f"Preserved import artifact changed: {name}")
    cache = cached_files()
    if cache != smoke["cache"]:
        raise ValueError("Preserved packed Mathlib cache differs")
    return {"d39_smoke_sha256": file_sha(D39 / "author_runtime_smoke.json"),
            "d39_resident_source_sha256": file_sha(D39 / "lean_resident_probe.py"),
            "lean": runtime["runtime"], "lake": runtime["lake"],
            "lean_sha256": runtime["runtime_files_sha256"]["bin/lean.exe"],
            "lake_sha256": runtime["runtime_files_sha256"]["bin/lake.exe"],
            "cwd": PROJECT.relative_to(REPO).as_posix(), "source": source["author"],
            "package_commits": {name: value["commit"] for name, value in source["packages"].items()},
            "built_imports": smoke["built_imports"], "cache": cache}


def resident_controls():
    started = perf_counter()
    environment = verified_environment()
    recheck_wall_seconds = perf_counter() - started
    bin_dir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bin_dir / "lake.exe"), "env", str(bin_dir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    output = []
    with tempfile.TemporaryDirectory(prefix="d40-trusted-baseline-", dir=CACHE) as work:
        document = Path(work) / "TrustedBaseline.lean"
        resident = ResidentLean(command, PROJECT, REQUEST_TIMEOUT_SECONDS, env=env)
        try:
            for case, (header, expected_type), body, expected in controls():
                template = trusted_source(header, expected_type)
                source = fill_proof_slot(template, body)
                row = resident.check(document, source, [TARGET])
                output.append({"case": case, "expected": expected,
                               "immutable_template_sha256": hashlib.sha256(template.encode()).hexdigest(),
                               "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                               "match": row["status"] == expected, **row})
        finally:
            start_close = perf_counter()
            resident.close()
            close_wall_seconds = perf_counter() - start_close
    return {"status": "PASS_TRUSTED_CONTROLS" if all(row["match"] for row in output) else "FAIL_TRUSTED_CONTROLS",
            "scope": "Fixed trusted new CPU fixtures. No author replay, unresolved theorem, model code or GPU.",
            "environment": environment, "recheck_wall_seconds": recheck_wall_seconds,
            "resident_startup_seconds": resident.startup_seconds, "resident_shutdown_seconds": close_wall_seconds,
            "resident_wall_seconds": resident.startup_seconds + close_wall_seconds + sum(row["elapsed_seconds"] for row in output),
            "max_heartbeats": HEARTBEATS, "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS, "controls": output}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = resident_controls()
    with args.output.open("xb") as handle:
        handle.write((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"status": result["status"], "controls": [(row["case"], row["status"]) for row in result["controls"]]}))
    raise SystemExit(0 if result["status"].startswith("PASS") else 1)
