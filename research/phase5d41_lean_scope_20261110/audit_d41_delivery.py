"""Verify the archive counts, exact-scope controls and paired cost evidence."""

from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean
import subprocess


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BASE = "94fc3cf7be07c59db3db9bab55c7492712d5c746"
OLD = ("research/phase5d25_constraint_revision_20261109", "research/phase5d35_witness_gated_revision_20261109",
       "research/phase5d36_progressive_witness_20261109", "research/phase5d37_scoped_repair_20261110",
       "research/phase5d38_proof_release_20261110", "research/phase5d39_blueprint_trace_20261110",
       "research/phase5d40_proof_authoring_20261110")


def load(name):
    return json.loads((ROOT / name).read_bytes())


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inspect_pairs(name, queue, flags):
    data = load(name)
    require(data["queue_sha256"] == digest("D41_PAIRED_QUEUE_FREEZE.json") and data["server_flags"] == flags and
            data["new_model_tokens"] == data["gpu_seconds"] == 0, "Paired proof inputs or flags differ")
    expected_accept = ["ordinary_full_proof_control"]
    output = {}
    for case, report in data["per_case"].items():
        frozen = queue["cases"][case]
        runs = report["ordered_runs"]
        require([row["policy"] for row in runs] == frozen["sequence"] and not report["false_rejections"],
                "Paired sequence differs or filtered proof was falsely rejected")
        summaries = {}
        for policy in ("direct", "query_then_full"):
            rounds = [r for r in runs if r["policy"] == policy]
            require(len(rounds) == 2, "Repeated paired order is incomplete")
            for r in rounds:
                require([(row["id"], row["source_sha256"]) for row in r["rows"]] ==
                        [(row["id"], row["source_sha256"]) for row in frozen["inputs"]], "A matched proof input changed")
                require([row["id"] for row in r["rows"] if row["status"] == "KERNEL_ACCEPTED"] == expected_accept,
                        "A passing proof was lost or another appeared")
                require(r["rows"][0]["status"] == "REJECTED", "An exact historical negative was skipped or accepted")
                if policy == "direct":
                    require(not r["queries"] and r["rows"][1]["status"] == "REJECTED", "Direct proof pass is not complete")
                else:
                    require(len(r["queries"]) == 1 and not r["queries"][0]["available"] and
                            r["rows"][1]["status"] == "SKIPPED_MANDATORY_UNAVAILABLE", "Unbound or incorrect hard skip")
            summaries[policy] = {"wall_seconds_each": [r["elapsed_seconds"] for r in rounds],
                                 "wall_seconds_mean": mean(r["elapsed_seconds"] for r in rounds)}
        if not flags:
            require(report["existing_exact_retrieval"]["status"] == "REJECTED", "Existing exact? result differs")
        output[case] = {**summaries, "matching_accepted_count": 1, "historical_hard_skips": 0,
                        "synthetic_hard_skips": 2, "false_rejections": 0}
    return output


