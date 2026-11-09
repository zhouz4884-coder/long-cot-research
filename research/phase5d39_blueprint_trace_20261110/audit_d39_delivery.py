"""Reconcile the full corpus with the same-version preservation and cost receipts."""

import hashlib
import json
from pathlib import Path
import subprocess

from audit_corpus_totals import require, run as recount_corpus


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BASE = "df460b430f8ec792af69b896edc5aa9f958a90a8"


def load(name):
    return json.loads((ROOT / name).read_bytes())


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def preserving_suite(name, retained):
    proof = load(f"p159_{name}_kernel_receipt.json")
    require(proof["status"] == "SAME_TARGET_PRESERVATION_KERNEL_ACCEPTED" and proof["same_explicit_target_type"] and
            proof["author_exact_accepted"] and proof["prior_proofs_independently_accepted"] and
            proof["prior_verified_declarations_preserved_in_same_target_certificate"] == retained and
            proof["verified_prior_cells_released"] == 0, "A primary same-target preservation control is missing")
    require(proof["source_receipt_sha256"] == digest(f"p159_{name}_source_receipt.json") and
            proof["runtime_observation_sha256"] == digest(f"p159_{name}_runtime_observed.json"), "Primary proof receipt source differs")
    return proof


def run():
    old = ("research/phase5d25_constraint_revision_20261109", "research/phase5d35_witness_gated_revision_20261109",
           "research/phase5d36_progressive_witness_20261109", "research/phase5d37_scoped_repair_20261110",
           "research/phase5d38_proof_release_20261110")
    subprocess.run(["git", "diff", "--exit-code", BASE, "--", *old], cwd=REPO, check=True)
    corpus = recount_corpus()
    nominations = load("corpus_replay_nomination.json")
    require(nominations["gate_sha256"] == digest("D39_REPLAY_GATE.json") and
            nominations["corpus_inventory_sha256"] == corpus["inventory_sha256"], "Nomination source changed")
    order = [row["state_id"] for row in nominations["nominations_in_lexical_target_order"]]
    require(order[:2] == ["p94_bad.state0", "p165_bad.state0"] and len(order) == 4 and
            nominations["positive_minimum_release_certificates"] == 0, "Archive selection or necessity count differs")
    smoke, source, tool = (load(f"author_runtime_{name}.json") for name in ("smoke", "sources", "toolchain"))
    require(smoke["status"] == "PASS_MATCHED_AUTHOR_IMPORT_POSITIVE" and len(source["packages"]) == 10 and
            source["author"]["verified_materialized_blobs"] == 939 and smoke["cache"]["packed_count"] == 8542 and
            smoke["runtime"]["runtime_files_sha256"] == tool["runtime_files_sha256"], "Exact author runtime receipts are incomplete")
    p159 = load("p159_identity_receipt.json")
    require(p159["status"] == "PASS" and len(p159["preserved_declarations"]) == 3 and
            p159["verified_original_proof_cells_released"] == 0 and
            p159["source_receipt_sha256"] == digest("p159_reviewed_source_receipt.json") and
            p159["approved_runtime_observation_sha256"] == digest("p159_p159_runtime_observed.json"),
            "The mandatory p159 same-environment counterexample is missing")
    probes = load("p159_closure_probe_receipt.json")
    require(probes["freeze_sha256"] == digest("p159_closure_probe_freeze.json"), "Trusted dependency probe freeze differs")
    primary = {}
    for name, retained in (("p94", 1), ("p165", 3)):
        proof = preserving_suite(name, retained)
        used = probes["cases"][name]
        require(used["returncode"] == 0 and used["all_preserved_nodes_actually_in_target_local_closure"] and
                len(used["target_paths_to_preserved_declared_nodes"]) == retained and
                used["base_source_receipt_sha256"] == proof["source_receipt_sha256"], "Compiled preservation scope differs")
        primary[name] = {"full_target_verified": True, "proved_cells_retained_and_used": retained,
                         "verified_cells_released": 0, "target_proof_paths": used["target_paths_to_preserved_declared_nodes"]}
    supplemental = load("supplement_runtime_observed.json")
    require(supplemental["source_receipt_sha256"] == digest("supplement_source_receipt.json"), "Supplement source changed")
    p82 = supplemental["results"]["supplement_p82_preserved_transport.lean"]
    p30 = supplemental["results"]["supplement_p30_preserved_direct.lean"]
    retry = load("supplement_inverse_retry_observed.json")
    require(all(row["status"] == "VERIFIED" and row["matches_author_elaborated_target_type"] and
                row["protected_source_preserved"] for row in (p82, p30)) and p82["protected_declaration_actually_used"] and
            not p30["protected_declaration_actually_used"], "The supplemental source controls are incomplete")
    require(retry["status"] == "PASS" and retry["protected_source_preserved"] and retry["protected_declaration_actually_used"] and
            retry["target_type"] == p30["target_type"] and retry["retry_source_receipt_sha256"] == digest("supplement_inverse_retry_source.json"),
            "The clean p30 actual-use retry does not match the same target")
    cost = load("p159_replay_cost_results.json")
    require(cost["status"] == "PASS" and cost["all_statuses_match"] and len(cost["cold"]) == len(cost["resident"]) == 3 and
            cost["new_gpu_seconds"] == cost["new_model_tokens"] == 0 and cost["source_review_receipt_sha256"] ==
            p159["source_receipt_sha256"], "Pinned p159 cost comparison is missing")
    files = ["D39_EVIDENCE_INPUTS.json", "D39_SOURCE_LICENSES.json", "D39_REPLAY_GATE.json", "D39_SUPPLEMENT_FREEZE.json",
             "corpus_freeze.json", "corpus_inventory.json", "corpus_summary.json", "corpus_replay_nomination.json",
             "D39_CORPUS_VALIDATION.json", "author_runtime_toolchain.json", "author_runtime_sources.json",
             "author_runtime_smoke.json", "p159_reviewed_source_receipt.json", "p159_identity_receipt.json",
             "p159_p159_runtime_observed.json", "p159_p94_source_receipt.json", "p159_p165_source_receipt.json",
             "p159_p94_runtime_observed.json", "p159_p165_runtime_observed.json", "p159_p94_kernel_receipt.json",
             "p159_p165_kernel_receipt.json", "p159_closure_probe_freeze.json", "p159_closure_probe_receipt.json",
             "supplement_source_receipt.json", "supplement_runtime_observed.json", "supplement_inverse_retry_source.json",
             "supplement_inverse_retry_observed.json", "p159_replay_cost_results.json"]
    report = {"status": "COMPLETE_NO_GO_CLOSE_MINIMUM_RELEASE_MAINLINE", "baseline_commit": BASE,
              "archive": {"independent_target_clusters": corpus["independent_target_clusters"], "episodes": corpus["episodes"],
                          "step_records": corpus["step_records"], "author_rescan_success": corpus["author_rescan_accepted_episodes"],
                          "positive_minimum_release_certificates": 0, "unresolved_dynamic_states": len(nominations["unresolved_states"])},
              "mandatory_negative": {"target": "p159", "verified_cells_released": 0, "retained_used_count": 3},
              "primary_nominated_targets": primary,
              "supplemental_nominated_targets": {"p82": "SAME_TARGET_PROTECTED_DECLARATION_RETAINED_AND_USED",
                                                  "p30": "SAME_TARGET_PROTECTED_DECLARATION_RETAINED_WITH_UNUSED_AND_USED_VARIANTS"},
              "independent_verified_required_release_cases": 0, "independent_model_test_denominator": 0,
              "model_tokens": 0, "gpu_seconds": 0,
              "cpu_cost": {"cold_three": cost["cold_total_seconds"], "resident_three_including_shutdown": cost["resident_total_including_shutdown_seconds"],
                           "one_author_batch": cost["local_cold_batch"]["elapsed_seconds"], "material_preparation": cost["material_preparation_seconds"]},
              "reason": "All four source-change nominations admit a same-target preserved proof in the matched author environment. Unknown states remain unknown. No independent baseline gap qualifies a model experiment.",
              "evidence_sha256": {name: digest(name) for name in files}}
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    destination = ROOT / "D39_DELIVERY_AUDIT.json"
    if destination.exists():
        require(destination.read_bytes() == raw, "The final D3.9 audit differs on replay")
    else:
        destination.write_bytes(raw)
    return report


if __name__ == "__main__":
    data = run()
    print(json.dumps({key: data[key] for key in ("status", "archive", "independent_verified_required_release_cases", "cpu_cost")}, indent=2))
