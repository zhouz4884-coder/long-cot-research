"""Score frozen D4.3 selections, using only the declared gold projection."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from freeze_cohort import DRAWS, MANIFEST_SHA256, SAMPLE_COUNT, digest, write_exclusive
from run_selection import bind_reviewed, pool_from_rows
from scoped_refutation import _digest as canonical_digest


ARMS = ("native_draw0", "thinking_preferred_draw0", "final_majority", "inclusive_majority",
        "ordinary_same_access", "scoped_refutation", "author_whole_draw0_diagnostic")
ORDINARY_ARMS = ("ordinary_same_access", "inclusive_majority", "final_majority")
GOLD_COLUMNS = ("problem_id", "sample_id", "draw_index", "response_sha256", "accepted_answer_integers")
AUTHOR_COLUMNS = ("extracted_answer_integer", "is_correct")
TERMINATIONS = ("NATIVE_STOP", "LENGTH_CAP", "TERMINATION_UNKNOWN")
TRANSITIONS = ("correct_to_correct", "correct_to_wrong", "wrong_to_correct", "wrong_to_wrong")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def index_rows(rows: list[dict], key: str) -> dict:
    result = {row[key]: row for row in rows}
    require(len(rows) == len(result), f"Duplicate {key}")
    return result


def sample_identity(row: dict) -> tuple:
    return tuple(row[key] for key in GOLD_COLUMNS[:4])


def verify_paid(row: dict, proof: dict) -> dict:
    """Check serialized applications and cost accounting without consulting gold."""
    pool = row["pool"]["inclusive_ranked"]
    direct, scoped = row["ordinary"], row["scoped"]
    objective, approved = bind_reviewed(proof)
    binding = asdict(objective)
    require((scoped["question_sha256"], row["objective_id"], row["scope"]) ==
            (objective.question_sha256, objective.objective_id, objective.scope), "Exact scoped objective binding differs")
    approved_by_hash = {item.sha256: item for item in approved}
    expected_calls = list(approved_by_hash) if pool else []
    by_arm = {}
    for arm, branch in (("ordinary", direct), ("scoped", scoped)):
        require([call["prerequisite_sha256"] for call in branch["calls"]] == expected_calls,
                "Paid calls differ from ordered approved prerequisites")
        checks, calls, evaluated = [], {}, 0
        ops = 0
        paid_calls = 0
        for position, call in enumerate(branch["calls"], 1):
            key = call["prerequisite_sha256"]
            require(key not in calls and list(call["candidates"]) == pool, "Changed paid candidate order or duplicate call")
            calls[key] = None
            if arm == "ordinary":
                refuted = call["refuted"]
                require(refuted == sorted(set(refuted)) and set(refuted) <= set(pool), "Invalid ordinary elimination")
                require(call["paid_candidate_evaluations"] == len(pool), "Ordinary call budget differs")
                for rank, value in enumerate(pool, 1):
                    checks.append((key, rank, value, value in refuted, None))
                calls[key] = set(refuted)
                paid_calls += 1
                evaluated += call["paid_candidate_evaluations"]
                ops += call["decision_primitive_numeric_operations"]
                continue
            require(call["batch_receipt_sha256"] == canonical_digest(
                {k: v for k, v in call.items() if k != "batch_receipt_sha256"}), "Scoped batch hash differs")
            require(call["requested_binding"] == binding and call["question_sha256"] == binding["question_sha256"]
                    and call["request_number"] == position
                    and call["application_sha256"] == approved_by_hash[key].application_sha256,
                    "Scoped batch binding differs")
            receipts = call["receipts"]
            active = call["status"] == "EVALUATED"
            require((active or call["status"] == "UNKNOWN") and (bool(receipts) == active)
                    and call["paid_predicate_calls"] == int(active)
                    and call["paid_candidate_evaluations"] == len(receipts), "Scoped batch accounting differs")
            if active:
                require([receipt["candidate"] for receipt in receipts] == pool, "Scoped receipt candidate order differs")
                calls[key] = set()
            for rank, receipt in enumerate(receipts, 1):
                payload = {k: v for k, v in receipt.items() if k not in ("receipt_sha256", "certificate_sha256")}
                refuted = receipt["status"] == "REFUTED"
                sha = receipt["receipt_sha256"]
                prereq = receipt["prerequisite"]
                require((refuted or receipt["status"] == "NOT_REFUTED") and sha == canonical_digest(payload)
                        and receipt["prerequisite_sha256"] == key == canonical_digest(prereq)
                        and receipt["candidate_index"] == rank and receipt["predicate_call"] == paid_calls + 1
                        and receipt["authority"] == ("REJECT_THIS_VALUE_ONLY" if refuted else "NONE")
                        and receipt["certificate_sha256"] == (sha if refuted else None)
                        and prereq["binding"] == binding and prereq["application_sha256"] == call["application_sha256"],
                        "Scoped candidate receipt differs")
                checks.append((key, rank, receipt["candidate"], refuted, sha))
                if refuted:
                    calls[key].add(receipt["candidate"])
            require(sum(receipt["primitive_numeric_operations"] for receipt in receipts)
                    == call["primitive_numeric_operations"], "Scoped per-call operations differ")
            paid_calls += call["paid_predicate_calls"]
            evaluated += call["paid_candidate_evaluations"]
            ops += call["primitive_numeric_operations"]
        eliminated = {value for _, _, value, refuted, _ in checks if refuted}
        survivors = [value for value in pool if value not in eliminated]
        fallback = bool(pool and not survivors)
        expected = survivors[0] if survivors else pool[0] if fallback else None
        chosen_arm = "ordinary_same_access" if arm == "ordinary" else "scoped_refutation"
        ops_key = "decision_primitive_numeric_operations" if arm == "ordinary" else "primitive_numeric_operations"
        require(paid_calls == branch["paid_predicate_calls"] and evaluated == branch["paid_candidate_evaluations"]
                and ops == branch[ops_key] and sorted(eliminated) == branch["eliminated"]
                and fallback == row["empty_survivor_fallback"][arm] and expected == row["selection"][chosen_arm],
                "Frozen selection or paid-work reconciliation differs")
        by_arm[arm] = {"checks": checks, "calls": calls, "survivors": survivors}
    require(scoped["requests"] == len(scoped["calls"])
            and by_arm["scoped"]["survivors"] == row["scoped_survivors"], "Scoped requests or survivors differ")
    require(row["scope_review_count"] == len(approved),
            "Frozen approved-predicate budget differs")
    mixed = [key for key, rejected in by_arm["scoped"]["calls"].items() if rejected and len(rejected) < len(pool)]
    require(mixed == row["discriminating_prerequisites"], "Frozen mixed-outcome certificate list differs")
    return by_arm


def prepare(selection: dict, machine: dict, cohort: dict, evaluation: dict, review: dict, proofs: dict) -> list[dict]:
    """Bind all denominators, identities and paid receipt evidence before opening labels."""
    require(selection["status"] == "ALL_32_SELECTIONS_FROZEN_WITHOUT_GOLD"
            and machine["status"] == "FROZEN_MACHINE_READOUT_WITHOUT_GOLD"
            and evaluation["status"] == "RULES_FROZEN_BEFORE_CANDIDATE_SCORE"
            and review["status"] == "ROLE_REVIEW_FROZEN_WITHOUT_GOLD"
            and proofs["status"] == "REVIEWED_QUESTION_ONLY_PREREQUISITES_FROZEN"
            and tuple(cohort["draws"]) == tuple(evaluation["draws"]) == DRAWS, "Unexpected input phase or draws")
    questions = index_rows(cohort["selected"], "problem_id")
    selected = index_rows(selection["rows"], "problem_id")
    native = index_rows(machine["rows"], "sample_id")
    reviewed = index_rows(review["rows"], "sample_id")
    approved = index_rows(proofs["rows"], "problem_id")
    require(list(questions) == list(selected) and len(questions) == SAMPLE_COUNT
            and set(approved) == set(questions) and set(reviewed) <= set(native)
            and len(native) == SAMPLE_COUNT * len(DRAWS), "Changed frozen denominator or order")
    allowed_bare = {key for key, value in reviewed.items() if value["approve_unanchored_thinking_box"]}
    denied_thinking = {key for key, value in reviewed.items() if value["explicit_object_or_qualifier_mismatch_observed"]}
    prepared = []
    for pid, question in questions.items():
        row = selected[pid]
        proof = approved[pid]
        require(proof["normalized_question_sha256"] == question["normalized_question_sha256"],
                "Normalized question identity differs")
        samples = [native[item["sample_id"]] for item in question["samples"]]
        require(tuple(item["draw_index"] for item in question["samples"]) == DRAWS, "Changed sample order")
        for source, frozen in zip(samples, question["samples"]):
            require(sample_identity(source) == sample_identity({**frozen, "problem_id": pid})
                    and source["seed"] == frozen["seed"] and source["termination"] in TERMINATIONS,
                    "Changed machine identity or termination")
        pool = row["pool"]
        by_draw = {int(key): pair for key, pair in pool["values_by_draw"].items()}
        require(tuple(sorted(by_draw)) == DRAWS and all(len(pair) == 2 for pair in by_draw.values()),
                "Incomplete values by draw")
        final = pool["final_ranked"]
        inclusive = pool["inclusive_ranked"]
        broad = row["broad_inclusive_ranked"]
        rebuilt = pool_from_rows(samples, allowed_bare, denied_thinking)
        rebuilt_broad = pool_from_rows(samples, allowed_bare, denied_thinking, all_bare=True)
        require(canonical_digest(pool) == canonical_digest(rebuilt)
                and broad == list(rebuilt_broad["inclusive_ranked"]), "Recomputed role-bound pool differs")
        for values in (final, inclusive, broad):
            require(all(type(x) is int for x in values) and len(values) == len(set(values)), "Invalid frozen pool")
        for sample in samples:
            final_value, thought = by_draw[sample["draw_index"]]
            require((sample["termination"] == "NATIVE_STOP" and final_value == sample["final"]["value"]
                     and (thought is None or (thought == sample["thinking"]["value"]
                                              and sample["boundary"] == "CLOSED_THINKING")))
                    or (sample["termination"] != "NATIVE_STOP" and final_value is None and thought is None),
                    "Frozen channel eligibility differs")
        require(set(final) == {pair[0] for pair in by_draw.values() if pair[0] is not None}
                and set(inclusive) == {value for pair in by_draw.values() for value in pair if value is not None}
                and set(inclusive) <= set(broad)
                and row["disagreement_subset_member"] == (len(inclusive) > 1)
                and set(row["selection"]) == set(ARMS), "Frozen pool membership, arms, or disagreement differs")
        chosen = row["selection"]
        final0, thought0 = by_draw[0]
        require(chosen["native_draw0"] == final0
                and chosen["thinking_preferred_draw0"] == (thought0 if thought0 is not None else final0)
                and chosen["final_majority"] == (final[0] if final else None)
                and chosen["inclusive_majority"] == (inclusive[0] if inclusive else None)
                and chosen["author_whole_draw0_diagnostic"] == samples[0]["author_whole_response_candidate"],
                "Draw0 or majority selection differs")
        for kind in ("input", "output"):
            key = f"{kind}_tokens"
            require(sum(sample[key] for sample in samples) == row[f"observed_{key}_all_draws"]
                    and samples[0][key] == row[f"observed_{key}_draw0"], "Frozen token accounting differs")
        prepared.append({"question": question, "row": row, "samples": samples, "by_draw": by_draw,
                         "paid": verify_paid(row, proof)})
    require(len({sample["sample_id"] for item in prepared for sample in item["samples"]}) == len(native),
            "Duplicate or omitted frozen sample")
    return prepared


def load_gold(source: Path, prepared: list[dict], cohort: dict, author_diagnostics: bool) -> tuple[dict, dict]:
    """Open labels only for pre-bound identities and use exact file bytes for projection."""
    import pyarrow.parquet as pq

    raw = (source / "PUBLICATION_MANIFEST.json").read_bytes()
    manifest_hash = digest(raw)
    require(manifest_hash == MANIFEST_SHA256 == cohort["publication_manifest_sha256"], "Changed publication manifest")
    manifest = json.loads(raw)
    require(manifest["contract_sha256"] == cohort["contract_sha256"], "Changed source contract")
    declared = index_rows(manifest["files"], "path")
    columns = GOLD_COLUMNS + (AUTHOR_COLUMNS if author_diagnostics else ())
    gold, identity_rows, verified = {}, {}, []
    for draw in DRAWS:
        expected = {sample["sample_id"]: sample_identity(sample) for item in prepared for sample in item["samples"]
                    if sample["draw_index"] == draw}
        path = f"data/draw-{draw:02}.parquet"
        shard = (source / path).read_bytes()
        info = declared[path]
        require(len(shard) == info["size"] and digest(shard) == info["sha256"], f"Changed gold source shard {draw}")
        verified.append({"path": path, "size": info["size"], "sha256": info["sha256"]})
        projected = pq.read_table(BytesIO(shard), columns=list(columns),
                                  filters=[("sample_id", "in", sorted(expected))]).to_pylist()
        rows = index_rows(projected, "sample_id")
        require(set(rows) == set(expected), "Gold projection omitted or added frozen samples")
        for sample_id, row in rows.items():
            require(sample_identity(row) == expected[sample_id], "Gold projection identity differs")
            accepted = row["accepted_answer_integers"]
            require(isinstance(accepted, list) and bool(accepted) and all(type(value) is int for value in accepted),
                    "Invalid accepted-answer set")
            accepted = frozenset(accepted)
            pid = row["problem_id"]
            require(pid not in gold or gold[pid] == accepted, "Gold answer set changed across draws")
            gold[pid] = accepted
            identity_rows[sample_id] = row
    ordered = [identity_rows[key] for key in sorted(identity_rows)]
    return gold, {
        "publication_manifest_sha256": manifest_hash, "verified_gold_shards": verified,
        "projection_columns": list(columns), "projected_gold_rows": len(identity_rows),
        "gold_projection_sha256": canonical_digest([{key: row[key] for key in GOLD_COLUMNS} for row in ordered]),
        "author_diagnostic_projection_sha256": canonical_digest(ordered) if author_diagnostics else None,
        "author_rows": identity_rows if author_diagnostics else {},
    }


def status(value: int | None, accepted: frozenset[int]) -> str:
    return "NO_SELECTION" if value is None else "CORRECT" if value in accepted else "INCORRECT"


def transition(thought: int, final: int, accepted: frozenset[int]) -> str:
    return f"{'correct' if thought in accepted else 'wrong'}_to_{'correct' if final in accepted else 'wrong'}"


def summarize_cases(rows: list[dict], baseline: str) -> dict:
    correct = Counter(arm for row in rows for arm, outcome in row["selection_status"].items() if outcome == "CORRECT")
    by_arm = {}
    for arm in ARMS:
        eligible = sum(row["eligible_correct_by_arm"][arm] for row in rows)
        no_selection = sum(row["selection_status"][arm] == "NO_SELECTION" for row in rows)
        paired = {}
        for comparator in dict.fromkeys(("inclusive_majority", baseline)):
            repairs = sum(row["selection_status"][arm] == "CORRECT" and row["selection_status"][comparator] != "CORRECT"
                          for row in rows)
            harms = sum(row["selection_status"][arm] != "CORRECT" and row["selection_status"][comparator] == "CORRECT"
                        for row in rows)
            paired[comparator] = {"repairs": repairs, "harms": harms, "net": repairs - harms}
        by_arm[arm] = {"correct": correct[arm], "denominator": len(rows),
                       "accuracy": correct[arm] / len(rows) if rows else None,
                       "no_selection": no_selection, "correct_value_available": eligible,
                       "no_correct_value_in_allowed_pool": len(rows) - eligible,
                       "selection_failure_with_correct_available": eligible - correct[arm],
                       "paired": paired}
    pools = {}
    for pool in ("final", "inclusive", "inclusive_all_bare_sensitivity"):
        memberships = [row["observed_candidate_gold_membership"][pool] for row in rows]
        pools[pool] = {"hindsight_correct_value_covered": sum(any(flags) for flags in memberships),
                       "empty": sum(not flags for flags in memberships),
                       "nonempty_without_correct_value": sum(bool(flags) and not any(flags) for flags in memberships)}
    return {"question_count": len(rows), "by_arm": by_arm, "fixed_pool_hindsight_coverage": pools,
            "inclusive_adds_correct_value_beyond_final": sum(
                any(row["observed_candidate_gold_membership"]["inclusive"])
                and not any(row["observed_candidate_gold_membership"]["final"]) for row in rows)}


def score(prepared: list[dict], gold: dict, evaluation: dict, author_rows: dict) -> dict:
    rows, differences, correct_refutations = [], [], []
    terminations, channel_unknown, comparable, comparable_disagree = (
        Counter({key: 0 for key in TERMINATIONS}), Counter(), Counter(dict.fromkeys(TRANSITIONS, 0)),
        Counter(dict.fromkeys(TRANSITIONS, 0)))
    costs = {name: Counter() for name in ("ordinary", "scoped", "pool")}
    coverage = Counter()
    author = Counter()
    for item in prepared:
        row, samples, by_draw, paid = (item[k] for k in ("row", "samples", "by_draw", "paid"))
        pid = row["problem_id"]
        accepted = gold[pid]
        selected = row["selection"]
        final0, thought0 = by_draw[0]
        pool = row["pool"]
        finals, inclusive = pool["final_ranked"], pool["inclusive_ranked"]
        observed = {"final": [x in accepted for x in finals], "inclusive": [x in accepted for x in inclusive],
                    "inclusive_all_bare_sensitivity": [x in accepted for x in row["broad_inclusive_ranked"]]}
        channels = []
        for sample in samples:
            final, thought = by_draw[sample["draw_index"]]
            end = sample["termination"]
            terminations[end] += 1
            readout = {"draw_index": sample["draw_index"], "termination": end, "boundary": sample["boundary"],
                       "thinking_status": sample["thinking"]["status"], "final_status": sample["final"]["status"]}
            if end == "NATIVE_STOP":
                readout.update({"eligible_thinking_correct": None if thought is None else thought in accepted,
                                "eligible_final_correct": None if final is None else final in accepted})
                if final is not None and thought is not None:
                    pair = transition(thought, final, accepted)
                    comparable[pair] += 1
                    comparable_disagree[pair] += thought != final
                    readout.update({"correctness_transition": pair, "values_differ": thought != final})
                else:
                    missing = "both_missing" if final is None and thought is None else (
                        "thinking_missing" if thought is None else "final_missing")
                    channel_unknown[missing] += 1
            channels.append(readout)
            if author_rows:
                label = author_rows[sample["sample_id"]]
                whole = sample["author_whole_response_candidate"]
                author["records"] += 1
                author["whole_parser_value_agreement"] += whole == label["extracted_answer_integer"]
                author["whole_parser_correctness_agreement"] += (whole in accepted) == label["is_correct"]
        batch_checks = {}
        for arm in ("ordinary", "scoped"):
            checked = paid[arm]["checks"]
            arm_cost = row[arm]
            for key in ("paid_predicate_calls", "paid_candidate_evaluations", "wall_ns", "cpu_ns"):
                costs[arm][key] += arm_cost[key]
            ops = "primitive_numeric_operations" if arm == "scoped" else "decision_primitive_numeric_operations"
            costs[arm]["reported_numeric_operations"] += arm_cost[ops]
            costs[arm]["predicate_requests"] += len(arm_cost["calls"])
            batch_checks[arm] = []
            for prereq, rank, value, refuted, receipt in checked:
                record = {"prerequisite_sha256": prereq, "inclusive_candidate_rank": rank,
                          "matches_accepted_gold": value in accepted, "refuted": refuted}
                if receipt is not None:
                    record["receipt_sha256"] = receipt
                batch_checks[arm].append(record)
                if refuted and value in accepted:
                    correct_refutations.append({"problem_id": pid, "arm": arm, **record})
            coverage[f"{arm}_correct_value_eliminated_questions"] += any(
                x in accepted for x in arm_cost["eliminated"])
            coverage[f"{arm}_wrong_distinct_candidates_eliminated"] += sum(x not in accepted for x in arm_cost["eliminated"])
        discrepancy = {
            "per_predicate_refuted_set_or_application": paid["ordinary"]["calls"] != paid["scoped"]["calls"],
            "eliminated_values": row["ordinary"]["eliminated"] != row["scoped"]["eliminated"],
            "selected_value": selected["ordinary_same_access"] != selected["scoped_refutation"],
            "fallback": row["empty_survivor_fallback"]["ordinary"] != row["empty_survivor_fallback"]["scoped"],
        }
        if any(discrepancy.values()):
            differences.append({"problem_id": pid, **discrepancy})
        coverage["approved_predicate_questions"] += row["scope_review_count"] > 0
        coverage["scoped_paid_predicate_questions"] += row["scoped"]["paid_predicate_calls"] > 0
        coverage["scoped_any_refutation_certificate_questions"] += bool(row["scoped"]["eliminated"])
        coverage["scoped_discriminating_questions"] += bool(row["discriminating_prerequisites"])
        coverage["scoped_discriminating_questions_with_survivor"] += bool(
            row["discriminating_prerequisites"] and row["scoped_survivors"])
        for arm in ("ordinary", "scoped"):
            coverage[f"{arm}_empty_survivor_fallback_questions"] += row["empty_survivor_fallback"][arm]
        costs["pool"]["shared_pool_construction_cpu_ns"] += row["pool_cpu_ns"]
        for unit in ("input", "output"):
            for scope in ("all_draws", "draw0"):
                key = f"observed_{unit}_tokens_{scope}"
                costs["pool"][key] += row[key]
        eligible = {arm: any(observed["inclusive"]) for arm in ARMS}
        eligible.update({"native_draw0": final0 in accepted,
                         "thinking_preferred_draw0": final0 in accepted or thought0 in accepted,
                         "final_majority": any(observed["final"]),
                         "author_whole_draw0_diagnostic": selected["author_whole_draw0_diagnostic"] in accepted})
        rows.append({"problem_id": pid, "disagreement_subset_member": row["disagreement_subset_member"],
                     "selection_status": {arm: status(selected[arm], accepted) for arm in ARMS},
                     "eligible_correct_by_arm": eligible, "observed_candidate_gold_membership": observed,
                     "scoped_survivor_gold_membership": [value in accepted for value in row["scoped_survivors"]],
                     "empty_survivor_fallback": row["empty_survivor_fallback"], "channels": channels,
                     "paid_candidate_checks": batch_checks})
    strongest = max(ORDINARY_ARMS, key=lambda arm: sum(row["selection_status"][arm] == "CORRECT" for row in rows))
    full = summarize_cases(rows, strongest)
    disputes = summarize_cases([row for row in rows if row["disagreement_subset_member"]], strongest)
    policy = evaluation["admission"]
    net = full["by_arm"]["scoped_refutation"]["paired"][strongest]["net"]
    gate = {
        "minimum_discriminating_problems": policy["minimum_independent_problems_with_non_format_discriminating_proof"],
        "observed_discriminating_problems": coverage["scoped_discriminating_questions"],
        "minimum_net_vs_strongest": policy["minimum_net_correct_against_strongest_same_access_arm"],
        "observed_net_vs_strongest": net,
        "correct_value_refutations_require_review": bool(correct_refutations and
                                                         policy["require_independent_review_of_any_correct_value_refutation"]),
    }
    gate["admitted"] = (gate["observed_discriminating_problems"] >= gate["minimum_discriminating_problems"]
                        and gate["observed_net_vs_strongest"] >= gate["minimum_net_vs_strongest"]
                        and not gate["correct_value_refutations_require_review"])
    upstream = {}
    for arm in ARMS:
        scope = "draw0" if "draw0" in arm else "all_draws"
        upstream[arm] = {
            "observed_input_tokens": costs["pool"][f"observed_input_tokens_{scope}"],
            "observed_output_tokens": costs["pool"][f"observed_output_tokens_{scope}"],
            "additional_generation_runs": 0,
        }
    return {"status": "D43_FROZEN_SELECTIONS_SCORED", "full_cohort": full, "pre_gold_disagreement_subset": disputes,
            "strongest_same_pool_ordinary": strongest, "strongest_same_pool_ordinary_tie_order": list(ORDINARY_ARMS),
            "sample_readout": {"termination_counts": dict(terminations), "native_missing_channels": dict(channel_unknown),
                               "native_comparable_2x2": dict(comparable),
                               "native_comparable_disagreement_2x2": dict(comparable_disagree)},
            "certificate_coverage": dict(coverage), "correct_value_refutations": correct_refutations,
            "scoped_direct_exact_discrepancies": differences, "admission": gate,
            "observed_cost": {name: dict(values) for name, values in costs.items()},
            "observed_upstream_cost_by_arm": upstream,
            "author_whole_readout_agreement": dict(author) if author_rows else None, "rows": rows}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("selection", "machine", "cohort", "eval-freeze", "review", "proofs", "source", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--expected-selection-sha256", required=True)
    cli.add_argument("--author-diagnostics", action="store_true")
    args = cli.parse_args()
    require(not args.output.exists(), "Scoring output already exists")
    names = ("selection", "machine", "cohort", "eval_freeze", "review", "proofs")
    inputs = {name: getattr(args, name).read_bytes() for name in names}
    hashes = {name: digest(raw) for name, raw in inputs.items()}
    require(hashes["selection"] == args.expected_selection_sha256, "External selection freeze hash differs")
    data = {name: json.loads(raw) for name, raw in inputs.items()}
    selection, machine, cohort, evaluation = (data[key] for key in names[:4])
    require(all(selection["input_sha256"][key] == value for key, value in hashes.items() if key != "selection")
            and machine["cohort_freeze_sha256"] == evaluation["cohort_freeze_sha256"] ==
                data["proofs"]["cohort_freeze_sha256"] == hashes["cohort"]
            and data["review"]["machine_readout_sha256"] == hashes["machine"]
            and selection["selector_sha256"] == digest(Path(__file__).with_name("run_selection.py").read_bytes()),
            "Frozen selection ancestry differs")
    prepared = prepare(selection, machine, cohort, evaluation, data["review"], data["proofs"])
    began_wall, began_cpu = perf_counter_ns(), thread_time_ns()
    gold, source_receipt = load_gold(args.source, prepared, cohort, args.author_diagnostics)
    report = score(prepared, gold, evaluation, source_receipt.pop("author_rows"))
    report.update({"input_sha256": hashes, "source_receipt": source_receipt,
                   "scorer_sha256": digest(Path(__file__).read_bytes()),
                   "scoring_cost": {"wall_ns": perf_counter_ns() - began_wall, "cpu_ns": thread_time_ns() - began_cpu},
                   "frozen_processing_cost": {"machine_readout": machine["cost"], "selection_all_arms": selection["cost"],
                                              "role_review_wall_bracket_seconds": data["review"].get(
                                                  "observed_review_wall_bracket_seconds"),
                                              "proof_authoring_and_review_wall_brackets": [
                                                  {key: item.get(key) for key in (
                                                      "indices", "author_reported_timing", "review_reported_timing",
                                                      "author_wall_upper_bound_since_question_view_seconds",
                                                      "review_wall_upper_bound_since_question_view_seconds")}
                                                  for item in data["proofs"].get("local_handoffs", [])],
                                              "new_generation_runs": 0,
                                              "arm_upstream_draws": {arm: (1 if "draw0" in arm else len(DRAWS))
                                                                     for arm in ARMS}}})
    write_exclusive(args.output, report)
    print(f"{report['status']}: {len(report['rows'])} questions")


if __name__ == "__main__":
    main()
