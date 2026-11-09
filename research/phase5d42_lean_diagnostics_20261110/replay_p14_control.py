"""Same-source, line-preserving interventions on the reviewed D4.0 p14 control."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
BASE = "ad202e572534c8e7376d9fba7f8191fb7b3012d6"
TARGET = "P14Bad.p14_target"
sys.path.append(str(D39))
from author_runtime_setup import PROJECT, clean_env
from lean_resident_probe import ResidentLean, cold_check
from measure_p159_replay_cost import check_environment


def digest(x):
    return hashlib.sha256(x.encode() if isinstance(x, str) else x).hexdigest()


def pinned(name):
    path = D40 / name
    raw = path.read_bytes()
    relative = path.relative_to(REPO).as_posix()
    committed = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=REPO)
    if raw != committed:
        raise ValueError("Published D4.0 source receipt differs")
    return json.loads(raw)


def replace_exact(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one reviewed edit anchor: {old!r}")
    return text.replace(old, new, 1)


def make_variants(archive_dir):
    raw = (archive_dir / "p14_archived_exact_failure.lean").read_bytes()
    pin = pinned("cases_archive_failure_receipt.json")["cases"]["p14"]
    if digest(raw) != pin["source_sha256"] or pin["source_shape_rejections"]:
        raise ValueError("p14 is not the earlier review-approved exact archived file")
    source = raw.decode()
    scope = pinned("cases_source_receipt.json")["source_cases"]["p14"]
    header = scope["exact_target_header"] + " := by\n"
    imports = re.findall(r"(?m)^import (\S+)\s*$", source)
    if imports != scope["exact_imports"] or source.count(header) != 1 or source.splitlines()[10] != "  intro n":
        raise ValueError("Archived p14 source scope differs")
    neutral = replace_exact(source, "  intro n\n", "  intro m\n")
    no_intro = replace_exact(source, "  intro n\n", "  skip   \n")
    if any(len(x.encode()) != len(raw) or x.count("\n") != source.count("\n") for x in (neutral, no_intro)):
        raise ValueError("Equal-width single-line control differs")
    commute = replace_exact(no_intro, ":= by simp [pow_succ]\n", ":= by simp [pow_succ, mul_comm]\n")
    old_patch = ("      apply dvd_add\n"
                 "      · exact dvd_mul_of_dvd_left ih 10\n"
                 "      · exact dvd_mul_of_dvd_left (by norm_num : (11 : ℤ) ∣ (11 : ℤ)) ((-1 : ℤ)^k)\n")
    witness = ("      rcases ih with ⟨q, hq⟩\n"
               "      refine ⟨10*q + (-1 : ℤ)^k, ?_⟩\n"
               "      rw [hq]\n"
               "      ring\n")
    local = replace_exact(commute, old_patch, witness)
    before, remainder = source.split(header)
    _, after = remainder.split("\nend P14Bad\n")
    def whole(body):
        return before + header + body + "\n\nend P14Bad\n" + after
    variants = {"archived_exact": source, "neutral_binder_rename": neutral, "replace_intro_with_skip": no_intro,
                "skip_and_commutativity": commute, "ordinary_local_witness_patch": local,
                "whole_exact_query": whole("  exact?"),
                "ordinary_whole_induction": whole("  induction n <;> grind [pow_succ]")}
    for text in variants.values():
        if text.count(header) != 1 or re.findall(r"(?m)^import (\S+)\s*$", text) != imports:
            raise ValueError("p14 edit changed its target or imports")
    return variants, imports


def freeze_variants(variants, imports, target):
    rows = {}
    for name, source in variants.items():
        original = variants["archived_exact"].splitlines()
        current = source.splitlines()
        changed = [i for i, (a, b) in enumerate(zip(original, current), 1) if a != b] if len(original) == len(current) else None
        rows[name] = {"source_sha256": digest(source), "bytes": len(source.encode()), "lines": len(current),
                      "changed_lines_if_same_line_count": changed}
    freeze = {"status": "FROZEN_BEFORE_LOCAL_REPLAY", "baseline": BASE, "target": TARGET, "imports": imports,
              "control_protocol_sha256": digest((ROOT / "D42_P14_CONTROL_PROTOCOL.json").read_bytes()), "variants": rows}
    raw = (json.dumps(freeze, ensure_ascii=False, indent=2) + "\n").encode()
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("p14 control differs from the immutable variant freeze")
    else:
        target.write_bytes(raw)
    return digest(raw)


def classify(message):
    text = message.lower()
    if "there are no additional binders" in text or "no additional binder" in text:
        return "INTRO_NO_BINDER"
    if "unknown identifier" in text or "unknown constant" in text:
        return "MISSING_NAME"
    if "no goals to be solved" in text:
        return "ALREADY_CLOSED_GOAL"
    if "unsolved goals" in text:
        return "UNSOLVED_GOALS"
    if "type mismatch" in text:
        return "TYPE_MISMATCH"
    if "heartbeat" in text or "recursion depth" in text:
        return "RESOURCE_LIMIT"
    return "OTHER_LEAN_ERROR"


def attach_scope(row, source):
    lines = source.splitlines()
    row["errors_in_emitted_order"] = [{"category": classify(m["message"]), "line": m["line"],
        "source_line_sha256": digest(lines[m["line"] - 1]) if m["line"] and m["line"] <= len(lines) else None,
        "message_sha256": digest(m["message"]), "message": m["message"]} for m in row["messages"] if m["severity"] == 1]
    row["emitted_target_axiom_diagnostics"] = [m["message"] for m in row["messages"] if m["message"].startswith(f"'{TARGET}' ")]
    return row


def run(args):
    started = time.perf_counter()
    variants, imports = make_variants(args.archive_dir)
    freeze_sha = freeze_variants(variants, imports, args.freeze)
    if args.output is None:
        print(freeze_sha)
        return
    lean, lake = args.lean.resolve(), args.lake.resolve()
    evidence = json.loads((D39 / "D39_EVIDENCE_INPUTS.json").read_bytes())
    version = check_environment(lean, lake, PROJECT.resolve(), evidence)
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env["PATH"]
    preparation = time.perf_counter() - started
    command = [str(lake), "env", str(lean)]
    with tempfile.TemporaryDirectory(prefix="d42_p14_", dir=PROJECT) as directory:
        path = Path(directory)
        server = ResidentLean(command, PROJECT, 120, env=env)
        try:
            preload = "".join(f"import {name}\n" for name in imports) + "\n#check Nat.add_zero\n"
            barrier = server.check(path / "resident.lean", preload, [])
            if barrier["status"] != "KERNEL_ACCEPTED":
                raise ValueError("Pinned p14 prelude did not initialize")
            resident = {}
            for name, text in variants.items():
                resident[name] = attach_scope(server.check(path / "resident.lean", text, [TARGET]), text)
                print(name, resident[name]["status"], [m["category"] for m in resident[name]["errors_in_emitted_order"]], flush=True)
        finally:
            now = time.perf_counter()
            server.close()
            shutdown = time.perf_counter() - now
        cold = {name: attach_scope(cold_check(command, PROJECT, path / f"cold_{name}.lean", variants[name], [TARGET],
                                             timeout=120, env=env), variants[name])
                for name in ("archived_exact", "ordinary_whole_induction")}
    result = {"status": "COMPLETE_P14_CAUSAL_CONTROL", "scope": "Previously reviewed historical p14, separate from new selected cases. Exact original and local edits were executed under the same author imports. Timing is observed CPU wall, not comparative production latency.",
              "freeze_sha256": freeze_sha, "version": version, "material_preparation_seconds": preparation,
              "resident_startup_seconds": server.startup_seconds, "prelude": barrier, "resident": resident,
              "resident_shutdown_seconds": shutdown, "cold": cold, "new_model_tokens": 0, "gpu_seconds": 0}
    with args.output.open("xb") as destination:
        destination.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive-dir", type=Path, required=True)
    cli.add_argument("--freeze", type=Path, required=True)
    for option in ("lean", "lake", "output"):
        cli.add_argument("--" + option, type=Path)
    run(cli.parse_args())
