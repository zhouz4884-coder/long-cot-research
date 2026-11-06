"""Metadata-only refinement of completed redacted scan; no source-content rescan.

Separates HEAD commit ancestry from an additional directly tree-valued local ref,
adds representative paths for the latter, and distinguishes generated figure PDFs.
"""
from pathlib import Path
import collections
import hashlib
import importlib.util
import json
import os
import subprocess

base = Path(__file__).resolve().parent
inventory = base/"publication_inventory_20261106.json"
raw = inventory.read_bytes()
data = json.loads(raw)
spec = importlib.util.spec_from_file_location("publication_rules", base/"audit_publication_inventory.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)
environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
def git(*args):
    return subprocess.check_output(["git", "-c", "core.quotePath=false", "-C", data["root"], *args], env=environment)
head = {x.split(b" ",1)[0].decode() for x in git("rev-list", "--objects", "HEAD").splitlines()}
all_paths = collections.defaultdict(set)
for line in git("rev-list", "--objects", "--all").splitlines():
    split = line.split(b" ",1)
    if len(split)==2 and split[1]: all_paths[rules.opaque("git-object:"+split[0].decode())].add(split[1].decode("utf-8", "surrogateescape"))
head_ids = {rules.opaque("git-object:"+oid) for oid in head}
for row in data["current_files"]:
    row["categories"] = rules.categories(row["path"])
    row["recommended_action"] = rules.action(row["categories"], row["findings"], row["content_scan"], row["bytes"])
for row in data["reachable_history_and_index"]:
    row["paths"] = sorted(set(row["paths"])|{rules.path_display(p) for p in all_paths[row["file_id"]]})
    row["categories"] = sorted({c for path in row["paths"] for c in rules.categories(path)})
    row["reachable_from_HEAD_history"] = row["file_id"] in head_ids
    row["only_extra_refs_or_index_not_HEAD"] = row["file_id"] not in head_ids
    if row["object_type"]=="blob": row["recommended_action"] = rules.action(row["categories"], row["findings"], row["content_scan"], row["bytes"])
data["current_actions"] = dict(collections.Counter(r["recommended_action"] for r in data["current_files"]))
data["metadata_refinement"] = {
    "content_scan_repeated": False,
    "original_scan_inventory_sha256": data.get("metadata_refinement", {}).get("original_scan_inventory_sha256", hashlib.sha256(raw).hexdigest()),
    "refinement_parent_inventory_sha256": hashlib.sha256(raw).hexdigest(),
    "original_content_scanner_sha256": data["audit_source_sha256"],
    "classification_source_sha256": hashlib.sha256((base/"audit_publication_inventory.py").read_bytes()).hexdigest(),
    "refinement_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "all_ref_object_type_counts": dict(collections.Counter(git("for-each-ref", "--format=%(objecttype)").decode().splitlines())),
    "HEAD_history_blob_count": sum(r["object_type"]=="blob" and r["reachable_from_HEAD_history"] for r in data["reachable_history_and_index"]),
    "extra_ref_blob_count_not_HEAD": sum(r["object_type"]=="blob" and not r["reachable_from_HEAD_history"] for r in data["reachable_history_and_index"]),
    "note": "Ordinary explicit branch push transfers its ancestry, not an unrelated tree-valued ref. Mirror/refspec choices can expand scope. Generated figure PDFs are origin-review candidates, not automatically third-party papers."
}
data["history_scope_groups"] = {}
for name, wanted in (("HEAD_commit_ancestry", True), ("additional_refs_not_HEAD", False)):
    selected = [r for r in data["reachable_history_and_index"] if r["object_type"]=="blob" and r["reachable_from_HEAD_history"]==wanted]
    data["history_scope_groups"][name] = {
        "blob_count": len(selected), "bytes": sum(r["bytes"] for r in selected),
        "category_object_counts": dict(collections.Counter(c for r in selected for c in r["categories"])),
        "scope_review_paths": sorted({p for r in selected if set(r["categories"])&{"paper_or_document_fulltext_pdf", "external_fulltext_or_source_render", "user_attachment_or_external_source", "archive_or_duplicate_package", "other_queue_inventory_exclude"} for p in r["paths"]}),
        "credential_candidate_objects": sum(any(f["kind"]=="credential" for f in r["findings"]) for r in selected)}
data["large_history_blobs_10MiB_plus"] = [r for r in data["reachable_history_and_index"] if r["object_type"]=="blob" and r["bytes"]>=10*1024**2]
inventory.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"metadata_refinement":data["metadata_refinement"],"history_scope_groups":data["history_scope_groups"]},ensure_ascii=True,indent=2))
