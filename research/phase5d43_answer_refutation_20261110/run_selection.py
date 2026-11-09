"""Execute the preregistered D4.3 selectors. This module has no gold-data reader."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from freeze_cohort import digest, write_exclusive
from scoped_refutation import (
    CLOSED_INTERVAL,
    CONGRUENCE,
    FINITE_EXCLUSIONS,
    NecessaryPredicate,
    ObjectiveBinding,
    ReviewedPrerequisite,
    ScopedRefutationState,
    application_signature,
)


def rank(pool: dict[int, int], appearances: list[tuple[int, int]]) -> tuple[int, ...]:
    # Appearances lists all finals by draw, then eligible thinking occurrences.
    positions = {}
    for position, (_, value) in enumerate(appearances):
        positions.setdefault(value, position)
    return tuple(sorted(pool, key=lambda value: (-pool[value], positions[value])))


def eligible(row: dict, approved_bare: set[str], denied_thinking: set[str],
             *, all_bare: bool = False) -> tuple[int | None, int | None]:
    if row["termination"] != "NATIVE_STOP":
        return None, None
    final = row["final"]["value"]
    thought = row["thinking"]
    scope = thought["scope_status"]
    allowed = row["sample_id"] not in denied_thinking and row["boundary"] == "CLOSED_THINKING" and (
        scope == "GENERIC_TARGET_CLAIM"
        or (scope == "TERMINAL_BOX_UNANCHORED" and (all_bare or row["sample_id"] in approved_bare))
    )
    return final, (thought["value"] if allowed else None)


def pool_from_rows(rows: list[dict], approved_bare: set[str], denied_thinking: set[str],
                   *, all_bare: bool = False) -> dict:
    finals, thoughts, inclusive_votes = [], [], Counter()
    values_by_draw = {}
    for row in rows:
        draw = row["draw_index"]
        final, thought = eligible(row, approved_bare, denied_thinking, all_bare=all_bare)
        values_by_draw[draw] = (final, thought)
        if final is not None:
            finals.append((draw, final))
        if thought is not None:
            thoughts.append((draw, thought))
        distinct = {value for value in (final, thought) if value is not None}
        for value in distinct:
            inclusive_votes[value] += 2 // len(distinct)
    final_votes = Counter(value for _, value in finals)
    return {
        "values_by_draw": values_by_draw,
        "final_occurrences": finals,
        "thinking_occurrences": thoughts,
        "final_votes": final_votes,
        "inclusive_votes": inclusive_votes,
        "final_ranked": rank(final_votes, finals),
        "inclusive_ranked": rank(inclusive_votes, finals + thoughts),
    }


def ordinary_filter(candidates: tuple[int, ...], prerequisites: tuple[ReviewedPrerequisite, ...]) -> dict:
    """Direct, independent arithmetic using the same reviewed inputs and budget."""
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    calls, eliminated = [], set()
    for item in prerequisites if candidates else ():
        kind, args = item.predicate.kind, item.predicate.args
        if kind == CONGRUENCE:
            modulus, residue = args
            violations = {value for value in candidates if (value - residue) % modulus != 0}
            operations = 3 * len(candidates)
        elif kind == CLOSED_INTERVAL:
            low, high = args
            violations = {value for value in candidates if not (low <= value <= high)}
            # Short-circuit skips the upper comparison if the lower test fails.
            operations = sum(1 + int(value >= low) for value in candidates)
        elif kind == FINITE_EXCLUSIONS:
            violations = {value for value in candidates if value in args}
            operations = sum(args.index(value) + 1 if value in violations else len(args) for value in candidates)
        else:
            raise ValueError(f"Unexpected approved predicate kind {kind}")
        eliminated.update(violations)
        calls.append({
            "prerequisite_sha256": item.sha256, "candidates": candidates, "refuted": sorted(violations),
            "paid_candidate_evaluations": len(candidates), "decision_primitive_numeric_operations": operations,
        })
    return {
        "eliminated": sorted(eliminated), "calls": calls,
        "paid_predicate_calls": len(calls),
        "paid_candidate_evaluations": sum(row["paid_candidate_evaluations"] for row in calls),
        "decision_primitive_numeric_operations": sum(row["decision_primitive_numeric_operations"] for row in calls),
        "wall_ns": perf_counter_ns() - started_wall, "cpu_ns": thread_time_ns() - started_cpu,
    }


def scoped_filter(candidates: tuple[int, ...], binding: ObjectiveBinding,
                  prerequisites: tuple[ReviewedPrerequisite, ...]) -> dict:
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    state = ScopedRefutationState(binding.question_sha256, [p.sha256 for p in prerequisites])
    calls, eliminated = [], set()
    for item in prerequisites if candidates else ():
        batch = state.check_candidates(binding, candidates, item)
        for receipt in batch.receipts:
            if state.authorizes_refutation(binding, receipt.candidate, receipt):
                eliminated.add(receipt.candidate)
        calls.append(batch.as_dict())
    return {
        **state.report(), "eliminated": sorted(eliminated), "calls": calls,
        "wall_ns": perf_counter_ns() - started_wall, "cpu_ns": thread_time_ns() - started_cpu,
    }


def bind_reviewed(row: dict) -> tuple[ObjectiveBinding, tuple[ReviewedPrerequisite, ...]]:
    binding = ObjectiveBinding(row["exact_question_sha256"], row["objective_id"], row["scope"])
    approved = []
    for record in row["approved_predicates"]:
        predicate = NecessaryPredicate(record["kind"], tuple(record["args"]))
        item = ReviewedPrerequisite(
            binding, predicate, record["source_kind"], record["source_sha256"],
            record["review_sha256"], record["application_sha256"],
        )
        if item.application_sha256 != application_signature(binding, predicate) or item.sha256 != record["prerequisite_sha256"]:
            raise ValueError(f"Approved prerequisite identity differs for {row['problem_id']}")
        approved.append(item)
    if len(approved) > 2 or len({p.application_sha256 for p in approved}) != len(approved):
        raise ValueError("More than two distinct reviewed necessary predicates")
    return binding, tuple(approved)


def choose(ranked: tuple[int, ...], eliminated: list[int] = ()) -> tuple[int | None, bool]:
    rejected = set(eliminated)
    for value in ranked:
        if value not in rejected:
            return value, False
    return (ranked[0], True) if ranked else (None, False)


def run(machine: dict, review: dict, proofs: dict, cohort: dict) -> dict:
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    allowed_bare = {row["sample_id"] for row in review["rows"] if row["approve_unanchored_thinking_box"]}
    denied_thinking = {row["sample_id"] for row in review["rows"]
                       if row["explicit_object_or_qualifier_mismatch_observed"]}
    by_problem = defaultdict(list)
    for row in machine["rows"]:
        by_problem[row["problem_id"]].append(row)
    proof_rows = {row["problem_id"]: row for row in proofs["rows"]}
    if set(by_problem) != set(proof_rows) or len(by_problem) != 32:
        raise ValueError("Candidate and proof cohorts differ")
    results = []
    for question in cohort["selected"]:
        pid = question["problem_id"]
        rows = sorted(by_problem[pid], key=lambda row: row["draw_index"])
        if [(r["draw_index"], r["sample_id"], r["response_sha256"]) for r in rows] != [
            (r["draw_index"], r["sample_id"], r["response_sha256"]) for r in question["samples"]
        ]:
            raise ValueError(f"Unexpected frozen samples for {pid}")
        if proof_rows[pid]["normalized_question_sha256"] != question["normalized_question_sha256"]:
            raise ValueError(f"Proof question digest differs for {pid}")
        binding, prerequisites = bind_reviewed(proof_rows[pid])
        started = thread_time_ns()
        pool = pool_from_rows(rows, allowed_bare, denied_thinking)
        broad = pool_from_rows(rows, allowed_bare, denied_thinking, all_bare=True)
        pool_cpu_ns = thread_time_ns() - started
        candidates = pool["inclusive_ranked"]
        direct = ordinary_filter(candidates, prerequisites)
        scoped = scoped_filter(candidates, binding, prerequisites)
        direct_choice, direct_empty = choose(candidates, direct["eliminated"])
        scoped_choice, scoped_empty = choose(candidates, scoped["eliminated"])
        final, thought = pool["values_by_draw"][0]
        survivors = [value for value in candidates if value not in scoped["eliminated"]]
        distinguishing = [
            call["prerequisite_sha256"] for call in scoped["calls"]
            if {r["status"] for r in call["receipts"]} == {"NOT_REFUTED", "REFUTED"}
        ]
        results.append({
            "problem_id": pid, "objective_id": binding.objective_id, "scope": binding.scope,
            "pool": pool, "broad_inclusive_ranked": broad["inclusive_ranked"],
            "pool_cpu_ns": pool_cpu_ns,
            "scope_review_count": len(prerequisites),
            "ordinary": direct, "scoped": scoped, "scoped_survivors": survivors,
            "discriminating_prerequisites": distinguishing,
            "disagreement_subset_member": len(candidates) > 1,
            "selection": {
                "native_draw0": final,
                "thinking_preferred_draw0": thought if thought is not None else final,
                "final_majority": choose(pool["final_ranked"])[0],
                "inclusive_majority": choose(candidates)[0],
                "ordinary_same_access": direct_choice,
                "scoped_refutation": scoped_choice,
                "author_whole_draw0_diagnostic": rows[0]["author_whole_response_candidate"],
            },
            "empty_survivor_fallback": {"ordinary": direct_empty, "scoped": scoped_empty},
            "observed_input_tokens_all_draws": sum(row["input_tokens"] for row in rows),
            "observed_output_tokens_all_draws": sum(row["output_tokens"] for row in rows),
            "observed_input_tokens_draw0": rows[0]["input_tokens"],
            "observed_output_tokens_draw0": rows[0]["output_tokens"],
        })
    return {
        "status": "ALL_32_SELECTIONS_FROZEN_WITHOUT_GOLD",
        "cost": {"wall_ns": perf_counter_ns() - started_wall, "cpu_ns": thread_time_ns() - started_cpu},
        "rows": results,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("machine", "review", "proofs", "cohort", "eval-freeze", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    inputs = {name: getattr(args, name).read_bytes()
              for name in ("machine", "review", "proofs", "cohort", "eval_freeze")}
    data = {name: json.loads(raw) for name, raw in inputs.items()}
    hashes = {name: digest(raw) for name, raw in inputs.items()}
    if (data["machine"]["cohort_freeze_sha256"] != hashes["cohort"]
            or data["proofs"]["cohort_freeze_sha256"] != hashes["cohort"]
            or data["review"]["machine_readout_sha256"] != hashes["machine"]
            or data["eval_freeze"]["cohort_freeze_sha256"] != hashes["cohort"]
            or data["proofs"]["status"] != "REVIEWED_QUESTION_ONLY_PREREQUISITES_FROZEN"):
        raise ValueError("Selection inputs have different freeze identities")
    report = run(*(data[k] for k in ("machine", "review", "proofs", "cohort")))
    report["input_sha256"] = hashes
    report["selector_sha256"] = digest(Path(__file__).read_bytes())
    write_exclusive(args.output, report)
    print(f"{report['status']}: {len(report['rows'])} questions")


if __name__ == "__main__":
    main()
