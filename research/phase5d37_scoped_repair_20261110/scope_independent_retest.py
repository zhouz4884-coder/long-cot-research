"""Re-evaluate the disclosed challenge after scope changes using a synthetic fixture policy."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from scope_independent_audit import (
    CHALLENGE, D3, ROOT, DESTINATION as FIRST, compile_contract, from_baseline, make_event, sha,
)
from goal_claim_detector import target_id_for
from point_verifier import PointVerifier
from scope_adapter import bind_event_scope


DESTINATION = ROOT / "scope_independent_retest_results.json"


def observed_event(case, target):
    event = make_event(case, SimpleNamespace(target=target))
    left, right = event["clause_char_span"]
    text = case["full_text"]
    start, end = max(0, left - 160), min(len(text), right + 100)
    event["context_char_span"] = [start, end]
    event["context"] = text[start:end]
    if event["context"][left - start:right - start] != event["clause"]:
        raise ValueError("Fixture clause does not match its enclosing context")
    return event


def authority(scope, case, contract):
    """Independently reconstruct the point-policy effects on a synthetic role."""
    checker = PointVerifier(contract, point_budget=16, work_budget=1024)
    bound, value = case["seed_feasible_bound"], case["value"]
    seeded = checker.check(bound)
    if seeded.status != "CERTIFIED_FEASIBLE":
        raise ValueError("Synthetic bound must pass the trusted point predicate")
    if not scope.admits_point_check:
        return "NONE", None
    if scope.may_refute_global_maximum and value < bound:
        return "REFUTE_GLOBAL_MAXIMUM", None
    receipt = checker.check(value)
    if scope.may_refute_feasibility_claim and receipt.status == "CERTIFIED_INFEASIBLE":
        return "REFUTE_FEASIBILITY_ONLY", receipt.status
    if receipt.status == "CERTIFIED_FEASIBLE" and value > bound:
        return "RAISE_FEASIBLE_BOUND_ONLY", receipt.status
    return "NONE", receipt.status


def legacy_eligible(row):
    probe = row["legacy_emission_probe"]
    return bool(probe.get("same_value_candidates") or probe.get("same_value_selected"))


def retest(adapter_sha, output):
    adapter = ROOT / "scope_adapter.py"
    if sha(adapter.read_bytes()) != adapter_sha:
        raise ValueError("Expected fixed retest adapter bytes")
    original_bytes, first_bytes = CHALLENGE.read_bytes(), FIRST.read_bytes()
    original, first = json.loads(original_bytes), json.loads(first_bytes)
    if first["challenge_sha256"] != sha(original_bytes):
        raise ValueError("Original result must bind the original disclosed challenge")
    earlier = {row["id"]: row for row in first["cases"]}
    visible = from_baseline(D3 / "prepared_data/bank/visible.jsonl")
    question, = (row["question"] for row in map(json.loads, visible.splitlines()) if row["case_id"] == "D3_E15")
    contract = compile_contract(question)
    target = target_id_for(contract)
    rows = []
    for case in original["cases"]:
        event = observed_event(case, target)
        role = bind_event_scope(event, trusted_target_id=target)
        actual, receipt = authority(role, case, contract)
        old = earlier[case["id"]]
        expected = case["expected_authority"]
        if old["expected"] != expected:
            raise ValueError("Authority labels must remain frozen")
        rows.append({"id": case["id"], "category": case["category"], "expected": expected,
                     "first_actual": old["actual"], "first_role": old["actual_role"],
                     "retest_actual": actual, "retest_role": role.role, "point_status": receipt,
                     "old_lexical_or_final_eligible": legacy_eligible(old),
                     "terminal_committed": event["terminal_committed"], "clause": event["clause"],
                     "enclosing_context": event["context"]})
    if set(earlier) != {r["id"] for r in rows} or sha(adapter.read_bytes()) != adapter_sha:
        raise ValueError("Challenge membership or runtime source changed")
    transitions = Counter(("correct" if row["first_actual"] == row["expected"] else "error")
                          + "_to_" + ("correct" if row["retest_actual"] == row["expected"] else "error") for row in rows)
    wrong_negatives = [row["id"] for row in rows if row["expected"] == "NONE" and row["retest_actual"] != "NONE"]
    wrong_positives = [row["id"] for row in rows if row["expected"] != "NONE" and row["retest_actual"] != row["expected"]]
    report = {"status": "COMPLETE_DISCLOSED_CHALLENGE_RETEST",
              "scope": "Same already disclosed synthetic controls after adapter revision. Role-to-point policy is independently applied. No frozen-inventory bypass, live behavior, held-out estimate, or new generation.",
              "utc": datetime.now(timezone.utc).isoformat(), "challenge_sha256": sha(original_bytes),
              "first_result_sha256": sha(first_bytes), "first_scope_adapter_sha256": first["scope_adapter_sha256"],
              "retest_scope_adapter_sha256": adapter_sha, "transitions": dict(transitions),
              "retest_false_authority_ids": wrong_negatives, "retest_positive_mismatch_ids": wrong_positives,
              "retest_false_authority_old_emitter_eligible": sum(
                  row["id"] in wrong_negatives and row["old_lexical_or_final_eligible"] for row in rows),
              "rows": rows}
    with output.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"transitions": dict(transitions), "false_authority_ids": wrong_negatives,
                      "positive_mismatch_ids": wrong_positives, "result_sha256": sha(output.read_bytes())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-sha", required=True)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    options = parser.parse_args()
    retest(options.adapter_sha, options.output)
