"""Freeze 100 historical FULL-policy cases using only salted problem-ID hashes.

Reads existing sources only. Does not launch a model/worker or use correctness,
Wait, length, cap or ECN information to rank/select cases.
"""

import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(r"D:\ACL")
SALT = "ACL-natural-P1-20261105-development-observation-v1"
OUT = Path(__file__).with_name("P1_sampling_manifest.json")
SOURCES = [ROOT / "results/online/qwen3_4b_0.jsonl",
           ROOT / "results/online/qwen3_4b_1.jsonl"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    # Selection phase: the ranking function receives only problem IDs.
    eligible = {}
    file_hashes = {str(path): digest(path.read_bytes()) for path in SOURCES}
    for path in SOURCES:
        with path.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if row.get("method") != "full":
                    continue
                problem_id = row["problem_id"]
                if problem_id in eligible:
                    raise ValueError("Duplicate FULL problem ID: " + problem_id)
                eligible[problem_id] = (path, line_number)
    if len(eligible) != 300:
        raise ValueError("Expected the audited 300-case historical pool")
    rank = {pid: digest((SALT + "\0" + pid).encode("utf-8")) for pid in eligible}
    selected = sorted(eligible, key=lambda pid: (rank[pid], pid))[:100]
    selected_set = set(selected)

    # Read metadata only after selection has been fixed.
    selected_rows = {}
    for path in SOURCES:
        with path.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if row.get("method") != "full" or row["problem_id"] not in selected_set:
                    continue
                selected_rows[row["problem_id"]] = (row, line_number, digest(raw))

    question_source = ROOT / "data/test.jsonl"
    question_index = {}
    with question_source.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            if raw.strip():
                row = json.loads(raw)
                question_index[row["problem_id"]] = {
                    "source_path": str(question_source), "line_number_1based": line_number,
                    "source_line_sha256_including_line_ending": digest(raw),
                    "question_utf8_sha256": digest(row["question"].encode("utf-8")),
                }

    references = []
    for relative, role in [
        ("scripts/evaluate_online.py", "Local historical runner reference: decode(8192), then Engine.answer; Gold graded afterward"),
        ("reason_transition/core.py", "Local engine reference: thinking prompt, sampling, forced boxed answer cue/cap"),
        ("configs/qwen3_4b_pilot.json", "Local declared model/data revision and sampling reference; not a per-row execution attestation"),
    ]:
        path = ROOT / relative
        references.append({"path": str(path), "sha256": digest(path.read_bytes()), "role": role})

    cases = []
    for index, pid in enumerate(selected, 1):
        row, line_number, line_hash = selected_rows[pid]
        path, expected_line = eligible[pid]
        assert line_number == expected_line
        trace = row["trace"]
        answer = row["answer"]
        ids = trace["ids"]
        cases.append({
            "sample_rank_1based": index, "problem_id": pid, "sampling_sha256": rank[pid],
            "source_path": str(path), "source_line_number_1based": line_number,
            "source_file_sha256": file_hashes[str(path)],
            "source_line_sha256_including_line_ending": line_hash,
            "question_origin": question_index[pid],
            "generation_policy": "historical_FULL_thinking_policy_then_forced_boxed_answer_readout",
            "uninterrupted_native_episode": False,
            "method": row["method"], "effective_method": row.get("effective_method"),
            "seed": row["seed"], "dtype_recorded": row.get("dtype"),
            "model_basename_recorded": row.get("model_path", "").rsplit("/", 1)[-1],
            "model_revision_recorded_in_row": row.get("model_revision"),
            "execution_code_sha256_recorded_in_row": row.get("code_sha256"),
            "quality_labels_available_during_decisions_recorded": row.get("quality_labels_available_during_decisions"),
            "trace_token_count": len(ids),
            "trace_ids_sha256_json_compact_utf8": digest(json.dumps(ids, separators=(",", ":")).encode("utf-8")),
            "trace_text_sha256_utf8": digest(trace["text"].encode("utf-8")),
            "trace_stop_reason": trace.get("stop_reason"),
            "trace_length_censored": bool(trace.get("length_censored")),
            "row_length_censored": bool(row.get("length_censored")),
            "answer_length_censored": bool(answer.get("length_censored")),
            "answer_stop_reason": answer.get("stop_reason"),
            "forced_readout_control_prefix_input_tokens": answer.get("control_prefix_input_tokens"),
            "forced_answer_prefix_hash_recorded": answer.get("answer_prefix_hash"),
            "annotation_scope": "Original trace only; forced answer, Gold, grade and correctness excluded from annotation view",
            "natural_event_labels": "NOT_AUDITED",
        })

    result = {
        "schema_version": "P1_historical_sampling_manifest_v1",
        "date": "2026-11-05",
        "purpose": "Frozen development observation sample; not a new independent test set or a natural-intervention result",
        "eligible_pool": {"method": "full", "unique_problem_ids": len(eligible),
                          "source_file_sha256": file_hashes,
                          "sorted_problem_ids_sha256_newline_delimited_utf8": digest(("\n".join(sorted(eligible)) + "\n").encode("utf-8")),
                          "question_source_path": str(question_source),
                          "question_source_sha256": digest(question_source.read_bytes())},
        "sampling": {"n": 100, "salt": SALT,
                     "ranking": "Ascending SHA256(UTF8(salt + NUL + problem_id)), then problem_id as a tie-breaker",
                     "selection_uses_only": ["historical method=full pool membership", "problem_id", "fixed salt"],
                     "selection_does_not_use": ["correctness", "Gold", "Wait", "length", "cap", "ECN", "event labels"],
                     "cap_filtered": False},
        "generation_protocol_origin": {
            "classification": "FULL policy with bounded thinking plus separate forced boxed answer readout; not native_uninterrupted",
            "local_source_references": references,
            "source_interpretation": "evaluate_online.py decodes thinking with cap 8192 and no full-policy decision hook; then calls Engine.answer. core.py adds a boxed-answer cue even after natural thinking closure, caps answer decoding at 192, and records control-prefix tokens.",
            "provenance_limit": "Rows retain seed/dtype/model path and answer-control metadata, but omit immutable execution code/model hashes. Current local source/config hashes are supplemental references, not proof they were the historical executed bytes. Bind archived run provenance before precise replay claims.",
            "native_pilot_excluded": "native_pilot_* provides a separate uninterrupted but capped protocol and is not mixed into this 100-case pool"},
        "summary_metadata_not_event_rates": {
            "sample_count": len(cases),
            "trace_capped_count": sum(case["trace_length_censored"] for case in cases),
            "trace_stop_reason_counts": dict(collections.Counter(case["trace_stop_reason"] for case in cases)),
            "no_semantic_event_rate_audited": True},
        "cases": cases,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "sha256": digest(OUT.read_bytes()),
                      "metadata_summary": result["summary_metadata_not_event_rates"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
