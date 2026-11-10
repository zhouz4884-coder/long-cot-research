"""Project only pinned ComBench construction questions and safe metadata."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha1, sha256
from io import StringIO
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HF_REPO = "Simplified-Reasoning/ComBench"
HF_REV = "110c7561f007ee0ee60410003a98010230b2c937"
CODE_REV = "a1afc8390be8a0cca800845a489454b43e866784"
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/{HF_REV}/"
ASSETS = {
    "data/construction.jsonl": (487780, "1597f9cb0c5aa0739d7d7194c051bfdff46890e4"),
    "metadata/categories.csv": (7631, "6281924a5e1f0065346ca158141122f063a5c8be"),
}
SAFE = ("id", "split", "source", "category", "query", "instruction")
SAFE_METADATA = ("id", "split", "source", "cb_id", "category")
PAPER_EXPOSED = {"IMO-2020-P4", "IMO-2022-P6", "USAMO-2009-P3-20-21"}
PAPER_EXPOSED_SOURCES = {"IMO-2020-P4", "IMO-2022-P6", "USAMO-2009-P3"}
CSV_FIELDS = (*SAFE_METADATA, "secondary_category_raw", "note")


def require(test, message):
    if not test:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, "An immutable local artifact differs")
        return
    with path.open("xb") as stream:
        stream.write(raw)


def verified_asset(raw_root, name):
    expected_size, expected_git = ASSETS[name]
    path = raw_root / name
    if path.exists():
        raw = path.read_bytes()
    else:
        request = Request(HF_BASE + name, headers={"User-Agent": "ComBenchQuestionProjection/1",
                                                   "Accept-Encoding": "identity"})
        with urlopen(request, timeout=30) as stream:
            raw = stream.read(expected_size + 1)
    git_oid = sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    require(len(raw) == expected_size and git_oid == expected_git, "Pinned ComBench source asset differs")
    save(path, raw)
    return raw, {"repository_path": name, "url": HF_BASE + name, "bytes": len(raw),
                 "git_blob_sha1": git_oid, "sha256": digest(raw)}


def unique_pairs(pairs):
    row = dict(pairs)
    if len(row) != len(pairs):
        raise ValueError("Duplicate JSON field")
    return row


def parse_metadata(raw):
    reader = csv.DictReader(StringIO(raw.decode("utf-8")))
    require(tuple(reader.fieldnames or ()) == CSV_FIELDS, "Unexpected category metadata header")
    rows = []
    for entry in reader:
        require(set(entry) == set(CSV_FIELDS), "Malformed metadata record")
        rows.append({key: entry[key] for key in SAFE_METADATA})
    require(len(rows) == 100 and len({row["id"] for row in rows}) == 100
            and Counter(row["split"] for row in rows) == {"analysis": 50, "construction": 50},
            "Category metadata denominator differs")
    return {row["id"]: row for row in rows if row["split"] == "construction"}


def source_family(source):
    match = re.fullmatch(r"([A-Z][A-Z0-9]*)[-_ ](?:19|20)[0-9]{2}.*", source)
    require(match is not None, "Unknown normalized contest identity")
    return match[1]


def normalized_question_sha256(question):
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", question)).strip().casefold()
    return digest(normalized.encode())


def project(raw, metadata):
    """Whole JSONL row parsed inside this trusted projector; only SAFE leaves it."""
    visible, exclusions, seen = [], [], set()
    schemas = Counter()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            source = json.loads(line, object_pairs_hook=unique_pairs)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Invalid construction JSONL record") from None
        require(type(source) is dict and set(SAFE) <= set(source)
                and all(type(source[key]) is str and source[key].strip() for key in SAFE),
                "Malformed construction question metadata")
        schemas[tuple(sorted(source))] += 1
        selected = {key: source[key] for key in SAFE}
        pid = selected["id"]
        require(pid not in seen and pid in metadata and selected["split"] == "construction",
                "Repeated or unknown construction identity")
        seen.add(pid)
        card = metadata[pid]
        require(all(selected[key] == card[key] for key in ("id", "split", "source", "category")),
                "Construction row differs from separate category metadata")
        family = source_family(selected["source"])
        selected.update({"cb_id": card["cb_id"], "source_family": family})
        if pid in PAPER_EXPOSED or selected["source"] in PAPER_EXPOSED_SOURCES:
            exclusions.append({key: selected[key] for key in (
                "id", "source", "cb_id", "category", "source_family")})
            continue
        visible.append({**selected, "question_sha256": digest(selected["query"].encode()),
                        "normalized_question_sha256": normalized_question_sha256(selected["query"]),
                        "instruction_sha256": digest(selected["instruction"].encode())})
    require(seen == set(metadata) and len(visible) == 47 and len(exclusions) == 3,
            "Constructive denominator or excluded examples differ")
    return visible, exclusions, schemas


def build(raw_root, question_path, receipt_path):
    outputs = (ROOT / "outputs").resolve()
    require(raw_root.resolve().is_relative_to(outputs) and question_path.resolve().is_relative_to(outputs)
            and question_path.resolve() != receipt_path.resolve(), "Keep source and question payloads in local outputs")
    combined, combined_source = verified_asset(raw_root, "data/construction.jsonl")
    metadata_bytes, metadata_source = verified_asset(raw_root, "metadata/categories.csv")
    metadata = parse_metadata(metadata_bytes)
    rows, excluded, schemas = project(combined, metadata)
    code_sha = digest(Path(__file__).read_bytes())
    visible = encode({
        "status": "D49_COMBENCH_QUESTION_ONLY_REVIEW_POOL",
        "dataset_revision": HF_REV, "construction_source_sha256": combined_source["sha256"],
        "safe_fields": list(SAFE), "rows": rows,
    })
    receipt = {
        "status": "D49_PINNED_COMBENCH_CONSTRUCTION_PROJECTED_BEFORE_INDEPENDENT_COHORT_REVIEW",
        "dataset": {"repo_id": HF_REPO, "revision": HF_REV, "declared_license": "Apache-2.0",
                    "card_url": HF_BASE + "README.md",
                    "card_sha256": "88d40603b5bc72c9829ca79555ee6641e61e9fb1d0f034c20c11c66ab1c4bb29"},
        "paper": "https://arxiv.org/abs/2606.10479v1",
        "code": {"revision": CODE_REV, "repo": "https://github.com/Simplified-Reasoning/ComBench",
                 "license_url": f"https://github.com/Simplified-Reasoning/ComBench/blob/{CODE_REV}/LICENSE",
                 "license_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"},
        "source_assets": [combined_source, metadata_source],
        "question_only_sha256": digest(visible), "projector_code_sha256": code_sha,
        "physical_column_boundary": "The separate CSV supports metadata-only filtering. No author Parquet conversion "
                                    "is available. This trusted process parses whole JSONL rows internally and exports "
                                    "only the explicit field allowlist. No reference, rubric, note or verifier is emitted.",
        "allowlist": {"construction_jsonl": list(SAFE), "categories_csv": list(SAFE_METADATA)},
        "source_schema_names_only": [{"fields": list(names), "rows": count} for names, count in sorted(schemas.items())],
        "counts": {"construction": len(metadata), "paper_exposed_removed": len(excluded), "eligible_questions": len(rows),
                   "eligible_by_category": dict(sorted(Counter(row["category"] for row in rows).items())),
                   "eligible_by_source_family": dict(sorted(Counter(row["source_family"] for row in rows).items()))},
        "paper_exposed_exclusions": excluded,
        "output_archive_provenance": {
            "public_per_attempt_artifact": "NOT_LOCATED_IN_FIRST_PARTY_RELEASE",
            "project_notice": "Full result artifacts are maintained separately.",
            "client_source": f"https://github.com/Simplified-Reasoning/ComBench/blob/{CODE_REV}/src/llm/client.py",
            "client_sha256": "71386782c13abc42d24a2072b85649566263b7e3eef5675b3b7b6cafef4415a2",
            "runner_source": f"https://github.com/Simplified-Reasoning/ComBench/blob/{CODE_REV}/src/eval/runner.py",
            "runner_sha256": "45021a3494203b9655a93ce9d93d04ce4fda77b7a44f4872dca88adca912f759",
            "recorded_channel": "The public client accumulates streamed content. Dedicated reasoning_content "
                                "is counted rather than retained as text, and finish_reason is debug metadata. "
                                "The normal successful cache stores response text and usage, not those debug fields. "
                                "No native reasoning transcript or EOS can be inferred from those public artifacts.",
        },
        "rights_scope": "The authors declare Apache-2.0 for their release. Original contest statements can carry "
                        "separate rights and attribution. Keep the combined source and projected question text local.",
    }
    save(question_path, visible)
    raw = encode(receipt)
    save(receipt_path, raw)
    print("D49 intake", digest(raw), "questions", len(rows))
    print("categories", receipt["counts"]["eligible_by_category"])
    print("source_families", receipt["counts"]["eligible_by_source_family"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "outputs/d49_combench_source_20261110")
    parser.add_argument("--questions", type=Path,
                        default=ROOT / "outputs/d49_combench_blind_20261110/d49_construction_questions.json")
    parser.add_argument("--receipt", type=Path, default=HERE / "D49_COMBENCH_INTAKE_RECEIPT.json")
    args = parser.parse_args()
    build(args.raw, args.questions, args.receipt)


if __name__ == "__main__":
    main()
