"""Bind independent gold-blind scope judgments to exact archived prefixes."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns

from freeze_d45_intake import digest, load, sha, write_exclusive
from extract_candidates import load_author_scorer


def review(
    strict_path: Path, blind_path: Path, packet_freeze_path: Path, rules_path: Path,
    packets: list[Path], decisions: list[Path], scorer_path: Path,
) -> tuple[dict, dict]:
    began = perf_counter_ns()
    strict, blind, frozen = map(load, (strict_path, blind_path, packet_freeze_path))
    if (
        frozen["strict_readout_sha256"] != sha(strict_path)
        or frozen["rules_sha256"] != sha(rules_path)
        or strict["blind_input_sha256"] != sha(blind_path)
    ):
        raise ValueError("Scope review did not use the frozen strict observations")
    updated = deepcopy(strict)
    raw = {row["sample_id"]: row for row in blind["rows"]}
    rows = {row["sample_id"]: row for row in updated["rows"]}
    expected_jobs = {f'{row["sample_id"]}@{point}' for row in strict["rows"] for point in ("early", "late")
                     if row[point]["status"] == "LATER_UNSCOPED_BOX"}
    seen = set()
    audited = []
    parser = load_author_scorer(scorer_path)
    for packet, decision_file, manifest in zip(packets, decisions, frozen["packets"], strict=True):
        p, d = load(packet), load(decision_file)
        if sha(packet) != d["packet_sha256"] or sha(packet) != manifest["packet_sha256"]:
            raise ValueError("Scope reviewer worked from different observation bytes")
        items = {r["job_id"]: r for r in p["rows"]}
        judgments = {r["job_id"]: r for r in d["rows"]}
        if list(items) != manifest["job_ids"] or set(items) != set(judgments) or len(items) != len(d["rows"]):
            raise ValueError("Scope review denominator changed")
        for jid, item in items.items():
            if jid in seen:
                raise ValueError("Duplicate scope judgment")
            seen.add(jid)
            sid, point = jid.rsplit("@", 1)
            row, judgment = rows[sid], judgments[jid]
            ev = row[point]
            text = raw[sid]["response"]
            left, right = ev["observation_char_span_in_response"]
            start, end = ev["char_span_in_response"]
            if not (
                ev["status"] == "LATER_UNSCOPED_BOX" and row["case_id"] == item["case_id"]
                and ev["source_excerpt_sha256"] == item["source_box_sha256"] == judgment["source_box_sha256"]
                and item["visible_excerpt"] == text[max(left, right - 3000):right]
                and item["source_box"] == text[start:end]
                and digest(item["source_box"].encode()) == ev["source_excerpt_sha256"]
            ):
                raise ValueError("Scope judgment does not match the observed box")
            events, malformed = parser.scan_box_events(item["source_box"])
            boxes = [x for x in events if x.valid]
            official = parser.parse_aime_integer(boxes[0].interior_raw) if len(boxes) == 1 and not malformed else None
            bound = judgment["decision"] == "BOUND"
            value = judgment["value"]
            if (
                judgment["decision"] not in {"BOUND", "UNKNOWN"}
                or (bound and (type(value) is not int or value != official))
                or (not bound and value is not None)
            ):
                raise ValueError(f"Scope reviewer changed the exact boxed value: {jid}")
            if bound:
                ev.update(status="EXPLICIT_SCOPED_OPTIMUM", value=value,
                          rational={"numerator": value, "denominator": 1},
                          scope_status="ORIGINAL_REQUESTED_OPTIMUM", complete_explicit_candidate=True,
                          evidence_source="GOLD_BLIND_SCOPE_SENSITIVITY_ONLY")
            audited.append({
                **judgment, "observation_prefix_sha256": ev["observation_prefix_sha256"],
                "review_output_sha256": sha(decision_file),
            })
    if seen != expected_jobs or len(seen) != 58:
        raise ValueError("Gold-blind scope adjudication missed frozen cases")
    audit = {
        "status": "D45_SCOPE_SENSITIVITY_FROZEN_BEFORE_GOLD", "strict_readout_sha256": sha(strict_path),
        "packet_freeze_sha256": sha(packet_freeze_path), "rules_sha256": sha(rules_path),
        "review_decisions": dict(Counter(row["decision"] for row in audited)),
        "cost_scope": "Manual role judgments not timed per case. Local receipt reconciliation wall recorded separately.",
        "reconciliation_wall_ns": perf_counter_ns() - began, "rows": audited,
    }
    updated["scope"] = "Gold-blind role adjudication sensitivity. Preregistered strict scope results remain separate."
    updated["early_counts"] = dict(Counter(row["early"]["status"] for row in updated["rows"]))
    updated["late_counts"] = dict(Counter(row["late"]["status"] for row in updated["rows"]))
    return audit, updated


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("strict", "blind", "packet-freeze", "rules", "author-scorer", "audit-output", "claim-output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--packets", nargs=2, type=Path, required=True)
    cli.add_argument("--decisions", nargs=2, type=Path, required=True)
    args = cli.parse_args()
    audit, claims = review(args.strict, args.blind, args.packet_freeze, args.rules,
                           args.packets, args.decisions, args.author_scorer)
    write_exclusive(args.audit_output, audit)
    claims["scope_sensitivity_review_sha256"] = sha(args.audit_output)
    write_exclusive(args.claim_output, claims)
    print(audit["status"], audit["review_decisions"], sha(args.claim_output))


if __name__ == "__main__":
    main()
