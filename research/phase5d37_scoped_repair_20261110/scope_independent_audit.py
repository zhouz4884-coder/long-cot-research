"""Adversarially evaluate the frozen scope policy and actual point-gate authority."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from freeze_scope_regressions import D36, ROOT, from_baseline
from rebuild_scope_inventory import clause_offsets
from scope_adapter import bind_event_scope, classify_scope
from scoped_obligation import ScopedPointGate
from witness_contract import compile_contract


D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
sys.path.extend((str(D3), str(D36)))
from complete_answer import _rational
from complete_answer_v2 import extract_final_answer
from wcpr_worker import paragraph_matches


CHALLENGE = ROOT / "scope_independent_challenge.json"
DESTINATION = ROOT / "scope_independent_results.json"
AUTHORITY = frozenset({"NONE", "REFUTE_GLOBAL_MAXIMUM", "REFUTE_FEASIBILITY_ONLY", "RAISE_FEASIBLE_BOUND_ONLY"})


def sha(raw):
    return sha256(raw).hexdigest()


def make_event(case, gate, *, full=False):
    text = case["full_text"]
    surface = case["source_surface"]
    left = text.index(surface)
    right = left + len(surface)
    start, end = (0, len(text)) if full else clause_offsets(text, (left, right))
    mismatch = case["synthetic_binding_mismatch"]
    kind = ("FEASIBLE_CANDIDATE" if case["id"] in {"P03", "P04", "P05", "H03", "A01"}
            else "MAXIMALITY_CLAIM")
    trajectory = "synthetic/" + case["id"]
    return {"id": f"{trajectory}:{case.get('sequence', 1)}", "trajectory": trajectory, "phase": case["phase"],
            "kind": kind, "value": case["value"], "terminal_committed": case["terminal_committed"],
            "target_id": "untrusted-test-target" if mismatch == "target" else gate.target,
            "source_span": {"char_span": [left, right], "text": "synthetically forged" if mismatch == "source_text" else surface},
            "clause_char_span": [start, end], "clause": text[start:end],
            "observed_prefix_sha256": sha(text.encode())}


def initial_gate(contract, case):
    gate = ScopedPointGate(contract)
    seed = case["seed_feasible_bound"]
    text = f"Observed comparison operand {seed}."
    seed_event = {"id": case["id"], "sequence": 0,
                  "phase": "checkpoint_operand", "kind": "FEASIBLE_CANDIDATE", "value": seed,
                  "terminal_committed": True, "synthetic_binding_mismatch": None,
                  "source_surface": str(seed), "full_text": text}
    seeded = gate.step(make_event(seed_event, gate))
    if seeded["authority"] != "RAISE_FEASIBLE_BOUND_ONLY" or gate.bound.value != seed:
        raise ValueError("The seeded candidate did not pass the same trusted point predicate")
    return gate


def legacy_emission_probe(case):
    text, value = case["full_text"], case["value"]
    if case["phase"] == "thinking":
        candidates = []
        for source, field, maximum, _ in paragraph_matches(text):
            if int(text[slice(*field)]) == value:
                candidates.append({"source_span": source, "source": text[slice(*source)],
                                   "role": "MAXIMALITY_CLAIM" if maximum else "FEASIBLE_CANDIDATE"})
        return {"mode": "published_d36_thinking_lexical_adapter", "same_value_candidates": candidates}
    if case["phase"] == "final":
        selected = extract_final_answer(text, "scalar")
        literal = _rational(selected["components"][0]) if selected.get("status") == "ok" else None
        return {"mode": "published_d36_f2_final_readout", "selection_status": selected["status"],
                "same_value_selected": literal == value}
    return {"mode": "trusted_checkpoint_operand_fixture"}


def evaluate(case, contract):
    gate = initial_gate(contract, case)
    event = make_event(case, gate)
    outcome = gate.step(event)
    full_gate = initial_gate(contract, case)
    full_outcome = full_gate.step(make_event(case, full_gate, full=True))
    full_role = classify_scope(case["full_text"], case["phase"], case["value"],
                               terminal_committed=case["terminal_committed"])
    local_direct_role = classify_scope(event["clause"], case["phase"], case["value"],
                                       terminal_committed=case["terminal_committed"])
    if outcome["role"] != bind_event_scope(event, trusted_target_id=gate.target).role:
        raise ValueError("Action and adapter role disagree")
    expected, actual = case["expected_authority"], outcome["authority"]
    label = ("AGREEMENT" if expected == actual else "FALSE_AUTHORITY" if expected == "NONE"
             else "MISSED_AUTHORITY" if actual == "NONE" else "WRONG_AUTHORITY")
    if actual not in AUTHORITY or expected not in AUTHORITY:
        raise ValueError("Unexpected semantic action")
    return {"id": case["id"], "category": case["category"], "value": case["value"], "expected": expected,
            "actual": actual, "result": label, "actual_role": outcome["role"],
            "same_gate_full_text_authority": full_outcome["authority"],
            "direct_full_text_role_with_commitment": full_role.role,
            "direct_clause_role_with_commitment": local_direct_role.role,
            "clause": event["clause"], "source_span": event["source_span"],
            "point_status": None if outcome["point"] is None else outcome["point"]["status"],
            "bound_witness_value": None if outcome["witness"] is None else outcome["witness"]["value"],
            "legacy_emission_probe": legacy_emission_probe(case)}


def independent_arithmetic():
    def feasible(value):
        digits = list(map(int, str(value)))
        return all(c >= a + b for a, b, c in zip(digits, digits[1:], digits[2:]))
    largest_three = max(n for n in range(100, 1000) if feasible(n))
    if (largest_three != 909 or feasible(998) or feasible(172) or not feasible(20246)
            or not feasible(1011235) or not feasible(123)):
        raise ValueError("Fresh fixtures have inconsistent arithmetic assumptions")
    return {"largest_feasible_three_digit": largest_three, "998_fits_modulo_ten_third_digit": 8 >= (9 + 9) % 10,
            "998_feasible_under_original": feasible(998), "172_feasible_under_original": feasible(172),
            "20246_feasible_under_original": feasible(20246)}


def run(output):
    raw = CHALLENGE.read_bytes()
    frozen = json.loads(raw)
    if (frozen["status"] != "FROZEN_BEFORE_FIRST_EVALUATION"
            or frozen["scope_adapter_sha256_at_freeze"] != sha((ROOT / "scope_adapter.py").read_bytes())
            or frozen["case_count"] != len(frozen["cases"])
            or not 15 <= len(frozen["cases"]) <= 25):
        raise ValueError("Frozen scope challenge or adapter changed")
    visible = from_baseline(D3 / "prepared_data/bank/visible.jsonl")
    row, = (x for x in map(json.loads, visible.splitlines()) if x["case_id"] == "D3_E15")
    contract = compile_contract(row["question"])
    math_controls = independent_arithmetic()
    cases = [evaluate(case, contract) for case in frozen["cases"]]
    counts = Counter(case["result"] for case in cases)
    extras = Counter(case["actual"] for case in cases if case["result"] == "FALSE_AUTHORITY")
    report = {"status": "COMPLETE_SCOPE_ADVERSARIAL_DEVELOPMENT_AUDIT",
              "first_evaluated_utc": datetime.now(timezone.utc).isoformat(),
              "challenge_sha256": sha(raw), "scope_adapter_sha256": frozen["scope_adapter_sha256_at_freeze"],
              "scoped_obligation_sha256": sha((ROOT / "scoped_obligation.py").read_bytes()),
              "point_verifier_sha256": sha((D36 / "point_verifier.py").read_bytes()),
              "scope": "Independent synthetic authority and boundary challenge. Old parser probes are eligibility diagnostics, not live generation.",
              "expected_none": sum(x["expected"] == "NONE" for x in cases),
              "expected_nonempty": sum(x["expected"] != "NONE" for x in cases),
              "counts": dict(counts), "false_authority_types": dict(extras),
              "math_controls": math_controls, "cases": cases}
    raw_report = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(raw_report)
    print(json.dumps({"counts": report["counts"], "false_authority_types": report["false_authority_types"],
                      "result_sha256": sha(raw_report)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    run(parser.parse_args().output)
