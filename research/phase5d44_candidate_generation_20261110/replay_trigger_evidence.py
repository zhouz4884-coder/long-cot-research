"""Replay the exact D4.4 trigger at observed box closures in authorized blind archive text."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from obligation_trigger import BOX, SCOPE_PATTERNS, detect, digest

HERE = Path(__file__).resolve().parent
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
CASES = {
    "2012-I-4": "FIRST_EVENT",
    "2009-II-12": "EXTREMUM",
    "2018-II-14": "SCOPE_CONTROL",
    "2013-II-11": "SCOPE_CONTROL",
    "2017-I-3": "SCOPE_CONTROL",
    "2023-II-2": "EXTREMUM",
}
ACTIVE_DEVELOPMENT = {"2012-I-4", "2009-II-12"}


def load(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def evidence_case(sample: dict, approved_rows: dict) -> dict:
    pid = sample["problem_id"]
    kind = CASES[pid]
    exact = digest(sample["problem"])
    row = approved_rows[pid]
    if exact != row["exact_question_sha256"]:
        raise ValueError("Archive problem changed from the reviewed question")
    items = row["approved_predicates"]
    item = None
    if kind != "SCOPE_CONTROL" and items:
        approved = items[0]
        proof, = (p for p in row["proposal_audit"] if p["source_sha256"] == approved["source_sha256"])
        item = {
            "question_sha256": exact, "kind": approved["kind"].lower(), "args": approved["args"],
            "review_sha256": approved["review_sha256"], "proof_sha256": proof["proof_sha256"],
            "scope_patterns": SCOPE_PATTERNS[pid],
            "cue": "Recheck the remaining mathematical obligation before settling the result.",
        }
    return {"case_id": pid, "question_sha256": exact, "problem_kind": kind, "obligation": item}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("historical-blind", "replication-blind", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    old, old_hash = load(args.historical_blind)
    extra, extra_hash = load(args.replication_blind)
    intake, _ = load(D43 / "D43_PILOT_INTAKE.json")
    readout, _ = load(HERE / "D44_READOUT_FREEZE.json")
    if old_hash != intake["blind_view_sha256"] or extra_hash != readout["blind_input_sha256"]:
        raise ValueError("Archive trigger replay requires the verified blind projections")
    proof, proof_hash = load(D43 / "D43_PREREQUISITE_FREEZE.json")
    reviewed = {row["problem_id"]: row for row in proof["rows"]}
    rows = []
    for sample in [*old["rows"], *extra["rows"]]:
        pid = sample["problem_id"]
        if pid not in CASES:
            continue
        text = sample["response"]
        if digest(text) != sample["response_sha256"]:
            raise ValueError("Observed archive text changed")
        case = evidence_case(sample, reviewed)
        thinking = text.partition("</think>")[0]
        if thinking.startswith("<think>"):
            thinking = thinking[len("<think>"):]
        checked, chosen = 0, None
        for match in BOX.finditer(thinking):
            prefix = thinking[:match.end()]
            checked += 1
            decision = detect(case, prefix)
            if decision:
                chosen = {key: value for key, value in decision.items() if key != "cue"}
                chosen["observation_char_end"] = len(prefix)
                chosen["observed_prefix_sha256"] = digest(prefix)
                break
        rows.append({
            "sample_id": sample["sample_id"], "problem_id": pid, "draw_index": sample["draw_index"],
            "problem_kind": case["problem_kind"], "response_sha256": sample["response_sha256"],
            "finish_reason": sample["finish_reason"], "box_closure_observations": checked,
            "historical_obligation_available": case["obligation"] is not None, "first_trigger": chosen,
        })
    if len(rows) != len(CASES) * 8 or len({r["sample_id"] for r in rows}) != len(rows):
        raise ValueError("Unexpected scope or count in the archive replay")
    triggers = Counter(row["problem_id"] for row in rows if row["first_trigger"])
    report = {
        "status": "HISTORICAL_PREFIX_TRIGGER_REPLAY",
        "scope": "String-prefix observations only; archived native token, RNG and KV state are unavailable.",
        "sources": {"historical_blind_sha256": old_hash, "replication_blind_sha256": extra_hash,
                    "approved_prerequisites_sha256": proof_hash,
                    "trigger_sha256": sha256((HERE / "obligation_trigger.py").read_bytes()).hexdigest()},
        "independent_development_problems_triggered": len(set(triggers) & ACTIVE_DEVELOPMENT),
        "triggers_by_problem": dict(triggers), "rows": rows,
        "cost": {"wall_ns": perf_counter_ns() - started_wall, "cpu_ns": thread_time_ns() - started_cpu},
    }
    with args.output.open("xb") as output:
        output.write((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())
    print(report["status"], report["independent_development_problems_triggered"], dict(triggers))


if __name__ == "__main__":
    main()
