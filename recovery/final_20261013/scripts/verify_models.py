"""Verify local Qwen files against a frozen Hugging Face revision, not names."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--path", required=True)
    p.add_argument("--metadata", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    root = Path(args.path)
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    report = {"model_id": metadata["id"], "revision": metadata["sha"], "path": str(root), "files": []}
    for item in metadata["siblings"]:
        name = item["rfilename"]
        if name in [".gitattributes", "README.md", "LICENSE"]:
            continue
        f = root / name
        record = {"name": name, "exists": f.is_file()}
        if f.is_file():
            sha = hashlib.sha256()
            with f.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    sha.update(block)
            record.update(bytes=f.stat().st_size, sha256=sha.hexdigest())
            if item.get("lfs"):
                record["matches_revision"] = sha.hexdigest() == item["lfs"]["sha256"]
            else:
                b = f.read_bytes()
                record["matches_revision"] = hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest() == item["blobId"]
        report["files"].append(record)
        print(name,record.get("matches_revision",False),flush=True)
    report["all_match"] = all(r.get("matches_revision",False) for r in report["files"])
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["all_match"]:
        raise SystemExit("Model file mismatch: do not assign an unverified revision")


if __name__ == "__main__":
    main()
