#!/usr/bin/env python3
"""Independent read-only all-refs Git history credential-signature audit.

Only redacted file IDs, paths, sizes, rule names and counts are persisted.
No credential/helper/config inspection, active-key validation, Git writes or GPU.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(r"D:\ACL")
OUT = ROOT/"research/repository_phase_plan_20261106"


def opaque(value):
    return "h_"+hashlib.sha256(("independent_history_v1:"+value).encode()).hexdigest()[:20]


def main():
    begin = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    spec = importlib.util.spec_from_file_location("redacted_inventory_rules", OUT/"audit_publication_inventory.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    # Credential-only independent pass: no email/IP/path values or excerpts emitted.
    audit.PRIVACY_RULES = {}
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    def git(*args, data=None):
        proc = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(ROOT), *args],
                              input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if proc.returncode:
            raise RuntimeError("Read-only Git command failed: "+args[0])
        return proc.stdout
    head_start = git("rev-parse", "HEAD").strip().decode()
    objects, names = set(), {}
    for line in git("rev-list", "--all", "--objects").splitlines():
        bits = line.split(b" ", 1)
        oid = bits[0].decode()
        objects.add(oid)
        if len(bits) > 1:
            names[oid] = bits[1].decode("utf-8", "replace")
    meta = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
               data=("\n".join(sorted(objects))+"\n").encode())
    selected = []
    all_type_counts = Counter()
    for line in meta.splitlines():
        oid, kind, size = line.decode().split()
        all_type_counts[kind] += 1
        if kind in {"blob", "commit", "tag"}:
            selected.append((oid, kind, int(size)))
    cat = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    inventory, candidates, statuses, rules = [], [], Counter(), Counter()
    try:
        for index, (oid, kind, size) in enumerate(selected):
            cat.stdin.write((oid+"\n").encode()); cat.stdin.flush()
            header = cat.stdout.readline().decode().split()
            if len(header) != 3 or header[0] != oid or int(header[2]) != size:
                raise RuntimeError("Git object stream header mismatch")
            def blocks():
                left = size
                while left:
                    data = cat.stdout.read(min(1024*1024, left))
                    if not data: raise RuntimeError("Truncated Git object stream")
                    left -= len(data)
                    yield data
            name = names.get(oid, "git_"+kind+".txt")
            status, findings = audit.scan_chunks(blocks(), name)
            if cat.stdout.read(1) != b"\n": raise RuntimeError("Git object newline missing")
            findings = [item for item in findings if item["kind"] == "credential"]
            row = {"file_id": opaque(oid), "object_type": kind, "bytes": size,
                   "representative_path": audit.path_display(name) if kind == "blob" else None,
                   "scan_status": status, "findings": findings}
            inventory.append(row)
            statuses[status] += 1
            for finding in findings: rules[finding["rule"]] += finding["count"]
            if findings: candidates.append(row)
            if (index+1) % 250 == 0:
                print(json.dumps({"stage": "history_only", "scanned_objects": index+1,
                                  "credential_candidate_objects_so_far": len(candidates)}), flush=True)
    finally:
        cat.stdin.close(); cat.stdout.close(); cat.wait()
    head_end = git("rev-parse", "HEAD").strip().decode()
    result = {"schema_version": "independent_history_credential_audit_v1", "root": str(ROOT),
              "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": time.monotonic()-begin,
              "head_start": head_start, "head_end": head_end, "head_changed": head_start != head_end,
              "all_reachable_object_type_counts": dict(all_type_counts),
              "examined_blob_commit_tag_objects": len(inventory),
              "scan_status_counts": dict(statuses), "credential_candidate_objects": len(candidates),
              "credential_rule_counts": dict(rules), "candidates": candidates, "inventory": inventory,
              "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rules_source_sha256": hashlib.sha256((OUT/"audit_publication_inventory.py").read_bytes()).hexdigest(),
              "limitations": [
                "Heuristic signatures/literal assignments only; not an active credential verification or secret-free proof.",
                "Known placeholder patterns are filtered. Generic model token terminology never constitutes a match.",
                "Binary/compressed/archive/PDF payloads are not decoded/OCR-scanned; their exclusion/status is explicit.",
                "Only objects reachable from all current local refs; no dangling objects, reflogs or remote clone audit.",
                "Representative Git path only; identical blobs may have more historical aliases.",
                "No source text, credential, secret-derived hash, commit message, author email or match value is persisted."
              ]}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/"history_credential_audit_independent.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(path), "credential_candidate_objects": len(candidates),
                      "rule_counts": dict(rules), "examined": len(inventory), "seconds": result["elapsed_seconds"]}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
