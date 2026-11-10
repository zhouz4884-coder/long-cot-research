"""Compare the frozen HMMT questions with available prior question projections."""
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = (
    ("outputs/d43_aime_source_20261110/d43_question_only.json", "questions", "problem_id"),
    ("outputs/d44_aime_source_20261110/d44_live_visible.json", "rows", "case_id"),
    ("outputs/d45_aime_source_20261110/d45_question_only.json", "rows", "case_id"),
    ("outputs/d46_aime_source_20261110/d46_question_only.json", "rows", "case_id"),
    ("outputs/d47_aime_source_20261110/d47_question_only.json", "rows", "case_id"),
    ("research/phase5d35_witness_gated_revision_20261109/prepared/e12_checkpoint.json", None, "case_id"),
    ("research/phase5d35_witness_gated_revision_20261109/prepared/e15_checkpoint.json", None, "case_id"),
)


def digest(raw):
    return sha256(raw).hexdigest()


def normalize(statement):
    statement = unicodedata.normalize("NFKC", statement).casefold()
    statement = re.sub(r"\\(?:left|right|displaystyle)\b", "", statement)
    return "".join(re.findall(r"[a-z0-9]+", statement))


def main():
    before = []
    receipts = []
    for filename, collection, identity in OLD:
        raw = (ROOT / filename).read_bytes()
        source = json.loads(raw)
        rows = [source] if collection is None else source[collection]
        before.extend((r[identity], normalize(r["question"])) for r in rows)
        receipts.append({"path": filename, "rows": len(rows), "sha256": digest(raw)})
    path = ROOT / "outputs/d48_matharena_blind_20261110/d48_reasoning_only.json"
    current_raw = path.read_bytes()
    current = json.loads(current_raw)
    if current["status"] != "D48_LOCAL_REASONING_ONLY_BLIND":
        raise ValueError("Expected the question/think-only archive projection")
    matched = []
    identities = set()
    fingerprints = set()
    for row in current["rows"]:
        question = row["question"]
        if digest(question.encode()) != row["archive_problem_sha256"]:
            raise ValueError("Question bytes differ")
        normalized = normalize(question)
        if not normalized or normalized in fingerprints or row["case_id"] in identities:
            raise ValueError("Missing or duplicate HMMT question")
        fingerprints.add(normalized)
        identities.add(row["case_id"])
        identity, similarity = max(((i, SequenceMatcher(None, normalized, q).ratio()) for i, q in before),
                                   key=lambda pair: pair[1])
        if similarity == 1 or row["case_id"] in {i for i, _ in before}:
            raise ValueError("A heldout HMMT identity or question overlaps a prior projection")
        matched.append({"case_id": row["case_id"], "normalized_question_sha256": digest(normalized.encode()),
                        "nearest_prior_id": identity, "normalized_character_similarity": round(similarity, 4)})
    expected = {r[0] for r in json.loads((HERE / "D48_QUESTION_FREEZE.json").read_bytes())["rows"] if r[1]}
    if identities != expected:
        raise ValueError("HMMT IDs differ from frozen cohort")
    print(json.dumps({
        "status": "NO_EXACT_QUESTION_OVERLAP_IN_AVAILABLE_D43_TO_D47_AND_E12_E15",
        "checked_prior_question_rows": len(before), "checked_current_question_rows": len(identities),
        "prior_sources": receipts, "current_input_sha256": digest(current_raw),
        "scope": "Uses only question strings. Character similarity is a screening diagnostic, not a semantic equivalence proof.",
        "rows": matched,
    }, indent=2))


if __name__ == "__main__":
    main()
