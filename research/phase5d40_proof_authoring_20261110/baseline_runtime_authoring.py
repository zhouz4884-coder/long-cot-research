"""Fixed-action CPU proof authoring baseline for approved immutable source slots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter

from baseline_runtime_probe import (APPLY_LIBRARY, CACHE, EXACT_LIBRARY, HEARTBEATS, LEAN_ROOT, NORMAL, PREFIX, PROJECT,
                                    REQUEST_TIMEOUT_SECONDS, ROOT, SIGNATURE_DVD, WRAPPER_OPTIONS, clean_env,
                                    fill_proof_slot, file_sha, verified_environment)
from lean_resident_probe import ResidentLean, cold_check


CASES = ("p14", "p41", "p138")
SOURCE_RECEIPT = ROOT / "cases_source_receipt.json"
FREEZE = ROOT / "D40_SOURCE_SELECTION_FREEZE.json"
PROTOCOL = ROOT / "baseline_runtime_protocol.json"
SIGS = ("sub_dvd_pow_sub_pow", "Nat.sub_dvd_pow_sub_pow", "Nat.sub_one_dvd_pow_sub_one", "Int.ModEq.dvd",
        "Int.ModEq.pow", "Nat.modEq_iff_dvd'", "Nat.ModEq.pow")
NAT_MODEQ = """refine (Nat.modEq_iff_dvd' ?_).mp ?_
· positivity
· nth_rewrite 1 [← one_pow n]
  apply Nat.ModEq.pow
  norm_num [Nat.ModEq]"""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pinned_text(directory, meta):
    name = meta["name"]
    if Path(name).name != name:
        raise ValueError("Reviewed fixture must have an explicit basename")
    raw = (directory / name).read_bytes()
    if len(raw) != meta["bytes"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
        raise ValueError(f"Reviewed fixture changed: {name}")
    return raw.decode("utf-8")


def fixture(source_case, directory):
    receipt = source_case["local_slot"]
    source = pinned_text(directory, receipt["author_target_slot"])
    absence = pinned_text(directory, receipt["absence"])
    header = source_case["exact_target_header"]
    if digest(header) != source_case["target_header_sha256"] or source.count(header + " := by\n") != 1:
        raise ValueError("Theorem header differs from reviewed slot")
    imports = "".join(f"import {name}\n" for name in source_case["exact_imports"])
    if not source.startswith(imports + "\n") or not absence.startswith(imports + "\n"):
        raise ValueError("Fixture import prelude differs from reviewed scope")
    name, = re.findall(r"(?m)^#check (P\d+Bad\.p\d+_target)$", absence)
    # The common wrapper inserts only checker options and a named axiom query.
    strict = imports + "\n" + WRAPPER_OPTIONS + source[len(imports):] + f"\n#print axioms {name}\n"
    return strict, absence, name, imports


def choices(header):
    methods = [("ExactLibrary", EXACT_LIBRARY), ("ApplyLibrary", APPLY_LIBRARY)]
    methods.extend(("Normal:" + name, name) for name in NORMAL)
    if "∣" in header and "^" in header:
        methods.extend(("Signature:" + name, body) for name, body in SIGNATURE_DVD)
    if "(n : ℕ)" in header:
        if "(h₀ : 0 < n)" in header:
            methods.append(("Signature:NatModEqPower", NAT_MODEQ))
        prologue = "clear h₀\n" if "(h₀ : 0 < n)" in header else ""
        for label, tactic in (("simp_pow", "simp_all [pow_succ]"),
                              ("simp_pow_omega", "simp_all [pow_succ] <;> omega"),
                              ("grind_pow", "grind [pow_succ]")):
            methods.append(("Induction:" + label, prologue + "induction n <;> " + tactic))
    if "Nat.divisors" in header:
        methods.append(("Finite:subst_decide", "subst_vars\ndecide"))
        methods.append(("Finite:subst_norm_num", "subst_vars\nnorm_num"))
    return methods


def audit_absence(row, target):
    errors = [entry["message"] for entry in row["messages"] if entry["severity"] == 1]
    return (row["status"] == "REJECTED" and len(errors) == 1 and target in errors[0]
            and any(needle in errors[0].lower() for needle in ("unknown identifier", "unknown constant")))


def verify_offline(reference_dir, meta, command, env, work):
    name = meta["filename"]
    if name != "p40_author_exact_offline_check.lean" or meta["reference_in_authoring_slots"]:
        raise ValueError("Unexpected offline control or reference leakage")
    path = reference_dir / name
    if file_sha(path) != meta["exact_reviewed_check_sha256"]:
        raise ValueError("Offline p40 reviewed source differs")
    data = path.read_bytes().decode("utf-8")
    names = re.findall(r"(?m)^#print axioms (P40Bad\.[a-z_][a-z_0-9]*)\s*$", data)
    if set(names) != {"P40Bad." + short for short in meta["archived_transitive_axioms"]} or len(names) != 3:
        raise ValueError("Offline control missing one exact named axiom check")
    row = cold_check(command, PROJECT, work / "OfflineP40.lean", data, names, timeout=REQUEST_TIMEOUT_SECONDS, env=env)
    same = {name.split(".")[-1]: sorted(items) for name, items in row["axioms"].items()}
    expected = {name: sorted(items) for name, items in meta["archived_transitive_axioms"].items()}
    return {**row, "matches_archived_axioms": same == expected, "reference_used_for_baseline_generation": False}


def run(slots, reference_dir):
    trusted = json.loads((ROOT / "baseline_runtime_trusted.json").read_bytes())
    if trusted["status"] != "PASS_TRUSTED_CONTROLS":
        raise ValueError("Corrected trusted fixture controls must pass first")
    receipt = json.loads(SOURCE_RECEIPT.read_bytes())
    if receipt["status"] != "ARCHIVE_BOUND_TARGET_SLOTS_ONLY" or receipt["freeze_sha256"] != file_sha(FREEZE):
        raise ValueError("Reviewed sources must bind the fixed selection")
    if receipt["raw_failed_proofs_staged"] or receipt["author_gate_sources_staged"] or slots.resolve() == reference_dir.resolve():
        raise ValueError("Unreviewed source or author proof reference in candidate input scope")
    environment = verified_environment()
    if environment != trusted["environment"]:
        raise ValueError("Pinned runtime differs from the trusted controls")
    material = {name: fixture(receipt["source_cases"][name], slots) for name in CASES}
    out = {}
    bin_dir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bin_dir / "lake.exe"), "env", str(bin_dir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix="d40-approved-baseline-", dir=CACHE) as temp:
        work = Path(temp)
        document = work / "AuthorTarget.lean"
        resident = ResidentLean(command, PROJECT, REQUEST_TIMEOUT_SECONDS, env=env)
        try:
            for case in CASES:
                template, absence_source, target, imports = material[case]
                absence = resident.check(document, absence_source, [])
                if not audit_absence(absence, target):
                    raise ValueError(f"The target absence check failed: {case}")
                header = receipt["source_cases"][case]["exact_target_header"]
                signature_probe = None
                if "∣" in header and "^" in header:
                    checks = imports + "\n" + "\n".join(f"#check {name}" for name in SIGS) + "\n"
                    signature_probe = resident.check(document, checks, [])
                trials = []
                for method, action in choices(header):
                    rendered = fill_proof_slot(template, action)
                    row = resident.check(document, rendered, [target])
                    trials.append({"method": method, "proof_body_sha256": digest(action), **row})
                accepted = [row for row in trials if row["status"] == "KERNEL_ACCEPTED"]
                first = next((index for index, row in enumerate(trials, 1) if row["status"] == "KERNEL_ACCEPTED"), None)
                out[case] = {"target": target, "scope": "Same imports and theorem header; proof body only",
                             "rendered_template_sha256": digest(template), "target_header_sha256": digest(header),
                             "original_imports": receipt["source_cases"][case]["exact_imports"], "absence_control": absence,
                             "signature_availability_probe": signature_probe, "trials": trials,
                             "accepted_actions": [row["method"] for row in accepted],
                             "first_accepted_action": accepted[0]["method"] if accepted else None,
                             "first_accepted_action_ordinal": first,
                             "proof_submission_wall_through_first_accept_seconds":
                                 sum(row["elapsed_seconds"] for row in trials[:first]) if first else None,
                             "all_proof_submission_wall_seconds": sum(row["elapsed_seconds"] for row in trials)}
        finally:
            closing = perf_counter()
            resident.close()
            shutdown = perf_counter() - closing
        elapsed_resident = perf_counter() - started
        offline = verify_offline(reference_dir, receipt["offline_positive_reference"], command, env, work)
    expected_offline = offline["status"] == "KERNEL_ACCEPTED" and offline["matches_archived_axioms"]
    return {"status": "COMPLETE_APPROVED_CPU_BASELINE" if expected_offline else "OFFLINE_CONTROL_DIVERGED",
            "scope": "One fixed resident sequence in the author runtime. No model or GPU. CPU automation acts on exact reviewed proof slots.",
            "source_receipt_sha256": file_sha(SOURCE_RECEIPT), "protocol_sha256": file_sha(PROTOCOL),
            "environment": environment, "max_heartbeats": HEARTBEATS, "resident_startup_seconds": resident.startup_seconds,
            "resident_shutdown_seconds": shutdown, "resident_sequence_total_wall_seconds": elapsed_resident,
            "cases": out, "same_family_p40_separate_offline": offline,
            "case_count": len(out), "cases_with_accepted_action": sum(bool(row["accepted_actions"]) for row in out.values()),
            "new_model_tokens": 0, "gpu_seconds": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("slots", "reference-dir", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.slots, args.reference_dir)
    with args.output.open("xb") as handle:
        handle.write((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"status": result["status"], "accepted": {case: row["accepted_actions"]
                     for case, row in result["cases"].items()}, "offline_p40": result["same_family_p40_separate_offline"]["status"]}))
    raise SystemExit(0 if result["status"].startswith("COMPLETE") else 1)
