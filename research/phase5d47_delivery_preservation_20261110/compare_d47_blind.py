"""Replay paid archive observations and freeze delivery decisions without labels."""
from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d47_contracts import canonical, reconstruct
from d47_ordinary_controls import ordinary_point
from d47_point_domains import check
from delivery_preservation import (
    CONTEXT_CAP, ELIGIBLE_NATIVE_EOS, FINAL, FORMAT_FAILURE, SCOPE_UNKNOWN, THINKING,
    UNCERTAIN_TERMINATION, DeliveryPreserver, DeliveryScope, Observation, PointCustody, naive_best_verified, point,
)
from freeze_d47_intake import HERE, digest, load, sha, write_exclusive

SLOTS = (("early", THINKING, 1), ("late", THINKING, 2), ("final_point", FINAL, 3))


def issue(row, key, stage, ordinal, reading, sample, scope, readout_sha):
    begin, end = reading["observation_char_span_in_response"]
    source = sample["response"]
    prefix = source[begin:end]
    a, b = reading["assertion_span"]
    lo, hi = reading["numeric_span"]
    literal = reading["numeric_text"]
    actual_close = source.find("</think>")
    if stage == FINAL:
        if row["termination"] != "NATIVE_STOP" or actual_close < 0 or begin != actual_close+len("</think>"):
            raise ValueError("Final candidate is not a native post-thinking observation")
    elif actual_close >= 0 and end > actual_close:
        raise ValueError("Thinking certificate used later bytes")
    if not (
        digest(prefix.encode()) == reading["observation_prefix_sha256"]
        and 0 <= a <= lo < hi <= b <= len(prefix)
        and prefix[lo:hi] == literal
        and digest(prefix[a:b].encode()) == reading["assertion_sha256"]
        and point.exact_literal(literal) == Fraction(reading["value"])
        and reading["assertion_role"] == point.ASSERTED_ORIGINAL_CANDIDATE
        and reading["direction"] == scope.binding.direction
    ):
        raise ValueError(f"Different source binding for {row['sample_id']} {key}")
    review_sha = canonical({
        "issuer": readout_sha, "stage": key, "sample": row["sample_id"], "scope": scope.sha256,
        "assertion": reading["assertion_sha256"], "blind_review": reading.get("scope_review_sha256"),
    })
    candidate = point.CandidateReceipt(
        scope.binding, row["sample_id"], row["response_sha256"], reading["observation_prefix_sha256"],
        (lo, hi), literal, (a, b), reading["assertion_sha256"], point.ASSERTED_ORIGINAL_CANDIDATE, review_sha,
    )
    return Observation(candidate, scope.unit_id, stage, ordinal), prefix


def endpoint(row):
    if row["termination"] == "LENGTH_CAP":
        return CONTEXT_CAP
    if row["termination"] != "NATIVE_STOP":
        return UNCERTAIN_TERMINATION
    if not row["native_final_eligible"]:
        return FORMAT_FAILURE if row["boundary"] == "CLOSED_THINKING" else SCOPE_UNKNOWN
    if row["final_point"]["status"] != "EXPLICIT_SCOPED_POINT":
        return SCOPE_UNKNOWN
    return ELIGIBLE_NATIVE_EOS


def independent_point(cid, value, meter):
    start, cpu, before = perf_counter_ns(), thread_time_ns(), meter._spent
    try:
        legal = ordinary_point(cid, Fraction(value), meter)
    except point._BudgetExhausted:
        legal = None
    return {
        "status": point.UNKNOWN if legal is None else point.PROVEN_FEASIBLE if legal else point.PROVEN_INFEASIBLE,
        "work": meter._spent-before, "wall_ns": perf_counter_ns()-start, "cpu_ns": thread_time_ns()-cpu,
    }


