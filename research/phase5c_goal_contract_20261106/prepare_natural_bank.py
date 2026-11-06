"""Freeze an ID-only 32-question historical readout bank, excluding the P1 100.

CPU/stdlb only. No model, GPU, credential route, manual trace inspection or
correctness-based selection. Gold and historical forced readout stay separate.
Existing frozen outputs may only be reproduced byte-for-byte, never replaced.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
P1 = ROOT / "research/next_design_20261105/P1_sampling_manifest.json"
P1_SHA = "6ee72c687db428cf341ec0f65ce1c3d51de94aa57eb8033e899baeccd0ce30eb"
SALT = "ACL-Phase5C-natural-readout-bank32-v1-20261106"
N = 32
SOURCES = [ROOT / "results/online/qwen3_4b_0.jsonl", ROOT / "results/online/qwen3_4b_1.jsonl"]
QUESTIONS = ROOT / "data/test.jsonl"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def encode_json(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def encode_jsonl(rows):
    return ("\n".join(canonical(row) for row in rows) + "\n").encode("utf-8")


def freeze_write(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("Refusing to replace frozen output with different bytes: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def select_ids(eligible_ids, excluded_ids):
    """Only IDs enter the sampling function; no quality, text or length input."""
    remaining = set(eligible_ids) - set(excluded_ids)
    ranks = {pid: sha((SALT + "\0" + pid).encode("utf-8")) for pid in remaining}
    ordered = sorted(remaining, key=lambda pid: (ranks[pid], pid))
    return ordered[:N], remaining, ranks


def main():
    p1_bytes = P1.read_bytes()
    assert sha(p1_bytes) == P1_SHA
    p1 = json.loads(p1_bytes)
    excluded = {case["problem_id"] for case in p1["cases"]}
    assert len(excluded) == 100
    expected_sources = p1["eligible_pool"]["source_file_sha256"]
    source_bytes = {}
    for path in SOURCES:
        raw = path.read_bytes()
        matching = [(old_path, expected) for old_path, expected in expected_sources.items()
                    if Path(old_path).name == path.name]
        assert len(matching) == 1
        original_path, expected = matching[0]
        assert sha(raw) == expected
        source_bytes[path] = (raw, original_path)
    qbytes = QUESTIONS.read_bytes()
    assert sha(qbytes) == p1["eligible_pool"]["question_source_sha256"]

    # Selection index uses only FULL membership, problem ID and source location.
    eligible = {}
    for path, (data, original_path) in source_bytes.items():
        for line_no, raw in enumerate(data.splitlines(keepends=True), 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row.get("method") != "full":
                continue
            pid = row["problem_id"]
            assert pid not in eligible, "Duplicate FULL problem ID"
            eligible[pid] = {"path": path, "original_path": original_path, "line": line_no}
    assert len(eligible) == 300
    all_ids_sha = sha(("\n".join(sorted(eligible)) + "\n").encode("utf-8"))
    assert all_ids_sha == p1["eligible_pool"]["sorted_problem_ids_sha256_newline_delimited_utf8"]
    assert excluded <= set(eligible)
    selected, remaining, ranks = select_ids(set(eligible), excluded)
    assert len(remaining) == 200 and len(selected) == N and len(set(selected)) == N
    assert not set(selected) & excluded

    # Only now access selected trace text, quality metadata and evaluation fields.
    questions = {}
    for line_no, raw in enumerate(qbytes.splitlines(keepends=True), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        if row["problem_id"] in selected:
            questions[row["problem_id"]] = (row, line_no, raw)
    assert len(questions) == N
    visible, evaluation, cases = [], [], []
    source_lines = {path: data.splitlines(keepends=True) for path, (data, _) in source_bytes.items()}
    lengths, char_lengths, subjects, stops, score_counts = [], [], Counter(), Counter(), Counter()
    capped = 0
    for rank, pid in enumerate(selected, 1):
        loc = eligible[pid]
        raw = source_lines[loc["path"]][loc["line"] - 1]
        row = json.loads(raw)
        q, qline, qraw = questions[pid]
        assert row["problem_id"] == pid and row["method"] == "full"
        trace = row["trace"]
        text, ids = trace["text"], trace["ids"]
        assert isinstance(text, str) and isinstance(ids, list) and all(type(v) is int for v in ids)
        assert len(ids) == trace["tokens"]
        bank_id = f"C{rank:03}"
        trace_sha = sha(text.encode("utf-8"))
        ids_sha = sha(json.dumps(ids, separators=(",", ":")).encode("utf-8"))
        v = {"schema_version": "phase5c_visible_historical_readout_v1", "bank_id": bank_id,
             "problem_id": pid, "question": q["question"], "trace_text": text, "trace_ids": ids,
             "trace_token_count": len(ids), "trace_stop_reason": trace.get("stop_reason"),
             "trace_length_censored": bool(trace.get("length_censored")),
             "source_scope": "Historical FULL thinking only; independent forced final answer omitted; not native_uninterrupted.",
             "model_input_rule": "Construct LM messages only from declared question/trace text or IDs. Never serialize this whole record or join the evaluation file online."}
        visible.append(v)
        assert row["correct"] in (0, 1, False, True)
        e = {"schema_version": "phase5c_evaluation_only_v1", "bank_id": bank_id, "problem_id": pid,
             "gold": q["gold"], "subject": q.get("subject"), "level": q.get("level"), "task": q.get("task"),
             "historical_recorded_correct": bool(row["correct"]), "historical_grade": row.get("grade"),
             "historical_forced_answer_text": row["answer"]["text"],
             "historical_forced_answer_ids": row["answer"]["ids"],
             "historical_answer_stop_reason": row["answer"].get("stop_reason"),
             "historical_answer_length_censored": bool(row["answer"].get("length_censored")),
             "evaluation_rule": "Offline grading only. Not available to extraction, projection, gate, retries, method selection or decode."}
        evaluation.append(e)
        case = {"bank_id": bank_id, "sample_rank_1based": rank, "problem_id": pid,
                "sampling_sha256": ranks[pid], "source_path": str(loc["path"]),
                "historical_source_path_recorded": loc["original_path"], "source_line_1based": loc["line"],
                "source_file_sha256": sha(source_bytes[loc["path"]][0]),
                "source_line_sha256_including_line_ending": sha(raw),
                "question_source_path": str(QUESTIONS), "question_source_line_1based": qline,
                "question_source_line_sha256_including_line_ending": sha(qraw),
                "question_utf8_sha256": sha(q["question"].encode("utf-8")),
                "trace_text_sha256_utf8": trace_sha, "trace_ids_sha256_json_compact_utf8": ids_sha,
                "visible_record_sha256_canonical_utf8": sha(canonical(v).encode("utf-8")),
                "evaluation_record_sha256_canonical_utf8": sha(canonical(e).encode("utf-8")),
                "seed_recorded": row.get("seed"), "dtype_recorded": row.get("dtype"),
                "model_basename_recorded": row.get("model_path", "").rsplit("/", 1)[-1],
                "model_revision_recorded": row.get("model_revision"),
                "execution_code_sha256_recorded": row.get("code_sha256"),
                "trace_stop_reason": trace.get("stop_reason"), "trace_length_censored": bool(trace.get("length_censored")),
                "trace_tokens": len(ids), "trace_characters": len(text)}
        cases.append(case)
        lengths.append(len(ids)); char_lengths.append(len(text))
        subjects[q.get("subject", "unknown")] += 1; stops[trace.get("stop_reason", "unknown")] += 1
        score_counts[str(int(bool(row["correct"])))] += 1
        capped += bool(trace.get("length_censored"))

    vbytes, ebytes = encode_jsonl(visible), encode_jsonl(evaluation)
    metadata = {"scope": "Post-selection metadata, never used by ID-only sampling; not semantic event rates or new model results.",
                "n": N, "thinking_cap_count": capped, "thinking_stop_reasons": dict(sorted(stops.items())),
                "subject_counts": dict(sorted(subjects.items())),
                "trace_token_count": {"min": min(lengths), "max": max(lengths), "sum": sum(lengths),
                                      "mean": statistics.mean(lengths), "median": statistics.median(lengths)},
                "trace_character_count": {"min": min(char_lengths), "max": max(char_lengths), "sum": sum(char_lengths)},
                "historical_score_counts_evaluation_metadata_only": dict(sorted(score_counts.items())),
                "new_model_generation_count": 0, "new_GPU_seconds": 0,
                "manual_trace_fine_reading_in_this_preparation": False}
    manifest = {"schema_version": "phase5c_bank32_id_only_v1", "date": "2026-11-06",
                "status": "FROZEN_BEFORE_NEW_READOUT_OUTPUTS",
                "purpose": "Single-model paired readout exploration on a fresh subset of the historical development pool. Not a formal unseen benchmark.",
                "sampling": {"salt": SALT, "n": N, "remaining_pool_n": len(remaining), "source_FULL_pool_n": len(eligible),
                             "ranking": "Ascending SHA256(UTF8(salt + NUL + problem_id)), then problem_id.",
                             "inputs": ["FULL pool membership", "problem_id", "P1 excluded ID membership", "fixed salt"],
                             "forbidden_inputs": ["Gold", "correctness", "grade", "answer", "Wait/revision cues", "trace length", "cap", "candidate counts"],
                             "incorrect_or_cap_filter": False, "P1_overlap": 0,
                             "all_FULL_IDs_sha256_newline_utf8": all_ids_sha,
                             "remaining200_IDs_sha256_newline_utf8": sha(("\n".join(sorted(remaining)) + "\n").encode()),
                             "selected32_IDs_sha256_newline_utf8": sha(("\n".join(selected) + "\n").encode())},
                "excluded_P1_manifest": {"path": str(P1), "sha256": P1_SHA, "n": len(excluded)},
                "source_file_sha256": {str(path): sha(raw) for path, (raw, _) in source_bytes.items()},
                "question_source_sha256": sha(qbytes),
                "generation_origin": p1["generation_protocol_origin"],
                "provenance_limits": ["Historical thinking is bounded at8192, followed by an independently forced boxed answer readout.",
                                      "Historical rows omit immutable executed code/model hashes; no exact execution replay claim.",
                                      "Excluding P1 removes that diagnostic overlap, not all historical development exposure.",
                                      "No MATH500 identity or official untouched test-set claim.",
                                      "Old source correctness and Gold stay in the separate offline evaluation file."],
                "files": {"bank_visible.jsonl": {"sha256": sha(vbytes), "bytes": len(vbytes), "records": N},
                          "bank_evaluation_only.jsonl": {"sha256": sha(ebytes), "bytes": len(ebytes), "records": N}},
                "preparation_source_sha256": sha(Path(__file__).read_bytes()), "cases": cases}
    assert all(not ({"gold", "grade", "correct", "answer", "historical_recorded_correct", "historical_forced_answer_text"} & set(v)) for v in visible)
    assert [v["bank_id"] for v in visible] == [v["bank_id"] for v in evaluation]
    assert set(v["problem_id"] for v in visible) == set(selected)
    # Independent source/record recount after projected output creation.
    for v, case in zip(visible, cases):
        raw = source_lines[Path(case["source_path"])][case["source_line_1based"] - 1]
        original = json.loads(raw)
        assert original["trace"]["text"] == v["trace_text"] and original["trace"]["ids"] == v["trace_ids"]
        assert sha(raw) == case["source_line_sha256_including_line_ending"]
    for path, (raw, _) in source_bytes.items():
        assert path.read_bytes() == raw
    assert QUESTIONS.read_bytes() == qbytes and P1.read_bytes() == p1_bytes
    manifest_bytes = encode_json(manifest)
    audit = {"status": "PASS", "selection_only_IDs": True, "pool_FULL_unique": len(eligible),
             "excluded_P1_unique": len(excluded), "remaining_unique": len(remaining), "selected_unique": len(selected),
             "P1_overlap": 0, "visible_records": len(visible), "evaluation_records": len(evaluation),
             "source_file_hashes_match_frozen_P1": True, "source_line_and_trace_recount": N,
             "visible_top_level_Gold_quality_answer_fields": 0,
             "source_bytes_unchanged": True, "question_source_unchanged": True, "P1_manifest_unchanged": True,
             "manifest_sha256": sha(manifest_bytes), "visible_sha256": sha(vbytes), "evaluation_sha256": sha(ebytes),
             "metadata_sha256": sha(encode_json(metadata)), "new_GPU_seconds": 0,
             "no_manual_selected_trace_fine_reading": True}
    for name, data in [("bank_visible.jsonl", vbytes), ("bank_evaluation_only.jsonl", ebytes),
                       ("NATURAL_BANK_MANIFEST.json", manifest_bytes), ("BANK_METADATA_SUMMARY.json", encode_json(metadata)),
                       ("BANK_PREPARATION_AUDIT.json", encode_json(audit))]:
        freeze_write(OUT / name, data)
    print(json.dumps({"status": "PASS", "n": N, "remaining_pool": len(remaining), "P1_overlap": 0,
                      "manifest_sha256": sha(manifest_bytes), "visible_sha256": sha(vbytes), "evaluation_sha256": sha(ebytes),
                      "metadata": metadata}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
