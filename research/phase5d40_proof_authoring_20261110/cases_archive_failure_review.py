"""Bind, review, and optionally replay exact author .check.lean negatives offline."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import tarfile

from cases_source_review import ARCHIVES, CASES, D39, DEEPSEEK, QWEN, ROOT, default_archive, digest, need, published, read_member

sys.path.insert(0, str(D39))
from p159_run_reviewed import PROJECT, RUNTIME, invoke, verify_runtime


# Entire bytes of these three files were separately reviewed after deterministic selection.
REVIEWED = {
    "p14": ("data/llm_calls/p14_monolithic_toolsrc_v0/typed/step02.check.lean",
            "85df13c04b2d38bacfb4faa15b0f5322564f38f8a9167931428066c883722335"),
    "p41": ("data/llm_calls/p41_monolithic_toolsrc_v0/typed/step01.check.lean",
            "1fd1e6b5451f5e83328a64dc7b5c213f73e7badd29309157a3d4ca01b7488e00"),
    "p138": ("data/llm_calls/p138_monolithic_toolsrc_v0/typed/step01.check.lean",
             "21ab05366f842aee1c357f318fc3fe9d4d30a0af057078adf33c156250ab1628"),
}
REVIEW_RECEIPT_SHA = "f3be83588b932129259564fc6bcd222685a85a3c50e2eb47b5342dd1c5cb5156"
MODE = {"typed": 0, "patch": 1, "rewrite": 2}
FORBIDDEN = re.compile(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|elab|macro|"
                       r"attribute|set_option|opaque|native_decide)\b|#|```")
AXIOMS = re.compile(r"'([\w.]+)' depends on axioms: \[([^]]*)\]")


def shape(case, raw):
    source = raw.decode()
    _, _, target, modules = CASES[case]
    ns = case.upper() + "Bad"
    prefix = "".join(f"import {m}\n" for m in modules) + f"\nnamespace {ns}\n"
    main = source.split("#print axioms", 1)[0]
    reasons = []
    if not main.startswith(prefix):
        reasons.append("IMPORTS_OR_NAMESPACE_DIFFER")
    if main.count(target + " :=") != 1:
        reasons.append("EXACT_TARGET_HEADER_DIFFERS")
    if not main.endswith(f"end {ns}\n"):
        reasons.append("NAMESPACE_CLOSURE_DIFFERS")
    if FORBIDDEN.search(main):
        reasons.append("UNREVIEWED_OR_ADMITTED_CODE")
    if any(not line.startswith(("theorem ", "@[blueprint ", "--", "end ", " ", "\t")) for line in
           main[len(prefix):].splitlines() if line):
        reasons.append("UNREVIEWED_TOP_LEVEL_FORM")
    names = tuple(re.findall(r"(?m)^theorem (\w+)", main))
    suffix = "".join(f"#print axioms {ns}.{n}\n" for n in names)
    if not names or main + suffix != source:
        reasons.append("NONSTANDARD_AUDIT_SUFFIX")
    return reasons, main


def classify(message):
    cases = (("Tactic `introN` failed", "INTRO_NO_BINDER"),
             ("expected token", "SYNTAX_EXPECTED_TOKEN"),
             ("failed to synthesize instance", "INSTANCE_SYNTHESIS"),
             ("Missing cases", "MISSING_CASES"),
             ("unsolved goals", "UNSOLVED_GOALS"),
             ("Unknown identifier", "UNKNOWN_IDENTIFIER"),
             ("don't know how to synthesize implicit argument", "IMPLICIT_ARGUMENT"),
             ("failed to infer `have`", "HAVE_TYPE_INFERENCE"))
    return next((label for anchor, label in cases if message.startswith(anchor)), "OTHER_LEAN_ERROR")


def reported_axioms(text, target):
    matches = [hit[2] for hit in AXIOMS.finditer(text) if hit[1] == target]
    need(len(matches) == 1, "Missing target axiom report")
    return sorted({v.strip() for v in matches[0].split(",") if v.strip()})


def collect(paths):
    inventory_raw = published(D39 / "corpus_inventory.json")
    inventory = json.loads(inventory_raw)
    scope_raw = (ROOT / "cases_source_receipt.json").read_bytes()
    scope = json.loads(scope_raw)
    need(scope["published_inventory_sha256"] == digest(inventory_raw)
         and scope["author_runtime_pins"] == inventory["author_lean_runtime_pins"], "Source scope differs")
    pins = scope["author_runtime_pins"]
    choices = {case: [] for case in REVIEWED}
    for model_order, model in enumerate((DEEPSEEK, QWEN)):
        path = paths[model]
        need(path.stat().st_size <= 64 * 1024 * 1024 and digest(path.read_bytes()) == ARCHIVES[model][1],
             "Archive bytes differ")
        with tarfile.open(path, "r:gz") as tar:
            members = {item.name: item for item in tar.getmembers() if item.isfile()}
            fetch = lambda name, sha: read_member(tar, name, sha)
            wanted = []
            for ep in inventory["episodes"]:
                case = ep["state_id"].split("_")[0]
                if ep["model"] != model or case not in REVIEWED:
                    continue
                need(not ep["author_rescan_pass"] and ep["loop_time_outcome"] == "budget_exhausted",
                     "Negative archive stratum differs")
                for step in ep["steps"]:
                    if step["outcome"] != "ARCHIVED_LEAN_ERROR":
                        continue
                    for row in step["author_elaborations"]:
                        member = row["member"].removesuffix(".elab.json") + ".lean"
                        if (row["member"].endswith(".check.elab.json") and member in members
                                and row["exit_code"] not in (None, 0) and not row["timed_out"] and row["error_count"]):
                            wanted.append((members[member].offset, case, ep, step, row, member))
            for _, case, ep, step, row, member in sorted(wanted, key=lambda x: x[0]):
                need(members[member].size <= 1024 * 1024, "Negative source exceeds bounded read")
                with tar.extractfile(members[member]) as stream:
                    source = stream.read(1024 * 1024 + 1)
                reasons, main = shape(case, source)
                sha = digest(source)
                details = {"member": member, "source_sha256": sha, "source_shape_rejections": reasons}
                if (member, sha) == REVIEWED[case]:
                    detail = json.loads(fetch(step["archive_member"], step["sha256"]))
                    log = json.loads(fetch(row["member"], row["sha256"]))
                    need(detail["tool_execution"]["module_sha256"] == digest(main)
                         and log["pins"] == pins and log["exit_code"] == row["exit_code"] and not log["timed_out"],
                         "Exact negative does not bind author step and diagnostic")
                    errors = [{"line": x.get("line"), "column": x.get("col"), "class": classify(x["message"]),
                               "message": x["message"]} for x in log["diagnostics"] if x["severity"] == "error"]
                    target = f"{case.upper()}Bad.{case}_target"
                    closure = reported_axioms(log["stdout"], target)
                    need(len(errors) == row["error_count"] and "sorryAx" in closure, "Original target was not a rejected proof")
                    details.update({"raw": source, "expected_errors": errors, "expected_axioms": closure,
                                    "author_exit_code": row["exit_code"], "diagnostic_sha256": row["sha256"],
                                    "author_module_sha256": digest(main), "target": target})
                choices[case].append(((model_order, MODE[ep["mode"]], step["step"], member), details))
    return choices, pins, digest(scope_raw)


def prepare(paths, out, receipt):
    chosen, pins, scope_sha = collect(paths)
    out.mkdir(parents=True, exist_ok=False)
    result = {}
    for case, source in chosen.items():
        source.sort(key=lambda pair: pair[0])
        rank, expected = next(pair for pair in source if not pair[1]["source_shape_rejections"])
        need((expected["member"], expected["source_sha256"]) == REVIEWED[case] and "raw" in expected,
             "First deterministic eligible source differs from independently reviewed one")
        raw = expected.pop("raw")
        errors = expected.pop("expected_errors")
        offline_errors = (json.dumps(errors, indent=2, ensure_ascii=False) + "\n").encode()
        file, diag = f"{case}_archived_exact_failure.lean", f"{case}_archived_errors.offline.json"
        for name, data in ((file, raw), (diag, offline_errors)):
            with (out / name).open("xb") as stream:
                stream.write(data)
        result[case] = {**expected, "rank": list(rank[:-1]), "reviewed_source": file,
                        "offline_original_diagnostics": diag, "offline_original_diagnostics_sha256": digest(offline_errors),
                        "original_error_classes": [x["class"] for x in errors],
                        "candidate_count": len(source),
                        "shape_rejection_counts": dict(Counter(reason for _, e in source for reason in e["source_shape_rejections"]))}
    report = {"status": "THREE_EXACT_ARCHIVED_NEGATIVES_REVIEWED", "source_slot_receipt_sha256": scope_sha,
              "author_pins": pins, "scope": "Exact known source checks and diagnostics offline, disjoint from authoring slots.",
              "ordering": "DeepSeek before Qwen, typed before patch before rewrite, then step number and member path.",
              "cases": result, "model_generation": False, "local_execution_performed_by_prepare": False}
    raw = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "sha256": digest(raw)}))


def replay(scratch, prep, output):
    prep_raw = prep.read_bytes()
    source = json.loads(prep_raw)
    need(digest(prep_raw) == REVIEW_RECEIPT_SHA and source["status"] == "THREE_EXACT_ARCHIVED_NEGATIVES_REVIEWED"
         and set(source["cases"]) == set(REVIEWED),
         "Negative review receipt incomplete")
    smoke_path = D39 / "author_runtime_smoke.json"
    smoke = smoke_path.read_bytes()
    pins = verify_runtime(RUNTIME.resolve(), PROJECT.resolve(), smoke)
    need(pins == source["author_pins"], "Wrong author runtime")
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "HF_TOKEN", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"}}
    env.update({"PATH": str(RUNTIME.resolve() / "bin") + os.pathsep + env["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    results = {}
    for case, row in source["cases"].items():
        fixture = scratch / row["reviewed_source"]
        raw = fixture.read_bytes()
        expected = (scratch / row["offline_original_diagnostics"]).read_bytes()
        need((row["member"], digest(raw)) == REVIEWED[case] and digest(expected) == row["offline_original_diagnostics_sha256"]
             and not shape(case, raw)[0], "Refusing source outside the exact reviewed negatives")
        run = invoke(RUNTIME.resolve(), PROJECT.resolve(), env, fixture, digest(raw))
        messages = [json.loads(line) for line in run["stdout"].splitlines() if line.startswith("{")]
        errors = [{"line": m.get("pos", {}).get("line"), "class": classify(m["data"]), "message": m["data"]}
                  for m in messages if m.get("severity") == "error"]
        original = json.loads(expected)
        expected_classes = [(x["line"], x["class"]) for x in original]
        observed_classes = [(x["line"], x["class"]) for x in errors]
        closure = reported_axioms("\n".join(m["data"] for m in messages), row["target"])
        classes_match = expected_classes == observed_classes
        closure_match = closure == row["expected_axioms"]
        fail = run["returncode"] == row["author_exit_code"] and run["returncode"] not in (None, 0)
        results[case] = {"source_sha256": digest(raw), "immutable_target": row["target"],
                         "original_returncode": row["author_exit_code"], "local_returncode": run["returncode"],
                         "original_lines_and_classes": expected_classes, "local_lines_and_classes": observed_classes,
                         "all_messages_exact_equal": [x["message"] for x in original] == [x["message"] for x in errors],
                         "compiler_error_classes_and_lines_equal": classes_match,
                         "expected_target_axioms": row["expected_axioms"], "local_target_axioms": closure,
                         "target_axiom_closure_equal": closure_match,
                         "local_wall_seconds": run["wall_seconds"],
                         "same_archived_failure_reproduced": fail and classes_match and closure_match and "sorryAx" in closure,
                         "kernel_proof_accepted": False}
        with (scratch / f"{case}_local_errors.offline.json").open("xb") as stream:
            stream.write((json.dumps(errors, ensure_ascii=False, indent=2) + "\n").encode())
    report = {"status": "PASS_EXACT_ARCHIVED_NEGATIVES_REPRODUCED" if all(
        row["same_archived_failure_reproduced"] for row in results.values()) else "ARCHIVED_NEGATIVE_REPLAY_DIFFERS",
              "review_receipt_sha256": digest(prep_raw), "author_runtime_smoke_sha256": digest(smoke),
              "author_pins": pins, "scope": "Actual negative CPU replay only. Original and local detailed errors remain offline.",
              "cases": results, "model_generation": False, "gpu_seconds": 0}
    raw = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "sha256": digest(raw)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    source = sub.add_parser("prepare")
    source.add_argument("--output-dir", type=Path, required=True)
    source.add_argument("--receipt", type=Path, default=ROOT / "cases_archive_failure_receipt.json")
    source.add_argument("--deepseek-archive", type=Path, default=default_archive(DEEPSEEK))
    source.add_argument("--qwen-archive", type=Path, default=default_archive(QWEN))
    actual = sub.add_parser("replay")
    actual.add_argument("--scratch", type=Path, required=True)
    actual.add_argument("--review-receipt", type=Path, default=ROOT / "cases_archive_failure_receipt.json")
    actual.add_argument("--output", type=Path, default=ROOT / "cases_archive_failure_runtime.json")
    a = parser.parse_args()
    if a.mode == "prepare":
        prepare({DEEPSEEK: a.deepseek_archive, QWEN: a.qwen_archive}, a.output_dir.resolve(), a.receipt)
    else:
        replay(a.scratch.resolve(), a.review_receipt, a.output)
