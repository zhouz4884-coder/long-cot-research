"""Fetch atomic paired-generation files while preserving prior byte receipts."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import sys

from fetch_coverage import local_destination, remote_bytes, sha, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    remote = json.loads((root / "COVERAGE_LAUNCH.json").read_text(encoding="utf-8"))["root"]
    sys.path.insert(0, "C:/Users/LENOVO/.codex/local-tools")
    from contractkv_ssh_credential import ssh_client
    client = ssh_client()
    sftp = client.open_sftp()
    rows = []
    try:
        def fetch(relative):
            raw = remote_bytes(sftp, remote + "/" + relative)
            destination = local_destination(root, relative)
            mutable = "progress" in destination.name or "launcher" in destination.name or destination.suffix == ".log"
            if destination.exists() and not mutable and destination.read_bytes() != raw:
                raise ValueError("Previously retrieved paired evidence changed")
            if destination.suffix == ".json":
                json.loads(raw)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".download.tmp")
            temporary.write_bytes(raw)
            temporary.replace(destination)
            rows.append({"path": relative, "bytes": len(raw), "sha256": sha(raw)})

        def walk(relative):
            for entry in sorted(sftp.listdir_attr(remote + "/" + relative), key=lambda item: item.filename):
                child = relative + "/" + entry.filename
                if stat.S_ISLNK(entry.st_mode):
                    raise ValueError("Remote artifact symlink is unsupported")
                if stat.S_ISDIR(entry.st_mode):
                    walk(child)
                elif not entry.filename.endswith(".tmp"):
                    fetch(child)

        walk("paired_results")
        for worker in (0, 1):
            fetch(f"logs/pairing_{worker}.log")
        fetch("pairing_launcher.json")
        status = json.loads((root / "pairing_launcher.json").read_text(encoding="utf-8"))
        report = {"retrieved_utc": datetime.now(timezone.utc).isoformat(), "launcher": status,
                  "status": "COMPLETE" if status["status"] == "FINISHED" and all(worker["exit_code"] == 0 for worker in status["workers"]) else "IN_PROGRESS_OR_FAILED",
                  "files": rows}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_json(root / "pairing_fetch_receipts" / (stamp + ".json"), report)
        write_json(root / "PAIRING_RETRIEVAL_MANIFEST.json", report)
        print(json.dumps({"status": report["status"], "files": len(rows), "launcher": status}, indent=2))
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
