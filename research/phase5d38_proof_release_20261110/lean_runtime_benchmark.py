"""Read back a pinned public miniF2F CPU setup and check trusted source fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter

from lean_runtime_install import PREFIX, REPO, ROOT, file_sha, verify_required


BENCHMARK = REPO / "outputs/d38_minif2f_f0a20e14"
BENCHMARK_COMMIT = "f0a20e14c1eeccd859d51bb4c2b3ee487889c303"
CACHE = REPO / "outputs/d38_mathlib_cache_f0a20e14"
TEST_SOURCE_SHA256 = "8e135204947654a6f5234ee3da830ea7b72337f33dc29229fd8be6c69ac1c0b7"
NAMES = {"mathd_numbertheory_66": "source_proof", "mathd_algebra_302": "source_proof",
         "mathd_algebra_141": "statement_only", "numbertheory_4x3m7y3neq2003": "statement_only",
         "induction_12dvd4expnp1p20": "statement_only"}
ALLOWED = {"Classical.choice", "propext", "Quot.sound"}
FIXTURE_SHA256 = {
    "induction_12dvd4expnp1p20.absent.lean": "4ef50da98bd986018a24d89d689a75c450aaf89fee523bbe28c250ae0f689496",
    "induction_12dvd4expnp1p20.lean": "98ca1b3ede15750203d78228bdef353b153f49bd34c803169ba8f92e6463e98e",
    "mathd_algebra_141.absent.lean": "666f3a23d41cb24396e4e62379baa326a6e8effe77c46df67f34f8d09751d82a",
    "mathd_algebra_141.lean": "28d0c21369d46a231c9155162505abaa8abde637c2bf49c557a592bad20facbc",
    "mathd_algebra_302.absent.lean": "323f3f9e319f9b5c7bbfcc5957dc2d78762fd60df445064541878ac8a325669b",
    "mathd_algebra_302.lean": "d0c1591f0f835804685c2ff9a4be6b94d5ced3fcf10ae226962861f853414503",
    "mathd_numbertheory_66.absent.lean": "34e722c7b7070bc98cb6ba407f769c4cd2ac702cd2a9ccadb7325a5268b37a8c",
    "mathd_numbertheory_66.lean": "46143c8a8776b823e9071ce7cf70b65b2cca56189b81afaa67536790f2b81efe",
    "numbertheory_4x3m7y3neq2003.absent.lean": "67bb757f2e964f92060482ac54ec523bdb99be67b72a06b0bfc35f0bb277f1c5",
    "numbertheory_4x3m7y3neq2003.lean": "a060f0e61d396be5585af63ce1845fec16b6ae90879793a508a5ca836a6c8a6f",
}


def manifest_readback(bench):
    def git(cwd, *args):
        return subprocess.check_output(["git", "-C", str(cwd), *args], timeout=15)

    if (git(bench, "rev-parse", "HEAD").decode().strip() != BENCHMARK_COMMIT
            or git(bench, "status", "--porcelain", "--untracked-files=no")):
        raise ValueError("Benchmark checkout differs from the frozen public commit")
    official = git(bench, "show", "HEAD:lake-manifest.json")
    if json.loads(official) != json.loads((bench / "lake-manifest.json").read_bytes()):
        raise ValueError("Resolved benchmark manifest differs from the pinned source")
    packages = {}
    for row in json.loads(official)["packages"]:
        checkout = bench / ".lake/packages" / row["name"]
        head = git(checkout, "rev-parse", "HEAD").decode().strip()
        if head != row["rev"] or git(checkout, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError(f"Package source identity mismatch: {row['name']}")
        packages[row["name"]] = {"origin": row["url"], "commit": head,
                                 "tree": git(checkout, "rev-parse", "HEAD^{tree}").decode().strip()}
    return {"benchmark_commit": BENCHMARK_COMMIT, "benchmark_tree": git(bench, "rev-parse", "HEAD^{tree}").decode().strip(),
            "lake_manifest_sha256": hashlib.sha256(official).hexdigest(), "packages": packages}


def cache_readback(cache):
    began = perf_counter()
    paths = sorted(cache.rglob("*.ltar"), key=lambda p: p.relative_to(cache).as_posix())
    whole = hashlib.sha256()
    size = 0
    for path in paths:
        count = path.stat().st_size
        size += count
        whole.update((path.relative_to(cache).as_posix() + "\t" + str(count) + "\t" + file_sha(path) + "\n").encode())
    return {"count": len(paths), "bytes": size, "sha256_ordered_path_size_hash_lines": whole.hexdigest(),
            "wall_seconds": perf_counter() - began}


def build_fixtures(bench, folder):
    raw = subprocess.check_output(["git", "-C", str(bench), "show", "HEAD:MiniF2F/Test.lean"], timeout=15)
    if hashlib.sha256(raw).hexdigest() != TEST_SOURCE_SHA256:
        raise ValueError("Exact pinned competition declarations unavailable")
    full = raw.decode("utf-8")
    preamble = ("import MiniF2F.ProblemImports\n\nopen scoped Nat\nopen scoped Real\n"
                "set_option autoImplicit false\nset_option relaxedAutoImplicit false\n\n")
    for theorem, role in NAMES.items():
        start, = re.finditer(rf"(?m)^theorem {re.escape(theorem)}\b", full)
        exact = full[start.start():full.index("\n\n", start.start())].rstrip()
        if role == "source_proof":
            content = preamble + exact + f"\n#print axioms {theorem}\n"
        else:
            statement = exact.partition(":=")[0].rstrip()
            content = preamble + statement + " := by\n  skip\n"
        for name, text in ((f"{theorem}.lean", content), (f"{theorem}.absent.lean", preamble + f"#check {theorem}\n")):
            data = text.encode("utf-8")
            if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256[name]:
                raise ValueError(f"Rebuilt trusted fixture bytes differ: {name}")
            (folder / name).write_bytes(data)


def compile_fixtures(bench, runtime, cache, fixtures):
    lake = runtime / "bin/lake.exe"
    lean = runtime / "bin/lean.exe"
    verify_required(runtime)
    env = {key: value for key, value in os.environ.items() if key.upper() not in
           {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "MATHLIB_CACHE_GET_URL", "MATHLIB_CACHE_PUT_URL"}}
    env.update({"PATH": str(runtime / "bin") + os.pathsep + os.environ["PATH"], "MATHLIB_CACHE_DIR": str(cache),
                "XDG_CACHE_HOME": str(cache), "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    output = {}
    for theorem, role in NAMES.items():
        for absent in (False, True):
            name = f"{theorem}{'.absent' if absent else ''}.lean"
            source = fixtures / name
            raw = source.read_bytes()
            source_sha = hashlib.sha256(raw).hexdigest()
            if source_sha != FIXTURE_SHA256[name]:
                raise ValueError(f"Refusing to execute Lean source outside pinned controls: {name}")
            began = perf_counter()
            process = subprocess.run([str(lake), "env", str(lean), "--json", str(source)], cwd=bench, env=env,
                                     text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120)
            text = process.stdout + process.stderr
            messages = [json.loads(line) for line in process.stdout.splitlines() if line.startswith("{")]
            diagnostics = [entry["data"] for entry in messages if entry.get("severity") == "error"]
            pattern = re.compile(re.escape(f"'{theorem}' depends on axioms:") + r"\s*\[([^]]*)\]")
            deps = pattern.search("\n".join(m.get("data", "") for m in messages))
            axioms = sorted(p.strip() for p in deps[1].split(",")) if deps else []
            if absent:
                passed = (process.returncode != 0 and len(diagnostics) == 1 and theorem in diagnostics[0]
                          and ("unknown identifier" in diagnostics[0].lower() or "unknown constant" in diagnostics[0].lower()))
            elif role == "source_proof":
                passed = (process.returncode == 0 and not diagnostics and "sorryAx" not in text
                          and (deps is not None or f"'{theorem}' does not depend on any axioms" in text)
                          and set(axioms) <= ALLOWED)
            else:
                passed = (process.returncode != 0 and len(diagnostics) == 1
                          and diagnostics[0].startswith("unsolved goals"))
            output[name] = {"kind": "absence_control" if absent else role, "source_sha256": source_sha,
                            "exit_code": process.returncode, "axioms": axioms, "errors": diagnostics,
                            "wall_seconds": perf_counter() - began, "expected_outcome_observed": passed,
                            "stderr": process.stderr.replace(str(bench), "<benchmark>").replace(str(fixtures), "<fixtures>")}
    return output


def run(bench, root, cache, fixtures):
    sources = manifest_readback(bench)
    binary_artifacts = [bench / ".lake/build/lib/lean/MiniF2F/ProblemImports.olean",
                        bench / ".lake/packages/mathlib/.lake/build/lib/lean/Mathlib.olean",
                        bench / ".lake/packages/formal_conjectures/.lake/build/lib/lean/FormalConjectures/Util/Answer.olean"]
    paths = {p.relative_to(bench).as_posix(): {"bytes": p.stat().st_size, "sha256": file_sha(p)} for p in binary_artifacts}
    controls = compile_fixtures(bench, root / PREFIX, cache, fixtures)
    return {"status": "PASS" if all(row["expected_outcome_observed"] for row in controls.values()) else "FAIL",
            "scope": "Two upstream reference proofs, three statement-only elaborations and five absence controls. No independent/model proof scores.",
            "source_identity": sources, "built_artifacts": paths, "packed_mathlib_cache": cache_readback(cache),
            "controls": controls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", type=Path, default=BENCHMARK)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bench, root, cache = args.bench.resolve(), args.root.resolve(), args.cache.resolve()
    if args.fixtures:
        receipt = run(bench, root, cache, args.fixtures.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="d38-lean-bench-controls-", dir=cache) as temp:
            fixtures = Path(temp)
            build_fixtures(bench, fixtures)
            receipt = run(bench, root, cache, fixtures)
    with args.output.open("xb") as target:
        target.write((json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"status": receipt["status"], "controls": {name: row["expected_outcome_observed"]
                     for name, row in receipt["controls"].items()}}))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
