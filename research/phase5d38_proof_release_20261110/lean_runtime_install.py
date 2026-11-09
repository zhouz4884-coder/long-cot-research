"""Install a SHA-pinned official Lean 4 distribution inside workspace outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
from time import perf_counter
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
VERSION = "4.27.0"
ARCHIVE = f"lean-{VERSION}-windows.tar.zst"
PREFIX = f"lean-{VERSION}-windows"
URL = f"https://github.com/leanprover/lean4/releases/download/v{VERSION}/{ARCHIVE}"
SHA256 = "c34b9c2820857185978fc7310c8badeda68c9c16e83edecf176a8003c5fda1b2"
ROOT = REPO / "outputs" / "d38_lean_4_27_0_windows"
REQUIRED_SHA256 = {
    "bin/lean.exe": "ae20fac75dfa9d92866f9c08acdff978c0f06020ab8c4ee4fc9af9505238cf81",
    "bin/lake.exe": "cf3f1119fe62a1963b527bc4ff8fce2d32c8948fc2553b6e20ef7a9787eb59e9",
    "lib/lean/Init.olean": "20b419dfc12a9527a50673966008780f9c2110339753d4722ef92c8ab7c5204c",
    "lib/lean/Lean.olean": "86178b72126294e667cda343fba4ff3f5c79e6f27dcc70fe3c0193c49d1040fc",
    "lib/lean/Std.olean": "d4121ba485c2eda293cd6a530888370a1a0dde7f4d573ccd733362efd07bc102",
}


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_required(runtime):
    actual = {name: file_sha(runtime / name) for name in REQUIRED_SHA256}
    if actual != REQUIRED_SHA256:
        raise ValueError("Extracted Lean executable or core modules differ from frozen runtime")
    return actual


def fetch(path):
    began = perf_counter()
    request = Request(URL, headers={"User-Agent": "D38-Lean-Official-Release"})
    with tempfile.NamedTemporaryFile(prefix="lean-download-", dir=path.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            with urlopen(request, timeout=45) as response:
                shutil.copyfileobj(response, temp, 4 * 1024 * 1024)
        except BaseException:
            temp.close()
            staged.unlink()
            raise
    if file_sha(staged) != SHA256:
        staged.unlink()
        raise ValueError("Official archive SHA-256 mismatch")
    staged.replace(path)
    return perf_counter() - began


def install(root):
    import zstandard

    outputs = (REPO / "outputs").resolve()
    root = root.resolve()
    if root == outputs or not root.is_relative_to(outputs):
        raise ValueError("Lean installation must stay inside the workspace outputs directory")
    if platform.system() != "Windows" or platform.machine().upper() not in {"AMD64", "X86_64"}:
        raise ValueError("This runtime receipt is pinned to Windows x64")
    root.mkdir(parents=True, exist_ok=True)
    archive = root / ARCHIVE
    seconds = fetch(archive) if not archive.exists() else None
    if file_sha(archive) != SHA256:
        raise ValueError("Existing archive does not match the pinned release bytes")
    installed = root / PREFIX
    extract_seconds = None
    if not installed.exists():
        began = perf_counter()
        with tempfile.TemporaryDirectory(prefix="lean-extract-", dir=root) as work:
            staging = Path(work)
            with archive.open("rb") as packed, zstandard.ZstdDecompressor().stream_reader(packed) as unpacked:
                with tarfile.open(fileobj=unpacked, mode="r|") as source:
                    source.extractall(staging, filter="data")
            verified = staging / PREFIX
            if not (verified / "bin/lean.exe").is_file() or not (verified / "lib/lean/Lean.olean").is_file():
                raise ValueError("Extracted archive is missing required Lean runtime files")
            verified.replace(installed)
        extract_seconds = perf_counter() - began
    runtime = verify_required(installed)
    return {"archive_url": URL, "archive_sha256": SHA256, "archive_bytes": archive.stat().st_size,
            "download_wall_seconds": seconds, "extract_wall_seconds": extract_seconds,
            "runtime_root": installed.relative_to(REPO).as_posix(), "files_sha256": runtime,
            "zstandard": zstandard.__version__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(install(args.root), indent=2))


if __name__ == "__main__":
    main()
