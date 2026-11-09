"""Build only pinned public dependencies and compile a fixed trusted positive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from time import perf_counter

from author_runtime_setup import (AUTHOR_ROOT, CACHE, LEAN_ROOT, PREFIX, PROJECT, REPO, clean_env, fetch_sources,
                                  file_sha, scoped, verify_toolchain)


BIN = LEAN_ROOT / PREFIX / "bin"
THEOREM = "D39AuthorRuntime.positive"
TRUSTED = """import Mathlib
import Architect

set_option warningAsError true

namespace D39AuthorRuntime

@[blueprint "thm:d39-runtime-positive"
  (statement := /-- A fixed arithmetic identity in the author-matched runtime. -/)]
theorem positive (a b : Nat) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by
  ring

end D39AuthorRuntime

#print axioms D39AuthorRuntime.positive
"""


def lake_env(cache_backend):
    env = clean_env(scoped(CACHE))
    env["PATH"] = str(BIN) + os.pathsep + env["PATH"]
    env["MATHLIB_CACHE_USE_CLOUDFLARE"] = "1" if cache_backend == "cloudflare" else "0"
    return env


def stage_command(stage, args, attempt, timeout, backend):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", attempt):
        raise ValueError("Attempt identifier contains invalid characters")
    cache = scoped(CACHE)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"author_runtime_{stage}_{attempt}.log"
    start = perf_counter()
    try:
        with path.open("xb") as log:
            proc = subprocess.run([str(BIN / "lake.exe"), *args], cwd=scoped(PROJECT), env=lake_env(backend),
                                  stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        code, timed_out = proc.returncode, False
    except subprocess.TimeoutExpired:
        code, timed_out = None, True
    raw = path.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()
    tail = [line.replace(str(AUTHOR_ROOT), "<author>").replace(str(CACHE), "<cache>") for line in lines[-20:]]
    return {"status": "PASS" if code == 0 else "TIMEOUT" if timed_out else "FAILED",
            "command": ["lake.exe", *args], "public_cache_backend": backend, "elapsed_seconds": perf_counter() - start,
            "exit_code": code, "timeout_seconds": timeout, "log_sha256": file_sha(path),
            "log_bytes": len(raw), "log_relative_path": path.relative_to(REPO).as_posix(), "log_tail": tail}


def cached_files():
    cache = scoped(CACHE)
    aggregate = hashlib.sha256()
    paths = sorted(cache.rglob("*.ltar"), key=lambda path: path.relative_to(cache).as_posix())
    total = 0
    for path in paths:
        size = path.stat().st_size
        total += size
        aggregate.update((path.relative_to(cache).as_posix() + "\t" + str(size) + "\t" + file_sha(path) + "\n").encode())
    return {"packed_count": len(paths), "packed_bytes": total, "sha256_ordered_path_size_hash_lines": aggregate.hexdigest()}


def smoke():
    runtime = verify_toolchain()
    sources = fetch_sources()
    paths = (".lake/packages/mathlib/.lake/build/lib/lean/Mathlib.olean",
             ".lake/packages/LeanArchitect/.lake/build/lib/lean/Architect.olean")
    artifacts = {name: {"bytes": (PROJECT / name).stat().st_size, "sha256": file_sha(PROJECT / name)} for name in paths}
    cache = scoped(CACHE)
    with tempfile.TemporaryDirectory(prefix="d39-trusted-", dir=cache) as stage:
        fixture = Path(stage) / "AuthorRuntimePositive.lean"
        data = TRUSTED.encode("utf-8")
        fixture.write_bytes(data)
        start = perf_counter()
        proc = subprocess.run([str(BIN / "lake.exe"), "env", str(BIN / "lean.exe"), "--json", str(fixture)],
                              cwd=scoped(PROJECT), env=lake_env("azure"), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=150, check=False)
        elapsed = perf_counter() - start
        stdout = proc.stdout.replace(str(fixture), fixture.name).replace(fixture.as_posix(), fixture.name)
        stderr = proc.stderr.replace(str(fixture), fixture.name).replace(fixture.as_posix(), fixture.name)
    messages = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    diagnostic = "\n".join(entry.get("data", "") for entry in messages)
    dependencies = re.search(re.escape(f"'{THEOREM}' depends on axioms:") + r"\s*\[([^]]*)\]", diagnostic)
    axioms = sorted(s.strip() for s in dependencies[1].split(",")) if dependencies else []
    proven = ((dependencies is not None or f"'{THEOREM}' does not depend on any axioms" in diagnostic)
              and set(axioms) <= {"propext", "Classical.choice", "Quot.sound"} and proc.returncode == 0
              and not any(entry.get("severity") == "error" for entry in messages) and "sorryAx" not in diagnostic)
    return {"status": "PASS_MATCHED_AUTHOR_IMPORT_POSITIVE" if proven else "FAIL_MATCHED_AUTHOR_IMPORT_POSITIVE",
            "scope": "One fixed trusted arithmetic proof with both author-pinned imports and a LeanArchitect annotation. No archived model code loaded.",
            "runtime": runtime, "sources": sources, "imports": ["Mathlib", "Architect"], "built_imports": artifacts,
            "cache": cached_files(), "run": {"command": ["lake.exe", "env", "lean.exe", "--json", fixture.name],
            "fixture_sha256": hashlib.sha256(data).hexdigest(), "theorem": THEOREM, "axioms": axioms,
            "exit_code": proc.returncode, "wall_seconds": elapsed, "stdout": stdout, "stderr": stderr}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("cache", "build", "smoke"))
    parser.add_argument("--attempt", default="v1")
    parser.add_argument("--backend", choices=("azure", "cloudflare"), default="azure")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action in {"cache", "build"}:
        verify_toolchain()
        fetch_sources()
    if args.action == "cache":
        if shutil.disk_usage(scoped(CACHE).parent).free < 7_000_000_000:
            raise ValueError("Insufficient free space for pinned full Mathlib cache")
        command = ["exe", "cache", "get", "Mathlib", "--repo=leanprover-community/mathlib4"]
        result = stage_command("cache", command, args.attempt, 900, args.backend)
    elif args.action == "build":
        result = stage_command("build", ["build", "@LeanArchitect/Architect"], args.attempt, 360, args.backend)
    else:
        result = smoke()
    with args.output.open("xb") as receipt:
        receipt.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": result["status"], "action": args.action, "receipt": args.output.name}, ensure_ascii=False))
    return 0 if result["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
