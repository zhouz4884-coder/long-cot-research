"""Exercise the online interfaces on exact historical prefixes and adverse controls."""

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from audit_dev_checkpoints import D3, make_tokenizer, observed_view
from bounded_witness_search import replay_search, search_witness
from development_worker import e15_plan, prior_exact, typed_gate
from witness_contract import check_candidate, check_claim_witness, compile_contract
from witness_verifier import OBSERVED, OFFLINE, ONLINE, Witness


ROOT = Path(__file__).resolve().parent
FIXTURES = {
    "E12": ("last_live_before_close", "before_parameters_control"),
    "E15": ("after_reasserted_maximum", "before_observed_larger_candidate_control"),
    "P02": ("first_live_after_selected_lift_claim", "before_134_control"),
    "E14": ("after_renewed_universal", "before_observed_pair_control"),
    "E06": ("last_live_before_close", "before_45_control"),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def choose(gate, kind, *, value=None):
    return next((item for item in reversed(gate.records) if item.goal_claim_type == kind
                 and (value is None or item.value == value)), None)


def proof_summary(result):
    return {key: result.get(key) for key in ("status", "action", "reason", "witness", "released_value", "certificate_sha256",
                                             "proof_scope", "paid_check_count", "mathematical") if key in result}


def main():
    runtime_files = ("candidate_archive.py", "goal_claim_detector.py", "witness_contract.py", "witness_verifier.py",
                     "bounded_witness_search.py", "development_worker.py", "prepare_checkpoints.py")
    source_sha256 = {name: sha((ROOT / name).read_bytes()) for name in runtime_files}
    tokenizer = make_tokenizer()
    engine = SimpleNamespace(tokenizer=tokenizer)
    tokenizer_path = ROOT.parents[1] / "outputs/d2_tokenizer_20261107/tokenizer.json"
    identity = SimpleNamespace(tokenizer_sha256=sha(tokenizer_path.read_bytes()))
    table = json.loads((ROOT / "D35_DEV_CHECKPOINTS.json").read_bytes())
    rows, controls = [], []

    def test(case, name, actual, expected, action="NONE"):
        status = actual if isinstance(actual, str) else actual["status"]
        permit = actual.get("action", "NONE") if isinstance(actual, dict) else "NONE"
        controls.append({"case": case, "control": name, "actual": status, "expected": expected, "action": permit,
                         "passed": status == expected and permit == action})

    for case, (window, previous) in FIXTURES.items():
        later = observed_view(tokenizer, table, case, window)
        earlier = observed_view(tokenizer, table, case, previous)
        gate = typed_gate(later, engine, identity, later["observed_generated_ids"])
        before = typed_gate(earlier, engine, identity, earlier["observed_generated_ids"])
        contract = gate.contract
        row = {"case": case, "window": window, "prefix_sha256": gate.prefix.prefix_sha256,
               "early_control_window": previous, "template": contract.template_id,
               "observed_objects": len(gate.records), "typed_objects": dict(Counter(x.goal_claim_type for x in gate.records)),
               "detection_seconds": gate.extract_seconds, "real_trigger": False, "legal_revision": False}
        direct = search_witness(contract, budget=300_000, purpose="SOLVE")
        row["same_tool_direct_baseline"] = {**proof_summary(direct), "receipt_replayed": replay_search(contract, direct)}
        forged_contract = replace(contract, goal="INVALID_OBJECTIVE")
        test(case, "wrong_objective_contract", check_candidate(forged_contract, 1), "UNKNOWN")
        test(case, "missing_original_statement", "UNKNOWN" if compile_contract(later["question"][:-15]) is None else "COMPILED", "UNKNOWN")

        if case == "E12":
            candidate, exact = prior_exact(gate)
            row["prior_observed_candidate"] = candidate.as_dict()
            row["actual_certificate"] = proof_summary(exact)
            # Replaying already written final tokens is a separate post-draft
            # development check. Its result never becomes a GPU launch input.
            raw = json.loads((D3 / table["cases"][case]["source_result_path"]).read_bytes())
            if sha((D3 / table["cases"][case]["source_result_path"]).read_bytes()) != later["source_result_sha256"]:
                raise ValueError("Historical source changed")
            draft = typed_gate(later, engine, identity, raw["generated_ids"])
            revision = choose(draft, "FINAL_ANSWER_REVISION")
            original = next((x for x in draft.records if x.candidate_id == candidate.candidate_id), None)
            gated = draft.verify(revision.candidate_id, Witness(OBSERVED, original.candidate_id)) if revision and original else None
            row["observed_final_draft_arbitration"] = None if gated is None else proof_summary(gated)
            row["real_trigger"] = revision is not None
            row["legal_revision"] = gated is not None and gated["action"] == "VETO_DRAFT_AND_DELIVER_CERTIFIED"
            test(case, "future_claim_before_original_parameters", before.verify(candidate.candidate_id), "UNKNOWN")
            test(case, "offline_certificate_cannot_revise", draft.verify(revision.candidate_id, Witness(OFFLINE)), "UNKNOWN")
            test(case, "wrong_sequence_parameter", check_candidate(contract, {**candidate.assignments, "d": 1, "answer": 45}), "INVALID_CANDIDATE")
            test(case, "incomplete_sequence_parameters", check_candidate(contract, {"answer": candidate.value}), "UNKNOWN")

        elif case == "E15":
            packet = json.loads((ROOT / "prepared/e15_checkpoint.json").read_bytes())
            plan = e15_plan(gate, packet, tokenizer)
            claim = gate.archive.validated(plan["incumbent_id"], gate.prefix)
            row["real_trigger"], row["legal_revision"] = True, plan["verdict"]["action"] == "RETRACT_EXTREMUM_ONLY"
            row["observed_dominance"] = proof_summary(plan["verdict"])
            row["source_bound_cuts"] = {key: plan[key] for key in ("scope_cut", "generic_cut", "scope_cut_discards_witness_source")}
            test(case, "future_larger_candidate", before.verify(claim.candidate_id, Witness(OBSERVED, plan["witness_id"])), "UNKNOWN")
            test(case, "known_larger_number_is_not_a_licensed_offline_input", gate.verify(claim.candidate_id, Witness(OFFLINE)), "UNKNOWN")
            test(case, "larger_but_digit_rule_invalid", check_claim_witness(contract, claim.claim, 99999999), "INVALID_COUNTEREXAMPLE")
            test(case, "wrong_extremum_direction", check_claim_witness(contract, {"kind": "MIN", "value": claim.value}, plan["witness"]), "UNKNOWN")

        else:
            kind = "MINIMALITY_CLAIM" if case == "P02" else "UNIVERSAL_CLAIM"
            claim = choose(gate, kind)
            row["real_trigger"] = claim is not None
            if claim is None:
                rows.append(row)
                continue
            row["source_claim"] = claim.as_dict()
            if case == "P02":
                small = search_witness(contract, claim.claim, budget=64)
                searched = search_witness(contract, claim.claim, budget=1_000)
                result = gate.verify(claim.candidate_id, Witness(ONLINE, search_receipt=searched))
                row["bounded_online_search"] = searched
                row["candidate_feasibility"] = proof_summary(gate.verify(choose(gate, "FEASIBLE_CANDIDATE", value=claim.value).candidate_id,
                                                                        prerequisite=searched.get("prerequisite"))) if choose(gate, "FEASIBLE_CANDIDATE", value=claim.value) else None
                test(case, "bounded_search_exhaustion", gate.verify(claim.candidate_id, Witness(ONLINE, search_receipt=small)), "UNKNOWN")
                test(case, "explicit_offline_origin", gate.verify(claim.candidate_id, Witness(OFFLINE, search_receipt=searched)), "UNKNOWN")
                test(case, "tampered_search_result", gate.verify(claim.candidate_id, Witness(ONLINE, search_receipt={**searched, "witness": {"p": 17, "m": 1}})), "UNKNOWN")
                test(case, "wrong_prime_domain", check_claim_witness(contract, claim.claim, {"p": 13, "m": 1}, prerequisite=searched.get("prerequisite")), "INVALID_COUNTEREXAMPLE")
                test(case, "missing_least_prime_proof", check_claim_witness(contract, claim.claim, searched.get("witness")), "UNKNOWN")
                complete = choose(gate, "COMPLETE_SOLUTIONS_CLAIM")
                if complete is not None:
                    cert = search_witness(contract, complete.claim, budget=1_000)
                    row["completeness_refutation"] = proof_summary(gate.verify(complete.candidate_id, Witness(ONLINE, search_receipt=cert)))
            else:
                wanted = {"pair": [16, 18]} if case == "E14" else {"n": 45}
                point = choose(gate, "FEASIBLE_CANDIDATE", value=wanted)
                if point is None:
                    rows.append(row)
                    continue
                result = gate.verify(claim.candidate_id, Witness(OBSERVED, point.candidate_id))
                row["observed_point"] = point.as_dict()
                test(case, "out_of_domain_point", check_claim_witness(contract, claim.claim, {"pair": [16, 31]} if case == "E14" else {"n": 1001}), "INVALID_COUNTEREXAMPLE")
                test(case, "pseudo_counterexample_satisfies_claim", check_claim_witness(contract, claim.claim, {"pair": [23, 29]} if case == "E14" else {"n": 25}), "INVALID_COUNTEREXAMPLE")
                test(case, "future_point_source", before.verify(claim.candidate_id, Witness(OBSERVED, point.candidate_id)), "UNKNOWN")
            row["actual_arbitration"] = proof_summary(result)
            row["legal_revision"] = result["action"] in ("RETRACT_EXTREMUM_ONLY", "RETRACT_CLAIM_ONLY")
        rows.append(row)
    native = [json.loads(line) for line in (D3 / "prepared_data/bank/visible.jsonl").read_bytes().splitlines()]
    compiled = [item["case_id"] for item in native if compile_contract(item["question"]) is not None]
    if source_sha256 != {name: sha((ROOT / name).read_bytes()) for name in runtime_files}:
        raise ValueError("The implementation changed during the CPU replay")
    passed = (len(rows) == 5 and all(row["real_trigger"] and row["legal_revision"] for row in rows)
              and all(control["passed"] for control in controls))
    audit = {"status": "PASS" if passed else "FAIL", "scope": "Historical selected development windows; no new accuracy or population trigger estimate",
             "contract_compilation": {"selected_development": [len(rows), 5], "historical_formal_problem_bank": [len(compiled), len(native)],
                                      "matched_source_ids": compiled}, "real_automatic_triggers": sum(row["real_trigger"] for row in rows),
             "legally_admitted_actions": sum(row["legal_revision"] for row in rows),
             "adverse_controls_passed": sum(x["passed"] for x in controls), "adverse_controls_total": len(controls),
             "rows": rows, "controls": controls, "additional_GPU_seconds": 0, "source_sha256": source_sha256}
    (ROOT / "OFFLINE_DEVELOPMENT_AUDIT.json").write_bytes((json.dumps(audit, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({**{k: v for k, v in audit.items() if k not in ("rows", "controls")},
                      "admissions": [[row["case"], row["real_trigger"], row["legal_revision"]] for row in rows],
                      "failed_controls": [x for x in controls if not x["passed"]]}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
