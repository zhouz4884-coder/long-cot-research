"""Prepare exact private scope packets and bind independent judgments without gold."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns

from freeze_d46_intake import HERE, ROOT, digest, load, sha, write_exclusive
from extract_candidates import load_author_scorer
from point_verifier import ASSERTED_ORIGINAL_CANDIDATE, exact_literal

RULES = HERE / "D46_SCOPE_AUDIT_RULES.json"


def jobs(claims: dict, blind: dict, cohort: dict, parser) -> list[dict]:
    raw = {r["sample_id"]: r["response"] for r in blind["rows"]}
    cases = {r["case_id"]: r for r in cohort["rows"]}
    records = []
    for row in claims["rows"]:
        cid = row["case_id"]
        for point in ("early", "late"):
            observation = row[point]
            if observation["status"] not in {"EXPLICIT_SCOPED_POINT", "LATER_UNSCOPED_BOX"}:
                continue
            text = raw[row["sample_id"]]
            begin, end = observation["observation_char_span_in_response"]
            excerpt_start = max(begin, end-3000)
            if observation["status"] == "EXPLICIT_SCOPED_POINT":
                lo, hi = (begin+p for p in observation["numeric_span"])
                a, b = (begin+p for p in observation["assertion_span"])
                literal = text[lo:hi]
                if digest(literal.encode()) != observation["numeric_sha256"]:
                    raise ValueError("Strict numeric source changed")
                excerpt_start = min(excerpt_start, a)
            else:
                a, b = observation["char_span_in_response"]
                box = text[a:b]
                parsed, malformed = parser.scan_box_events(box)
                if digest(box.encode()) != observation["source_excerpt_sha256"]:
                    raise ValueError("Unscoped source box changed")
                if malformed or len(parsed) != 1 or not parsed[0].valid:
                    lo, hi = a, b
                    literal = box
                else:
                    lo, hi = a+box.index("{")+1, b-1
                    literal = text[lo:hi]
            value = exact_literal(literal)
            if not begin <= excerpt_start <= a <= lo < hi <= b <= end:
                raise ValueError("Scope packet exceeded the actual observed prefix")
            records.append({
                "job_id": row["sample_id"] + "@" + point, "case_id": cid, "direction": cases[cid]["direction"],
                "objective_summary": cases[cid]["description"], "visible_excerpt": text[excerpt_start:end],
                "numeric_literal": literal, "numeric_span_in_excerpt": [lo-excerpt_start, hi-excerpt_start],
                "numeric_sha256": digest(literal.encode()),
                "exact_value": None if value is None else value.numerator if value.denominator == 1 else str(value),
                "observation_prefix_sha256": observation["observation_prefix_sha256"],
                "private_source_offsets": {"begin": begin, "excerpt": excerpt_start, "lo": lo, "hi": hi, "assertion_end": b},
            })
    return records


def prepare(claims_path: Path, blind_path: Path, cohort_path: Path, parser_path: Path,
            packet_paths: list[Path], output: Path) -> None:
    claims, blind, cohort = map(load, (claims_path, blind_path, cohort_path))
    if claims["blind_input_sha256"] != sha(blind_path) or claims["cohort_freeze_sha256"] != sha(cohort_path):
        raise ValueError("Scope packets do not match strict archive receipts")
    records = jobs(claims, blind, cohort, load_author_scorer(parser_path))
    packets = []
    for index, path in enumerate(packet_paths):
        items = records[index::len(packet_paths)]
        write_exclusive(path, {"status": "BLIND_ROLE_ADJUDICATION_ONLY", "rows": items})
        packets.append({"sha256": sha(path), "job_ids": [row["job_id"] for row in items]})
    write_exclusive(output, {
        "status": "D46_SCOPE_PACKETS_FROZEN_BEFORE_GOLD", "strict_claims_sha256": sha(claims_path),
        "blind_sha256": sha(blind_path), "cohort_sha256": sha(cohort_path), "rules_sha256": sha(RULES),
        "packets": packets, "job_count": len(records),
    })
    print("D46_SCOPE_PACKETS_FROZEN_BEFORE_GOLD", len(records))


def finalize(args) -> None:
    began = perf_counter_ns()
    strict, blind, cohort, freeze = map(load, (args.claims, args.blind, args.cohort, args.freeze))
    if (sha(args.claims) != freeze["strict_claims_sha256"] or sha(args.blind) != freeze["blind_sha256"]
            or sha(args.cohort) != freeze["cohort_sha256"] or sha(RULES) != freeze["rules_sha256"]):
        raise ValueError("Scope review sources changed")
    expected = jobs(strict, blind, cohort, load_author_scorer(args.author_scorer))
    expected_by_id = {r["job_id"]: r for r in expected}
    sensitivity = deepcopy(strict)
    by_sample = {r["sample_id"]: r for r in sensitivity["rows"]}
    raw = {r["sample_id"]: r["response"] for r in blind["rows"]}
    results, seen = [], set()
    for packet_path, review_path, pinned in zip(args.packets, args.reviews, freeze["packets"], strict=True):
        packet, review = load(packet_path), load(review_path)
        if sha(packet_path) != pinned["sha256"] or review["packet_sha256"] != pinned["sha256"]:
            raise ValueError("Blinded reviewer packet identity changed")
        expected_packet = [expected_by_id[x] for x in pinned["job_ids"]]
        actual = {r["job_id"]: r for r in review["rows"]}
        if packet["rows"] != expected_packet or set(actual) != set(pinned["job_ids"]) or len(actual) != len(review["rows"]):
            raise ValueError("Blinded scope review denominator changed")
        for item in expected_packet:
            jid = item["job_id"]
            if jid in seen:
                raise ValueError("Duplicate scope decision")
            seen.add(jid)
            decision = actual[jid]
            status = decision["decision"]
            if (decision["numeric_sha256"] != item["numeric_sha256"] or status not in {"BOUND", "UNKNOWN", "WRONG_OBJECT"}
                    or (status == "BOUND" and (decision["value"] is None or decision["value"] != item["exact_value"]))
                    or (status != "BOUND" and decision["value"] is not None)):
                raise ValueError(f"Scope adjudication changed an exact literal: {jid}")
            sid, point = jid.rsplit("@", 1)
            row = by_sample[sid]
            obs = row[point]
            strict_status = obs["status"]
            if status == "BOUND" and strict_status == "LATER_UNSCOPED_BOX":
                span = item["private_source_offsets"]
                begin, lo, hi, end = (span[k] for k in ("begin", "lo", "hi", "assertion_end"))
                start = span["excerpt"]
                value = Fraction(decision["value"])
                obs.update(
                    status="EXPLICIT_SCOPED_POINT", scope_status="ORIGINAL_REQUESTED_SCALAR", direction=row["direction"],
                    assertion_role=ASSERTED_ORIGINAL_CANDIDATE, complete_explicit_candidate=True,
                    value=decision["value"], rational={"numerator": value.numerator, "denominator": value.denominator},
                    numeric_span=[lo-begin, hi-begin], numeric_text=item["numeric_literal"],
                    assertion_span=[start-begin, end-begin], assertion_sha256=digest(raw[sid][start:end].encode()),
                    scope_review_sha256=sha(review_path),
                )
            elif status != "BOUND" and strict_status == "EXPLICIT_SCOPED_POINT":
                obs.update(status="BLIND_REVIEW_ABSTAINS", scope_status="UNBOUND", complete_explicit_candidate=False,
                           value=None, rational=None)
            results.append({**decision, "strict_status": strict_status, "review_output_sha256": sha(review_path)})
    if seen != set(expected_by_id):
        raise ValueError("Incomplete blind role audit")
    audit = {"status": "D46_SCOPE_JUDGMENTS_FROZEN_BEFORE_GOLD", "packet_freeze_sha256": sha(args.freeze),
             "strict_claims_sha256": sha(args.claims), "rules_sha256": sha(RULES),
             "decisions": dict(Counter(row["decision"] for row in results)),
             "wall_ns": perf_counter_ns()-began, "manual_role_judgment_cost": "Not timed per case", "rows": results}
    write_exclusive(args.output, audit)
    sensitivity["scope"] = "Separate gold-blind semantic sensitivity. Strict primary observations remain unchanged."
    sensitivity["scope_audit_sha256"] = sha(args.output)
    for point in ("early", "late"):
        sensitivity[point + "_counts"] = dict(Counter(r[point]["status"] for r in sensitivity["rows"]))
    write_exclusive(args.sensitivity, sensitivity)
    print(audit["status"], audit["decisions"], sha(args.sensitivity))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("prepare", "finalize"))
    for flag in ("claims", "blind", "cohort", "author-scorer", "freeze"):
        cli.add_argument("--" + flag, required=True, type=Path)
    cli.add_argument("--packets", required=True, type=Path, nargs=2)
    cli.add_argument("--reviews", type=Path, nargs=2)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--sensitivity", type=Path)
    args = cli.parse_args()
    if not all(path.resolve().is_relative_to(ROOT / "outputs") for path in args.packets):
        cli.error("Private excerpt packets stay under outputs")
    if args.mode == "prepare":
        prepare(args.claims, args.blind, args.cohort, args.author_scorer, args.packets, args.freeze)
    else:
        if args.output is None or args.sensitivity is None or args.reviews is None:
            cli.error("Finalize requires both review files and both output paths")
        finalize(args)


if __name__ == "__main__":
    main()
