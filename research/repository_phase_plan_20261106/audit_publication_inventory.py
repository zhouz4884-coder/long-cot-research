#!/usr/bin/env python3
"""Read-only worktree/index/all-reachable-Git publication inventory.

Never prints or stores matched credential/PII strings, source snippets, commit
messages, credential-helper output, or secret hashes. Only rule/count/opaque
file identity/path metadata are emitted. No Git mutation or network operation.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import codecs
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import zipfile


MIB = 1024**2
TEXT_EXTENSIONS = {".py", ".ps1", ".sh", ".json", ".jsonl", ".yaml", ".yml", ".md", ".txt", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".bib", ".ris", ".tex", ".log", ".env", ".xml"}
BINARY_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".xz", ".bz2", ".7z", ".tar", ".npz", ".npy", ".pt", ".pth", ".pkl", ".pickle", ".safetensors", ".bin", ".dll", ".pyd", ".so", ".exe", ".whl", ".pyc", ".woff", ".woff2", ".ttf"}
ARCHIVES = {".zip", ".gz", ".xz", ".bz2", ".7z", ".tar", ".whl"}
RUNTIME_NAMES = {".tools", ".venv", "venv", "env", "vendor", "site-packages", "__pycache__", "runtime4552", "node_modules"}
SECRET_RULES = {
    "github_token_signature": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "openai_key_signature": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    "huggingface_key_signature": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    "aws_access_key_signature": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key_signature": re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    "bearer_literal": re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~-]{24,})"),
    "credential_url_password": re.compile(r"(?i)\b(?:https?|ssh|sftp)://[^\s/:@]{1,80}:([^\s/@]{4,})@"),
    "credential_assignment_literal": re.compile(r'''(?ix)(?:["']?\b(?:password|passwd|pwd|api_key|api_secret|access_token|refresh_token|client_secret|secret_key|aws_secret_access_key|hf_token|github_token)\b["']?)\s*[:=]\s*["']([^\r\n"']{4,256})["']'''),
    "private_key_material": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\s*\n([A-Za-z0-9+/=\r\n]{120,20000})-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
}
PRIVACY_RULES = {
    "email_address_present_review_context": re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "private_ipv4_operational_metadata": re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"),
    "absolute_windows_user_path": re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\s\\/\"'<>]{1,80}"),
    "absolute_linux_home_path": re.compile(r"(?<![A-Za-z0-9])/(?:home|root)/[^\s/\"'<>]{1,80}"),
    "phone_field_literal_review": re.compile(r'''(?ix)(?:["']?\b(?:phone|mobile|telephone|手机号)\b["']?)\s*[:=]\s*["']?(\+?[0-9][0-9 -]{7,18})'''),
}


def opaque(value):
    return "f_"+hashlib.sha256(("ACL_publication_audit_v1:"+value).encode("utf-8", "replace")).hexdigest()[:20]


def path_display(path):
    # Paths normally are safe metadata. Defensive redaction handles embedded URLs/credential-shaped names.
    value = path.replace("\\", "/")
    for pattern in SECRET_RULES.values():
        value = pattern.sub("[REDACTED_PATH_COMPONENT]", value)
    return value


def placeholder(value):
    stripped = value.strip()
    if re.search(r"(?i)(example|placeholder|dummy|changeme|your[_ -]|not[_ -]?real|fake|<|>|\$\{|os\.|environ|xxxxx)", stripped): return True
    if stripped.lower() in {"none", "null", "true", "false", "password", "secret", "test", "testing", "pass", "token", "api_key"}: return True
    if len(set(stripped)) <= 2: return True
    return False


class Scanner:
    def __init__(self):
        self.tail = ""
        self.offset = 0
        self.seen = set()
        self.counts = Counter()
    def feed(self, chunk):
        text = self.tail+chunk
        origin = self.offset-len(self.tail)
        for bucket, rules in (("credential", SECRET_RULES), ("privacy", PRIVACY_RULES)):
            for rule, pattern in rules.items():
                for match in pattern.finditer(text):
                    position = (rule, origin+match.start(), origin+match.end())
                    if position in self.seen: continue
                    self.seen.add(position)
                    candidate = match[1] if match.lastindex else match[0]
                    if bucket == "credential" and placeholder(candidate): continue
                    self.counts[bucket+":"+rule] += 1
        self.offset += len(chunk)
        self.tail = text[-32768:]
    def result(self):
        return [{"kind": key.split(":", 1)[0], "rule": key.split(":", 1)[1], "count": count,
                 "interpretation": "literal/signature candidate, never verified against service" if key.startswith("credential:") else "context review; may be public bibliographic or normal author metadata"}
                for key, count in sorted(self.counts.items())]


def categories(path):
    p = Path(path)
    parts = [s.lower() for s in path.replace("\\", "/").split("/")]
    name, ext = p.name.lower(), p.suffix.lower()
    flags = []
    if any(x in RUNTIME_NAMES or x.startswith("runtime4552") for x in parts) or ext in {".pyc", ".pyd", ".dll", ".so", ".exe", ".whl"}:
        flags.append("runtime_or_vendor_copy")
    if "models" in parts or ext in {".safetensors", ".bin", ".pt", ".pth"}: flags.append("model_or_tensor_binary")
    if ext in ARCHIVES: flags.append("archive_or_duplicate_package")
    if ext == ".pdf":
        if any(x in {"figures", "plots"} for x in parts): flags.append("generated_research_figure_candidate")
        elif any(x in {"sources", "inputs", "pdfs"} or "literature" in x for x in parts): flags.append("paper_or_document_fulltext_pdf")
        else: flags.append("pdf_origin_review")
    if any(x in {"inputs", "attachments", "goal_sources", "official_sources"} for x in parts) or re.search(r"用户|已粘贴|用户讨论|USER_DIAGNOSIS|USER_ROADMAP", p.name, re.I):
        flags.append("user_attachment_or_external_source")
    if "sources" in parts and ext not in {".bib", ".ris", ".json"}: flags.append("external_fulltext_or_source_render")
    if any(x in {"extracted_text", "rendered_pages"} for x in parts) or ("research" in parts and "renders" in parts): flags.append("external_fulltext_or_source_render")
    if re.match(r"^20\d{2}\.(?:acl|emnlp|findings|icml|iclr|neurips)[.-].*\.(?:txt|jsonl)$", name): flags.append("external_fulltext_or_source_render")
    if ext in {".png", ".jpg", ".jpeg"} and re.search(r"page|paper|deer|table|full", name): flags.append("source_page_image_review")
    if ext in {".npz", ".npy", ".pkl", ".pickle"}: flags.append("large_numeric_or_serialized_artifact")
    if ext in {".jsonl", ".csv", ".tsv"} or "data" in parts or any("bank" in x or "trace" in x for x in parts): flags.append("dataset_or_raw_trace_license_review")
    if "logs" in parts or ext == ".log" or re.search(r"preflight|deployment|ssh_|queue|worker|live_observation|goal_sources", name): flags.append("operational_or_personal_metadata_review")
    if name in {".env", ".env.local", "id_rsa", "id_ed25519", "credentials", ".netrc"} or ext in {".pem", ".key", ".p12", ".pfx"}: flags.append("credential_file_name_review")
    if re.search(r"v100.*inventory.*0?2", name): flags.append("other_queue_inventory_exclude")
    if any(x.startswith(".git") for x in parts) and ".gitignore" not in parts and ".gitattributes" not in parts: flags.append("git_internal_or_nested_repo")
    return sorted(set(flags))


def action(flags, findings, scanned, size):
    if any(f["kind"] == "credential" for f in findings): return "WITHHOLD_CREDENTIAL_CANDIDATE"
    exclusions = {"runtime_or_vendor_copy", "model_or_tensor_binary", "archive_or_duplicate_package", "paper_or_document_fulltext_pdf",
                  "user_attachment_or_external_source", "external_fulltext_or_source_render", "credential_file_name_review", "git_internal_or_nested_repo", "other_queue_inventory_exclude"}
    if set(flags)&exclusions: return "EXCLUDE_FROM_INITIAL_SNAPSHOT"
    if size > 100*MIB: return "EXCLUDE_OVERSIZE_OR_SEPARATE_APPROVED_ARTIFACT"
    if any(f["kind"] == "privacy" for f in findings) or flags or size > 10*MIB: return "REVIEW_REDACT_OR_LICENSE_CHECK"
    if scanned not in {"text_scanned", "empty_file"}: return "REVIEW_UNSCANNED_BINARY"
    return "INCLUDE_CANDIDATE_AFTER_FINAL_ALLOWLIST_REVIEW"


def scan_chunks(chunks, name, skip=False):
    iterator = iter(chunks)
    first = next(iterator, b"")
    scanner = Scanner()
    if not first:
        return "empty_file", []
    extension = Path(name).suffix.lower()
    if skip or extension in BINARY_EXTENSIONS:
        for _ in iterator: pass
        return "excluded_runtime_not_content_scanned" if skip else "binary_or_archive_not_content_scanned", []
    if first.startswith(codecs.BOM_UTF16_LE) or first.startswith(codecs.BOM_UTF16_BE):
        decoder = codecs.getincrementaldecoder("utf-16")("replace")
    elif b"\0" in first[:8192]:
        for _ in iterator: pass
        return "binary_or_unknown_encoding_not_content_scanned", []
    else:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
    scanner.feed(decoder.decode(first))
    for chunk in iterator: scanner.feed(decoder.decode(chunk))
    scanner.feed(decoder.decode(b"", final=True))
    return "text_scanned", scanner.result()


def read_file_chunks(path):
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024*1024)
            if not block: break
            yield block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(r"D:\ACL"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.root.resolve(strict=True), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started, start_utc = time.monotonic(), datetime.now(timezone.utc).isoformat()
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    def git(*arguments, stdin=None):
        result = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *arguments], input=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if result.returncode: raise RuntimeError("Read-only Git command failed: "+arguments[0])
        return result.stdout
    def paths(data): return [s.decode("utf-8", "surrogateescape") for s in data.split(b"\0") if s]
    head_start = git("rev-parse", "HEAD").strip().decode()
    tracked, untracked = set(paths(git("ls-files", "-z"))), set(paths(git("ls-files", "--others", "--exclude-standard", "-z")))
    index = {}
    for item in git("ls-files", "--stage", "-z").split(b"\0"):
        if not item: continue
        info, name = item.split(b"\t", 1)
        mode, oid, stage = info.decode().split()
        index[name.decode("utf-8", "surrogateescape")] = {"oid": oid, "mode": mode, "stage": stage}
    worktree, root_summary, files_meta, walk_errors, reparse_dirs = [], defaultdict(lambda: Counter()), [], [], []
    for directory, dirs, names in os.walk(root, followlinks=False):
        kept = []
        for d in dirs:
            entry = Path(directory)/d
            if d.lower() == ".git": continue
            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                reparse_dirs.append(path_display(entry.relative_to(root).as_posix())); continue
            kept.append(d)
        dirs[:] = kept
        for name in names:
            path = Path(directory)/name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                files_meta.append((rel, 0, True)); continue
            try: size = path.stat().st_size
            except OSError:
                walk_errors.append(opaque(rel)); continue
            files_meta.append((rel, size, False))
            root_summary[rel.split("/")[0]]["files"] += 1
            root_summary[rel.split("/")[0]]["bytes"] += size
    inventory_paths = {rel for rel, _, _ in files_meta if rel in tracked or rel in untracked}
    # Ignored roots are metadata-inventoried too; never copied or read for credentials.
    for rel, size, symlink in files_meta:
        if rel not in inventory_paths: continue
        path = root/rel
        flags = categories(rel)
        status = "tracked" if rel in tracked else "untracked_nonignored"
        skip_runtime = "runtime_or_vendor_copy" in flags
        if symlink: scanned, findings = "symlink_target_not_followed", []
        else:
            try: scanned, findings = scan_chunks(read_file_chunks(path), rel, skip_runtime)
            except (OSError, UnicodeError): scanned, findings = "read_error", []
        worktree.append({"file_id": opaque("worktree:"+rel), "path": path_display(rel), "git_status": status,
                         "bytes": size, "categories": flags, "content_scan": scanned, "findings": findings,
                         "recommended_action": action(flags, findings, scanned, size)})
    print(json.dumps({"stage": "worktree_scanned", "files": len(worktree)}, ensure_ascii=True), flush=True)
    commits = git("rev-list", "--all").splitlines()
    rev_objects = git("rev-list", "--objects", "--all").splitlines()
    all_objects = {line.split(b" ", 1)[0].decode() for line in rev_objects}
    all_objects.update(row["oid"] for row in index.values() if row["mode"] != "160000")
    object_paths = defaultdict(set)
    # --all may also reach a tree-valued ref that is not part of any commit tree.
    for line in rev_objects:
        parts = line.split(b" ", 1)
        if len(parts) == 2 and parts[1]: object_paths[parts[0].decode()].add(parts[1].decode("utf-8", "surrogateescape"))
    trees = set(git("log", "--all", "--format=%T").splitlines())
    for tree in trees:
        for entry in git("ls-tree", "-r", "-z", "--full-tree", tree.decode()).split(b"\0"):
            if not entry: continue
            info, name = entry.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            if kind == "blob": object_paths[oid].add(name.decode("utf-8", "surrogateescape"))
    for name, row in index.items():
        if row["mode"] != "160000": object_paths[row["oid"]].add(name)
    object_list = sorted(all_objects)
    metadata = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", stdin=("\n".join(object_list)+"\n").encode())
    objects = []
    for line in metadata.splitlines():
        oid, kind, size = line.decode().split()
        if kind in {"blob", "commit", "tag"}: objects.append((oid, kind, int(size)))
    cat = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    historical, object_types = [], Counter()
    try:
        for oid, kind, size in objects:
            cat.stdin.write((oid+"\n").encode()); cat.stdin.flush()
            header = cat.stdout.readline().decode().split()
            if len(header) != 3 or header[0] != oid or int(header[2]) != size:
                raise RuntimeError("Git object stream header mismatch")
            def blob_chunks():
                remaining = size
                while remaining:
                    block = cat.stdout.read(min(1024*1024, remaining))
                    if not block: raise RuntimeError("Unexpected Git object stream end")
                    remaining -= len(block)
                    yield block
            names = sorted(object_paths.get(oid, []))
            representative = names[0] if names else "git_"+kind+".txt"
            scanned, findings = scan_chunks(blob_chunks(), representative)
            if cat.stdout.read(1) != b"\n": raise RuntimeError("Git object stream terminator mismatch")
            flags = sorted({f for name in names for f in categories(name)})
            historical.append({"file_id": opaque("git-object:"+oid), "object_type": kind, "bytes": size,
                               "paths": [path_display(name) for name in names], "content_scan": scanned,
                               "categories": flags, "findings": findings,
                               "recommended_action": action(flags, findings, scanned, size) if kind == "blob" else "REVIEW_COMMIT_OR_TAG_METADATA_AND_MESSAGE"})
            object_types[kind] += 1
    finally:
        cat.stdin.close(); cat.stdout.close(); cat.wait()
    print(json.dumps({"stage": "all_reachable_and_index_objects_scanned", "objects": len(historical)}, ensure_ascii=True), flush=True)
    archives = []
    archive_hash_groups = defaultdict(list)
    for rel, size, symlink in files_meta:
        if symlink or Path(rel).suffix.lower() != ".zip" or any(p.lower() in {".tools", ".venv", "vendor", "models"} for p in Path(rel).parts): continue
        path = root/rel
        digest = hashlib.sha256()
        try:
            for block in read_file_chunks(path): digest.update(block)
            archive_hash_groups[digest.hexdigest()].append(path_display(rel))
            with zipfile.ZipFile(path) as z:
                members = z.infolist()
                archives.append({"file_id": opaque("archive:"+rel), "path": path_display(rel), "bytes": size,
                    "entry_count": len(members), "uncompressed_bytes": sum(x.file_size for x in members),
                    "pdf_entries": sum(x.filename.lower().endswith(".pdf") for x in members),
                    "runtime_entries": sum("runtime_or_vendor_copy" in categories(x.filename) for x in members),
                    "credential_filename_entries": sum("credential_file_name_review" in categories(x.filename) for x in members),
                    "encrypted_entries": sum(bool(x.flag_bits&1) for x in members),
                    "content_scope": "Archive directory metadata only; members not extracted or secret-scanned; archive excluded."})
        except (OSError, zipfile.BadZipFile):
            archives.append({"file_id": opaque("archive:"+rel), "path": path_display(rel), "bytes": size, "error": "archive_metadata_unreadable"})
    findings_by_rule = {"current": Counter(), "reachable_history_and_index": Counter()}
    for scope, rows in (("current", worktree), ("reachable_history_and_index", historical)):
        for row in rows:
            for finding in row["findings"]: findings_by_rule[scope][finding["kind"]+":"+finding["rule"]] += finding["count"]
    credential_current = [r for r in worktree if any(f["kind"] == "credential" for f in r["findings"])]
    credential_history = [r for r in historical if any(f["kind"] == "credential" for f in r["findings"])]
    large_current = sorted([{"file_id": opaque("worktree:"+rel), "path": path_display(rel), "bytes": size,
                             "git_status": "tracked" if rel in tracked else "untracked_nonignored" if rel in untracked else "ignored_or_not_candidate"}
                            for rel, size, sym in files_meta if size >= 10*MIB and not sym], key=lambda x: -x["bytes"])
    head_end = git("rev-parse", "HEAD").strip().decode()
    result = {"schema_version": "publication_inventory_redacted_v1", "started_utc": start_utc,
        "completed_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.monotonic()-started,
        "root": str(root), "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Current tracked and nonignored-untracked file contents; metadata for other local files; every blob/commit/annotated-tag reachable from all refs plus index blobs.",
        "never_emitted": "Matched credential/PII values, source snippets, private key/token/password text, commit messages, credential-helper output.",
        "git_snapshot": {"head_start": head_start, "head_end": head_end, "head_changed_during_audit": head_start != head_end,
                         "reachable_commit_count": len(commits), "unique_commit_trees": len(trees), "reachable_plus_index_object_count": len(all_objects)},
        "counts": {"tracked_paths": len(tracked), "untracked_nonignored_paths": len(untracked), "filesystem_metadata_files": len(files_meta),
                   "filesystem_bytes": sum(s for _, s, _ in files_meta), "worktree_content_inventory": len(worktree),
                   "historical_object_types": dict(object_types), "current_credential_candidate_files": len(credential_current),
                   "historical_credential_candidate_objects": len(credential_history)},
        "findings_by_rule": {scope: dict(counts) for scope, counts in findings_by_rule.items()},
        "current_actions": dict(Counter(r["recommended_action"] for r in worktree)),
        "filesystem_top_level_metadata": {k: dict(v) for k, v in sorted(root_summary.items())},
        "current_files": worktree, "reachable_history_and_index": historical,
        "credential_candidates_current": credential_current, "credential_candidates_history": credential_history,
        "large_current_files_10MiB_plus": large_current,
        "large_history_blobs_10MiB_plus": [r for r in historical if r["object_type"] == "blob" and r["bytes"] >= 10*MIB],
        "zip_inventory": archives, "byte_identical_zip_groups": [v for v in archive_hash_groups.values() if len(v)>1],
        "reparse_directories_not_followed": reparse_dirs, "walk_error_ids": walk_errors,
        "limitations": ["Heuristic candidates are not verified active credentials; placeholders filtered; model token vocabulary is not a secret rule.",
            "Compressed/binary/PDF payloads and excluded runtime copies are not plaintext/OCR-scanned; do not call the repository secret-free.",
            "Ignored filesystem contents are metadata-inventoried only; no credential stores/helper or paths outside this workspace were read.",
            "All refs reachable history is covered; dangling objects/reflogs/remote copies not covered.",
            "Concurrent worktree edits may occur; repeat audit on the final isolated allowlist snapshot before upload.",
            "Email detection may be public paper author/Git author metadata; context review needed, not an automatic secret classification."]}
    destination = output/"publication_inventory_20261106.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(destination), "counts": result["counts"], "actions": result["current_actions"],
                      "credential_rule_counts_redacted": {scope: {k:v for k,v in counts.items() if k.startswith("credential:")} for scope,counts in result["findings_by_rule"].items()}}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
