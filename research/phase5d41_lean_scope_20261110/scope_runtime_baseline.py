"""Timed, trusted explicit-global-name controls in the preserved Lean runtime."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import perf_counter


ROOT = Path(__file__).resolve().parent
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
sys.path.insert(0, str(D40))
from baseline_runtime_probe import CACHE, LEAN_ROOT, PREFIX, PROJECT, clean_env, verified_environment
from lean_resident_probe import ResidentLean, cold_check, proof_scope


TIMEOUT = 120
MODES = ("proof", "check", "environment")
SCOPES = ("p14", "p41")
ABSENT = {"p14": "sub_dvd_pow_sub_pow", "p41": "Nat.sub_one_dvd_pow_sub_one"}
FABRICATED = "D41ScopeRuntimeMissing.pinnedNeedle"
ALLOWED_BROADEN = ["Mathlib.Algebra.Ring.GeomSum", "Mathlib.Data.Int.ModEq", "Mathlib.Data.Nat.ModEq"]


def digest(data):
    return sha256(data).hexdigest()


def load_inputs():
    freeze = ROOT / "D41_SCOPE_INPUT_FREEZE.json"
    protocol = ROOT / "D41_REPLAY_AND_COST_PROTOCOL.json"
    control_freeze = ROOT / "scope_runtime_freeze.json"
    data = json.loads(freeze.read_bytes())
    allowlist = json.loads(protocol.read_bytes())["additional_import_upper_bound_only"]
    if allowlist != ALLOWED_BROADEN or data["status"] != "FROZEN_BEFORE_NEW_SCOPE_PROBES":
        raise ValueError("Exact context or visibility-only permission differs from the freeze")
    receipt = (D40 / "baseline_runtime_approved.json").read_bytes()
    if digest(receipt) != data["source_receipts_sha256"]["runtime"]:
        raise ValueError("Previously published narrow-scope evidence differs")
    locked = json.loads(receipt)["cases"]
    for scope in SCOPES:
        if data["prior_scope_negatives"][scope]["original_imports"] != locked[scope]["original_imports"]:
            raise ValueError("Original import list differs from D4.0")
    return data["prior_scope_negatives"], allowlist, {"input_freeze": digest(freeze.read_bytes()),
                                                       "replay_cost_protocol": digest(protocol.read_bytes()),
                                                       "trusted_control_freeze": digest(control_freeze.read_bytes())}


def fixed_cases(scope):
    def name_probe(case, name):
        return {"id": case, "name": name, "visibility": "ABSENT", "expected_proof": "UNKNOWN_NAME",
                "type": ": True", "proof": f"  have _h := @{name}\n  exact True.intro"}

    return [
        {"id": "visible_valid", "name": "Nat.add_zero", "visibility": "PRESENT", "expected_proof": "PROVED",
         "type": "(n : Nat) : n + 0 = n", "proof": "  exact Nat.add_zero n"},
        {"id": "visible_wrong_type", "name": "Nat.add_zero", "visibility": "PRESENT", "expected_proof": "TYPE_MISMATCH",
         "type": ": True", "proof": "  exact Nat.add_zero 0"},
        {"id": "visible_open_obligations", "name": "Nat.le_trans", "visibility": "PRESENT",
         "expected_proof": "UNSOLVED_GOALS", "type": "(a b : Nat) : a ≤ b", "proof": "  apply Nat.le_trans"},
        name_probe("known_library_absent_here", ABSENT[scope]), name_probe("fabricated_name", FABRICATED),
    ]


def prelude(imports):
    return "".join(f"import {module}\n" for module in imports) + "\nset_option warningAsError true\n\n"


def block(mode, case):
    name = case["name"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.']*", name):
        raise ValueError("Only fixed explicit global declaration names are accepted")
    if mode == "check":
        return f"#check @{name}\n", []
    if mode == "environment":
        return ("open Lean in\nrun_cmd do\n  let env ← getEnv\n"
                f"  let existsInScope := (env.find? `{name}).isSome\n"
                f'  logInfo m!"D41_EXACT_KEY {name} {{existsInScope}}"\n'), []
    target = "d41_scope_" + case["id"]
    return f"theorem {target} {case['type']} := by\n{case['proof']}\n#print axioms {target}\n", [target]


def source_for(imports, requests):
    text, rows = prelude(imports), []
    for mode, case in requests:
        body, targets = block(mode, case)
        first = text.count("\n") + 1
        rows.append({"mode": mode, "case": case, "targets": targets, "first": first,
                     "last": first + body.count("\n") - 1})
        text += body + "\n"
    return text, rows


def classify(block_meta, messages):
    mode, case = block_meta["mode"], block_meta["case"]
    errors = [item["message"].lower() for item in messages if item["severity"] == 1]
    unknown = any(any(token in error for token in ("unknown identifier", "unknown constant")) for error in errors)
    if mode == "proof":
        closed = proof_scope(messages, block_meta["targets"])
        if closed["status"] == "KERNEL_ACCEPTED":
            return "PROVED"
        if unknown:
            return "UNKNOWN_NAME"
        if any("type mismatch" in error for error in errors):
            return "TYPE_MISMATCH"
        if any("unsolved goals" in error for error in errors):
            return "UNSOLVED_GOALS"
        return "OTHER_PROOF_FAILURE"
    if mode == "check":
        if unknown:
            return "ABSENT"
        return "PRESENT" if not errors and any(item["severity"] == 3 for item in messages) else "QUERY_ERROR"
    prefix = "D41_EXACT_KEY " + case["name"] + " "
    outcomes = [m["message"].removeprefix(prefix) for m in messages if m["message"].startswith(prefix)]
    if errors or outcomes not in (["true"], ["false"]):
        return "QUERY_ERROR"
    return "PRESENT" if outcomes == ["true"] else "ABSENT"


def interpreted(meta, row):
    messages = [item for item in row["messages"]
                if item["line"] is not None and meta["first"] <= item["line"] <= meta["last"]]
    expected = meta["case"]["expected_proof"] if meta["mode"] == "proof" else meta["case"]["visibility"]
    result = classify(meta, messages)
    return {"case": meta["case"]["id"], "name": meta["case"]["name"], "mode": meta["mode"],
            "status": result, "expected": expected, "match": result == expected, "messages": messages}


def run_batch(command, env, folder, scope, imports, mode, cases):
    source, blocks = source_for(imports, [(mode, case) for case in cases])
    path = folder / f"batch_{scope}_{mode}.lean"
    raw = cold_check(command, PROJECT, path, source, [], timeout=TIMEOUT, env=env)
    covered = {n for m in blocks for n in range(m["first"], m["last"] + 1)}
    errors_outside = [m for m in raw["messages"] if m["severity"] == 1 and m["line"] not in covered]
    return {"batch_elapsed_seconds": raw["elapsed_seconds"], "exit_code": raw["exit_code"],
            "source_sha256": raw["source_sha256"], "errors_outside_blocks": errors_outside,
            "cases": [interpreted(m, raw) for m in blocks]}


def run_resident(command, env, path, imports, cases):
    resident = ResidentLean(command, PROJECT, TIMEOUT, env=env)
    rows = []
    try:
        # Separate import startup from the marginal request costs of all three arms.
        anchor = prelude(imports) + "#check @Nat.add_zero\n"
        prewarm = resident.check(path, anchor, [])
        for index, case in enumerate(cases):
            modes = MODES[index % len(MODES):] + MODES[:index % len(MODES)]
            for mode in modes:
                source, (meta,) = source_for(imports, [(mode, case)])
                raw = resident.check(path, source, meta["targets"])
                result = interpreted(meta, raw)
                rows.append({**result, "elapsed_seconds": raw["elapsed_seconds"], "source_sha256": raw["source_sha256"],
                             "matching_publications": raw["matching_publications"], "document_version": raw["document_version"]})
    finally:
        closing = perf_counter()
        resident.close()
        close_elapsed = perf_counter() - closing
    return {"startup_seconds": resident.startup_seconds, "prewarm": prewarm, "shutdown_seconds": close_elapsed,
            "cases": rows, "marginal_request_wall_seconds_by_mode":
                {mode: sum(r["elapsed_seconds"] for r in rows if r["mode"] == mode) for mode in MODES}}


def broad_cases(scope_meta):
    names = list(scope_meta["names_rejected_in_original_imports"]) + [FABRICATED]
    return [{"id": f"visibility_{i}", "name": name, "visibility": "ABSENT" if name == FABRICATED else "PRESENT"}
            for i, name in enumerate(names, 1)]


def run(smoke):
    scopes, allowlist, material_hashes = load_inputs()
    start = perf_counter()
    environment = verified_environment()
    preparation = perf_counter() - start
    bin_dir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bin_dir / "lake.exe"), "env", str(bin_dir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    results, broader = {}, {}
    with tempfile.TemporaryDirectory(prefix="d41-fixed-runtime-", dir=CACHE) as temp:
        folder = Path(temp)
        for scope in SCOPES[:1] if smoke else SCOPES:
            imports = scopes[scope]["original_imports"]
            cases = fixed_cases(scope)
            resident = run_resident(command, env, folder / f"resident_{scope}.lean", imports, cases)
            print(json.dumps({"checkpoint": scope, "resident_cases_closed": len(resident["cases"])}), flush=True)
            item = {"original_imports": imports, "trusted_fixture_definition": cases, "resident": resident}
            if not smoke:
                cold = []
                for case in cases:
                    source, (meta,) = source_for(imports, [("proof", case)])
                    raw = cold_check(command, PROJECT, folder / f"cold_{scope}_{case['id']}.lean", source, meta["targets"],
                                     timeout=TIMEOUT, env=env)
                    cold.append({**interpreted(meta, raw), "elapsed_seconds": raw["elapsed_seconds"],
                                 "exit_code": raw["exit_code"], "source_sha256": raw["source_sha256"]})
                item["cold_single_proof"] = cold
                item["batch"] = {mode: run_batch(command, env, folder, scope, imports, mode, cases) for mode in MODES}
                print(json.dumps({"checkpoint": scope, "original_cold_single": len(cold), "original_batches": len(item["batch"])}), flush=True)
                visible = broad_cases(scopes[scope])
                wider = imports + allowlist
                broader[scope] = {"imports": wider, "visibility_only": True,
                                  "batch": {mode: run_batch(command, env, folder, scope + "_broader", wider, mode, visible)
                                            for mode in ("check", "environment")}}
            results[scope] = item
    output_rows = [row for item in results.values() for row in item["resident"]["cases"]]
    output_rows.extend(row for item in results.values() for row in item.get("cold_single_proof", []))
    batches = [batch for item in results.values() for batch in item.get("batch", {}).values()]
    batches.extend(batch for item in broader.values() for batch in item["batch"].values())
    output_rows.extend(row for batch in batches for row in batch["cases"])
    passed = all(row["match"] for row in output_rows) and all(not batch["errors_outside_blocks"] for batch in batches)
    return {"status": "PASS_TRUSTED_RUNTIME" if passed else "FAIL_TRUSTED_RUNTIME", "smoke": smoke,
            "scope": "CPU trusted explicit-name controls only. No raw author proofs, model, or GPU.",
            "material_hashes": material_hashes, "environment": environment, "preparation_seconds": preparation,
            "controls": len(output_rows), "matched": sum(row["match"] for row in output_rows),
            "original_imports": results, "broader_visibility_only": broader}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = run(args.smoke)
    with args.output.open("xb") as handle:
        handle.write((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({key: data[key] for key in ("status", "smoke", "controls", "matched")}))
    raise SystemExit(0 if data["status"].startswith("PASS") else 1)
