"""Score the frozen D4.4 historical and replication blocks after an explicit hash gate."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
HISTORICAL = (0, 1, 2, 3)
REPLICATION = (4, 5, 6, 7)
GROUPS = ("historical", "replication", "merged")
TERMINATIONS = ("NATIVE_STOP", "LENGTH_CAP", "TERMINATION_UNKNOWN")
IDENTITY = ("problem_id", "sample_id", "draw_index", "seed", "response_sha256")
SOURCE_IDENTITY = ("rendered_prompt_sha256", "source_record_sha256", "contract_sha256")
GOLD_COLUMNS = (*IDENTITY, *SOURCE_IDENTITY, "accepted_answer_integers")
HEX_SHA = re.compile(r"[0-9a-f]{64}")


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def by_key(rows: list[dict], key: str) -> dict:
    indexed = {row[key]: row for row in rows}
    require(len(indexed) == len(rows), f"Duplicate {key}")
    return indexed


def identity(row: dict) -> tuple:
    return tuple(row[key] for key in IDENTITY)


def valid_answer(value: object) -> bool:
    return type(value) is int and 0 <= value <= 999


def native_final(row: dict) -> int | None:
    if row["termination"] == "NATIVE_STOP":
        return row["final"]["value"]
    return None


def validate_row(row: dict, expected: dict, question: dict) -> None:
    require(identity(row) == identity(expected) and type(row["seed"]) is int
            and row["seed"] == 1234 + 480 * row["draw_index"] + question["eval_index"],
            f"Changed sample or seed for {question['problem_id']}")
    require(type(row["response_sha256"]) is str and HEX_SHA.fullmatch(row["response_sha256"]) is not None,
            "Malformed response digest")
    final, thought = row["final"], row["thinking"]
    for readout in (final, thought):
        value = readout["value"]
        require((value is None and not readout["complete_explicit_candidate"])
                or (valid_answer(value) and readout["complete_explicit_candidate"] and readout["status"] == "EXPLICIT_INTEGER"),
                "Changed readout semantics")
    require(final["value"] is None or row["boundary"] == "CLOSED_THINKING", "Final integer without channel boundary")
    require(row["termination"] in TERMINATIONS and (row["author_whole_response_candidate"] is None
            or valid_answer(row["author_whole_response_candidate"])), "Changed termination or whole diagnostic")
    require(all(type(row[key]) is int and row[key] >= 0 for key in
                ("input_tokens", "output_tokens", "effective_max_new_tokens"))
            and row["output_tokens"] <= row["effective_max_new_tokens"], "Malformed recorded token cost")


def prepare(readout: dict, receipt: dict, freeze: dict, cohort: dict, historical: dict) -> list[dict]:
    """Verify the scored population before any label column is opened."""
    require(freeze["status"] == "REPLICATION_RULES_FROZEN_BEFORE_NEW_DRAW_CONTENT_OR_SCORE"
            and receipt["status"] == "PINNED_ADDITIONAL_DRAWS_VERIFIED_METADATA_ONLY"
            and readout["status"] == "D44_NEW_DRAW_READOUTS_FROZEN_WITHOUT_GOLD"
            and historical["status"] == "FROZEN_MACHINE_READOUT_WITHOUT_GOLD"
            and tuple(freeze["historical_draws"]) == tuple(cohort["draws"]) == HISTORICAL
            and tuple(freeze["replication_draws"]) == tuple(receipt["draws"]) == tuple(readout["draws"]) == REPLICATION
            and tuple(freeze["reserved_unopened_draws"]) == tuple(range(8, 16)),
            "Changed frozen phases or draw ranges")
    source = receipt["source"]
    require(freeze["source_revision"] == source["revision"] == cohort["source_revision"]
            and freeze["upstream_manifest_sha256"] == source["publication_manifest"]["sha256"] ==
                cohort["publication_manifest_sha256"]
            and freeze["upstream_generation_contract_sha256"] == source["publication_contract_sha256"] ==
                cohort["contract_sha256"]
            and receipt["model"]["id"] == cohort["model"]["id"]
            and receipt["model"]["revision"] == cohort["model"]["revision"], "Changed model or source contract")
    shard_keys = ("path", "sha256", "size")
    require([{key: row[key] for key in shard_keys} for row in receipt["shards"]] ==
            freeze["replication_expected_shards"], "Changed approved shard set")
    authority = receipt["cohort_identity"]
    require(authority["d43_cohort_sha256"] == historical["cohort_freeze_sha256"] == readout["cohort_freeze_sha256"] ==
            freeze["d43_cohort_sha256"],
            "Changed historical cohort identity")
    questions = by_key(cohort["selected"], "problem_id")
    matched = by_key(authority["rows"], "problem_id")
    older = by_key(historical["rows"], "sample_id")
    newer = by_key(readout["rows"], "sample_id")
    require(list(questions) == list(matched)
            and len(questions) == authority["selected_question_count"] == freeze["fixed_questions"] == 32
            and len(older) == len(newer) == authority["selected_draw_count"] == freeze["replication_expected_rows"] == 128,
            "Changed question or sample denominator")
    prepared = []
    covered = [set(), set()]
    for pid, question in questions.items():
        anchor = matched[pid]
        require(question["eval_index"] == anchor["eval_index"], f"Changed index for {pid}")
        blocks = []
        for wanted, records, index, seen in (
            (HISTORICAL, question["samples"], older, covered[0]),
            (REPLICATION, anchor["samples"], newer, covered[1]),
        ):
            require(tuple(record["draw_index"] for record in records) == wanted, "Changed sample order")
            rows = []
            for record in records:
                sample = index[record["sample_id"]]
                validate_row(sample, {**record, "problem_id": pid}, question)
                require(sample["sample_id"] not in seen, "Sample assigned to more than one question")
                seen.add(sample["sample_id"])
                rows.append(sample)
            blocks.append(rows)
        prepared.append({"problem_id": pid, "anchor": anchor, "historical": blocks[0], "replication": blocks[1]})
    require(covered[0] == set(older) and covered[1] == set(newer), "Frozen input has unbound readouts")
    return prepared


def load_gold(source: Path, prepared: list[dict], receipt: dict) -> tuple[dict, dict]:
    """Read exactly the selected replication identities and accepted integer sets."""
    import pyarrow.parquet as pq

    manifest = receipt["source"]["publication_manifest"]
    raw = (source / manifest["path"]).read_bytes()
    require(len(raw) == manifest["size"] and digest(raw) == manifest["sha256"], "Changed local publication manifest")
    manifest_rows = by_key(json.loads(raw)["files"], "path")
    label_sets, projection = {}, []
    for draw, record in zip(REPLICATION, receipt["shards"]):
        path = f"data/draw-{draw:02}.parquet"
        require(record["path"] == path and all(record[key] == manifest_rows[path][key] for key in ("size", "sha256")),
                "Shard receipt disagrees with upstream manifest")
        shard = (source / path).read_bytes()
        require(len(shard) == record["size"] and digest(shard) == record["sha256"], f"Changed source bytes in draw {draw}")
        expected = {row["sample_id"]: (row, item["anchor"]) for item in prepared for row in item["replication"]
                    if row["draw_index"] == draw}
        rows = by_key(pq.read_table(BytesIO(shard), columns=list(GOLD_COLUMNS),
                                   filters=[("sample_id", "in", sorted(expected))], use_threads=False).to_pylist(), "sample_id")
        require(set(rows) == set(expected), "Gold projection has unexpected identities")
        for sample_id, row in sorted(rows.items()):
            sample, anchor = expected[sample_id]
            require(identity(row) == identity(sample)
                    and all(row[key] == anchor[key] for key in SOURCE_IDENTITY[:2])
                    and row["contract_sha256"] == receipt["source"]["publication_contract_sha256"],
                    "Changed accepted-integer row identity")
            accepted = row["accepted_answer_integers"]
            require(isinstance(accepted, list) and bool(accepted) and all(valid_answer(value) for value in accepted),
                    "Missing or malformed accepted integer set")
            pid = row["problem_id"]
            values = frozenset(accepted)
            require(pid not in label_sets or values == label_sets[pid], "Accepted answers differ across replication draws")
            label_sets[pid] = values
            projection.append(row)
    require(len(label_sets) == len(prepared), "Incomplete accepted-answer projection")
    compact = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return label_sets, {"manifest_sha256": manifest["sha256"], "projected_rows": len(projection),
                        "projection_columns": list(GOLD_COLUMNS), "projected_gold_sha256": digest(compact)}


def rank(values: list[int]) -> list[int]:
    # Counter preserves the first occurrence of each value in draw order.
    votes = Counter(values)
    return sorted(votes, key=lambda value: -votes[value])


def score_status(value: int | None, labels: frozenset[int]) -> str:
    return "NO_SELECTION" if value is None else "CORRECT" if value in labels else "INCORRECT"


def block(rows: list[dict], labels: frozenset[int]) -> dict:
    values = [value for row in rows if (value := native_final(row)) is not None]
    whole = [value for row in rows if (value := row["author_whole_response_candidate"]) is not None]
    ranked = rank(values)
    ranked_whole = rank(whole)
    membership = [value in labels for value in ranked]
    raw = []
    for row in rows:
        value = native_final(row)
        native, end = row["termination"] == "NATIVE_STOP", row["termination"]
        final_status = score_status(value, labels)
        outcome = ("NATIVE_CORRECT" if final_status == "CORRECT" else "NATIVE_WRONG" if final_status == "INCORRECT"
                   else "NATIVE_NO_ELIGIBLE_FINAL" if native else end)
        raw.append({"draw_index": row["draw_index"], "sample_id": row["sample_id"], "termination": end,
                    "boundary": row["boundary"], "final_readout_status": row["final"]["status"],
                    "native_final_outcome": outcome,
                    "native_final_matches_accepted": None if value is None else value in labels,
                    "author_whole_matches_accepted": None if row["author_whole_response_candidate"] is None
                    else row["author_whole_response_candidate"] in labels,
                    "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"]})
    return {
        "draws": raw,
        "native_final_majority_status": score_status(ranked[0] if ranked else None, labels),
        "native_final_coverage": any(membership), "native_ranked_membership": membership,
        "native_candidate_count": len(values), "native_distinct_value_count": len(ranked),
        "native_pool_state": ("CORRECT_AVAILABLE" if any(membership) else "EMPTY" if not ranked
                              else "SAME_WRONG_VALUE" if len(ranked) == 1 else "MIXED_WRONG_VALUES"),
        "earliest_correct_native_draw": next((r["draw_index"] for r in raw if r["native_final_matches_accepted"]), None),
        "author_whole_diagnostic": {"coverage": any(value in labels for value in ranked_whole),
                                    "majority_status": score_status(ranked_whole[0] if ranked_whole else None, labels),
                                    "scorable_draws": len(whole)},
        "input_tokens": sum(r["input_tokens"] for r in rows), "output_tokens": sum(r["output_tokens"] for r in rows),
    }


def summarize(blocks: list[dict]) -> dict:
    draws = [draw for item in blocks for draw in item["draws"]]
    return {
        "question_count": len(blocks), "observed_draw_count": len(draws),
        "native_final_coverage": sum(item["native_final_coverage"] for item in blocks),
        "native_final_majority_correct": sum(item["native_final_majority_status"] == "CORRECT" for item in blocks),
        "native_final_majority_accuracy": (
            sum(item["native_final_majority_status"] == "CORRECT" for item in blocks) / len(blocks) if blocks else None),
        "native_final_pool_states": dict(sorted(Counter(item["native_pool_state"] for item in blocks).items())),
        "native_selection_failure_with_correct_available": sum(item["native_final_coverage"] and
            item["native_final_majority_status"] != "CORRECT" for item in blocks),
        "termination_counts": dict(sorted(Counter(row["termination"] for row in draws).items())),
        "outcome_counts": dict(sorted(Counter(row["native_final_outcome"] for row in draws).items())),
        "native_ineligible_format_counts": dict(sorted(Counter(row["final_readout_status"] for row in draws
            if row["native_final_outcome"] == "NATIVE_NO_ELIGIBLE_FINAL").items())),
        "author_whole_diagnostic": {"coverage": sum(item["author_whole_diagnostic"]["coverage"] for item in blocks),
            "majority_correct": sum(item["author_whole_diagnostic"]["majority_status"] == "CORRECT" for item in blocks),
            "correct_draws": sum(row["author_whole_matches_accepted"] is True for row in draws),
            "scorable_draws": sum(item["author_whole_diagnostic"]["scorable_draws"] for item in blocks)},
        "observed_input_tokens": sum(item["input_tokens"] for item in blocks),
        "observed_output_tokens": sum(item["output_tokens"] for item in blocks),
    }


def paired(left: list[bool], right: list[bool]) -> dict:
    return {"both": sum(a and b for a, b in zip(left, right)),
            "historical_only": sum(a and not b for a, b in zip(left, right)),
            "comparison_only": sum(not a and b for a, b in zip(left, right)),
            "neither": sum(not a and not b for a, b in zip(left, right))}


def stratum(rows: list[dict]) -> str:
    ends = {row["termination"] for row in rows}
    if ends == {"LENGTH_CAP"}:
        return "ALL_CAP"
    if "LENGTH_CAP" in ends:
        return "MIXED_WITH_CAP"
    return "ALL_NATIVE" if ends == {"NATIVE_STOP"} else "NO_CAP_WITH_UNKNOWN_TERMINATION"


def historical_check(row: dict, expected: dict) -> None:
    original = row["historical"]
    observed_draw0 = original["draws"][0]
    prior = expected["selection_status"]
    known = {True: "CORRECT", False: "INCORRECT", None: "NO_SELECTION"}
    require(original["native_ranked_membership"] == expected["observed_candidate_gold_membership"]["final"]
            and original["native_final_majority_status"] == prior["final_majority"]
            and known[observed_draw0["native_final_matches_accepted"]] == prior["native_draw0"]
            and known[observed_draw0["author_whole_matches_accepted"]] == prior["author_whole_draw0_diagnostic"],
            f"Historical scoring does not reproduce for {row['problem_id']}")
    current = [(r["draw_index"], r["termination"], r["native_final_matches_accepted"]) for r in original["draws"]]
    past = [(r["draw_index"], r["termination"], r.get("eligible_final_correct")) for r in expected["channels"]]
    require(current == past, f"Historical per-draw readout does not reproduce for {row['problem_id']}")


def score(prepared: list[dict], labels: dict, historical_snapshot: dict) -> dict:
    prior = by_key(historical_snapshot["rows"], "problem_id")
    require(set(prior) == set(labels) == {item["problem_id"] for item in prepared}, "Historical scoring universe differs")
    rows = []
    for item in prepared:
        pid = item["problem_id"]
        old, new = item["historical"], item["replication"]
        groups = {"historical": block(old, labels[pid]), "replication": block(new, labels[pid]),
                  "merged": block(old + new, labels[pid])}
        row = {"problem_id": pid, "pre_score_historical_cap_stratum": stratum(old), **groups}
        row["earliest_new_correct_draw_on_historical_miss"] = (
            groups["replication"]["earliest_correct_native_draw"] if not groups["historical"]["native_final_coverage"] else None)
        historical_check(row, prior[pid])
        rows.append(row)
    grouped = {key: summarize([row[key] for row in rows]) for key in GROUPS}
    historical = grouped["historical"]
    old_cohort = historical_snapshot["full_cohort"]
    old_cost = historical_snapshot["observed_cost"]["pool"]
    require(historical["native_final_coverage"] ==
                old_cohort["fixed_pool_hindsight_coverage"]["final"]["hindsight_correct_value_covered"]
            and historical["native_final_majority_correct"] == old_cohort["by_arm"]["final_majority"]["correct"]
            and historical["observed_input_tokens"] == old_cost["observed_input_tokens_all_draws"]
            and historical["observed_output_tokens"] == old_cost["observed_output_tokens_all_draws"],
            "Historical aggregates do not reproduce")
    effects = {}
    for key in GROUPS[1:]:
        effects[key] = {
            "coverage": paired([r["historical"]["native_final_coverage"] for r in rows],
                               [r[key]["native_final_coverage"] for r in rows]),
            "majority_correct": paired([r["historical"]["native_final_majority_status"] == "CORRECT" for r in rows],
                                      [r[key]["native_final_majority_status"] == "CORRECT" for r in rows]),
        }
    strata = {}
    for key in sorted({row["pre_score_historical_cap_stratum"] for row in rows}):
        members = [row for row in rows if row["pre_score_historical_cap_stratum"] == key]
        strata[key] = {group: summarize([row[group] for row in members]) for group in GROUPS}
    missed = [r for r in rows if not r["historical"]["native_final_coverage"]]
    return {"status": "D44_FIXED_BLOCKS_SCORED", "blocks": grouped, "paired_vs_historical": effects,
            "historical_cap_strata": strata, "historical_misses": [r["problem_id"] for r in missed],
            "historical_miss_first_new_correct_draws": [
                {"problem_id": r["problem_id"], "draw_index": r["earliest_new_correct_draw_on_historical_miss"]}
                for r in missed],
            "historical_snapshot_reproduced": True, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("readout", "acquisition", "source-receipt", "source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-readout-sha256", required=True)
    parser.add_argument("--historical-dir", type=Path, default=D43)
    args = parser.parse_args()
    require(not args.output.exists(), "Scoring output exists")
    input_paths = {
        "readout": args.readout, "acquisition": args.acquisition, "source_receipt": args.source_receipt,
        "d43_cohort": args.historical_dir / "D43_COHORT_FREEZE.json",
        "d43_readout": args.historical_dir / "D43_MACHINE_READOUT_FREEZE.json",
        "d43_scored_historical": args.historical_dir / "D43_SCORED_RESULTS.json",
    }
    raw = {key: path.read_bytes() for key, path in input_paths.items()}
    hashes = {key: digest(content) for key, content in raw.items()}
    require(hashes["readout"] == args.expected_readout_sha256, "External readout freeze hash differs")
    data = {key: json.loads(content) for key, content in raw.items()}
    freeze, readout = data["acquisition"], data["readout"]
    require(readout["acquisition_freeze_sha256"] == hashes["acquisition"]
            and readout["source_receipt_sha256"] == hashes["source_receipt"]
            and all(freeze[f"{key}_sha256"] == hashes[key] for key in ("d43_cohort", "d43_readout", "d43_scored_historical"))
            and readout["extractor_sha256"] == freeze["d43_extractor_sha256"] ==
                digest((args.historical_dir / "extract_candidates.py").read_bytes())
            and readout["author_parser_sha256"] == data["d43_readout"]["author_parser_sha256"],
            "Unbound readout, source receipt or historical evidence")
    receipt = data["source_receipt"]
    prepared = prepare(readout, receipt, freeze, data["d43_cohort"], data["d43_readout"])
    start_wall, start_cpu = perf_counter_ns(), thread_time_ns()
    labels, source = load_gold(args.source, prepared, receipt)
    report = score(prepared, labels, data["d43_scored_historical"])
    report.update({"input_sha256": hashes, "scorer_sha256": digest(Path(__file__).read_bytes()), "gold_source": source,
                   "scoring_wall_ns": perf_counter_ns() - start_wall, "scoring_cpu_ns": thread_time_ns() - start_cpu,
                   "replication_blind_readout_cost": readout["cost"],
                   "new_generations": 0, "historical_gpu_wall_clock": "NOT_RECORDED",
                   "selection_policy": "Native final majority; break ties by earliest valid draw. Coverage is a separate hindsight diagnostic."})
    with args.output.open("xb") as stream:
        stream.write((json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())
    print(f"{report['status']}: {len(report['rows'])} questions")


if __name__ == "__main__":
    main()
