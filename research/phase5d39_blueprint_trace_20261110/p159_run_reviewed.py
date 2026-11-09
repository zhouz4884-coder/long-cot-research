"""Run only the three fixed fixture sets under the verified author environment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter

from p159_prepare_reviewed import ROOT, digest, need


REPO = ROOT.parents[1]
SUITES = {
    "p159": ("p159_reviewed_source_receipt.json", "d3e7fbb9f90b18d6af2c992b6461e09605da279f11f01e3f439e9d1c5e8b0438",
             "longcot-d39-p159-reviewed-20261110"),
    "p165": ("p159_p165_source_receipt.json", "8b035ddb1e22daf4fd10c054edb3ef1d0c3776b0c3cbd2caeae93608e4cebd17",
             "longcot-d39-p165-reviewed-20261110"),
    "p94": ("p159_p94_source_receipt.json", "d2556fc10cd3cf3095050c82352ace19d5e07b4d66ae7317add59d8994bf9a19",
            "longcot-d39-p94-reviewed-20261110"),
}
RUNTIME = REPO / "outputs/d39_lean_4_31_0_windows/lean-4.31.0-windows"
PROJECT = REPO / "outputs/d39_blueprintrepair_954edd3/BlueprintRepair"


def git(package, *args):
    return subprocess.check_output(["git", "-C", str(package), *args], encoding="utf-8", timeout=20).strip()


def verify_runtime(runtime, project, raw):
    smoke = json.loads(raw)
    evidence = json.loads((ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes())
    need(smoke["status"] == "PASS_MATCHED_AUTHOR_IMPORT_POSITIVE"
         and smoke["sources"]["author"]["commit"] == evidence["author_commit"], "Author runtime is not verified")
    for name, sha in smoke["runtime"]["runtime_files_sha256"].items():
        need(digest((runtime / name).read_bytes()) == sha, "Compiler image differs")
    for rows in (smoke["sources"]["asset_hashes"], smoke["built_imports"]):
        for name, row in rows.items():
            raw = (project / name).read_bytes()
            need(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "Author project or import bytes differ")
    package_rows = smoke["sources"]["packages"]
    need({k: v["commit"] for k, v in package_rows.items()} == {r["name"]: r["rev"] for r in evidence["packages"]},
         "Author package revisions differ")
    for name, row in package_rows.items():
        package = project / ".lake/packages" / name
        need(git(package, "rev-parse", "HEAD") == row["commit"]
             and not git(package, "status", "--porcelain", "--untracked-files=no"), "Package checkout differs")
    return {"lean_toolchain": evidence["toolchain"], "mathlib_rev": package_rows["mathlib"]["commit"],
            "leanarchitect_rev": package_rows["LeanArchitect"]["commit"]}


def invoke(runtime, project, env, fixture, sha):
    print("BEGIN", fixture.name, flush=True)
    started = perf_counter()
    try:
        completed = subprocess.run([str(runtime / "bin/lake.exe"), "env", str(runtime / "bin/lean.exe"),
                                    "--json", str(fixture)], cwd=project, env=env, capture_output=True,
                                   encoding="utf-8", errors="strict", timeout=150)
        stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as failure:
        decode = lambda data: data.decode("utf-8", "replace") if isinstance(data, bytes) else data or ""
        stdout, stderr, code = decode(failure.stdout), decode(failure.stderr), None
    seconds = perf_counter() - started
    lines = []
    for line in stdout.splitlines():
        if line.startswith("{"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                need(code is None, "Unexpected malformed Lean diagnostic")
                continue
            row.pop("fileName", None)
            lines.append(json.dumps(row, ensure_ascii=False))
        else:
            lines.append(line)
    print("END", fixture.name, code, round(seconds, 2), flush=True)
    return {"source_sha256": sha, "returncode": code, "stdout": "\n".join(lines) + "\n",
            "stderr": stderr.replace(str(fixture), fixture.name).replace(str(project), "<author_project>"),
            "wall_seconds": seconds}


def run(suite, runtime, project, smoke_path, scratch, output):
    label, expected_sha, _ = SUITES[suite]
    smoke_raw = smoke_path.read_bytes()
    pins = verify_runtime(runtime, project, smoke_raw)
    source_raw = (ROOT / label).read_bytes()
    need(digest(source_raw) == expected_sha, "Source receipt is not the independently reviewed set")
    source = json.loads(source_raw)
    need(source.get("expected_author_pins", source.get("author_pins")) == pins, "Fixture author environment differs")
    names = source["prepared_fixtures"]
    for name, row in names.items():
        need(Path(name).name == name and name.endswith(".lean"), "Unexpected fixture path")
        raw = (scratch / name).read_bytes()
        need(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "Fixture bytes differ")
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "MATHLIB_CACHE_GET_URL",
                                "MATHLIB_CACHE_PUT_URL", "HF_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"}}
    env.update({"PATH": str(runtime / "bin") + os.pathsep + env["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    cases = {}
    for name, row in names.items():
        fixture = scratch / name
        need(digest(fixture.read_bytes()) == row["sha256"], "Fixture changed after preflight")
        cases[name] = invoke(runtime, project, env, fixture, row["sha256"])
    packet = {"status": "COMPLETED_FUNCTIONAL_RUNS", "runtime_verified": True,
              "runtime_smoke_sha256": digest(smoke_raw), "source_receipt_sha256": expected_sha,
              "author_pins": pins, "scope": "Trusted fixture hashes only; not a timing comparison.", "cases": cases}
    with output.open("xb") as out:
        out.write((json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode())
    print("RECEIPT", output.name, digest(output.read_bytes()), flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("suite", choices=tuple(SUITES))
    cli.add_argument("--runtime", type=Path, default=RUNTIME)
    cli.add_argument("--project", type=Path, default=PROJECT)
    cli.add_argument("--runtime-smoke", type=Path, default=ROOT / "author_runtime_smoke.json")
    cli.add_argument("--scratch", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    options = cli.parse_args()
    scratch = options.scratch or Path(tempfile.gettempdir()) / SUITES[options.suite][2]
    run(options.suite, options.runtime.resolve(), options.project.resolve(), options.runtime_smoke.resolve(),
        scratch.resolve(), options.output.resolve())
