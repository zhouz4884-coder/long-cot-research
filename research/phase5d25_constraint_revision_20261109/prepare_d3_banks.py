"""Freeze disjoint D3 calibration and evaluation banks from public metadata."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import urllib.request

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
CACHE = REPO / "outputs" / "d3_source_20261109"
SOURCES = {
    "aime24.parquet": ("HuggingFaceH4/aime_2024", "2fe88a2f1091d5048c0f36abc874fb997b3dd99a",
                      "data/train-00000-of-00001.parquet", "26139847601a5037c237d5928b195e7260ca8074cf4f264b794af42847f79ccf"),
    "aime25i.jsonl": ("opencompass/AIME2025", "a6ad95f611d72cf628a80b58bd0432ef6638f958",
                     "aime2025-I.jsonl", "b91b3c96f05d9635d2a0692b124ebe023c1ff59cb19c074275e6c4b349d0659e"),
    "aime25ii.jsonl": ("opencompass/AIME2025", "a6ad95f611d72cf628a80b58bd0432ef6638f958",
                      "aime2025-II.jsonl", "16a2dcfbbf9db1b11f8a69a3ba5e4cac73e3641b19a37e2307e9c12240bbed5e"),
    "olympiad.parquet": ("Hothan/OlympiadBench", "91184b52131e7fc9455fef848035173aea8cc01a",
                         "OlympiadBench/OE_TO_maths_en_COMP/OE_TO_maths_en_COMP.parquet",
                         "7c17ca2662b3ea77cddcb66a64b04ad9b53d3d32fa372d444a4884739eb1638d"),
}
HISTORICAL_BANKS = (
    "data/math500_source.jsonl",
    "research/phase5d2_quarantined_rebase_20261107/d2_visible.jsonl",
    "research/phase5d_scope_rebase_20261106/native_visible.jsonl",
)
SALT = "longcot_d3_hard_disjoint_banks_20261109_v1"
STRATA = ("aime_2024", "aime_2025", "olympiad_Algebra", "olympiad_Number Theory")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def lexical(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace(r"\left", "").replace(r"\right", "")
    return re.findall(r"[a-z]+|\d+", text)


def shingles(text):
    seq = lexical(text)
    return set(zip(seq, seq[1:], seq[2:]))


def write_once(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Would overwrite frozen data {path}")
    else:
        path.write_bytes(raw)


def serialize(rows):
    return b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode() for row in rows)


def load_sources():
    source_rows, provenance = {}, {}
    for key, (dataset, revision, filename, expected) in SOURCES.items():
        path = CACHE / key
        if not path.is_file():
            with urllib.request.urlopen(f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{filename}", timeout=90) as stream:
                payload = stream.read()
            if sha(payload) != expected:
                raise ValueError(f"Dataset source bytes changed {key}")
            write_once(path, payload)
        raw = path.read_bytes()
        if sha(raw) != expected:
            raise ValueError(f"Dataset cache changed {key}")
        rows = pq.read_table(path).to_pylist() if path.suffix == ".parquet" else list(map(json.loads, raw.splitlines()))
        source_rows[key] = rows
        provenance[key] = {"dataset": dataset, "revision": revision, "filename": filename, "sha256": expected,
                           "rows": len(rows), "source_url": f"https://huggingface.co/datasets/{dataset}"}
    return source_rows, provenance


def main():
    source_rows, provenance = load_sources()
    historic = []
    history_sha = {}
    for name in HISTORICAL_BANKS:
        path = REPO / name
        raw = path.read_bytes()
        history_sha[name] = sha(raw)
        for row in map(json.loads, raw.splitlines()):
            q = row.get("question", row.get("problem"))
            if isinstance(q, str) and q:
                historic.append((tuple(lexical(q)), shingles(q)))
    if len(historic) < 530:
        raise ValueError("Historical exclusion pool is incomplete")
    candidates, exclusion = [], Counter()
    for key, rows in source_rows.items():
        for index, row in enumerate(rows):
            question = row.get("question", row.get("problem"))
            if not isinstance(question, str) or not question.strip() or re.search(r"\[asy\]|<image|\b(?:as shown|in the figure)\b", question, re.I):
                exclusion["requires_external_context_or_image"] += 1
                continue
            if key == "olympiad.parquet":
                if (row["subfield"] not in ("Algebra", "Number Theory") or row["answer_type"] != "Numerical"
                        or row["is_multiple_answer"] or row["context"] or row["unit"]):
                    exclusion["outside_structured_numeric_algebra_number_theory_stratum"] += 1
                    continue
                stratum = "olympiad_" + row["subfield"]
                source_id = str(row["id"])
            else:
                stratum = "aime_2024" if key.startswith("aime24") else "aime_2025"
                source_id = str(row["id"]) if "id" in row else f"{key}:{index+1:02d}"
            tokens, sig = tuple(lexical(question)), shingles(question)
            if any(tokens == other or (len(sig) >= 12 and len(other_sig) >= 12 and
                                       len(sig & other_sig) / len(sig | other_sig) >= .84)
                   for other, other_sig in historic):
                exclusion["matches_known_history_exact_or_lexical_near_duplicate"] += 1
                continue
            candidates.append({"source": key, "source_index": index, "source_id": source_id, "question": question,
                               "stratum": stratum, "problem_hash": sha(question.encode()), "answer_kind": "scalar",
                               "rank": sha(f"{SALT}/{stratum}/{source_id}".encode())})

    selected = {"precheck": [], "bank": []}
    selected_sigs = []
    for stratum in STRATA:
        unique = []
        for item in sorted((row for row in candidates if row["stratum"] == stratum), key=lambda row: row["rank"]):
            sig = shingles(item["question"])
            if any(sig == old or (len(sig) >= 12 and len(old) >= 12 and len(sig & old) / len(sig | old) >= .84)
                   for old in selected_sigs):
                exclusion["cross_bank_lexical_duplicate"] += 1
                continue
            unique.append(item)
            selected_sigs.append(sig)
            if len(unique) == 6:
                break
        if len(unique) != 6:
            raise ValueError(f"Insufficient disjoint problems in {stratum}")
        selected["precheck"].extend(unique[:2])
        selected["bank"].extend(unique[2:])

    bindings = {}
    for bank, rows in selected.items():
        visible, evaluation = [], []
        for index, row in enumerate(rows, 1):
            case_id = f"D3_{'P' if bank == 'precheck' else 'E'}{index:02d}"
            visible.append({"case_id": case_id, **row})
            source = source_rows[row["source"]][row["source_index"]]
            gold = source["final_answer"] if row["source"] == "olympiad.parquet" else [source["answer"]]
            if not isinstance(gold, list) or len(gold) != 1 or not isinstance(gold[0], (str, int)) or not str(gold[0]).strip():
                raise ValueError(f"Frozen source item has no scalar reference: {case_id}")
            evaluation.append({"case_id": case_id, "gold": str(gold[0]), "answer_kind": row["answer_kind"]})
        path = ROOT / "prepared_data" / bank
        visible_raw, evaluation_raw = serialize(visible), serialize(evaluation)
        write_once(path / "visible.jsonl", visible_raw)
        write_once(path / "eval_only.jsonl", evaluation_raw)
        bindings[bank] = {"count": len(rows), "seeds": [20261109] if bank == "precheck" else [20261109, 20261110],
                          "visible_sha256": sha(visible_raw), "eval_only_sha256": sha(evaluation_raw),
                          "selected_ids": [[row["case_id"], row["source_id"], row["stratum"]] for row in visible]}
    manifest = {"status": "FROZEN", "selection_salt": SALT, "source_artifacts": provenance, "historical_exclusion_sha256": history_sha,
                "historical_questions_seen": len(historic), "exclusions": dict(exclusion), "banks": bindings,
                "eligible_candidates_by_stratum": dict(Counter(row["stratum"] for row in candidates)),
                "selection_basis": "Metadata only, English text AIME and single numeric algebra/number theory OlympiadBench. Hash rank and disjoint splits fixed before any new model outcome. Exclusion is exact or lexical near-duplicate, not semantic equivalence.",
                "runtime": "Frozen Qwen3-4B FP16 SDPA, native thinking and original D2 sampling through natural EOS or actual context capacity."}
    write_once(ROOT / "D3_DATA_FREEZE.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"counts": {bank: data["count"] for bank, data in bindings.items()},
                      "eligible_candidates": manifest["eligible_candidates_by_stratum"], "exclusions": manifest["exclusions"]}, indent=2))


if __name__ == "__main__":
    main()