def run():
    subprocess.run(["git", "diff", "--exit-code", BASE, "--", *OLD], cwd=REPO, check=True)
    freeze = load("D41_SCOPE_INPUT_FREEZE.json")
    require(len(freeze["unresolved_state_ids"]) == 11 and len(freeze["same_family_solved_state_ids"]) == 20,
            "Frozen target cohort differs")
    summary = load("diagnostic_summary.json")
    episodes = [json.loads(line) for line in (ROOT / "diagnostic_ledger.jsonl").read_bytes().splitlines()]
    require(digest("diagnostic_ledger.jsonl") in json.dumps(summary), "Archive ledger is not bound by its summary")
    invocations = [inv for episode in episodes for step in episode["attempts"] for inv in step["invocations"]]
    require(len(episodes) == 186 and len(invocations) == 1128, "Archive invocation denominator differs")
    calls = Counter()
    for row in invocations:
        for diagnostic in row["diagnostics"]:
            calls[diagnostic["severity"]] += 1
    require(sum(calls.values()) == 4283 and calls["error"] == 3317, "Archived diagnostic denominator differs")
    component = load("scope_runtime_results.json")
    require(component["status"] == "PASS_TRUSTED_RUNTIME" and component["matched"] == component["controls"] == 102 and
            component["material_hashes"]["input_freeze"] == digest("D41_SCOPE_INPUT_FREEZE.json"),
            "Runtime component controls did not match their freeze")
    queue = load("D41_PAIRED_QUEUE_FREEZE.json")
    default = inspect_pairs("paired_reference_default_results.json", queue, [])
    zero = inspect_pairs("paired_reference_zero_delay_results.json", queue, ["-Dserver.reportDelayMs=0"])
    upper = load("upper_bound_full_proof_results.json")
    require(upper["freeze_sha256"] == digest("D41_UPPER_FULL_PROOF_FREEZE.json") and
            [r["status"] for r in upper["rows"]] == ["KERNEL_ACCEPTED", "REJECTED", "KERNEL_ACCEPTED"],
            "Broader import proof controls differ")
    authored = load("scope_cases_authored_runtime.json")
    require(authored["controls_sha256"] == digest("scope_cases_controls.json") and authored["controls"] == 19,
            "Authored safety control set differs")
    unsafe_naive = [case for context in authored["contexts"].values()
                    for case in context["would_be_false_rejections_if_import_only_test_were_a_hard_gate"]]
    historical = load("scope_cases_historical_runtime.json")
    require(historical["supplement_sha256"] == digest("scope_cases_historical_supplement.json") and
            set(historical["cases"]) == {"p104", "p115", "p139"}, "Historical source sample differs")
    actual_negatives = []
    historical_costs = {}
    for case, row in historical["cases"].items():
        exact = [result for name, result in row["results"].items() if name.endswith("_negative.lean")]
        if case == "p115":
            require(not exact, "Conditional p115 proof was not authorized for a full replay")
        else:
            require(len(exact) == 1 and exact[0]["status"] == "REJECTED", "A real source negative was not reproduced")
            actual_negatives.append(case)
            query = row["results"][f"{case}_same_scope_queries.lean"]
            require(query["status"] == "REJECTED" and not row["estimated_hard_skip_or_speedup"],
                    "A diagnostic query was mislabeled as successful or a simulated skip")
            historical_costs[case] = {"full_failed_check_seconds": exact[0]["elapsed_seconds"],
                                      "relative_and_root_query_seconds": query["elapsed_seconds"]}
    evidence = ("D41_SCOPE_INPUT_FREEZE.json", "D41_REPLAY_AND_COST_PROTOCOL.json", "D41_PAIRED_QUEUE_FREEZE.json",
                "D41_RESIDENT_DELAY_SENSITIVITY.json", "D41_RETRIEVAL_CONTROL_FREEZE.json", "D41_UPPER_FULL_PROOF_FREEZE.json",
                "diagnostic_freeze.json", "diagnostic_ledger.jsonl", "diagnostic_summary.json", "diagnostic_singleton_sites.json",
                "scope_runtime_freeze.json", "scope_runtime_results.json", "paired_reference_default_results.json",
                "paired_reference_zero_delay_results.json", "upper_bound_full_proof_results.json", "scope_cases_controls.json",
                "scope_cases_evidence.json", "scope_cases_authored_runtime.json", "scope_cases_historical_supplement.json",
                "scope_cases_historical_runtime.json")
    result = {"status": "COMPLETE_NO_GO_SCOPE_PREFILTER_NOT_ADMITTED", "baseline": BASE,
              "archive": {"independent_targets": 31, "invocations": len(invocations), "messages": sum(calls.values()),
                          "errors": calls["error"]}, "runtime_component_controls": component["matched"],
              "resident_paired_default": default, "resident_paired_zero_delay": zero,
              "actual_historical_negative_replays": sorted(actual_negatives), "historical_negative_only_costs": historical_costs,
              "p115_historical_full_replay_deferred": True,
              "authored_controls": {"total": authored["controls"], "expected_matches": authored["all_expected_matches"],
                                     "kernel_accepted": authored["kernel_accepted"], "naive_import_only_false_rejections": sorted(unsafe_naive)},
              "qualifying_independent_historical_targets": 0, "model_tokens": 0, "gpu_seconds": 0,
              "reason": "Exact scope is useful evidence for candidate diagnosis. Existing Lean lookup plus remaining full checks has no stable measured end-to-end increment here. The negative-only historical supplements do not establish a qualifying proof-search gain; import-only gates can reject well-typed local-context proofs.",
              "evidence_sha256": {name: digest(name) for name in evidence}}
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    path = ROOT / "D41_DELIVERY_AUDIT.json"
    if path.exists():
        require(path.read_bytes() == raw, "D4.1 delivery audit differs on replay")
    else:
        path.write_bytes(raw)
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: result[key] for key in ("status", "archive", "runtime_component_controls",
                                                 "actual_historical_negative_replays", "authored_controls",
                                                 "qualifying_independent_historical_targets")}, indent=2))
