"""Freeze question identities before projecting only publisher-separated reasoning."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "outputs/d50_matharena_source_20261110"
MODEL = ("QED-Nano", "other/qed-nano")
SPLITS = ("B", "Bprime", "H")
SALT = "D50-BRUMO-2025-CUSTODY-v1\0"
IDENTITY = ("problem_idx", "model_name", "model_config", "idx_answer")
SOURCE = {
    "question": ("brumo_2025", "6de9bc0987f5710c6376ee980e1483dbeb55cfda", "ef510deea34c5b6d165c06d020acede1c1031eb91d90336cb4d615d9e55ba391"),
    "archive": ("brumo_2025_outputs", "3b234efea64d03f80ec57a85e29879fc41b04864", "a89e9e9fcc64fb22116290f94eb84e7173edb7253321487a948af99790d8c573"),
}
PRIOR_QUESTION_JSON = (
    ("d43_aime_source_20261110/d43_question_only.json", "questions", "problem_id", "question"),
    ("d44_aime_source_20261110/d44_live_visible.json", "rows", "case_id", "question"),
    ("d45_aime_source_20261110/d45_question_only.json", "rows", "case_id", "question"),
    ("d46_aime_source_20261110/d46_question_only.json", "rows", "case_id", "question"),
    ("d47_aime_source_20261110/d47_question_only.json", "rows", "case_id", "question"),
    ("d49_combench_blind_20261110/d49_construction_questions.json", "rows", "id", "query"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return sha256(value.encode("utf-8") if type(value) is str else value).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def punctuation_fold(text):
    normalized = re.sub(r"\\(?:left|right|displaystyle)\b", "", normalize(text))
    return "".join(re.findall(r"[a-z0-9]+", normalized))


def metadata_source(kind):
    name, revision, expected = SOURCE[kind]
    path = DATA / f"{name}_{revision[:8]}.parquet"
    require(digest(path.read_bytes()) == expected, f"{kind} input differs from verified asset")
    base = f"https://huggingface.co/datasets/MathArena/{name}"
    return path, {
        "dataset": f"MathArena/{name}", "revision": revision, "file_sha256": expected,
        "bytes": path.stat().st_size, "license": "CC-BY-NC-SA-4.0",
        "data_card_url": f"{base}/blob/{revision}/README.md",
        "asset_url": f"{base}/resolve/{revision}/data/train-00000-of-00001.parquet",
    }


def case_id(index):
    return f"BRUMO-2025-P{int(index):02d}"


def prior_questions():
    receipts = []
    comparable = []
    for filename, rows_key, id_key, question_key in PRIOR_QUESTION_JSON:
        path = ROOT / "outputs" / filename
        contents = path.read_bytes()
        rows = json.loads(contents)[rows_key]
        comparable.extend((row[id_key], row[question_key]) for row in rows)
        receipts.append({"path": str(path.relative_to(ROOT).as_posix()), "sha256": digest(contents), "question_rows": len(rows)})
    for year in (2025, 2026):
        path = ROOT / "outputs/d48_matharena_raw_20261110" / f"hmmt_feb_{year}_outputs.parquet"
        question_rows = defaultdict(set)
        table = pq.ParquetFile(path)
        for row in table.read(columns=["problem_idx", "problem"], use_threads=False).to_pylist():
            question_rows[row["problem_idx"]].add(row["problem"])
        comparable.extend((f"HMMT-FEB-{year}-{i}", text) for i, values in question_rows.items() for text in sorted(values))
        receipts.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path.read_bytes()), "distinct_ids": len(question_rows), "question_rows": sum(map(len, question_rows.values())), "columns": ["problem_idx", "problem"]})
    prior_index = ROOT / "research/phase5d43_answer_refutation_20261110/D43_DEVELOPMENT_EXCLUSIONS.json"
    old = prior_index.read_bytes()
    catalog = json.loads(old)
    receipts.append({"path": prior_index.relative_to(ROOT).as_posix(), "sha256": digest(old), "question_rows": len(catalog["normalized_question_sha256"])})
    return comparable, set(catalog["excluded_problem_ids"]), set(catalog["normalized_question_sha256"]), receipts


def archive_rows(path, columns, *, selected_draw):
    filters = [("model_name", "=", MODEL[0]), ("model_config", "=", MODEL[1])]
    if selected_draw:
        filters.append(("idx_answer", "=", 0))
    rows = pq.read_table(path, columns=list(columns), filters=filters, use_threads=False).to_pylist()
    require(all(set(row) == set(columns) and (row["model_name"], row["model_config"]) == MODEL for row in rows), "archive projection custody mismatch")
    return rows


def freeze(receipt_path, question_output):
    questions, q_metadata = metadata_source("question")
    archive, a_metadata = metadata_source("archive")
    question_columns = ("problem_idx", "problem", "problem_type")
    archive_columns = (*IDENTITY, "problem", "user_message")
    bank = pq.ParquetFile(questions).read(columns=list(question_columns), use_threads=False).to_pylist()
    metadata = archive_rows(archive, archive_columns, selected_draw=False)
    originals = {int(row["problem_idx"]): row for row in bank}
    require(len(bank) == len(originals) == 30 and set(originals) == set(range(1, 31)), "unexpected question identities")
    draws = Counter((int(row["problem_idx"]), row["idx_answer"]) for row in metadata)
    require(draws == Counter({(i, draw): 1 for i in originals for draw in range(4)}), "model draw coverage differs")
    for row in metadata:
        original = originals[int(row["problem_idx"])]
        require(normalize(original["problem"]) == normalize(row["problem"]), "archive problem differs from bank")
        require(row["problem"] in row["user_message"], "archived problem is absent from prompt")

    old_text, old_ids, old_hashes, prior_receipts = prior_questions()
    old_ids.update(identity for identity, _ in old_text)
    old_hashes.update(digest(normalize(text)) for _, text in old_text)
    old_folded = [(identity, punctuation_fold(text)) for identity, text in old_text]
    by_subject = defaultdict(list)
    for index, row in originals.items():
        require(len(row["problem_type"]) == 1, "unexpected subject layout")
        by_subject[row["problem_type"][0]].append(index)
    require(sorted(map(len, by_subject.values())) == [5, 7, 8, 10], "unexpected subject counts")
    split_by_id = {}
    for subject in sorted(by_subject):
        for index in sorted(by_subject[subject], key=lambda i: digest(SALT + case_id(i))):
            split_by_id[index] = SPLITS[len(split_by_id) % 3]
    require(Counter(split_by_id.values()) == Counter({name: 10 for name in SPLITS}), "split must be balanced")

    selected = {int(row["problem_idx"]): row for row in metadata if row["idx_answer"] == 0}
    public_rows, local_rows = [], []
    for index, original in originals.items():
        old_identity = case_id(index)
        row = selected[index]
        normalized_hash = digest(normalize(row["problem"]))
        folded = punctuation_fold(row["problem"])
        near_id, near_ratio = max(((identity, SequenceMatcher(None, folded, text, autojunk=False).ratio())
                                  for identity, text in old_folded), key=lambda pair: pair[1])
        require(old_identity not in old_ids and normalized_hash not in old_hashes and near_ratio < 0.90, "prior overlap or near-overlap needs adjudication")
        public = {
            "case_id": old_identity, "problem_idx": index, "split": split_by_id[index], "subject": original["problem_type"][0],
            "source_problem_sha256": digest(original["problem"]), "archive_problem_sha256": digest(row["problem"]),
            "normalized_question_sha256": normalized_hash, "user_message_sha256": digest(row["user_message"]),
            "sample_uid": digest(wire([a_metadata["revision"], index, *MODEL, 0])),
            "nearest_old_question": near_id, "nearest_old_similarity": round(near_ratio, 6),
        }
        public_rows.append(public)
        local_rows.append(public | {"question": row["problem"], "user_message": row["user_message"]})
    write_new(question_output, {"status": "D50_LOCAL_QUESTION_ONLY", "rows": local_rows})
    write_new(receipt_path, {
        "status": "D50_BRUMO_B_BPRIME_H_FROZEN_BEFORE_ALL_MESSAGES",
        "archive_and_question_sources": {"question": q_metadata, "archive": a_metadata},
        "selection": {"model_name": MODEL[0], "model_config": MODEL[1], "draw_index": 0, "archived_identity_draws_per_question": 4},
        "split_rule": "Sort subjects ASCII, then sort within each subject by SHA256('D50-BRUMO-2025-CUSTODY-v1' + NUL + case ID), and cycle B, Bprime, H continuously across the concatenation.",
        "question_columns": list(question_columns), "archive_identity_columns": list(archive_columns),
        "projector_sha256": digest(Path(__file__).read_bytes()), "local_question_projection_sha256": digest(question_output.read_bytes()),
        "dedup_scope": "Exact normalized hashes and exact identities against the prior catalog and projected D43–D49 questions. Punctuation-fold similarity screens accessible older text at 0.90. This is local project nonoverlap, not model contamination or semantic independence certification.",
        "old_sources": prior_receipts, "old_unique_normalized_hashes": len(old_hashes), "old_direct_text_rows": len(old_text),
        "holdback": "No archive response, stop, answer or score columns were projected at freeze. QED teacher identity is publisher metadata, not row-bound model checkpoint bytes. Qwen student remains separate.",
        "rows": public_rows,
    })


def thinking_only(source):
    messages = json.loads(source)
    if type(messages) is not list or any(type(message) is not dict for message in messages):
        return None, "UNKNOWN_MESSAGE_LAYOUT"
    users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if len(users) != 1:
        return None, "UNKNOWN_USER_LAYOUT"
    assistant = messages[users[0] + 1:]
    if not assistant or any(message.get("role") != "assistant" or message.get("tool_calls") for message in assistant):
        return None, "UNKNOWN_TOOL_OR_ASSISTANT_LAYOUT"
    parts = [message for message in assistant if message.get("type") == "cot"]
    response_count = sum(message.get("type") in (None, "response") for message in assistant)
    if len(parts) != 1 or response_count != 1 or len(assistant) != 2 or assistant[0] is not parts[0]:
        return None, "UNKNOWN_NO_SINGLE_SEPARATE_COT"
    reasoning = parts[0].get("content")
    if type(reasoning) is not str or not reasoning.strip():
        return None, "UNKNOWN_EMPTY_COT"
    return reasoning, "ARCHIVE_COT_POSSIBLY_SUMMARY"


def project(frozen, frozen_sha, local_path, receipt_path):
    freeze_raw = frozen.read_bytes()
    require(digest(freeze_raw) == frozen_sha, "question freeze digest differs")
    freeze_receipt = json.loads(freeze_raw)
    require(freeze_receipt["status"] == "D50_BRUMO_B_BPRIME_H_FROZEN_BEFORE_ALL_MESSAGES", "incorrect freeze")
    require(freeze_receipt["projector_sha256"] == digest(Path(__file__).read_bytes()), "projector changed after freeze")
    archive, a_metadata = metadata_source("archive")
    require(freeze_receipt["archive_and_question_sources"]["archive"] == a_metadata, "archive identity differs")
    columns = (*IDENTITY, "problem", "user_message", "all_messages")
    selected = archive_rows(archive, columns, selected_draw=True)
    by_idx = {int(row["problem_idx"]): row for row in selected}
    require(len(selected) == len(by_idx) == len(freeze_receipt["rows"]) == 30, "draw zero row set mismatch")
    public_rows, local_rows = [], []
    for row in freeze_receipt["rows"]:
        joined = by_idx[row["problem_idx"]]
        require(joined["idx_answer"] == 0 and digest(joined["problem"]) == row["archive_problem_sha256"]
                and digest(joined["user_message"]) == row["user_message_sha256"], "frozen prompt or draw differs")
        thought, kind = thinking_only(joined["all_messages"])
        receipt_row = row | {
            "reasoning_kind": kind, "reasoning_sha256": digest(thought) if thought is not None else None,
            "thinking_unicode_characters": len(thought) if thought is not None else None,
            "thinking_utf8_bytes": len(thought.encode("utf-8")) if thought is not None else None,
            "native_eos_status": "UNKNOWN_NOT_INDEPENDENTLY_AVAILABLE",
        }
        public_rows.append(receipt_row)
        local_rows.append(receipt_row | {"question": joined["problem"], "user_message": joined["user_message"], "thinking": thought})
    write_new(local_path, {"status": "D50_LOCAL_THINKING_ONLY", "question_freeze_sha256": frozen_sha, "rows": local_rows})
    write_new(receipt_path, {
        "status": "D50_THINKING_ONLY_PROJECTED_AFTER_QUESTION_FREEZE",
        "question_freeze_sha256": frozen_sha, "archive_sha256": a_metadata["file_sha256"],
        "local_thinking_projection_sha256": digest(local_path.read_bytes()), "columns": list(columns),
        "channel_boundary": "Separate publisher `type=cot` record only. Never access response content, answer, gold_answer, parsed_answer or correctness. Provider summary, completeness, exact native tokenizer state, checkpoint bytes and EOS are not independently known.",
        "rows": public_rows,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    question = sub.add_parser("freeze")
    question.add_argument("--receipt", required=True, type=Path)
    question.add_argument("--local", required=True, type=Path)
    reasoning = sub.add_parser("project")
    reasoning.add_argument("--freeze", required=True, type=Path)
    reasoning.add_argument("--freeze-sha", required=True)
    reasoning.add_argument("--receipt", required=True, type=Path)
    reasoning.add_argument("--local", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.receipt, args.local)
    else:
        project(args.freeze, args.freeze_sha, args.local, args.receipt)


if __name__ == "__main__":
    main()
