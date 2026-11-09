"""Install a pinned author-matched Lean and Git dependency tree under outputs/ only."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import tempfile
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
OUTPUTS = REPO / "outputs"
D38 = REPO / "research/phase5d38_proof_release_20261110"
TRACE_FREEZE_SHA256 = "657b0e1d770340c543af9b645a265fcea55628a1ea8fcd8664b1433cd365e1ab"
AUTHOR = "https://github.com/Karifannaa/BlueprintRepair.git"
AUTHOR_COMMIT = "954edd366a0d1474ecfebe418d4cac14aaf8c6bf"
LEAN_COMMIT = "68218e876d2a38b1985b8590fff244a83c321783"
MATHLIB_COMMIT = "fabf563a7c95a166b8d7b6efca11c8b4dc9d911f"
ARCHITECT_COMMIT = "f38c848196b0467e7b9dcc3d129a866b4051c23c"
TOOLCHAIN = "leanprover/lean4:v4.31.0"
PREFIX = "lean-4.31.0-windows"
ARCHIVE = PREFIX + ".tar.zst"
RELEASE_URL = "https://github.com/leanprover/lean4/releases/download/v4.31.0/" + ARCHIVE
RELEASE_SHA256 = "9d482ee0c1af858cddb5bfb582969499a787caf9c4f953bc81d512da6dcc12c7"
LEAN_ROOT = OUTPUTS / "d39_lean_4_31_0_windows"
AUTHOR_ROOT = OUTPUTS / "d39_blueprintrepair_954edd3"
AUTHOR_GIT = AUTHOR_ROOT / "source.git"
PROJECT = AUTHOR_ROOT / "BlueprintRepair"
CACHE = OUTPUTS / "d39_mathlib_cache_fabf563"
AUTHOR_ASSET_HASHES = {
    "lean-toolchain": "efac0b94923b2d8b6840cd35be9177ad0fc5ab2332f4f4311c98712cee92fdee",
    "lake-manifest.json": "0a0c208296a9bf661300a3fe9d6a63ca20c24f46dc670e18c7a99cee2957aa68",
}
RUNTIME_HASHES = {
    "bin/lean.exe": "9b216deb50d37c32c829d1efaaa5bafd5560417d382df35a815489e31a31593f",
    "bin/lake.exe": "a5be0113af1c08ba678c1fad07594e1c5de6b871fe0c4144da2998488eba88a1",
    "lib/lean/Init.olean": "9e6e77b58b46742b93b7de481229698d853595479a6e154e9c6fcfdf63b485c8",
    "lib/lean/Lean.olean": "f3ad7edd2aafe4ef2d1f0548d85cf653dd903c499e7bc839fdb78e5b556297e5",
    "lib/lean/Std.olean": "1aff77f5060417a5ff128b6cb3c76c2726114923d76b3c8fab8111e4f97a9803",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scoped(path):
    root = OUTPUTS.resolve()
    path = path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Target must be strictly inside the repository outputs directory")
    return path


def install_toolchain():
    import zstandard

    if platform.system() != "Windows" or platform.machine().upper() not in {"AMD64", "X86_64"}:
        raise ValueError("Release fixture is pinned to Windows x64")
    root = scoped(LEAN_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / ARCHIVE
    download_seconds = extract_seconds = None
    if not archive.exists():
        began = perf_counter()
        with tempfile.TemporaryDirectory(prefix="d39-lean-download-", dir=root) as stage:
            staged = Path(stage) / ARCHIVE
            request = Request(RELEASE_URL, headers={"User-Agent": "D39-Lean-Pinned-Release"})
            with urlopen(request, timeout=45) as response, staged.open("xb") as sink:
                shutil.copyfileobj(response, sink, 4 * 1024 * 1024)
            if file_sha(staged) != RELEASE_SHA256:
                raise ValueError("Official Lean archive SHA-256 mismatch")
            staged.replace(archive)
        download_seconds = perf_counter() - began
    if file_sha(archive) != RELEASE_SHA256:
        raise ValueError("Existing Lean archive differs from official release")
    install = root / PREFIX
    if not install.exists():
        began = perf_counter()
        with tempfile.TemporaryDirectory(prefix="d39-lean-extract-", dir=root) as stage:
            target = Path(stage)
            with archive.open("rb") as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as bundle:
                    bundle.extractall(target, filter="data")
            if not (target / PREFIX / "bin/lean.exe").is_file():
                raise ValueError("Lean executable absent after extraction")
            (target / PREFIX).replace(install)
        extract_seconds = perf_counter() - began
    return {**verify_toolchain(), "download_wall_seconds": download_seconds,
            "extract_wall_seconds": extract_seconds, "zstandard": zstandard.__version__}


def clean_env(cache=None):
    removed = {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "MATHLIB_CACHE_GET_URL", "MATHLIB_CACHE_PUT_URL",
               "MATHLIB_CACHE_AZURE_BEARER_TOKEN", "MATHLIB_CACHE_SAS", "MATHLIB_CACHE_S3_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"}
    env = {name: value for name, value in os.environ.items() if name.upper() not in removed}
    if cache is not None:
        env.update({"MATHLIB_CACHE_DIR": str(cache), "XDG_CACHE_HOME": str(cache)})
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "core.longpaths", "GIT_CONFIG_VALUE_0": "true",
                "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": ""})
    return env


def verify_toolchain():
    root = scoped(LEAN_ROOT)
    path = root / PREFIX
    archive = root / ARCHIVE
    if file_sha(archive) != RELEASE_SHA256:
        raise ValueError("Pinned runtime archive changed")
    files = {name: file_sha(path / name) for name in RUNTIME_HASHES}
    if files != RUNTIME_HASHES:
        raise ValueError("Materialized runtime file differs from the author release")
    lean, lake = path / "bin/lean.exe", path / "bin/lake.exe"
    env = clean_env()
    def version(exe, flag):
        return subprocess.check_output([str(exe), flag], env=env, text=True, encoding="utf-8", timeout=15).strip()
    lean_version = version(lean, "--version")
    lake_version = version(lake, "--version")
    if LEAN_COMMIT not in lean_version or "version 4.31.0" not in lean_version or "Lean version 4.31.0" not in lake_version:
        raise ValueError("Toolchain binary does not report the author-pinned release")
    if Path(version(lean, "--print-prefix")).resolve() != path:
        raise ValueError("Compiler resolved an unexpected system runtime")
    return {"runtime": lean_version, "lake": lake_version, "runtime_root": path.relative_to(REPO).as_posix(),
            "archive_url": RELEASE_URL, "archive_sha256": RELEASE_SHA256, "archive_bytes": archive.stat().st_size,
            "runtime_files_sha256": files}


def git(path, *args, timeout=30):
    return subprocess.check_output(["git", "-C", str(path), *args], env=clean_env(), timeout=timeout)


def verify_git_checkout(path, expected):
    head = git(path, "rev-parse", "HEAD").decode().strip()
    if head != expected or git(path, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"Source worktree differs from pin: {path.name}")
    return {"commit": head, "tree": git(path, "rev-parse", "HEAD^{tree}").decode().strip()}


def shallow_checkout(path, remote, commit):
    path = scoped(path)
    parsed = urlsplit(remote)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        raise ValueError("Expected a pinned public GitHub HTTPS source")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="d39-shallow-", dir=path.parent) as stage:
            staged = Path(stage) / "worktree"
            staged.mkdir()
            git(staged, "init", "-q")
            git(staged, "remote", "add", "origin", remote)
            git(staged, "fetch", "-q", "--depth=1", "origin", commit, timeout=180)
            git(staged, "-c", "core.autocrlf=false", "checkout", "-q", "--detach", "FETCH_HEAD", timeout=80)
            verify_git_checkout(staged, commit)
            staged.replace(path)
    if git(path, "remote", "get-url", "origin").decode().strip() != remote:
        raise ValueError(f"Unexpected Git remote for {path.name}")
    return {"url": remote, **verify_git_checkout(path, commit)}


def materialize_author():
    root = scoped(AUTHOR_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    source_tar = root / "BlueprintRepair-source.tar"
    if not AUTHOR_GIT.exists():
        with tempfile.TemporaryDirectory(prefix="d39-author-git-", dir=root) as stage:
            source = Path(stage) / AUTHOR_GIT.name
            git(Path(stage), "init", "-q", "--bare", source.name)
            git(source, "remote", "add", "origin", AUTHOR)
            git(source, "fetch", "-q", "--depth=1", "origin", AUTHOR_COMMIT, timeout=180)
            git(source, "update-ref", "refs/heads/pinned", AUTHOR_COMMIT)
            git(source, "symbolic-ref", "HEAD", "refs/heads/pinned")
            source.replace(AUTHOR_GIT)
    head = git(AUTHOR_GIT, "rev-parse", "HEAD").decode().strip()
    remote = git(AUTHOR_GIT, "remote", "get-url", "origin").decode().strip()
    if head != AUTHOR_COMMIT or remote != AUTHOR:
        raise ValueError("Bare author source differs from the frozen public commit")
    subtree = git(AUTHOR_GIT, "rev-parse", "HEAD:BlueprintRepair").decode().strip()
    if not PROJECT.exists():
        with tempfile.TemporaryDirectory(prefix="d39-author-archive-", dir=root) as stage:
            work = Path(stage)
            path = work / source_tar.name
            stamp = git(AUTHOR_GIT, "show", "-s", "--format=%cI", AUTHOR_COMMIT).decode().strip()
            git(AUTHOR_GIT, "-c", "core.autocrlf=false", "archive", "--format=tar", "--prefix=BlueprintRepair/", f"--mtime={stamp}",
                "--output", str(path), subtree, timeout=60)
            with tarfile.open(path) as archive:
                for item in archive:
                    parts = PurePosixPath(item.name).parts
                    if not parts or parts[0] != "BlueprintRepair" or any(":" in part for part in parts):
                        raise ValueError("Unexpected materialized archive member")
                archive.extractall(work, filter="data")
            path.replace(source_tar)
            (work / PROJECT.name).replace(PROJECT)
    members = git(AUTHOR_GIT, "ls-tree", "-r", "-z", subtree).split(b"\0")
    checked = 0
    for item in filter(None, members):
        meta, raw_name = item.split(b"\t", 1)
        _, kind, oid = meta.split()
        target = PROJECT / raw_name.decode()
        if kind != b"blob" or not target.is_file() or target.is_symlink():
            raise ValueError("Materialized project source type differs from the commit")
        data = target.read_bytes()
        header = f"blob {len(data)}\0".encode()
        if hashlib.sha1(header + data).hexdigest().encode() != oid:
            raise ValueError(f"Author project blob changed: {target.name}")
        checked += 1
    return {"url": remote, "commit": head, "tree": git(AUTHOR_GIT, "rev-parse", "HEAD^{tree}").decode().strip(),
            "subtree": "BlueprintRepair", "subtree_git_sha1": subtree, "verified_materialized_blobs": checked,
            "archive_sha256": file_sha(source_tar), "archive_bytes": source_tar.stat().st_size}


def source_manifest():
    raw = (D38 / "blueprint_trace_freeze.json").read_bytes()
    if sha(raw) != TRACE_FREEZE_SHA256 or json.loads(raw)["artifact_commit"] != AUTHOR_COMMIT:
        raise ValueError("D3.8 trace freeze differs from the pinned author artifact")
    # The full commit has TeX artifact paths containing colons. Only the exact
    # project subtree is materialized, with all Git/NTFS protection retained.
    author = materialize_author()
    assets = {}
    for name in (*AUTHOR_ASSET_HASHES, "lakefile.toml"):
        committed = git(AUTHOR_GIT, "show", author["subtree_git_sha1"] + ":" + name)
        digest = sha(committed)
        if (PROJECT / name).read_bytes() != committed or name in AUTHOR_ASSET_HASHES and digest != AUTHOR_ASSET_HASHES[name]:
            raise ValueError(f"Author runtime asset differs from the D3.8 source pin: {name}")
        assets[name] = {"sha256": digest, "bytes": len(committed)}
    manifest = json.loads((PROJECT / "lake-manifest.json").read_bytes())
    if manifest["packagesDir"] != ".lake/packages" or (PROJECT / "lean-toolchain").read_text().strip() != TOOLCHAIN:
        raise ValueError("Unexpected author project package location or toolchain")
    pins = {entry["name"]: entry for entry in manifest["packages"]}
    if pins["mathlib"]["rev"] != MATHLIB_COMMIT or pins["LeanArchitect"]["rev"] != ARCHITECT_COMMIT:
        raise ValueError("Author's direct dependency revisions differ from the freeze")
    return author, assets, pins


def fetch_sources():
    start = perf_counter()
    author, assets, pins = source_manifest()
    def fetch(entry):
        return shallow_checkout(PROJECT / ".lake/packages" / entry["name"], entry["url"], entry["rev"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        data = dict(zip(pins, pool.map(fetch, pins.values()), strict=True))
    for name in ("mathlib", "LeanArchitect"):
        path = PROJECT / ".lake/packages" / name / "lean-toolchain"
        if path.read_text().strip() != TOOLCHAIN:
            raise ValueError(f"Direct package toolchain differs: {name}")
    return {"author": author, "asset_hashes": assets, "packages": data,
            "trace_freeze_sha256": TRACE_FREEZE_SHA256, "setup_wall_seconds": perf_counter() - start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("toolchain", "sources", "verify_toolchain"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    actions = {"toolchain": install_toolchain, "sources": fetch_sources, "verify_toolchain": verify_toolchain}
    result = actions[args.action]()
    raw = (json.dumps(result, indent=2) + "\n").encode()
    if args.output:
        with args.output.open("xb") as receipt:
            receipt.write(raw)
    print(raw.decode(), end="")


if __name__ == "__main__":
    main()
