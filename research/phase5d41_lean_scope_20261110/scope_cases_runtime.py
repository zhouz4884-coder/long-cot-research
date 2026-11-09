"""Run only frozen authored or reviewed archive scope fixtures on the pinned Lean runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import perf_counter

from scope_cases_prepare import ROOT, digest, need, save


D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
sys.path.insert(0, str(D39))
from lean_resident_probe import ResidentLean
from p159_run_reviewed import PROJECT, RUNTIME, verify_runtime


AUTHOR_SHA = "5bd1a17503ca3a48adb9ff2cedf53c9736c47fb813700556b7677dadfb2a06bf"
ARCHIVE_SHA = "2aa6fa45043b01000813f3c70a16a86a64b3da9a023681c3f4dc603ea0a73f38"
NAIVE_PROBES = {
    "p14": {"h": ["local_hypothesis"], "localZero": ["let_alias"],
            "_root_.Nat.d41_scope_no_such_lemma": ["fq_missing_fallback", "comment_not_term"],
            "_root_.Nat.add_zero": []},
    "p41": {"scopedZero": ["opened_alias"], "d41zero": ["local_notation_alias"],
            "n.succ": ["dot_notation"], "default": []},
}


def read_frozen(path, expected):
    raw = path.read_bytes()
    need(digest(raw) == expected, "Fixture receipt is outside the reviewed exact-byte set")
    return json.loads(raw)


def frozen_fixture(path, row):
    raw = path.read_bytes()
    need(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "Fixture bytes differ")
    return raw.decode()


def environment():
    smoke_raw = (D39 / "author_runtime_smoke.json").read_bytes()
    pins = verify_runtime(RUNTIME.resolve(), PROJECT.resolve(), smoke_raw)
    bin_dir = RUNTIME.resolve() / "bin"
    command = [str(bin_dir / "lake.exe"), "env", str(bin_dir / "lean.exe")]
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "HF_TOKEN",
                                "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"}}
    env.update({"PATH": str(bin_dir) + os.pathsep + env["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    return command, env, pins, digest(smoke_raw)


def kernel_class(checked):
    if checked["status"] == "KERNEL_ACCEPTED":
        return "PROVED"
    errors = [row["message"].lower() for row in checked["messages"] if row["severity"] == 1]
    tests = (
        (("expected token", "unexpected token"), "SYNTAX_ERROR"),
        (("function expected", "type mismatch", "application type mismatch"), "FUNCTION_OR_TYPE_ERROR"),
        (("failed to synthesize instance", "failed to synthesize"), "INSTANCE_SYNTHESIS"),
        (("unknown identifier", "unknown constant"), "UNKNOWN_IDENTIFIER"),
        (("unsolved goals",), "UNSOLVED_GOALS"),
    )
    for anchors, label in tests:
        if any(any(mark in msg for mark in anchors) for msg in errors):
            return label
    return checked["status"]


def with_resident(command, env, work, action):
    resident = ResidentLean(command, PROJECT.resolve(), 120, env=env)
    try:
        rows = action(resident, work)
    finally:
        shutdown_start = perf_counter()
        resident.close()
        shutdown = perf_counter() - shutdown_start
    return {**rows, "resident_startup_seconds": resident.startup_seconds, "resident_shutdown_seconds": shutdown,
            "resident_stderr": resident.stderr_excerpt.replace(str(work.parent), "<scratch>").replace(str(PROJECT), "<project>")}


def authored(input_file, scratch, output):
    freeze = read_frozen(input_file, AUTHOR_SHA)
    command, env, pins, smoke_sha = environment()
    expected = {}
    for row in freeze["cases"]:
        path = scratch / row["filename"]
        text = frozen_fixture(path, {"sha256": row["fixture_sha256"], "bytes": row["fixture_bytes"]})
        need(text == row["complete_source"], "Exact authored fixture differs from frozen text")
        expected[row["id"]] = row
    checks = {}
    with tempfile.TemporaryDirectory(prefix="d41-authored-runtime-") as temp:
        for context in ("p14", "p41"):
            members = [row for row in freeze["cases"] if row["original_import_scope"] == context]
            imports = members[0]["exact_imports"]
            need(all(row["exact_imports"] == imports for row in members), "Authored scope drift")
            prefix = "".join(f"import {name}\n" for name in imports) + "\nnamespace D41ScopeCases\n\n"
            queries = tuple(NAIVE_PROBES[context])
            text = prefix + "".join(f"#check {name}\n" for name in queries) + "\nend D41ScopeCases\n"
            line_to_name = {prefix.count("\n") + 1 + idx: name for idx, name in enumerate(queries)}

            def action(resident, doc):
                probe = resident.check(doc, text, [])
                absent = sorted({line_to_name[e["line"]] for e in probe["messages"] if e["line"] in line_to_name
                                 and e["severity"] == 1 and re.search("unknown (?:identifier|constant)", e["message"], re.I)})
                outcomes = []
                for row in members:
                    target = "D41ScopeCases." + row["decl"]
                    answer = resident.check(doc, row["complete_source"], [target])
                    need(answer["source_sha256"] == row["fixture_sha256"], "Resident checked wrong version")
                    label = kernel_class(answer)
                    outcomes.append({"id": row["id"], "expected": row["expected_kernel_class"], "observed": label,
                                     "expected_match": row["expected_kernel_class"] == label,
                                     "scope_policy": row["authorized_preflight"], **answer})
                examples = {case_id for name in absent for case_id in NAIVE_PROBES[context][name]}
                false_import_only = [row["id"] for row in outcomes if row["id"] in examples and row["observed"] == "PROVED"]
                return {"imports": imports, "import_only_probe": probe, "import_only_absent_examples": absent,
                        "would_be_false_rejections_if_import_only_test_were_a_hard_gate": false_import_only,
                        "rows": outcomes}

            checks[context] = with_resident(command, env, Path(temp) / f"{context}.lean", action)
    flat = [row for context in checks.values() for row in context["rows"]]
    report = {"status": "AUTHORED_SCOPE_CONTROL_KERNEL_RECOUNT_COMPLETED", "scope": "Functional authored controls, not a cost comparison or model result. Import-only probes intentionally omit local binding context.",
              "controls_sha256": AUTHOR_SHA, "runtime_smoke_sha256": smoke_sha, "author_pins": pins,
              "controls": len(flat), "kernel_accepted": sum(row["observed"] == "PROVED" for row in flat),
              "all_expected_matches": sum(row["expected_match"] for row in flat), "contexts": checks,
              "model_generation": False, "gpu_seconds": 0}
    print(json.dumps({"status": report["status"], "sha256": save(output, report),
                      "kernel_accepted": report["kernel_accepted"], "matches": report["all_expected_matches"]}))


def supplement(input_file, scratch, output):
    freeze = read_frozen(input_file, ARCHIVE_SHA)
    command, env, pins, smoke_sha = environment()
    for row in freeze["cases"].values():
        need(row["author_pins"] == pins, "Supplement author scope differs")
        for name, entry in row["prepared_fixtures"].items():
            frozen_fixture(scratch / name, entry)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="d41-supplement-runtime-") as temp:
        for case, row in freeze["cases"].items():
            namespace = case.upper() + "Bad"
            prefix = "".join(f"import {m}\n" for m in row["exact_imports"])
            warm = prefix + f"\nnamespace {namespace}\n\n#check Nat\n\nend {namespace}\n"

            def action(resident, doc):
                barrier = resident.check(doc, warm, [])
                need(not any(m["severity"] == 1 for m in barrier["messages"]), "Common prelude did not load")
                results = {"warm_scope_barrier": barrier}
                for name, entry in row["prepared_fixtures"].items():
                    text = frozen_fixture(scratch / name, entry)
                    targets = [row["qualified_target"]] if name.endswith("_negative.lean") else []
                    result = resident.check(doc, text, targets)
                    need(result["source_sha256"] == entry["sha256"], "Resident checked wrong supplement")
                    results[name] = result
                return {"scope_review": row["source_scope_review"], "results": results,
                        "estimated_hard_skip_or_speedup": False}

            checks[case] = with_resident(command, env, Path(temp) / f"{case}.lean", action)
    report = {"status": "HISTORICAL_SUPPLEMENT_NEGATIVE_AND_QUERY_CHECKS_COMPLETED", "scope": "Per-case same loaded import prefix. p104/p139 exact ordinary archived negatives and relative/root queries; p115 queries only. Negative-only, conditional measurements.",
              "supplement_sha256": ARCHIVE_SHA, "runtime_smoke_sha256": smoke_sha,
              "author_pins": pins, "cases": checks, "model_generation": False, "gpu_seconds": 0}
    print(json.dumps({"status": report["status"], "sha256": save(output, report)}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("authored", "supplement"))
    cli.add_argument("--scratch", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--input", type=Path)
    opts = cli.parse_args()
    if opts.mode == "authored":
        authored(opts.input or ROOT / "scope_cases_controls.json", opts.scratch.resolve(), opts.output)
    else:
        supplement(opts.input or ROOT / "scope_cases_historical_supplement.json", opts.scratch.resolve(), opts.output)
