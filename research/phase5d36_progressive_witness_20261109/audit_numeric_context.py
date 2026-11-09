"""Review the frozen literal scan for context and source-boundary artifacts."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re

from audit_d3_cross_phase import D3, OBSERVATIONS, ROOT, persist, verify_published
from numeric_contradiction import _math_relations, _OPERATORS, scan_numeric_relations


DESTINATION = ROOT / "D36_NUMERIC_CONTEXT_REVIEW.json"
_BULLET = re.compile(r"^-\s+")
_RHS_NUMBER = r"[+-]?[0-9]+(?:\.[0-9]+)?"
_ACCUMULATOR = re.compile(rf"^[+-]{_RHS_NUMBER}\s*=\s*{_RHS_NUMBER}[.]?$")
_PRIOR_RHS = re.compile(rf"=\s*{_RHS_NUMBER}[.]?\s*$")


def review_scope(text, row, occurrence):
    start, end = row["start"], row["end"]
    before = text[max(0, start - 300):start]
    after = text[end:end + 160]
    source = text[start:end]
    if source != row["source"]:
        raise ValueError("Literal observation does not match its source span")
    decision = {**row, "initial_scope": row["scope"], "initial_exact_truth": row["exact_truth"],
                "context_rule": "unchanged"}
    if row["extraction"] in {"EXPLICIT_NUMERIC_PROSE", "BOUNDED_ADJACENT_COREFERENCE"}:
        if (before and before[-1] in "/^_}" or re.match(r"(?:\.\.\.|…|\s*[/^_])", after)):
            return {**decision, "scope": "DEFERRED_COMPOSITE_OPERAND", "context_rule": "unparsed_adjacent_operand"}
    if row["extraction"] == "WHOLE_NUMERIC_LINE":
        if _BULLET.match(source):
            siblings = re.search(r"(?m)^\s*-\s+\d", before + "\n" + after)
            if siblings or before.rstrip().endswith(":"):
                try:
                    values = _math_relations(_BULLET.sub("", source, count=1))
                    left, op, right = values[occurrence]
                except (ValueError, ArithmeticError, SyntaxError, IndexError):
                    return {**decision, "scope": "DEFERRED_LIST_MARKUP", "context_rule": "unsupported_bullet"}
                return {**decision, "left": str(left), "operator": op, "right": str(right),
                        "exact_truth": _OPERATORS[op](left, right), "context_rule": "remove_markdown_list_marker"}
            return {**decision, "scope": "DEFERRED_LIST_MARKUP", "context_rule": "possible_bullet"}
        if _ACCUMULATOR.fullmatch(source) and _PRIOR_RHS.search(before):
            return {**decision, "scope": "DEFERRED_RUNNING_TOTAL", "context_rule": "missing_prior_accumulator_operand"}
    return decision


def review_numeric_relations(text, initial_rows=None):
    """Retain raw candidates and downgrade fragments before using a numeric alert."""
    rows = scan_numeric_relations(text) if initial_rows is None else initial_rows
    occurrences = Counter()
    results = []
    for row in rows:
        key = row["start"], row["end"]
        results.append(review_scope(text, row, occurrences[key]))
        occurrences[key] += 1
    return results


def main():
    frozen_raw = OBSERVATIONS.read_bytes()
    frozen = json.loads(frozen_raw)
    assert frozen["status"] == "FROZEN_BEFORE_REFERENCE"
    rows = []
    counts = Counter()
    for row in frozen["trajectories"]:
        source = json.loads(verify_published(D3 / row["source_path"]))
        thinking, _, _ = source["text"].partition("</think>")
        thinking = thinking.removeprefix("<think>")
        final = source["final_response"]
        for name, segment in (("thinking", thinking), ("final", final)):
            assert sha256(segment.encode()).hexdigest() == row[f"{'think' if name == 'thinking' else 'final'}_text_sha256"]
            checked = review_numeric_relations(segment, row[f"{name}_numeric_relations"])
            for event in checked:
                if event["initial_scope"] != "ASSERTED_EXACT" or event["initial_exact_truth"]:
                    continue
                retained = event["scope"] == "ASSERTED_EXACT" and not event["exact_truth"]
                counts["initial_false_candidates"] += 1
                counts["retained_exact_false_assertions" if retained else "rejected_context_artifacts"] += 1
                counts[event["context_rule"]] += 1
                rows.append({"case_id": row["case_id"], "seed": row["seed"], "phase": name,
                             "retained": retained, **event})
    report = {"status": "COMPLETE_CONTEXT_PRECISION_REVIEW",
              "scope": "A second-pass precision check motivated by the initial observed raw alerts. Never reads Gold.",
              "frozen_observation_sha256": sha256(frozen_raw).hexdigest(),
              "additional_gpu_seconds": 0, "counts": dict(counts),
              "retained_unique_trajectories": len({(r["case_id"], r["seed"]) for r in rows if r["retained"]}),
              "retained_unique_problems": len({r["case_id"] for r in rows if r["retained"]}),
              "reviewed_flags": rows}
    digest = persist(DESTINATION, report)
    print(json.dumps({k: v for k, v in report.items() if k != "reviewed_flags"}))
    print(json.dumps({"context_review_sha256": digest}))


if __name__ == "__main__":
    main()
