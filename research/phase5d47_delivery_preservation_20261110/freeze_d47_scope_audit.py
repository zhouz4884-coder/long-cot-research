"""Prepare exact private stage-separated packets and bind blind scope judgments."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns

from freeze_d47_intake import HERE, ROOT, digest, load, sha, write_exclusive
from extract_candidates import load_author_scorer
from point_verifier import ASSERTED_ORIGINAL_CANDIDATE, exact_literal

SLOTS = ("early", "late", "final_point")
RULES = HERE / "D47_SCOPE_AUDIT_RULES.json"


def jobs(readout, blind, cohort, parser):
    raw = {row["sample_id"]: row["response"] for row in blind["rows"]}
    scopes = {row["case_id"]: row for row in cohort["rows"]}
    packets = {slot: [] for slot in SLOTS}
    for row in readout["rows"]:
        text, spec = raw[row["sample_id"]], scopes[row["case_id"]]
        for slot in SLOTS:
            seen = row[slot]
            if slot == "final_point":
                if not row["native_final_eligible"] or "observation_char_span_in_response" not in seen or seen["status"] == "FINAL_CHANNEL_CONTROL_AMBIGUOUS":
                    continue
            elif seen["status"] not in {"EXPLICIT_SCOPED_POINT", "LATER_UNSCOPED_BOX"}:
                continue
            begin, end = seen["observation_char_span_in_response"]
            left = max(begin, end-3000)
            if seen["status"] == "EXPLICIT_SCOPED_POINT":
                a, b = (begin+offset for offset in seen["assertion_span"])
                lo, hi = (begin+offset for offset in seen["numeric_span"])
                literal = text[lo:hi]
                left = min(left, a)
                if digest(literal.encode()) != seen["numeric_sha256"]:
                    raise ValueError("Exact original literal changed")
            else:
                box_receipt = seen["official_final_box_receipt"] if slot == "final_point" else seen
                a, b = box_receipt["char_span_in_response"]
                box = text[a:b]
                parsed, malformed = parser.scan_box_events(box)
                if digest(box.encode()) != box_receipt["source_excerpt_sha256"]:
                    raise ValueError("Terminal box changed")
                if malformed or len(parsed) != 1 or not parsed[0].valid:
                    lo, hi = a, b
                else:
                    lo, hi = a+box.index("{")+1, b-1
                literal = text[lo:hi]
                left = min(left, a)
            if not begin <= left <= a <= lo < hi <= b <= end:
                raise ValueError("Scope packet exceeds the actual stage observation")
            value = exact_literal(literal)
            packets[slot].append({
                "job_id": row["sample_id"]+"@"+slot, "case_id": row["case_id"], "stage": slot,
                "original_object": spec["description"], "original_unit": spec["unit"], "direction": spec["direction"],
                "visible_excerpt": text[left:end], "numeric_literal": literal,
                "numeric_sha256": digest(literal.encode()), "numeric_span_in_excerpt": [lo-left, hi-left],
                "exact_value": None if value is None else value.numerator if value.denominator == 1 else str(value),
                "prefix_sha256": seen["observation_prefix_sha256"],
                "private_source_offsets": {"begin": begin, "left": left, "lo": lo, "hi": hi, "assertion_end": b},
            })
    return packets


def precheck(args):
    readout, blind, cohort = map(load, (args.readout, args.blind, args.cohort))
    if readout["blind_input_sha256"] != sha(args.blind) or readout["cohort_freeze_sha256"] != sha(args.cohort):
        raise ValueError("Different original blind source")
    return readout, blind, cohort


def prepare(args):
    readout, blind, cohort = precheck(args)
    packets = jobs(readout, blind, cohort, load_author_scorer(args.author_scorer))
    frozen = []
    for slot, path in zip(SLOTS, args.packets, strict=True):
        records = packets[slot]
        write_exclusive(path, {"status": "D47_STAGE_ONLY_BLIND_SCOPE_REVIEW", "stage": slot, "rows": records})
        frozen.append({"stage": slot, "sha256": sha(path), "job_ids": [r["job_id"] for r in records]})
    out = {"status": "D47_STAGE_PACKETS_FROZEN_BEFORE_GOLD", "readout_sha256": sha(args.readout),
           "blind_sha256": sha(args.blind), "cohort_sha256": sha(args.cohort), "rules_sha256": sha(RULES), "packets": frozen}
    write_exclusive(args.freeze, out)
    print(out["status"], {slot: len(values) for slot, values in packets.items()})


def finalize(args):
    began = perf_counter_ns()
    readout, blind, cohort = precheck(args)
    freeze = load(args.freeze)
    if [freeze[k] for k in ("readout_sha256", "blind_sha256", "cohort_sha256", "rules_sha256")] != [
        sha(args.readout), sha(args.blind), sha(args.cohort), sha(RULES),
    ]:
        raise ValueError("Exact blind review freeze differs")
    packets = jobs(readout, blind, cohort, load_author_scorer(args.author_scorer))
    sensitive = deepcopy(readout)
    by_sample = {row["sample_id"]: row for row in sensitive["rows"]}
    raw = {row["sample_id"]: row["response"] for row in blind["rows"]}
    judgments = []
    for slot, packet_path, result_path, expected in zip(SLOTS, args.packets, args.reviews, freeze["packets"], strict=True):
        packet, result = load(packet_path), load(result_path)
        if (
            sha(packet_path) != expected["sha256"] or result["packet_sha256"] != expected["sha256"]
            or packet["stage"] != slot or packet["rows"] != packets[slot]
            or [r["job_id"] for r in packets[slot]] != expected["job_ids"]
        ):
            raise ValueError("Role reviewer used a different stage or source")
        by_id = {r["job_id"]: r for r in result["rows"]}
        if len(by_id) != len(result["rows"]) or set(by_id) != set(expected["job_ids"]):
            raise ValueError("Blind review changed its denominator")
        review_sha = sha(result_path)
        for item in packets[slot]:
            jid = item["job_id"]
            sid, _ = jid.rsplit("@", 1)
            row, decision = by_sample[sid], by_id[jid]
            original = row[slot]["status"]
            bound = decision["decision"] == "BOUND"
            if (
                decision["numeric_sha256"] != item["numeric_sha256"]
                or decision["decision"] not in {"BOUND", "WRONG_OBJECT", "UNKNOWN"}
                or (bound and (decision["value"] is None or decision["value"] != item["exact_value"]))
                or (not bound and decision["value"] is not None)
            ):
                raise ValueError(f"Role review changed the exact literal: {jid}")
            if bound and original != "EXPLICIT_SCOPED_POINT":
                span = item["private_source_offsets"]
                begin, lo, hi, end, left = (span[k] for k in ("begin", "lo", "hi", "assertion_end", "left"))
                value = Fraction(decision["value"])
                if slot == "final_point" and value != Fraction(row["final"]["value"]):
                    raise ValueError("Blind final role changed the native delivered value")
                row[slot].update(
                    status="EXPLICIT_SCOPED_POINT", scope_status="ORIGINAL_REQUESTED_SCALAR", direction=row["direction"],
                    assertion_role=ASSERTED_ORIGINAL_CANDIDATE, complete_explicit_candidate=True,
                    value=decision["value"], rational={"numerator": value.numerator, "denominator": value.denominator},
                    numeric_span=[lo-begin, hi-begin], numeric_text=item["numeric_literal"],
                    assertion_span=[left-begin, end-begin], assertion_sha256=digest(raw[sid][left:end].encode()),
                    scope_review_sha256=review_sha,
                )
            elif not bound and original == "EXPLICIT_SCOPED_POINT":
                row[slot].update(status="BLIND_ROLE_REVIEW_ABSTAINS", scope_status="UNBOUND",
                                 complete_explicit_candidate=False, value=None, rational=None)
            judgments.append({**decision, "stage": slot, "strict_status": original, "review_output_sha256": review_sha})
    audit = {"status": "D47_STAGE_SCOPE_JUDGMENTS_FROZEN_BEFORE_GOLD",
             "packet_freeze_sha256": sha(args.freeze), "strict_readout_sha256": sha(args.readout), "rules_sha256": sha(RULES),
             "counts": dict(Counter(r["decision"] for r in judgments)),
             "manual_cost": "Individual reviewer durations not instrumented", "reconciliation_wall_ns": perf_counter_ns()-began,
             "rows": judgments}
    write_exclusive(args.output, audit)
    sensitive["scope"] = "Separate pre-gold stage-specific human scope sensitivity; strict primary remains fixed."
    sensitive["scope_audit_sha256"] = sha(args.output)
    for slot in SLOTS:
        sensitive[slot+"_counts"] = dict(Counter(r[slot]["status"] for r in sensitive["rows"]))
    write_exclusive(args.sensitivity, sensitive)
    print(audit["status"], audit["counts"], sha(args.sensitivity))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("prepare", "finalize"))
    for key in ("readout", "blind", "cohort", "author-scorer", "freeze"):
        cli.add_argument("--"+key, type=Path, required=True)
    cli.add_argument("--packets", nargs=3, type=Path, required=True)
    cli.add_argument("--reviews", nargs=3, type=Path)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--sensitivity", type=Path)
    args = cli.parse_args()
    if not all(path.resolve().is_relative_to(ROOT / "outputs") for path in args.packets):
        cli.error("Private excerpts stay in outputs")
    if args.mode == "prepare":
        prepare(args)
    else:
        if args.reviews is None or args.output is None or args.sensitivity is None:
            cli.error("Finalize needs review and output files")
        finalize(args)


if __name__ == "__main__":
    main()
