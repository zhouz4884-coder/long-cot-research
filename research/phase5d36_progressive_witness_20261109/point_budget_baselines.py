"""Compare bounded black-box point proposals with a separate complete solver."""

from itertools import islice
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from point_verifier import PointVerifier
from prepare_d36_checkpoints import FREEZE, ROOT, prepare, sha, write_once

D35 = ROOT.parent / "phase5d35_witness_gated_revision_20261109"
sys.path.append(str(D35))
from audit_dev_checkpoints import TOKENIZER, make_tokenizer
from bounded_witness_search import replay_search, search_witness
from wcpr_worker import observed_plan, source_prefix
from witness_contract import compile_contract


def proposal_order(observed):
    """Try observed values, then decimal extension from an observed large value."""
    distinct = sorted(set(observed), reverse=True)
    yield from distinct
    anchor = distinct[0]
    for offset in range(32):
        base = anchor + offset
        yield base * 10 + 9


def run_tools_only(contract, observed, budget, work):
    checker = PointVerifier(contract, point_budget=budget, work_budget=work)
    results = []
    for value in islice(proposal_order(observed), budget):
        result = checker.check(value)
        results.append({"value": value, "point": result.as_dict()})
    best = max((r["value"] for r in results if r["point"]["status"] == "CERTIFIED_FEASIBLE"), default=None)
    return {"candidate_proposals": results, "best_feasible": best,
            "complete_goal_certificate": False, "cost": checker.report(), "model_input_tokens": 0}


def run():
    prepare()
    freeze = json.loads(FREEZE.read_bytes())
    tokenizer = make_tokenizer()
    engine = SimpleNamespace(tokenizer=tokenizer)
    identity = SimpleNamespace(tokenizer_sha256=sha((TOKENIZER / "tokenizer.json").read_bytes()))
    arms = {}
    for checkpoint in freeze["checkpoints"]:
        packet = json.loads((ROOT / "prepared" / f"{checkpoint}_checkpoint.json").read_bytes())
        contract = compile_contract(packet["question"])
        prefix = source_prefix(engine, identity, packet, packet["generated_ids"], f"d36_{checkpoint}_tool_baseline")
        compared = observed_plan(prefix, contract)
        observed = (compared.left, compared.right)
        arms[checkpoint] = {"observed": observed, "comparison_source": compared.source_span.as_dict(),
                            "budgets": {str(k): run_tools_only(contract, observed, k, freeze["arithmetic_work_budget"])
                                        for k in freeze["point_budgets"]}}
    complete = search_witness(contract, budget=20_000, purpose="SOLVE")
    if not replay_search(contract, complete):
        raise ValueError("The separate full solver failed its receipt replay")
    report = {"scope": "CPU historical development. Tool-only proposals have the two observed values and the point API, and do not consult full solutions or Gold. Best feasible is not certified globally optimal.",
              "checkpoints": arms, "separate_unrestricted_solver": complete, "model_input_tokens": 0}
    target = ROOT / "D36_POINT_BASELINES.json"
    if target.exists():
        old = json.loads(target.read_bytes())
        for payload in (old, report):
            for arm in payload["checkpoints"].values():
                for result in arm["budgets"].values():
                    result["cost"].pop("point_check_seconds")
        if old != report:
            raise ValueError("Non-timing baseline fields do not replay")
        return json.loads(target.read_bytes())
    write_once(target, report)
    return report


if __name__ == "__main__":
    result = run()
    for checkpoint, row in result["checkpoints"].items():
        print(checkpoint, [(k, x["best_feasible"], x["cost"]["point_calls"]) for k, x in row["budgets"].items()])
    complete = result["separate_unrestricted_solver"]
    print(complete["status"], complete["certified_value"], complete["paid_check_count"])
