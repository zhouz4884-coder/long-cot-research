"""Test one compiler-guided deletion from the exact p14 archived failure."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from cases_archive_failure_review import PROJECT, RUNTIME, REVIEWED, classify, invoke, reported_axioms, shape, verify_runtime
from cases_source_review import D39, ROOT, SAFE_AXIOMS, digest, need


TARGET = "P14Bad.p14_target"
EXACT_LINE = b"  intro n\n"
LINE = 11


def save(path, obj):
    raw = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as out:
        out.write(raw)
    return digest(raw)


def run(source, freeze_path, result_path):
    original = source.read_bytes()
    archived = (ROOT / "cases_archive_failure_runtime.json").read_bytes()
    reference = json.loads(archived)["cases"]["p14"]
    need(digest(original) == REVIEWED["p14"][1] == reference["source_sha256"] and not shape("p14", original)[0]
         and reference["same_archived_failure_reproduced"]
         and reference["local_lines_and_classes"] == [[LINE, "INTRO_NO_BINDER"]],
         "The verified archived first failure does not bind this control")
    lines = original.splitlines(keepends=True)
    need(lines[LINE - 1] == EXACT_LINE and lines.count(EXACT_LINE) == 1, "Deletion is ambiguous")
    edited = b"".join(lines[:LINE - 1] + lines[LINE:])
    need(not shape("p14", edited)[0], "Deletion changes the immutable header, imports or audit suffix")
    smoke = (D39 / "author_runtime_smoke.json").read_bytes()
    pins = verify_runtime(RUNTIME.resolve(), PROJECT.resolve(), smoke)
    freeze = {"status": "FROZEN_SINGLE_LINE_DELETION_BEFORE_LEAN", "original_source_sha256": digest(original),
              "archived_negative_replay_sha256": digest(archived), "immutable_target": TARGET,
              "deleted_line": LINE, "deleted_text": EXACT_LINE.decode().rstrip("\n"),
              "edited_source_sha256": digest(edited), "author_pins": pins,
              "scope": "Auditor-selected one-line deletion. Derived control; not an archived successful output."}
    freeze_sha = save(freeze_path, freeze)
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "HF_TOKEN", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"}}
    env.update({"PATH": str(RUNTIME.resolve() / "bin") + os.pathsep + env["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    with tempfile.TemporaryDirectory(prefix="d40-p14-edit-control-") as temp:
        fixture = Path(temp) / "P14EditedReplay.lean"
        with fixture.open("xb") as stream:
            stream.write(edited)
        observed = invoke(RUNTIME.resolve(), PROJECT.resolve(), env, fixture, digest(edited))
    need(digest(source.read_bytes()) == digest(original), "Original archived fixture changed")
    messages = [json.loads(line) for line in observed["stdout"].splitlines() if line.startswith("{")]
    errors = [{"line": m.get("pos", {}).get("line"),
               "class": ("TYPE_MISMATCH" if m["data"].startswith("Type mismatch") else classify(m["data"])),
               "message": m["data"]} for m in messages if m.get("severity") == "error"]
    info = "\n".join(m["data"] for m in messages if m.get("severity") == "information")
    closure = [] if f"'{TARGET}' does not depend on any axioms" in info else reported_axioms(info, TARGET)
    accepted = (observed["returncode"] == 0 and not errors and not observed["stderr"].strip()
                and all(m.get("severity") != "warning" for m in messages) and set(closure) <= SAFE_AXIOMS)
    result = {"status": "EDITED_REPLAY_FULL_PROOF_ACCEPTED" if accepted else "EDITED_REPLAY_NEXT_FAILURE",
              "freeze_sha256": freeze_sha, "original_source_sha256": digest(original), "edited_source_sha256": digest(edited),
              "author_runtime_smoke_sha256": digest(smoke), "immutable_target": TARGET,
              "local_returncode": observed["returncode"], "local_errors": errors,
              "target_axiom_closure": closure, "local_wall_seconds": observed["wall_seconds"],
              "kernel_proof_accepted": accepted, "original_source_changed": False,
              "model_generation": False, "gpu_seconds": 0}
    print(json.dumps({"status": result["status"], "sha256": save(result_path, result), "errors": errors,
                      "axioms": closure}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, default=Path(tempfile.gettempdir()) /
                        "longcot-d40-archived-negatives-20261110/p14_archived_exact_failure.lean")
    parser.add_argument("--freeze", type=Path, default=ROOT / "cases_p14_one_line_edit_freeze.json")
    parser.add_argument("--output", type=Path, default=ROOT / "cases_p14_one_line_edit_runtime.json")
    a = parser.parse_args()
    run(a.original, a.freeze, a.output)