def compare(args):
    started, cpu = perf_counter_ns(), thread_time_ns()
    paths = {k: getattr(args, k) for k in ("cohort", "readout", "blind", "contracts", "controls", "rules")}
    data, shas = {k: load(v) for k, v in paths.items()}, {k: sha(v) for k, v in paths.items()}
    cohort, readout, blind, contracts, controls, rules = (
        data[k] for k in ("cohort", "readout", "blind", "contracts", "controls", "rules")
    )
    if not (
        readout["status"] == "FROZEN_D47_DELIVERY_READOUT_WITHOUT_GOLD"
        and readout["cohort_freeze_sha256"] == blind["cohort_freeze_sha256"] == contracts["cohort_sha256"] == shas["cohort"]
        and controls["cohort_freeze_sha256"] == shas["cohort"]
        and readout["observation_rules_sha256"] == cohort["observation_rules_sha256"]
        and readout["blind_input_sha256"] == shas["blind"]
        and contracts["gate_rules_sha256"] == shas["rules"]
        and contracts["contract_source_sha256"] == sha(HERE / "d47_contracts.py")
        and contracts["preservation_source_sha256"] == sha(HERE / "delivery_preservation.py")
        and controls["ordinary_code_sha256"] == sha(HERE / "d47_ordinary_controls.py")
        and cohort["point_domain_sha256"] == sha(HERE / "d47_point_domains.py")
        and readout["extractor_sha256"] == sha(HERE / "extract_d47_delivery.py")
    ):
        raise ValueError("Exact D4.7 scope and controls do not match the freeze")
    original = {r["case_id"]: r for r in contracts["rows"]}
    samples = {r["sample_id"]: r for r in blind["rows"]}
    if len(original) != rules["independent_questions"] or len(samples) != cohort["planned_trace_count"]:
        raise ValueError("Independent denominator changed")
    if len(readout["rows"]) != len(samples) or {r["sample_id"] for r in readout["rows"]} != set(samples):
        raise ValueError("Readout cohort changed")

    rows = []
    for row in readout["rows"]:
        cid, sid = row["case_id"], row["sample_id"]
        sample, binding_record = samples[sid], original[cid]
        contract = reconstruct(binding_record)
        scope = DeliveryScope(contract.binding, binding_record["unit"], contract.sha256, contract.checker_source_sha256,
                              sid, sample["response_sha256"])
        if row["unit"] != scope.unit_id or row["question_sha256"] != scope.binding.question_sha256 or row["response_sha256"] != sample["response_sha256"]:
            raise ValueError("Original objective unit or trace identity changed")
        observations = {}
        for key, stage, ordinal in SLOTS:
            reading = row[key]
            if reading["status"] == "EXPLICIT_SCOPED_POINT" and reading["scope_status"] == "ORIGINAL_REQUESTED_SCALAR":
                observations[key] = issue(row, key, stage, ordinal, reading, sample, scope, shas["readout"])
        engine = point.PointVerifier(
            contract, contract.sha256, check,
            approved_candidate_sha256=[r[0].candidate.sha256 for r in observations.values()],
            call_budget=rules["max_point_calls_per_rollout"], work_budget=rules["max_named_point_work_per_rollout"],
        )
        custody = PointCustody(scope, scope.sha256, engine,
                               approved_observation_sha256=[r[0].sha256 for r in observations.values()])
        state = DeliveryPreserver(custody)
        ordinary_meter = point.WorkMeter(rules["max_named_point_work_per_rollout"])
        thought_tickets, slots = [], {}
        final_ticket = None
        for key, stage, _ in SLOTS:
            if key not in observations:
                slots[key] = {"status": "NO_SCOPE_AUTHORITY", "observation_status": row[key]["status"]}
                continue
            ticket = custody.check(*observations[key])
            value = row[key]["value"]
            ordinary = independent_point(cid, value, ordinary_meter)
            status = None if ticket.point_receipt is None else ticket.point_receipt.status
            slots[key] = {"status": ticket.status, "proof_status": status, "value": str(Fraction(value)),
                          "ordinary": ordinary, "ticket": ticket.as_dict(),
                          "scope_review_sha256": row[key].get("scope_review_sha256")}
            if stage == THINKING:
                thought_tickets.append(ticket)
                state.observe(ticket)
            else:
                final_ticket = ticket
        # Native endpoint is used only after the earlier certificates have already been issued.
        termination = endpoint(row)
        native = row["final"]["value"] if row["native_final_eligible"] else None
        chosen = state.finish(termination, final_ticket, native_value=native)
        simple = naive_best_verified(custody, thought_tickets, termination, final_ticket, native_value=native)
        scalar = native
        if termination == ELIGIBLE_NATIVE_EOS:
            options = [Fraction(row[k]["value"]) for k in ("early", "late") if k in observations] + [Fraction(native)]
            fn = max if scope.binding.direction == "MAX" else min
            scalar = str(fn(options))
        rows.append({
            "case_id": cid, "sample_id": sid, "draw_index": row["draw_index"],
            "termination": row["termination"], "boundary": row["boundary"], "native_final_eligible": row["native_final_eligible"],
            "native_final_value": native, "original_unit": scope.unit_id, "slot_checks": slots,
            "numeric_only_value": None if scalar is None else str(scalar),
            "naive_best_verified": simple.as_dict(), "preservation": state.report(),
            "same_scalar_as_naive": chosen.proposed_value == simple.proposed_value and chosen.action == simple.action,
            "custody_work": custody.report(), "ordinary_work": dict(ordinary_meter._charges),
        })
    return {"status": "D47_BLIND_DELIVERY_COMPARISONS_FROZEN_WITHOUT_GOLD", "input_sha256": shas,
            "comparison_code_sha256": sha(Path(__file__)), "rows": rows,
            "wall_ns": perf_counter_ns()-started, "cpu_ns": thread_time_ns()-cpu}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("cohort", "readout", "blind", "contracts", "controls", "rules", "output"):
        cli.add_argument("--" + arg, required=True, type=Path)
    args = cli.parse_args()
    result = compare(args)
    write_exclusive(args.output, result)
    print(result["status"], len(result["rows"]), sha(args.output))


if __name__ == "__main__":
    main()
