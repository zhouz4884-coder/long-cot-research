"""Replay only the three immutable D4.2 source-review receipts under matched Lean."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter

from causal_cases_prepare import DEFAULT_SCRATCH, ROOT, digest, encode_json, need
from cascade_runtime_probe import (
    CACHE, LEAN_ROOT, PREFIX, PROJECT, TIMEOUT, ResidentLean, clean_env, cold_frame,
    resident_frame, verified_environment,
)


REVIEW_SHA = "35b92fe363277eccfff22ab75825f65857bad0dcda766fee1e1a9664b348db28"
VARIANTS = ("original", "noop", "placebo", "edited")
CASE_IDS = ("p104", "p113", "p41")


def source_inputs(scratch, source_review):
    raw = source_review.read_bytes()
    need(digest(raw) == REVIEW_SHA, "Source-review receipt hash differs")
    review = json.loads(raw)
    need(tuple(review["cases"]) == CASE_IDS, "Unexpected reviewed case set")
    inputs = {}
    for case, row in review["cases"].items():
        need(tuple(row["variants"]) == VARIANTS, "Unexpected variant set")
        contents = {}
        for name, item in row["variants"].items():
            need(item["filename"] == f"{case}_{name}.lean", "Unexpected variant filename")
            data = (scratch / item["filename"]).read_bytes()
            need(digest(data) == item["source_sha256"] and len(data) == item["bytes"], "Variant bytes differ")
            contents[name] = data.decode()
        archived = row["offline_diagnostics"]
        saved = (scratch / archived["filename"]).read_bytes()
        need(digest(saved) == archived["sha256"], "Archived diagnostics differ")
        need(contents["original"] == contents["noop"]
             and len(contents["placebo"].encode()) == len(contents["edited"].encode())
             and contents["placebo"].count("\n") == contents["edited"].count("\n"), "Controls do not match")
        inputs[case] = (row, contents, json.loads(saved))
    return inputs


def canonical(message):
    return re.sub(r"\?m\.\d+", "?m.<id>", message.rstrip())


def family(message):
    if message.startswith(("Function expected at", "Application type mismatch", "Type mismatch")):
        return "TYPE_APPLICATION_OR_CALC"
    if message.startswith(("Tactic `", "omega could not prove")):
        return "TACTIC_PROOF_STEP_FAILURE"
    if message.startswith(("unsolved goals", "Missing cases")):
        return "GOALS_OR_CASES"
    return "OTHER"


def observed_errors(frame, splice, variant):
    repair = splice["original_line"]
    delta = splice["line_delta"] if variant in {"edited", "placebo"} else 0
    for d in frame["diagnostics_in_reporting_order"]:
        if d["severity"] != 1:
            continue
        anchor = d["anchor"]["start"]
        need(anchor is not None, "A real error lacks a source-start anchor")
        current = anchor["line_1_based"]
        if current < repair:
            original = current
        elif current <= repair + delta:
            original = repair
        else:
            original = current - delta
        yield {"reported_index": d["reported_index"], "line": current, "mapped_original_line": original,
               "scalar_column_0_based": anchor["scalar_column_0_based"],
               "utf8_byte_offset": anchor["utf8_byte_offset"], "on_edited_site": original == repair,
               "category": family(d["message"]), "message": canonical(d["message"])}


def signature(d):
    return (d["mapped_original_line"], d["scalar_column_0_based"], d["category"], d["message"])


def raw_axioms(frame, target):
    reports = [d["message"] for d in frame["diagnostics_in_reporting_order"]
               if d["message"].startswith(f"'{target}' ")]
    if len(reports) != 1:
        return None
    if reports[0] == f"'{target}' does not depend on any axioms":
        return []
    report = re.fullmatch(rf"'{re.escape(target)}' depends on axioms:\s*\[([^]]*)\]", reports[0])
    return sorted(v.strip() for v in report[1].split(",") if v.strip()) if report else None


def compare(row, archived, variants):
    splice = row["localized_edit"]
    proof_results = {}
    for name, frame in variants.items():
        errors = list(observed_errors(frame, splice, name))
        warning_count = sum(d["severity"] == 2 for d in frame["diagnostics_in_reporting_order"])
        axioms = raw_axioms(frame, row["target"])
        strict = frame["status"]
        if strict == "KERNEL_ACCEPTED" and warning_count:
            strict = "REJECTED_WARNING"
        proof_results[name] = {"strict_target_status": strict, "warning_count": warning_count,
                               "target_axioms_reported_even_if_rejected": axioms, "errors": errors}

    original, edit = (proof_results[name]["errors"] for name in ("original", "edited"))
    author_messages = [canonical(d["message"]) for d in archived]
    original_keys = [signature(d) for d in original]
    edit_keys = [signature(d) for d in edit]
    dropped = Counter(original_keys) - Counter(edit_keys)
    new = Counter(edit_keys) - Counter(original_keys)
    persistent = Counter(original_keys) & Counter(edit_keys)
    return {
        "original_author_line_and_category_match": [(d["line"], d["category"]) for d in original] ==
        list(zip(row["original_error_lines"], row["original_error_classes"], strict=True)),
        "original_author_canonical_message_match": [d["message"] for d in original] == author_messages,
        "original_author_columns_minus_current_scalar_zero_based": [a["col"] - d["scalar_column_0_based"]
            for a, d in zip(archived, original)] if len(archived) == len(original) else None,
        "original_author_axiom_report_match": proof_results["original"]["target_axioms_reported_even_if_rejected"] ==
        row["author_target_axioms"],
        "identity_noop_preserves_ordered_error_signature": [signature(d) for d in proof_results["noop"]["errors"]]
        == original_keys,
        "matched_whitespace_placebo_preserves_ordered_mapped_error_signature":
        [signature(d) for d in proof_results["placebo"]["errors"]] == original_keys,
        "first_site_removed": bool(original) and any(d["on_edited_site"] for d in original)
        and not any(d["on_edited_site"] for d in edit),
        "removed_original_lines": [key[0] for key in dropped.elements()],
        "persistent_original_lines": [key[0] for key in persistent.elements()],
        "new_mapped_original_lines": [key[0] for key in new.elements()],
        "variants": proof_results,
    }


def run(scratch, source_review):
    inputs = source_inputs(scratch, source_review)
    environment = verified_environment()
    bindir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bindir / "lake.exe"), "env", str(bindir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    resident_runs, cold_runs = {}, {}
    with tempfile.TemporaryDirectory(prefix="d42-reviewed-causal-", dir=CACHE) as temp:
        folder = Path(temp)
        for case, (row, contents, _) in inputs.items():
            resident = ResidentLean(command, PROJECT, TIMEOUT, env=env)
            try:
                path = folder / f"Resident_{case}.lean"
                checks = {name: resident_frame(resident, path, source, [row["target"]])
                          for name, source in contents.items()}
            finally:
                started = perf_counter()
                resident.close()
                shutdown = perf_counter() - started
            resident_runs[case] = {"startup_seconds": resident.startup_seconds, "shutdown_seconds": shutdown,
                                   "checks": checks}
            print(json.dumps({"checkpoint": "resident_closed", "case": case,
                              "errors": {n: x["error_count"] for n, x in checks.items()}}), flush=True)
        for case, (row, contents, _) in inputs.items():
            cold_runs[case] = {name: cold_frame(command, folder / f"Cold_{case}_{name}.lean", source, [row["target"]], env)
                               for name, source in contents.items()}
            print(json.dumps({"checkpoint": "cold_closed", "case": case,
                              "errors": {n: x["error_count"] for n, x in cold_runs[case].items()}}), flush=True)

    cases = {}
    control_flags = ("original_author_line_and_category_match", "original_author_axiom_report_match",
                     "identity_noop_preserves_ordered_error_signature",
                     "matched_whitespace_placebo_preserves_ordered_mapped_error_signature")
    for case, (row, _, archived) in inputs.items():
        resident, cold = (compare(row, archived, frames) for frames in (resident_runs[case]["checks"], cold_runs[case]))
        transports_agree = all([signature(d) for d in resident["variants"][name]["errors"]]
                               == [signature(d) for d in cold["variants"][name]["errors"]]
                               and resident["variants"][name]["strict_target_status"] ==
                               cold["variants"][name]["strict_target_status"] for name in VARIANTS)
        cases[case] = {"target": row["target"], "resident_comparison": resident, "cold_comparison": cold,
                       "transports_agree_on_ordered_mapped_errors_and_strict_status": transports_agree,
                       "control_integrity": transports_agree and all(all(v[key] for key in control_flags)
                                                                     for v in (resident, cold)),
                       "resident_raw": resident_runs[case], "cold_raw": cold_runs[case]}
    return {"status": "PASS_CAUSAL_CONTROL_REPLAY" if all(x["control_integrity"] for x in cases.values())
            else "CAUSAL_CONTROL_REPLAY_DISAGREEMENT", "source_review_sha256": REVIEW_SHA,
            "scope": "Three targeted archive interventions. Control replay status is distinct from proof acceptance.",
            "strict_gate": "Exact target source, zero errors, zero warnings, named approved transitive axioms, and cold exit zero.",
            "diagnostic_identity": "Mapped original line, zero-based Unicode scalar column, category, and message with metavariable ids normalized.",
            "model_generation": False, "gpu_used": False, "environment": environment, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--source-review", type=Path, default=ROOT / "causal_cases_source_receipt.json")
    parser.add_argument("--output", type=Path, default=ROOT / "causal_cases_runtime.json")
    args = parser.parse_args()
    need(not args.output.exists(), "Refuse to overwrite frozen runtime output")
    report = run(args.scratch.resolve(), args.source_review.resolve())
    raw = encode_json(report)
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "sha256": digest(raw),
                      "controls": {case: x["control_integrity"] for case, x in report["cases"].items()}}))
