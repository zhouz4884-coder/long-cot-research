"""Validate the p165 and p94 preserving controls against their exact checked targets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from p159_identity_audit import collect, parse_output
from p159_prepare_reviewed import ROOT, digest, need
from p159_run_reviewed import SUITES


def summarize(suite, raw, source_raw):
    source, observed = json.loads(source_raw), json.loads(raw)
    need(suite in {"p165", "p94"} and digest(source_raw) == SUITES[suite][1]
         and observed["source_receipt_sha256"] == digest(source_raw)
         and observed["author_pins"] == source["author_pins"] and observed["runtime_verified"] is True,
         "Runtime records are not bound to reviewed source and exact environment")
    if suite == "p165":
        namespace, target = "P165Bad", "p165_target"
        exact_names = ("a_cubed", "a_value", "b_cubed", "b_value", target)
        before_names = ("a_value", "b_cubed", "b_value")
        preserved_names = exact_names
        paths = ("p165_author_rescan_exact_check.lean", "p165_author_bound_check.lean",
                 "p165_initial_three.lean", "p165_preserved_transplant.lean")
        archived = source["author_archived_check_axioms"]
        preserved_count = 3
    else:
        namespace, target = "P94Bad", "p94_target"
        exact_names = ("product_bound_wrong", target)
        before_names = ("product_bound_wrong",)
        preserved_names = ("product_bound_wrong", "product_bound_expanded", target)
        paths = ("p94_author_exact_check.lean", "p94_author_bound_check.lean",
                 "p94_qwen_helper_only.lean", "p94_preserving_bridge.lean")
        archived = {target: source["deepseek_target_author_axioms"]}
        preserved_count = 1
    need(set(observed["cases"]) == set(paths) == set(source["prepared_fixtures"]), "Unexpected fixture case membership")
    all_cases = {}
    for path, names in zip(paths, (exact_names, exact_names, before_names, preserved_names), strict=True):
        case = observed["cases"][path]
        need(case["source_sha256"] == source["prepared_fixtures"][path]["sha256"], "Fixture readback hash differs")
        data = parse_output(case["stdout"])
        errors = [m["data"] for m in data if m.get("severity") in {"warning", "error"}]
        accepted = case["returncode"] == 0 and not errors and not case["stderr"].strip()
        qualified = tuple(f"{namespace}.{n}" for n in names)
        axioms, _ = collect(data, qualified, identities=False) if accepted else ({}, {})
        type_lines = [m["data"] for m in data if m["data"].startswith(f"{namespace}.{target} : ")]
        if accepted and path in {paths[1], paths[3]}:
            need(len(type_lines) == 1, "The bound target type check did not emit its elaborated type")
        all_cases[path] = {"source_sha256": case["source_sha256"], "returncode": case["returncode"],
                           "accepted": accepted, "errors_or_warnings": errors,
                           "axioms": axioms, "target_type_print": type_lines[0] if len(type_lines) == 1 else None}
    exact, bound, before, preserved = (all_cases[path] for path in paths)
    original_accepted = exact["accepted"] and bound["accepted"]
    prior_verified = before["accepted"]
    match_type = bool(bound["target_type_print"]) and bound["target_type_print"] == preserved["target_type_print"]
    if original_accepted:
        need(exact["axioms"] == bound["axioms"] and all(exact["axioms"][f"{namespace}.{key}"] == val
                                                      for key, val in archived.items()),
             "Author exact axiom closure differs")
    if prior_verified and suite == "p94":
        need(before["axioms"][f"{namespace}.product_bound_wrong"] == source["qwen_helper_author_axioms"],
             "Prior proved helper has changed axiom closure")
    same_prior_axioms = bool(prior_verified and preserved["accepted"] and
                            all(preserved["axioms"][key] == val for key, val in before["axioms"].items()))
    accepted_preservation = original_accepted and prior_verified and preserved["accepted"] and match_type
    return {"status": "SAME_TARGET_PRESERVATION_KERNEL_ACCEPTED" if accepted_preservation else "PRESERVING_CONTROL_UNRESOLVED",
            "scope": "Functional proof checks only. p165 is a same-author-source three-body splice. p94 is an auditor-constructed cross-episode bridge.",
            "suite": suite, "source_receipt_sha256": digest(source_raw), "runtime_observation_sha256": digest(raw),
            "same_author_pins": observed["author_pins"], "author_exact_accepted": original_accepted,
            "prior_proofs_independently_accepted": prior_verified, "same_explicit_target_type": match_type,
            "preserved_prior_axiom_sets_equal": same_prior_axioms,
            "prior_verified_declarations_preserved_in_same_target_certificate": preserved_count if accepted_preservation else None,
            "verified_prior_cells_released": 0 if accepted_preservation else None,
            "model_generation": False, "cases": all_cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("p165", "p94"))
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.suite, args.observed.read_bytes(), (ROOT / SUITES[args.suite][0]).read_bytes())
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    with args.output.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"status": result["status"], "suite": args.suite, "receipt_sha256": digest(payload)}))
