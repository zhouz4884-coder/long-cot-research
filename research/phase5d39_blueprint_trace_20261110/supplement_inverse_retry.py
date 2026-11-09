"""Preserve the p30 warning trial and retry only its redundant final tactic."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter

from author_runtime_setup import clean_env
from measure_p159_replay_cost import FLAGS, check_environment
from supplement_controls import ROOT, digest, json_bytes, need, replace_once, verified_output, write_once


OLD = "    _ = 5 := by rw [h₀] <;> decide"
NEW = "    _ = 5 := by rw [h₀]"


def run(source_dir, lean, lake, project, output):
    first = ROOT / "supplement_runtime_observed.json"
    earlier_raw = first.read_bytes()
    earlier = json.loads(earlier_raw)
    receipt_raw = (ROOT / "supplement_source_receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    need(earlier["source_receipt_sha256"] == digest(receipt_raw), "First trial is not the reviewed result")
    old_name = "supplement_p30_preserved_inverse.lean"
    failed = earlier["results"][old_name]
    base = earlier["results"]["supplement_p30_author_check.lean"]
    need(failed["status"] == "UNVERIFIED" and failed["reason"] == "Lean emitted a warning or error"
         and base["status"] == "VERIFIED", "Expected warning-only trial missing")
    packets = [json.loads(line) for line in failed["stdout"].splitlines() if line.startswith("{")]
    errors = [packet for packet in packets if packet["severity"] == "error"]
    warnings = [packet["kind"] for packet in packets if packet["severity"] == "warning"]
    need(not errors and sorted(warnings) == ["linter.unreachableTactic", "linter.unusedTactic"],
         "The initial unverified trial has other diagnostics")
    old = (source_dir / old_name).read_bytes()
    need(digest(old) == failed["source_sha256"] == receipt["prepared_fixtures"][old_name]["sha256"], "First source differs")
    retry = replace_once(old.decode(), OLD, NEW).encode()
    path = source_dir / "supplement_p30_preserved_inverse_v2.lean"
    write_once(path, retry)
    source_receipt = {"status": "SINGLE_REDUNDANT_TACTIC_REMOVAL", "previous_result_sha256": digest(earlier_raw),
                      "previous_source_sha256": digest(old), "retry_source_sha256": digest(retry),
                      "only_diff": {"old": OLD, "new": NEW}, "old_warnings": warnings}
    write_once(ROOT / "supplement_inverse_retry_source.json", json_bytes(source_receipt))
    inputs = (ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes()
    need(digest(inputs) == receipt["author_inputs_sha256"], "Author runtime input pins changed")
    version = check_environment(lean, lake, project, json.loads(inputs))
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env.get("PATH", "")
    began = perf_counter()
    completed = subprocess.run([str(lake), "env", str(lean), "--json", str(path)], cwd=project, env=env,
                               creationflags=FLAGS, capture_output=True, timeout=120, encoding="utf-8", errors="replace")
    elapsed = perf_counter() - began
    report = {"runtime_version": version, "retry_source_receipt_sha256": digest(json_bytes(source_receipt)),
              "source_sha256": digest(retry), "returncode": completed.returncode, "wall_seconds": elapsed,
              "protected_source_preserved": True, "scope": "One secondary functional check; observed shared-host wall time only."}
    try:
        need(completed.returncode == 0 and not completed.stderr.strip(), "Lean retry did not close cleanly")
        report.update(verified_output(completed.stdout, "p30"))
        need(report["target_type"] == base["target_type"] and report["protected_declaration_actually_used"],
             "Retry changed the target or dropped the expected old proof dependency")
        report["status"] = "PASS"
    except ValueError as err:
        report.update(status="UNVERIFIED", reason=str(err), stdout=completed.stdout, stderr=completed.stderr)
    write_once(output, json_bytes(report))
    print(json.dumps({"status": report["status"], "actual_use": report.get("protected_declaration_actually_used"),
                      "wall_seconds": elapsed}))
    return report["status"] == "PASS"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source-dir", "lean", "lake", "project", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.source_dir.resolve(), args.lean.resolve(), args.lake.resolve(), args.project.resolve(),
                              args.output.resolve()) else 1)
