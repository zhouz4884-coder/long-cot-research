"""Same reviewed p159 inputs under cold and resident Lean, with batched axioms."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import time

from author_runtime_setup import PROJECT, clean_env, source_manifest, verify_git_checkout
from lean_resident_probe import compare, FLAGS


ROOT = Path(__file__).resolve().parent
LOCKED_TOOLCHAIN = "leanprover/lean4:v4.31.0"
FIXTURES = ("p159_initial_identity.lean", "p159_author_exact_check.lean", "p159_accepted_identity.lean")
EXPECTED = (3, 5, 5)


def digest(raw):
    return sha256(raw).hexdigest()


def check_environment(lean, lake, project, inputs):
    if project != PROJECT.resolve():
        raise ValueError("Use the verified isolated author project from author_runtime_setup.py")
    toolchain = (project / "lean-toolchain").read_bytes()
    lake_manifest = (project / "lake-manifest.json").read_bytes()
    if toolchain.decode().strip() != LOCKED_TOOLCHAIN or digest(toolchain) != inputs["toolchain_sha256"]:
        raise ValueError("The author Lean toolchain file is not exact")
    if digest(lake_manifest) != inputs["lake_manifest_sha256"]:
        raise ValueError("The author Lake dependency lock is not exact")
    runtime = json.loads((ROOT / "author_runtime_toolchain.json").read_bytes())
    smoke = json.loads((ROOT / "author_runtime_smoke.json").read_bytes())
    if (smoke["status"] != "PASS_MATCHED_AUTHOR_IMPORT_POSITIVE"
            or any(runtime.get(name) != value for name, value in smoke["runtime"].items())
            or digest(lean.read_bytes()) != runtime["runtime_files_sha256"]["bin/lean.exe"]
            or digest(lake.read_bytes()) != runtime["runtime_files_sha256"]["bin/lake.exe"]):
        raise ValueError("The author runtime and trusted smoke must pass before p159 replay")
    for name, artifact in smoke["built_imports"].items():
        raw = (project / name).read_bytes()
        if len(raw) != artifact["bytes"] or digest(raw) != artifact["sha256"]:
            raise ValueError("A built author import differs from its validated receipt")
    author, assets, pins = source_manifest()
    live = {name: {"url": pin["url"], **verify_git_checkout(project / ".lake/packages" / name, pin["rev"])}
            for name, pin in pins.items()}
    if author != smoke["sources"]["author"] or assets != smoke["sources"]["asset_hashes"] or live != smoke["sources"]["packages"]:
        raise ValueError("Live source or dependency trees differ from the author smoke")
    version = subprocess.check_output([str(lean), "--version"], cwd=project, env=clean_env(), creationflags=FLAGS).decode().strip()
    if "version 4.31.0" not in version or "68218e87" not in version:
        raise ValueError(f"Non-author Lean executable: {version}")
    return version


def reviewed_sources(folder, receipt):
    result = []
    for filename, target_count in zip(FIXTURES, EXPECTED, strict=True):
        raw = (folder / filename).read_bytes()
        expected = receipt["prepared_fixtures"][filename]
        if len(raw) != expected["bytes"] or digest(raw) != expected["sha256"]:
            raise ValueError("A p159 check-only source differs from the review receipt")
        source = raw.decode()
        targets = re.findall(r"(?m)^#print axioms (P159Bad\.[a-z_][a-z_0-9]*)\s*$", source)
        if len(targets) != target_count or len(set(targets)) != target_count:
            raise ValueError("A reviewed fixture lacks its named axiom closure checks")
        result.append((source, targets))
    return result


def run(args):
    started = time.perf_counter()
    evidence = json.loads((ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes())
    receipt_bytes = (ROOT / "p159_reviewed_source_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if receipt["raw_author_gate_executable"] or receipt["raw_prior_drafts_executable"]:
        raise ValueError("Unreviewed model code is not authorized for this probe")
    project, lean, lake = (p.resolve() for p in (args.project, args.lean, args.lake))
    version = check_environment(lean, lake, project, evidence)
    sources = reviewed_sources(args.reviewed_folder, receipt)
    preparation = time.perf_counter() - started
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env["PATH"]
    timed = compare([str(lake), "env", str(lean)], project, sources, timeout=180, env=env, scratch_parent=project)
    passed = timed["all_statuses_match"] and all(row["status"] == "KERNEL_ACCEPTED" for row in timed["cold"])
    batch = timed["cold"][1]
    report = {"status": "PASS" if passed else "FAIL", "scope": "CPU checker cost for exact reviewed p159 sources. The middle author-exact file checks the complete target and four support axioms in one batch. These are cold module loads versus the existing resident server, not model generation or a new algorithm benchmark.",
              "lean_version": version, "lean_binary_sha256": digest(lean.read_bytes()),
              "source_review_receipt_sha256": digest(receipt_bytes), "material_preparation_seconds": preparation,
              "fixture_order": list(FIXTURES), "local_cold_batch": {"lean_invocations": 1, "named_axiom_closures": len(batch["axioms"]),
                                                                       "elapsed_seconds": batch["elapsed_seconds"],
                                                                       "status": batch["status"]},
              **timed, "new_gpu_seconds": 0, "new_model_tokens": 0}
    with args.output.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({k: report[k] for k in ("status", "local_cold_batch", "cold_total_seconds",
                                          "resident_total_including_shutdown_seconds")}))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("project", "lean", "lake", "reviewed-folder", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    run(parser.parse_args())
