"""Recount D4.3 from raw projected labels, exact blind spans and frozen selections."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from freeze_cohort import BASELINE, DRAWS, digest, load_shards, lock_selection, question_digest, write_exclusive


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PHASE = HERE.relative_to(ROOT).as_posix()


def load(name: str) -> dict:
    return json.loads((HERE / name).read_bytes())


def sha(name: str) -> str:
    return digest((HERE / name).read_bytes())


def check_previous_phase() -> None:
    paths = subprocess.check_output(["git", "diff", "--name-only", "-z", BASELINE, "--"], cwd=ROOT)
    allowed = {"README.md", "docs/phases/INDEX_ZH.md"}
    assert all(
        not name or name in allowed or name.startswith(PHASE + "/")
        for name in paths.decode().split("\0")
    )


def check_blind_evidence(source: Path, cohort: dict, machine: dict, proofs: dict) -> None:
    intake = load("D43_PILOT_INTAKE.json")
    assert intake["source_receipt_sha256"] == sha("D43_SOURCE_RECEIPT.json")
    assert intake["cohort_freeze_sha256"] == sha("D43_COHORT_FREEZE.json")
    assert lock_selection(source, HERE / "D43_DEVELOPMENT_EXCLUSIONS.json") == {
        **cohort, "draws": tuple(cohort["draws"]),
    }
    raw = (source / "d43_pilot_gold_blind.json").read_bytes()
    qraw = (source / "d43_question_only.json").read_bytes()
    assert intake["blind_view_sha256"] == machine["blind_input_sha256"] == digest(raw)
    assert intake["question_only_view_sha256"] == proofs["question_only_sha256"] == digest(qraw)
    assert machine["extractor_sha256"] == sha("extract_candidates.py")
    assert machine["author_parser_sha256"] == digest((source / "aime_scorer.py").read_bytes())
    blind = json.loads(raw)["rows"]
    assert len(blind) == len(machine["rows"]) == 128
    source_rows = {r["sample_id"]: r for r in blind}
    terminations = Counter()
    checked_spans = 0
    for row in machine["rows"]:
        entry = source_rows[row["sample_id"]]
        text = entry["response"]
        assert not set(entry) & {"accepted_answer_integers", "is_correct", "gold_answer_raw", "scorer_trace_json"}
        assert digest(text.encode()) == row["response_sha256"]
        assert (row["termination"] == "LENGTH_CAP") == entry["cap_hit"]
        assert (row["termination"] == "NATIVE_STOP") == (entry["stop_token_id"] in {151643, 151645})
        terminations[row["termination"]] += 1
        for channel in ("thinking", "final"):
            observed = row[channel]
            if "char_span_in_response" in observed:
                start, end = observed["char_span_in_response"]
                assert 0 <= start < end <= len(text)
                assert digest(text[start:end].encode()) == observed["source_excerpt_sha256"]
                checked_spans += 1
    assert checked_spans == 233 and terminations == {"NATIVE_STOP": 116, "LENGTH_CAP": 12}
    questions = {row["problem_id"]: row["question"] for row in json.loads(qraw)["questions"]}
    for row in proofs["rows"]:
        question = questions[row["problem_id"]]
        assert digest(question.encode()) == row["exact_question_sha256"]
        assert question_digest(question) == row["normalized_question_sha256"]
        for proposal in row["proposal_audit"]:
            for anchor in proposal["premise_anchors"]:
                start, end = anchor["char_span_0_based_half_open"]
                assert digest(question[start:end].encode()) == anchor["sha256_utf8"]
    assert sum(len(row["proposal_audit"]) for row in proofs["rows"]) == 26
    assert sum(len(row["approved_predicates"]) for row in proofs["rows"]) == 25
    role = load("D43_ROLE_REVIEW_FREEZE.json")
    queue = load("D43_ROLE_AUDIT_QUEUE.json")
    assert role["queue_sha256"] == sha("D43_ROLE_AUDIT_QUEUE.json")
    assert role["machine_readout_sha256"] == queue["machine_readout_sha256"] == sha("D43_MACHINE_READOUT_FREEZE.json")
    assert [row["sample_id"] for row in role["rows"]] == [row["sample_id"] for row in queue["queue"]]
    assert len(role["rows"]) == 29 and sum(row["approve_unanchored_thinking_box"] for row in role["rows"]) == 5


def postscore_labels(source: Path, cohort: dict) -> dict:
    _, shards = load_shards(source)
    gold = {}
    by_sample = {s["sample_id"]: (row["problem_id"], s["response_sha256"])
                 for row in cohort["selected"] for s in row["samples"]}
    found = 0
    columns = ["problem_id", "sample_id", "response_sha256", "accepted_answer_integers"]
    for draw in DRAWS:
        for row in shards[draw].read(columns=columns).to_pylist():
            sid = row["sample_id"]
            if sid not in by_sample:
                continue
            pid = row["problem_id"]
            assert (pid, row["response_sha256"]) == by_sample[sid]
            labels = frozenset(row["accepted_answer_integers"])
            assert labels and all(type(label) is int and 0 <= label <= 999 for label in labels)
            assert gold.setdefault(pid, labels) == labels
            found += 1
    assert found == 128 and len(gold) == 32
    return gold


def recount(selection: dict, scored: dict, gold: dict) -> dict:
    arm = Counter()
    coverage, discriminating, false_refutations, wrong_distinct_eliminated = 0, 0, 0, 0
    failures = []
    by_problem = {row["problem_id"]: row for row in scored["rows"]}
    for row in selection["rows"]:
        pid = row["problem_id"]
        accepted = gold[pid]
        independent_status = {key: ("NO_SELECTION" if value is None else "CORRECT" if value in accepted else "INCORRECT")
                              for key, value in row["selection"].items()}
        assert independent_status == by_problem[pid]["selection_status"]
        arm.update(key for key, status in independent_status.items() if status == "CORRECT")
        ranked = row["pool"]["inclusive_ranked"]
        has_correct = bool(accepted.intersection(ranked))
        coverage += has_correct
        if not has_correct:
            failures.append(pid)
        assert row["scoped"]["eliminated"] == row["ordinary"]["eliminated"]
        eliminated = row["scoped"]["eliminated"]
        false_refutations += sum(value in accepted for value in eliminated)
        wrong_distinct_eliminated += sum(value not in accepted for value in eliminated)
        discriminating += bool(row["discriminating_prerequisites"])
        assert row["selection"]["scoped_refutation"] == row["selection"]["ordinary_same_access"]
        assert row["selection"]["scoped_refutation"] == row["selection"]["inclusive_majority"]
    assert dict(arm) == {name: item["correct"] for name, item in scored["full_cohort"]["by_arm"].items()}
    assert coverage == arm["scoped_refutation"] == 29
    assert arm["native_draw0"] == arm["thinking_preferred_draw0"] == 26
    assert false_refutations == 0 and wrong_distinct_eliminated == 6
    assert discriminating == scored["admission"]["observed_discriminating_problems"] == 3
    assert scored["admission"]["observed_net_vs_strongest"] == 0 and not scored["admission"]["admitted"]
    assert scored["sample_readout"]["native_comparable_2x2"] == {
        "correct_to_correct": 102, "correct_to_wrong": 0, "wrong_to_correct": 0, "wrong_to_wrong": 11,
    }
    return {"arm_correct": dict(arm), "fixed_pool_coverage": coverage, "no_correct_candidate_problems": failures,
            "discriminating_problems": discriminating, "wrong_values_refuted": wrong_distinct_eliminated,
            "correct_values_refuted": false_refutations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    check_previous_phase()
    cohort, machine, proofs, selection, scored = [load(name) for name in (
        "D43_COHORT_FREEZE.json", "D43_MACHINE_READOUT_FREEZE.json", "D43_PREREQUISITE_FREEZE.json",
        "D43_SELECTION_FREEZE.json", "D43_SCORED_RESULTS.json",
    )]
    check_blind_evidence(args.source, cohort, machine, proofs)
    assert selection["selector_sha256"] == sha("run_selection.py")
    assert scored["scorer_sha256"] == sha("score_selections.py")
    assert scored["input_sha256"]["selection"] == sha("D43_SELECTION_FREEZE.json")
    assert scored["input_sha256"]["proofs"] == sha("D43_PREREQUISITE_FREEZE.json")
    assert all(value["additional_generation_runs"] == 0 for value in scored["observed_upstream_cost_by_arm"].values())
    facts = recount(selection, scored, postscore_labels(args.source, cohort))
    out = {
        "status": "COMPLETE_NO_GO_FIXED_POOL_SELECTOR_NOT_ADMITTED",
        "baseline": BASELINE, "facts": facts, "independent_problems": 32,
        "fixed_samples": 128, "same_access_net_gain": 0, "new_gpu_rollouts": 0,
        "heldout_confirmation": "not admitted under frozen pilot gate",
        "evidence_sha256": {p.name: digest(p.read_bytes()) for p in sorted(HERE.glob("D43_*.json"))
                            if p.name != "D43_DELIVERY_AUDIT.json"},
    }
    if args.output:
        write_exclusive(args.output, out)
    print(out["status"], facts)


if __name__ == "__main__":
    main()
