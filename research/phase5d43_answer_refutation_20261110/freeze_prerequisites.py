"""Bind candidate-blind proof authoring and independent review without publishing source excerpts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from time import perf_counter_ns, thread_time_ns

from freeze_cohort import digest, question_digest, write_exclusive
from scoped_refutation import (
    CLOSED_INTERVAL,
    CONGRUENCE,
    FINITE_EXCLUSIONS,
    REVIEWED_NECESSARY_DERIVATION,
    NecessaryPredicate,
    ObjectiveBinding,
    ReviewedPrerequisite,
    application_signature,
)


def canonical(value) -> str:
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def anchor_receipt(question: str, item: str | dict) -> dict:
    if isinstance(item, str):
        offsets = [m.start() for m in re.finditer(re.escape(item), question)] if item else []
        if not offsets:
            raise ValueError("Quoted premise anchor is absent from the exact question")
        start, end = offsets[0], offsets[0] + len(item)
        repeats = len(offsets)
        role = "author_premise_quote"
    else:
        start, end = item["char_span_0_based_half_open"]
        if not (0 <= start < end <= len(question)) or digest(question[start:end].encode()) != item["sha256_utf8"]:
            raise ValueError("Declared premise anchor differs from the exact question")
        repeats = 1
        role = item["role"]
    return {"char_span_0_based_half_open": [start, end], "sha256_utf8": digest(question[start:end].encode()),
            "role_sha256": digest(role.encode()), "matching_position_count": repeats}


def typed(spec: dict) -> NecessaryPredicate:
    kind = spec["kind"]
    if kind == "congruence":
        return NecessaryPredicate(CONGRUENCE, (spec["modulus"], spec["residue"]))
    if kind == "closed_interval":
        return NecessaryPredicate(CLOSED_INTERVAL, (spec["lo"], spec["hi"]))
    if kind == "finite_exclusions":
        return NecessaryPredicate(FINITE_EXCLUSIONS, tuple(sorted(spec["integers"])))
    raise ValueError(f"Unknown authored predicate kind {kind}")


def make_row(question: dict, author: dict, review: dict) -> dict:
    keys = ("problem_id", "index")
    if not all(question[k] == author[k] == review[k] for k in keys):
        raise ValueError("Author and review target are not the same frozen question")
    text = question["question"]
    qhash = question_digest(text)
    if question["normalized_question_sha256"] != qhash or author["normalized_question_sha256"] != qhash:
        raise ValueError("Question differs from the frozen normalized identity")
    exact = digest(text.encode())
    scope_hash = digest(author["scope"].encode())
    binding = ObjectiveBinding(exact, author["objective_id"], "original-target:" + scope_hash)
    by_hash = {row["predicate_sha256"]: row for row in review["predicate_reviews"]}
    specs = author["predicates"]
    if set(by_hash) != {canonical(spec) for spec in specs} or len(by_hash) != len(specs):
        raise ValueError("Missing or duplicate exact predicate review")
    if review["objective_status"] not in {"APPROVE", "REJECT"}:
        raise ValueError("Missing independent judgment about the requested target")
    proposals, approved = [], []
    for spec in specs:
        spec_hash = canonical(spec)
        review_item = by_hash[spec_hash]
        source_anchors = [anchor_receipt(text, anchor) for anchor in spec["anchors"]]
        if not source_anchors:
            raise ValueError("A proposed prerequisite needs a premise anchor")
        provenance = {
            "exact_question_sha256": exact, "predicate_proposal_sha256": spec_hash,
            "scope_description_sha256": scope_hash, "proof_sha256": digest(spec["proof"].encode()),
            "premise_anchors": source_anchors,
        }
        provenance_hash = canonical(provenance)
        review_hash = canonical(review_item)
        decision = review_item["decision"]
        proposals.append({
            **provenance, "source_sha256": provenance_hash, "review_sha256": review_hash,
            "kind": spec["kind"], "decision": decision,
            "ordinary_direct_overlap": bool(review_item.get("ordinary_direct_overlap", False)),
        })
        if decision != "APPROVE" or review["objective_status"] != "APPROVE":
            continue
        predicate = typed(spec)
        if predicate.kind == CLOSED_INTERVAL and predicate.args[0] == predicate.args[1]:
            raise ValueError("An exact singleton is a direct solution, not a limited constraint")
        signature = application_signature(binding, predicate)
        item = ReviewedPrerequisite(
            binding, predicate, REVIEWED_NECESSARY_DERIVATION,
            provenance_hash, review_hash, signature,
        )
        approved.append({
            "kind": predicate.kind, "args": predicate.args, "source_kind": item.source_kind,
            "source_sha256": provenance_hash, "review_sha256": review_hash,
            "application_sha256": signature, "prerequisite_sha256": item.sha256,
        })
    if len(approved) > 2:
        raise ValueError("More than two approved predicates for a single question")
    return {
        "index": question["index"], "problem_id": question["problem_id"],
        "exact_question_sha256": exact, "normalized_question_sha256": qhash,
        "objective_id": binding.objective_id, "scope": binding.scope,
        "scope_description_sha256": scope_hash, "objective_review": review["objective_status"],
        "author_status": author["status"], "proposal_audit": proposals, "approved_predicates": approved,
    }


def freeze(question_path: Path, author_paths: list[Path], review_paths: list[Path]) -> dict:
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    question_bytes = question_path.read_bytes()
    question_sha = digest(question_bytes)
    question_only = json.loads(question_bytes)
    questions = {r["index"]: r for r in question_only["questions"]}
    if set(questions) != set(range(1, 33)):
        raise ValueError("Question-only view lacks all 32 locked questions")
    all_rows, handoffs = [], []
    for author_path, review_path in zip(author_paths, review_paths, strict=True):
        authored_bytes, reviewed_bytes = author_path.read_bytes(), review_path.read_bytes()
        authored, reviewed = json.loads(authored_bytes), json.loads(reviewed_bytes)
        authored_sha = digest(authored_bytes)
        if (authored["question_only_sha256"] != question_sha or reviewed["question_only_sha256"] != question_sha
                or reviewed["author_sha256"] != authored_sha):
            raise ValueError("Independent review is for a different input")
        by_index = {row["index"]: row for row in reviewed["rows"]}
        if len(by_index) != 16 or set(by_index) != {row["index"] for row in authored["rows"]}:
            raise ValueError("Missing independent review for assigned questions")
        for author in authored["rows"]:
            index = author["index"]
            all_rows.append(make_row(questions[index], author, by_index[index]))
        handoffs.append({
            "author_sha256": authored_sha, "review_sha256": digest(reviewed_bytes),
            "indices": sorted(by_index),
            "author_reported_timing": authored.get("timing"),
            "review_reported_timing": reviewed.get("timing"),
            "author_wall_upper_bound_since_question_view_seconds": round(
                author_path.stat().st_mtime - question_path.stat().st_mtime, 3,
            ),
            "review_wall_upper_bound_since_question_view_seconds": round(
                review_path.stat().st_mtime - question_path.stat().st_mtime, 3,
            ),
        })
    if sorted(row["index"] for row in all_rows) != list(range(1, 33)):
        raise ValueError("Question review coverage is incomplete")
    return {
        "status": "REVIEWED_QUESTION_ONLY_PREREQUISITES_FROZEN",
        "cohort_freeze_sha256": question_only["cohort_freeze_sha256"],
        "question_only_sha256": question_sha,
        "approval_boundary": "Independent math review authorizes exact necessary-condition applications. No gold or trace evidence used.",
        "local_handoffs": handoffs,
        "rows": sorted(all_rows, key=lambda row: row["index"]),
        "cost": {"wall_ns": perf_counter_ns() - started_wall, "cpu_ns": thread_time_ns() - started_cpu},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-only", type=Path, required=True)
    parser.add_argument("--authors", type=Path, nargs=2, required=True)
    parser.add_argument("--reviews", type=Path, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_exclusive(args.output, freeze(args.question_only, args.authors, args.reviews))


if __name__ == "__main__":
    main()
