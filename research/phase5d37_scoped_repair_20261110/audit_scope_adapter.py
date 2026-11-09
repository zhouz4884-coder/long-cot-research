"""Compare new and old semantic authority on the fixed D3.6 event frame."""

from collections import Counter
import json

from freeze_scope_regressions import D36, ROOT, from_baseline, sha
from rebuild_scope_inventory import write_once
from scope_adapter import ClaimScope, classify_scope, permits_existing_action
from scoped_obligation import FrozenEventInventory, ScopedPointGate
from witness_contract import compile_contract


def load(name):
    return json.loads((ROOT / name).read_bytes())


def point_admission(expected, got):
    return f"expected_{'eligible' if expected else 'withhold'}__new_{'eligible' if got else 'withhold'}"


def run():
    manifest = (ROOT / "scope_event_inventory.json").read_bytes()
    frozen_events = FrozenEventInventory(manifest)
    inventory = json.loads(manifest)
    review = load("scope_review_labels.json")
    if sha(manifest) != review["source_inventory_sha256"]:
        raise ValueError("Development scope labels are bound to a different event frame")
    refs = {item: group["expected_scope"] for group in review["groups"] for item in group["event_ids"]}
    if len(refs) != 451 or len(refs) != sum(len(group["event_ids"]) for group in review["groups"]):
        raise ValueError("The development reference does not cover all distinct events")
    packet = json.loads(from_baseline(D36 / "prepared/early_checkpoint.json"))
    contract = compile_contract(packet["question"])
    freeze = json.loads(from_baseline(D36 / "D36_EXPERIMENT_FREEZE.json"))
    kwargs = {"point_budget": freeze["primary_point_budget"], "work_budget": freeze["arithmetic_work_budget"]}
    gates = {}
    pairs, roles, old_actions, scoped_actions = Counter(), Counter(), Counter(), Counter()
    rows = []
    for event in inventory["events"]:
        key = event["trajectory"]
        if key not in gates:
            gates[key] = ScopedPointGate(contract, frozen_events, **kwargs)
        result = gates[key].step(event["id"])
        current = ClaimScope(result["role"])
        reference = ClaimScope(refs[event["id"]])
        pairs[point_admission(reference.admits_point_check, current.admits_point_check)] += 1
        roles[f"{reference.role}->{current.role}"] += 1
        scoped_actions[result["authority"]] += 1
        record = {"event_id": event["id"], "expected_scope": reference.role, "role": current.role,
                  "point_check_eligible": current.admits_point_check, "authority": result["authority"],
                  "new_point": result["point"], "new_witness": result["witness"],
                  "v2_terminal_veto": event["v2_terminal_veto"], "v2_feedback": event["v2_feedback"],
                  "v2_action": event["v2_action"]}
        if event["v2_feedback"] or event["v2_terminal_veto"]:
            if event["v2_action"] == "KEEP_BOUND":
                disposition = "NO_NEW_PROOF_OBLIGATION"
            elif not permits_existing_action(current, event["v2_action"]):
                disposition = "WITHHELD_SCOPE_UNRESOLVED" if current.role.startswith("UNKNOWN") else "WITHHELD_OUTSIDE_AUTHORITY"
            else:
                mapping = {"UPDATE_BOUND": "RAISE_FEASIBLE_BOUND_ONLY", "BLOCK_REGRESSION": "REFUTE_GLOBAL_MAXIMUM",
                           "REPAIR_INFEASIBLE": "REFUTE_FEASIBILITY_ONLY"}
                disposition = ("REPROVED_WITH_NEW_AUTHORITY" if result["authority"] == mapping[event["v2_action"]]
                               else "NOT_REPROVED_AT_OBSERVED_EVENT")
            record["previous_action_disposition"] = disposition
            old_actions[disposition] += 1
        rows.append(record)
    challenge = []
    for case in load("scope_challenge.json")["cases"]:
        role = classify_scope(case["text"], case["phase"], case["value"],
                              terminal_committed=case.get("terminal_committed", True)).role
        challenge.append({"id": case["id"], "expected": case["label"], "actual": role, "matches": role == case["label"]})
    regressions = []
    by_id = {r["event_id"]: r for r in rows}
    for example in load("scope_regressions.json")["fixtures"]:
        event, = (e for e in inventory["events"] if e["observed_prefix_sha256"] == example["observed_prefix_sha256"]
                  and e["source_span"] == example["source_span"] and e["phase"] == example["phase"]
                  and e["value"] == example["value"] and example["input"].endswith("/" + e["trajectory"] + ".json"))
        row = by_id[event["id"]]
        regressions.append({"fixture": example["id"], "event": event["id"], "role": row["role"],
                            "scope_matches": row["role"] == example["expected_scope"],
                            "v2_action": row["v2_action"], "new_authority": row["authority"]})
    positive_count = sum(ClaimScope(role).admits_point_check for role in refs.values())
    eligible = sum(row["point_check_eligible"] for row in rows)
    correctly_admitted = pairs[point_admission(True, True)]
    report = {"scope": "Offline fixed-frame scope and certificate comparison only. Labels cover development roles, not mathematical correctness, and were visible to adapter development. Replayed events came from old trajectories; feedback was not re-generated.",
              "event_count": len(rows), "old_point_events": inventory["event_count"], "new_point_eligible": eligible,
              "point_eligible_recall": [correctly_admitted, positive_count], "point_acceptance": [eligible, len(rows)],
              "point_false_authorization": [pairs[point_admission(False, True)], len(rows) - positive_count],
              "point_scope_confusion": dict(pairs), "role_confusion": dict(roles), "scoped_authority": dict(scoped_actions),
              "recorded_feedback": sum(bool(r["v2_feedback"]) for r in rows),
              "recorded_vetoes": sum(bool(r["v2_terminal_veto"]) for r in rows),
              "unique_previous_feedback_or_veto_disposition": dict(old_actions),
              "synthetic_challenge": challenge, "selected_real_regressions": regressions,
              "new_budgeted_point_calls": sum(g.checker.report()["point_calls"] for g in gates.values()),
              "new_budgeted_arithmetic_operations": sum(g.checker.report()["paid_operations"] for g in gates.values()),
              "rows": rows}
    write_once(ROOT / "scope_replay_audit.json", report)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "role_confusion", "synthetic_challenge"}}, indent=2))
