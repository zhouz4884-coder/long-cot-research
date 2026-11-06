"""Read frozen historical100; outcome-based triage is not event-rate estimation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
STRONG = re.compile(r"\bwait\b|\bhold on\b|\b(?:recalculat|recomput|reconsider)\w*|\b(?:mistake|correction)\b|不对|等等|重新(?:算|计算)|纠正|有误", re.I)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    source = ROOT / "research/next_design_20261105/P1_sampling_manifest.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    assert sha(source.read_bytes()) == "6ee72c687db428cf341ec0f65ce1c3d51de94aa57eb8033e899baeccd0ce30eb"
    source_bytes = {p: Path(p).read_bytes() for p in manifest["eligible_pool"]["source_file_sha256"]}
    for p, expected in manifest["eligible_pool"]["source_file_sha256"].items():
        assert sha(source_bytes[p]) == expected
    lines = {p: data.splitlines(keepends=True) for p, data in source_bytes.items()}
    qpath = Path(manifest["eligible_pool"]["question_source_path"])
    qbytes = qpath.read_bytes()
    assert sha(qbytes) == manifest["eligible_pool"]["question_source_sha256"]
    questions = {v["problem_id"]: v for v in map(json.loads, qbytes.splitlines()) if v}
    all_rows, records = [], {}
    for case in manifest["cases"]:
        raw = lines[case["source_path"]][case["source_line_number_1based"] - 1]
        assert sha(raw) == case["source_line_sha256_including_line_ending"]
        row = json.loads(raw)
        assert row["correct"] in (0, 1, False, True)
        text = row["trace"]["text"]
        assert sha(text.encode()) == case["trace_text_sha256_utf8"]
        rank = case["sample_rank_1based"]
        entry = {"rank": rank, "problem_id": case["problem_id"], "recorded_correct": bool(row["correct"]),
                 "thinking_cap": case["trace_length_censored"], "trace_tokens": case["trace_token_count"],
                 "trace_characters": len(text), "strong_cues": [{"start": v.start(), "end": v.end(), "text": v.group()} for v in STRONG.finditer(text)],
                 "source_line_sha256": sha(raw), "trace_sha256": sha(text.encode())}
        all_rows.append(entry)
        records[rank] = (case, row, questions[case["problem_id"]])
    targets = [v for v in all_rows if (not v["recorded_correct"] or v["thinking_cap"]) and v["strong_cues"]]
    controls = [v for v in all_rows if v["recorded_correct"] and not v["thinking_cap"] and v["strong_cues"]][:2]
    views = OUT / "natural_views"
    views.mkdir(exist_ok=True)
    for entry in targets + controls:
        case, row, q = records[entry["rank"]]
        text = row["trace"]["text"]
        paragraphs = [{"index": i + 1, "start": m.start(), "end": m.end(), "text": m.group().strip()}
                      for i, m in enumerate(re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text))]
        view = {"rank": entry["rank"], "problem_id": entry["problem_id"], "question": q["question"],
                "trace": text, "paragraphs": paragraphs, "trace_sha256": entry["trace_sha256"],
                "annotation_scope": "Historical thinking only. Gold, final forced readout, grade/correct omitted. Review target selection uses outcome and is disclosed separately."}
        path = views / f"rank_{entry['rank']:03}.json"
        path.write_text(json.dumps(view, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"scope": "Frozen100 metadata plus explicitly outcome-selected diagnostic subset; not native natural-event prevalence.",
              "manifest_sha256": sha(source.read_bytes()), "all100": all_rows,
              "summary": {"n": len(all_rows), "recorded_incorrect": sum(not v["recorded_correct"] for v in all_rows),
                          "thinking_cap": sum(v["thinking_cap"] for v in all_rows),
                          "incorrect_or_cap": sum(not v["recorded_correct"] or v["thinking_cap"] for v in all_rows),
                          "selected_targets": len(targets), "selected_correct_uncapped_controls": len(controls)},
              "target_ranks": [v["rank"] for v in targets], "control_ranks": [v["rank"] for v in controls],
              "limitations": ["Final recorded correctness comes from historical forced boxed readout, not uninterrupted native EOS.",
                              "Wait/cue count is lexical, not a verified revision count.",
                              "Outcome-selected labels do not estimate full100 or natural task event rates.",
                              "Correctness source is int0/1; normalized via bool, never identity-test against False."]}
    (OUT / "NATURAL_TRIAGE_INDEX.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "targets": report["target_ranks"], "controls": report["control_ranks"]}))


if __name__ == "__main__":
    main()
