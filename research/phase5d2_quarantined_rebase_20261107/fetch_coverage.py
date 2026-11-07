"""Fetch atomic D2 artifacts with byte receipts through the approved SSH helper."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys


ROOT = Path(__file__).resolve().parent
MODEL_ROOT = "/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B"
TOKENIZER_ASSETS = (
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "merges.txt", "vocab.json", "config.json", "generation_config.json",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".download.tmp")
    temp.write_bytes(raw)
    temp.replace(path)


def remote_bytes(sftp, path):
    with sftp.open(path, "rb") as stream:
        return stream.read()


def local_destination(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..") for part in parts):
        raise ValueError("Unsupported artifact path")
    destination = root.joinpath(*parts).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("Artifact destination leaves the chosen directory")
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--remote-root")
    parser.add_argument("--helper-dir", type=Path, default=Path("C:/Users/LENOVO/.codex/local-tools"))
    parser.add_argument("--tokenizer-output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    launch = json.loads((root / "COVERAGE_LAUNCH.json").read_text(encoding="utf-8"))
    remote = args.remote_root or launch["root"]
    if not PurePosixPath(remote).is_absolute() or ".." in PurePosixPath(remote).parts:
        raise ValueError("Remote study path must be an absolute directory")
    sys.path.insert(0, str(args.helper_dir))
    from contractkv_ssh_credential import ssh_client

    client = ssh_client()
    sftp = client.open_sftp()
    downloaded = []
    try:
        status_raw = remote_bytes(sftp, remote + "/coverage_launcher.json")
        status = json.loads(status_raw)
        finished = status.get("status") == "FINISHED"

        def fetch(relative):
            data = remote_bytes(sftp, remote + "/" + relative)
            destination = local_destination(root, relative)
            immutable = destination.name in ("result.json", "manifest.json", "summary.json", "started.json")
            if destination.suffix == ".json":
                parsed = json.loads(data)
                if destination.name == "result.json" and parsed.get("status") != "COMPLETE":
                    raise ValueError("A result is not an atomic completed record")
            if immutable and destination.exists() and destination.read_bytes() != data:
                raise ValueError("Previously fetched immutable artifact changed: " + relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(destination.name + ".download.tmp")
            temp.write_bytes(data)
            temp.replace(destination)
            downloaded.append({"path": relative, "bytes": len(data), "sha256": sha(data)})

        def walk(relative):
            try:
                entries = sftp.listdir_attr(remote + "/" + relative)
            except FileNotFoundError:
                return
            for entry in sorted(entries, key=lambda value: value.filename):
                child = relative + "/" + entry.filename
                if stat.S_ISLNK(entry.st_mode):
                    raise ValueError("Artifact symlink is unsupported")
                if stat.S_ISDIR(entry.st_mode):
                    walk(child)
                elif not entry.filename.endswith(".tmp"):
                    fetch(child)

        walk("native_results")
        walk("logs")
        # A live launch status can advance while result files are being fetched.
        fetch("coverage_launcher.json")
        status = json.loads((root / "coverage_launcher.json").read_text(encoding="utf-8"))
        finished = status.get("status") == "FINISHED"
        process_ids = {int(status["launcher_pid"])}
        process_ids.update(int(worker["pid"]) for worker in status.get("workers", []))
        command = "ps -p " + ",".join(str(pid) for pid in sorted(process_ids)) + " -o pid=,ppid=,stat=,etime=,comm="
        _, stdout, stderr = client.exec_command(command)
        process_snapshot = stdout.read().decode("utf-8")
        process_error = stderr.read().decode("utf-8")
        process_exit = stdout.channel.recv_exit_status()
        if process_exit not in (0, 1) or process_error:
            raise RuntimeError("Remote process observation failed")
        if args.tokenizer_output is not None:
            asset_records = None
            for worker in (0, 1):
                path = root / "native_results" / f"worker_{worker}" / "manifest.json"
                if path.exists():
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    model = manifest["model_files"]
                    if model["manifest_sha256"] != "37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511":
                        raise ValueError("Coverage worker model differs")
                    asset_records = {row["name"]: row for row in model["files"]}
                    break
            if asset_records is None:
                raise RuntimeError("Wait for a worker model manifest before fetching tokenizer assets")
            tokenizer_root = args.tokenizer_output.resolve()
            tokenizer_rows = []
            for name in TOKENIZER_ASSETS:
                if name not in asset_records:
                    continue
                raw = remote_bytes(sftp, MODEL_ROOT + "/" + name)
                expected = asset_records[name]
                if sha(raw) != expected["sha256"] or len(raw) != expected["size_bytes"]:
                    raise ValueError("Tokenizer/config asset differs from the worker manifest")
                destination = local_destination(tokenizer_root, name)
                if destination.exists() and destination.read_bytes() != raw:
                    raise ValueError("Local tokenizer/config asset changed")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                tokenizer_rows.append({"path": name, "bytes": len(raw), "sha256": sha(raw)})
            write_json(tokenizer_root / "TOKENIZER_FETCH_MANIFEST.json", {
                "model_manifest": model["manifest_sha256"], "files": tokenizer_rows,
            })
        completed = sum(row["path"].endswith("/result.json") for row in downloaded)
        protocol = json.loads((root / "COVERAGE_PROTOCOL.json").read_text(encoding="utf-8"))
        planned = protocol["questions"] * len(protocol["seeds"])
        receipt = {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "remote_root": remote,
            "launcher_status": status.get("status"),
            "complete_download_snapshot": finished and completed == planned,
            "completed_trajectory_files": completed,
            "planned_trajectories": planned,
            "process_observation": {"requested_pids": sorted(process_ids), "ps_output": process_snapshot,
                                    "exit_code": process_exit},
            "scope": "Atomic completed results and progress/status/log snapshots. Partial fetches support coverage monitoring.",
            "files": downloaded,
        }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_json(root / "coverage_fetch_receipts" / (timestamp + ".json"), receipt)
        write_json(root / "COVERAGE_RETRIEVAL_MANIFEST.json", receipt)
        print(json.dumps({key: value for key, value in receipt.items() if key != "files"}, ensure_ascii=False, indent=2))
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
