"""Separate archived final readout and independent exact scoring for the seven role receipts."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

from d50_brumo_archive import HERE, IDENTITY, MODEL, ROOT, digest, metadata_source, normalize, require, wire, write_new


SCOPE_SHA = "03c2eed796fbe964e044c96f25afac53c7c1ab188b08b4cfb385fec2e1e6fb84"
PARSER_SHA = "64534e1ccfae1741ba693044daed183558138acc1a6dc03f333e0d52a3d6492c"
CASE_SET = {4, 7, 8, 9, 12, 16, 24}
POSITIVE_ROLES = {
    "E_LOCAL_PROPAGATION", "W_TENTATIVE_REPLACEMENT_REJECTED",
    "W_COMMITTED_REPLACEMENT_LATER_REJECTED", "C_MAINTAINED_AND_USED",
}
parser_dir = ROOT / "research/phase5d48_local_proof_headroom_20261110"
require(digest((parser_dir / "d48_final_readout.py").read_bytes()) == PARSER_SHA, "independent parser differs")
sys.path.insert(0, str(parser_dir))
from d48_final_readout import as_fraction, exact, readout  # noqa: E402


def role_scope():
    raw = (HERE / "D50_BRUMO_BLIND_SCOPE.json").read_bytes()
    require(digest(raw) == SCOPE_SHA, "blind role scope differs")
    scope = json.loads(raw)
    require(scope["status"] == "D50_BRUMO_GOLD_BLIND_INITIAL_ROLE_CERTIFICATES_FROZEN", "invalid role freeze")
    rows = {int(row["case_id"][-2:]): row for row in scope["rows"] if row["role"] in POSITIVE_ROLES}
    require(set(rows) == CASE_SET, "unexpected scored identity set")
    return rows


def archive_projection(columns):
    source, metadata = metadata_source("archive")
    filters = [("problem_idx", "in", [str(i) for i in sorted(CASE_SET)]),
               ("model_name", "=", MODEL[0]), ("model_config", "=", MODEL[1]), ("idx_answer", "=", 0)]
    rows = pq.read_table(source, columns=list(columns), filters=filters, use_threads=False).to_pylist()
    mapped = {int(row["problem_idx"]): row for row in rows}
    require(len(rows) == len(mapped) == len(CASE_SET) and set(mapped) == CASE_SET, "archive subset identity differs")
    require(all((row["model_name"], row["model_config"]) == MODEL and row["idx_answer"] == 0 for row in rows), "archive model or draw differs")
    return mapped, metadata


def checked_final(raw_messages, thought_sha):
    messages = json.loads(raw_messages)
    assistant = [m for m in messages if m.get("role") == "assistant"]
    if len(assistant) != 2 or assistant[0].get("type") != "cot" or assistant[1].get("type") not in (None, "response"):
        return None
    require(digest(assistant[0]["content"]) == thought_sha, "archived thought differs from role freeze")
    return assistant[1].get("content")


def final_stage(output):
    scope = role_scope()
    cols = (*IDENTITY, "problem", "all_messages")
    archive, metadata = archive_projection(cols)
    rows = []
    for index in sorted(scope):
        entry, frozen = archive[index], scope[index]
        require(digest(entry["problem"]) == frozen["archive_problem_sha256"], "original archived problem differs")
        final = checked_final(entry["all_messages"], frozen["reasoning_sha256"])
        result = readout(final)
        value = result.pop("exact_value")
        identity = {name: frozen[name] for name in ("case_id", "sample_uid", "split", "role")}
        rows.append(identity | result | {
            "final_sha256": digest(final) if type(final) is str else None,
            "rational_sha256": digest(wire(value)) if value is not None else None,
            "native_eos_status": "UNKNOWN_NOT_INDEPENDENTLY_AVAILABLE",
        })
    write_new(output, {
        "status": "D50_ROLE_POSITIVE_FINAL_READOUT_FROZEN_BEFORE_KEYS",
        "scope_sha256": SCOPE_SHA, "archive_sha256": metadata["file_sha256"],
        "trusted_final_parser_sha256": PARSER_SHA, "postfreeze_script_sha256": digest(Path(__file__).read_bytes()),
        "columns": list(cols), "rows": rows,
    })


def independent_value(text):
    value, status = exact(text)
    return (digest(wire(as_fraction(value))) if value is not None else None), status


def score_stage(final_path, final_sha, output):
    scope = role_scope()
    contents = final_path.read_bytes()
    require(digest(contents) == final_sha, "final readout identity differs")
    final = json.loads(contents)
    require(final["status"] == "D50_ROLE_POSITIVE_FINAL_READOUT_FROZEN_BEFORE_KEYS"
            and final["scope_sha256"] == SCOPE_SHA and final["trusted_final_parser_sha256"] == PARSER_SHA
            and final["postfreeze_script_sha256"] == digest(Path(__file__).read_bytes()), "invalid final freeze")
    values = {int(row["case_id"][-2:]): row for row in final["rows"]}
    require(len(final["rows"]) == len(values) == 7 and set(values) == CASE_SET, "scored final identity differs")
    archive_cols = (*IDENTITY, "problem", "gold_answer", "correct")
    archive, metadata = archive_projection(archive_cols)
    source, source_metadata = metadata_source("question")
    source_cols = ("problem_idx", "problem", "answer")
    source_rows = pq.read_table(source, columns=list(source_cols), filters=[("problem_idx", "in", sorted(CASE_SET))], use_threads=False).to_pylist()
    reference = {int(row["problem_idx"]): row for row in source_rows}
    require(len(source_rows) == len(reference) == 7 and set(reference) == CASE_SET, "source key identity differs")
    rows = []
    for index in sorted(scope):
        entry, frozen, key, outcome = archive[index], scope[index], reference[index], values[index]
        require(digest(entry["problem"]) == frozen["archive_problem_sha256"] and outcome["sample_uid"] == frozen["sample_uid"], "original question or sample identity differs")
        require(normalize(entry["problem"]) == normalize(key["problem"]), "reference question differs")
        source_digest, source_status = independent_value(key["answer"])
        archive_digest, archive_status = independent_value(entry["gold_answer"])
        if source_digest is None or archive_digest is None:
            comparison = "UNKNOWN_KEY_FORMAT"
        elif source_digest != archive_digest:
            comparison = "UNKNOWN_SOURCE_KEYS_DISAGREE"
        elif outcome["rational_sha256"] is None:
            comparison = "UNKNOWN_FINAL_READOUT"
        else:
            comparison = "EXACT_CORRECT" if outcome["rational_sha256"] == source_digest else "EXACT_WRONG"
        rows.append({
            "case_id": frozen["case_id"], "sample_uid": frozen["sample_uid"], "split": frozen["split"], "role": frozen["role"],
            "independent_exact_comparison": comparison, "final_readout_status": outcome["status"],
            "source_key_sha256": digest(key["answer"]) if type(key["answer"]) is str else None,
            "archive_key_sha256": digest(entry["gold_answer"]) if type(entry["gold_answer"]) is str else None,
            "source_key_parse_status": source_status, "archive_key_parse_status": archive_status,
            "publisher_reported_correct": entry["correct"],
        })
    write_new(output, {
        "status": "D50_ROLE_POSITIVE_SEVEN_POSTFREEZE_EXACT_COMPARISON",
        "scope_sha256": SCOPE_SHA, "final_readout_sha256": final_sha, "trusted_parser_sha256": PARSER_SHA,
        "archive_sha256": metadata["file_sha256"], "source_questions_sha256": source_metadata["file_sha256"],
        "independent_comparison_rule": "Last balanced explicit final box, exact bounded rational arithmetic, and matching exact question-bank and archive answer keys. Unknown readouts, unsupported keys and key disagreement abstain. Publisher-reported correctness is a separate source field, never an input to the independent comparison.",
        "archive_columns": list(archive_cols), "source_columns": list(source_cols),
        "denominator": "Seven role-positive manually certified archived samples only. Not the thirty-question bank, a random final-accuracy estimate, or same-prefix intervention evidence.",
        "independent_counts": dict(Counter(row["independent_exact_comparison"] for row in rows)),
        "rows": rows,
    })


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    reader = sub.add_parser("final")
    reader.add_argument("--output", required=True, type=Path)
    evaluator = sub.add_parser("score")
    evaluator.add_argument("--final", required=True, type=Path)
    evaluator.add_argument("--final-sha", required=True)
    evaluator.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    if args.command == "final":
        final_stage(args.output)
    else:
        score_stage(args.final, args.final_sha, args.output)
