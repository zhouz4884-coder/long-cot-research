"""One separately frozen p113 implementation correction, no proof strategy change."""

import argparse
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter

from cascade_runtime_actions import P113_PLAIN
from cascade_runtime_ordinary import SOURCE_RECEIPT, SOURCE_SHA256, load_case, render
from cascade_runtime_probe import (CACHE, LEAN_ROOT, PREFIX, PROJECT, ROOT, ResidentLean, clean_env, cold_frame, digest,
                                   edit_span, resident_frame, verified_environment)


MATRIX = ROOT / "cascade_runtime_ordinary.json"
MATRIX_SHA256 = "333a58de1ff690aa7a11deaaaeaa503dcf827904cd3605caa188d85f485e3eb4"
FREEZE = ROOT / "cascade_runtime_plain_correction_freeze.json"
REDUNDANT = ("    change (3 : ℕ) ^ ((2 : ℕ) ^ ((k + 1) + 1)) =\n"
             "      1 + (2 : ℕ) ^ ((k + 1) + 3) * (2 * (t + 2 ^ (k + 1) * (2 * t + 1) ^ 2) + 1)\n")


def inputs(slots):
    raw, source = MATRIX.read_bytes(), SOURCE_RECEIPT.read_bytes()
    if digest(raw) != MATRIX_SHA256 or digest(source) != SOURCE_SHA256 or P113_PLAIN.count(REDUNDANT) != 1:
        raise ValueError("Original ordinary result or approved p113 proof material differs")
    matrix = json.loads(raw)
    case = load_case("p113", json.loads(source)["cases"]["p113"], slots)
    original = render(case, P113_PLAIN)
    cold = matrix["cases"]["p113"]["cold_plain"]
    warm, = (r for r in matrix["cases"]["p113"]["resident"] if r["action"] == "plain_whole_slot")
    for row in (warm, cold):
        if row["source_sha256"] != digest(original) or row["status"] != "REJECTED" or row["error_count"] != 1:
            raise ValueError("Expected the one frozen p113 proof rejection in both transports")
        error, = (x for x in row["diagnostics_in_reporting_order"] if x["severity"] == 1)
        if "`set_option linter.unusedTactic false`" not in error["message"] or "change" not in error["message"]:
            raise ValueError("The diagnostic does not identify the intended redundant change")
    corrected_body = P113_PLAIN.replace(REDUNDANT, "", 1)
    corrected = render(case, corrected_body)
    freeze = {"status": "FROZEN_SINGLE_P113_IMPLEMENTATION_CORRECTION", "original_matrix_sha256": MATRIX_SHA256,
              "approved_source_receipt_sha256": SOURCE_SHA256, "original_source_sha256": digest(original),
              "corrected_source_sha256": digest(corrected), "corrected_body_sha256": digest(corrected_body),
              "edits": edit_span(original, corrected), "target_header_sha256": case["target_header_sha256"],
              "imports": case["imports"], "reason": "Remove only the type-equivalent change rejected by strict unusedTactic lint."}
    return case, corrected, freeze


def run(slots):
    case, source, plan = inputs(slots)
    if json.loads(FREEZE.read_bytes()) != plan:
        raise ValueError("Correction differs from its own pre-run freeze")
    runtime = verified_environment()
    bindir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bindir / "lake.exe"), "env", str(bindir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    with tempfile.TemporaryDirectory(prefix="d42-p113-correction-", dir=CACHE) as temp:
        folder = Path(temp)
        server = ResidentLean(command, PROJECT, 120, env=env)
        try:
            path = folder / "ResidentP113.lean"
            prelude = "".join(f"import {name}\n" for name in case["imports"]) + "\n#check True.intro\n"
            warmup = resident_frame(server, path, prelude, [])
            warm = resident_frame(server, path, source, [case["target"]])
        finally:
            start_close = perf_counter()
            server.close()
            close = perf_counter() - start_close
        cold = cold_frame(command, folder / "ColdP113.lean", source, [case["target"]], env)
    passed = warm["status"] == cold["status"] == "KERNEL_ACCEPTED" and warm["axioms"] == cold["axioms"]
    return {"status": "PASS_SINGLE_ORDINARY_CORRECTION" if passed else "FAIL_SINGLE_ORDINARY_CORRECTION",
            "scope": "Same trusted target and ordinary proof, separate from the immutable first matrix. No archived code or model.",
            "freeze_sha256": digest(FREEZE.read_bytes()), "runtime": runtime, "resident_startup_seconds": server.startup_seconds,
            "resident_warmup": warmup, "resident_shutdown_seconds": close, "resident": warm, "cold": cold}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--slots", type=Path, required=True)
    cli.add_argument("--prepare", action="store_true")
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    if args.prepare:
        _, _, plan = inputs(args.slots)
        with FREEZE.open("xb") as stream:
            stream.write((json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode())
        print(digest(FREEZE.read_bytes()))
    else:
        if args.output is None:
            cli.error("--output is required for execution")
        result = run(args.slots)
        with args.output.open("xb") as stream:
            stream.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        print(result["status"])
        raise SystemExit(0 if result["status"].startswith("PASS") else 1)
