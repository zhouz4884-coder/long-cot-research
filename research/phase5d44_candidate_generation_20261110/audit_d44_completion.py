"""Recount the completed live pilot from frozen raw trajectories and labels."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json
import subprocess

import pyarrow.parquet as pq

from audit_d44_replication import HERE, ROOT, digest, load
from freeze_live_outcomes import freeze
from score_live import load_author_scorer

ARMS = ("NativeContinue", "GenericReminder", "TypedObligation", "IndependentRestart")
WORK = ("forward_calls", "forward_input_tokens", "attention_pairs")


def raw_work(ledger: list[dict]) -> dict:
    tokens = 0
    pairs = 0
    for row in ledger:
        width, prior = row["input_tokens"], row["past_tokens"]
        assert width > 0 and row["position_start"] == prior >= 0
        tokens += width
        pairs += width * (2 * prior + width + 1) // 2
    return dict(zip(WORK, (len(ledger), tokens, pairs), strict=True))


def audit(lab: Path, shard: Path, scorer_path: Path) -> dict:
    names = {
        "archive": "D44_ARCHIVE_DELIVERY_AUDIT.json", "outcome": "D44_LIVE_OUTCOME_FREEZE.json",
        "live": "D44_LIVE_RESULTS.json", "trigger": "D44_LIVE_TRIGGER_AUDIT.json",
        "label": "D44_LIVE_LABEL_CONFLICT_AUDIT.json", "cohort": "D44_LIVE_COHORT_FREEZE.json",
    }
    paths = {k: HERE / v for k, v in names.items()}
    archive, outcome, live, trigger, label, cohort = map(load, paths.values())
    assert freeze(lab) == outcome and outcome["independent_questions"] == 8
    assert archive["status"] == "ARCHIVE_RESULTS_AND_LIVE_LAUNCH_RECONCILED"
    assert all(len(x["coverage_ids"]) == 29 for x in archive["blocks"].values())
    assert archive["independent_archival_gate_questions"] == 2
    assert trigger["status"] == "PASS_EXACT_LIVE_TRIGGER_REPLAY_WITHOUT_LABELS"
    assert trigger["outcome_freeze_sha256"] == live["input_sha256"]["outcome"] == digest(paths["outcome"])
    assert live["scorer_sha256"] == digest(HERE / "score_live.py")
    assert label["frozen_score_sha256"] == digest(paths["live"])
    assert label["sensitivity_excluding_conflicted_case"]["typed_cost_censored_net_vs_recomputed_strongest"] == 0
    assert digest(shard) == cohort["question_source_shard_sha256"]
    ids = {row["case_id"] for row in cohort["rows"]}
    projected = pq.read_table(shard, columns=["problem_id", "accepted_answer_integers"],
                              filters=[("problem_id", "in", sorted(ids))]).to_pylist()
    labels = {row["problem_id"]: frozenset(row["accepted_answer_integers"]) for row in projected}
    assert len(projected) == 8 and set(labels) == ids and all(labels.values())
    scored = {row["case_id"]: row for row in live["rows"]}
    audited = {row["case_id"]: row for row in trigger["rows"]}
    assert set(scored) == set(audited) == ids
    parser = load_author_scorer(scorer_path)
    correct, physical = Counter(), Counter()
    terminal_count = 0
    for worker in outcome["workers"]:
        root = lab / "main_raw_results" / f'worker_{worker["worker"]}'
        for asset in worker["cases"]:
            cid = asset["case_id"]
            path = root / cid / "result.json"
            assert digest(path) == asset["result_sha256"] == audited[cid]["result_sha256"]
            raw = load(path)
            assert raw["trigger"]["status"] == scored[cid]["trigger_status"]
            assert raw["trigger"]["status"] in {"NO_ELIGIBLE_TRIGGER", "NO_REVIEWED_OBLIGATION"}
            assert raw["restore_parity"]["status"] == "NOT_TRIGGERED"
            assert tuple(raw["arms"]) == ARMS
            assert raw_work(raw["paid_forward_ledger"]) == raw["actual_paid_work"]
            physical.update(raw["actual_paid_work"])
            for name, arm in raw["arms"].items():
                assert arm["stop_reason"] == "EOS" and not arm["hit_context_cap"] and arm["think_closed"]
                if name in {"GenericReminder", "TypedObligation"}:
                    assert arm["generated_ids"] == raw["arms"]["NativeContinue"]["generated_ids"]
                    assert not any(arm["paid_work"].values())
                final = arm["text"].rsplit("</think>", 1)[1]
                events, malformed = parser.scan_box_events(final)
                boxes = [event for event in events if event.valid]
                assert boxes and not any(x["span"][0] > boxes[-1].span[0] for x in malformed)
                value = parser.parse_aime_integer(boxes[-1].interior_raw)
                assert value is not None
                hit = value in labels[cid]
                assert hit == (scored[cid]["arms"][name]["correctness"] == "CORRECT")
                correct[name] += hit
                terminal_count += 1
    assert terminal_count == 32 and dict(physical) == live["experimental_physical_forward_work"]
    assert all(correct[name] == live["by_arm"][name]["correct"] for name in ARMS)
    assert live["retention_gate"]["observed_net_repairs"] == -4 and not live["retention_gate"]["passed"]
    assert live["witness_conflicts_require_review"] and label["status"] == "OFFICIAL_LABEL_CONFLICT_VERIFIED_POST_SCORE"
    assert sum(row["detector_calls"] for row in audited.values()) == 1269
    raw_paths = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", "bfe5a55945a03046d8d9935f74e84db044da89ad", "--"], cwd=ROOT,
    ).decode().split("\0")
    phase = HERE.relative_to(ROOT).as_posix()
    assert all(not p or p in {"README.md", "docs/phases/INDEX_ZH.md"} or p.startswith(phase + "/") for p in raw_paths)
    return {
        "status": "COMPLETE_NO_GO_REAL_TRIGGER_GATE_NOT_ADMITTED",
        "independent_live_questions": 8, "verified_policy_terminal_count": terminal_count,
        "physical_generated_trajectories": 16, "live_trigger_count": 0,
        "official_key_correct": dict(correct), "main_physical_forward_work": dict(physical),
        "post_score_label_conflict_case": label["case_id"],
        "evidence_sha256": {key: digest(path) for key, path in paths.items()},
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("lab", "source-shard", "author-scorer", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    result = audit(args.lab, args.source_shard, args.author_scorer)
    with args.output.open("xb") as stream:
        stream.write((json.dumps(result, indent=2) + "\n").encode())
    print(result["status"], result["official_key_correct"])


if __name__ == "__main__":
    main()
