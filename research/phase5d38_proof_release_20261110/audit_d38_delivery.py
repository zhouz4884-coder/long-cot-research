"""Check scoped proof receipts and the D3.8 model admission decision."""

from collections import Counter
import json
import subprocess

from run_structural_controls import FOUNDATIONAL_AXIOMS, ROOT, digest, load


BASELINE = "bfb4ae10533502fe1194768aaaa2fb56214ece1b"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def inspect_proof(record):
    require(digest(record["source"].encode()) == record["input_sha256"], "Lean source digest differs")
    if record["status"] == "KERNEL_ACCEPTED":
        require(record["accepted_axioms"] is not None and set(record["accepted_axioms"]) <= FOUNDATIONAL_AXIOMS,
                "Proof uses an axiom outside the trusted foundation")


def inspect_matrix(matrix, protocol, methods, *, corrected=False):
    require(matrix["status"] == "COMPLETE_SYNTHETIC_CPU_MATRIX" and matrix["synthetic_control_count"] == len(protocol["cases"]) == 8,
            "Structural proof controls are incomplete")
    require(matrix["input_freeze_sha256"] == digest((ROOT / "D38_STRUCTURAL_CONTROL_FREEZE.json").read_bytes()), "Frozen controls changed")
    if corrected:
        require(matrix["runner_sha256"] == digest((ROOT / "run_structural_controls.py").read_bytes()) and
                matrix["method_freeze_sha256"] == digest((ROOT / "D38_STRUCTURAL_V2_FREEZE.json").read_bytes()),
                "Corrected runner or method freeze differs")
    stats = {name: {"kernel_targets": 0, "calls": 0, "seconds": 0.0} for name in methods}
    certified, pruned = Counter(), 0
    require([row["case"] for row in matrix["rows"]] == [row["id"] for row in protocol["cases"]], "Case order differs")
    for row in matrix["rows"]:
        for proof, expected in ((row["offline_witness"], "KERNEL_ACCEPTED"), (row["protected_prefix"], "KERNEL_ACCEPTED"),
                                (row["original_rejected_draft"], "REJECTED")):
            inspect_proof(proof)
            require(proof["status"] == expected, "Source control differs from expected evidence")
        require(set(row["arms"]) == set(methods), "Missing experiment arm")
        for name, result in row["arms"].items():
            ledger = result["verifier_calls"]
            require(len(ledger) == result["calls"] <= protocol["verifier_calls_per_arm"], "Verifier-call budget violated")
            for item in ledger:
                inspect_proof(item)
            if result["accepted"]:
                accepted = [item for item in ledger if item["input_sha256"] == result["accepted_source_sha256"] and
                            item["status"] == "KERNEL_ACCEPTED" and item["stage"] != "prove_no_extension_with_locks"]
                require(len(accepted) == 1 and f": {row['target']} := by" in accepted[0]["source"], "Claimed target proof is missing")
            stats[name]["kernel_targets"] += int(result["accepted"])
            stats[name]["calls"] += result["calls"]
            stats[name]["seconds"] += result["end_to_end_seconds"] if corrected else result["total_seconds"]
            if name == "scoped_release":
                scopes = result["scopes"]
                pruned += sum(item.get("prior_certificate_pruned_candidates", 0) for item in scopes)
                if result["accepted"]:
                    release = len(result["released_slots"])
                    necessary = [s for s in scopes if len(s["release"]) < release]
                    require(len(necessary) == (0, 1, 3)[release] and all(s["status"] == "FIXED_SCOPE_CONTRADICTION" and
                            s["kernel_refutation"] == "KERNEL_ACCEPTED" for s in necessary), "Minimum release lacks a lower-scope proof")
                    require(scopes[-1]["minimal_release_certified"], "Minimum release flag absent")
                    certified[str(release)] += 1
    return {"arms": stats, "minimum_certificate_counts": dict(certified), "pruned_candidates": pruned}


def run():
    repo = ROOT.parents[1]
    subprocess.run(["git", "diff", "--exit-code", BASELINE, "--", "research/phase5d25_constraint_revision_20261109",
                    "research/phase5d35_witness_gated_revision_20261109", "research/phase5d36_progressive_witness_20261109",
                    "research/phase5d37_scoped_repair_20261110"], cwd=repo, check=True)
    protocol = load("D38_STRUCTURAL_CONTROL_FREEZE.json")
    v1 = inspect_matrix(load("structural_control_results.json"), protocol, protocol["arms"])
    corrected = load("D38_STRUCTURAL_V2_FREEZE.json")
    v2 = inspect_matrix(load("structural_control_v2_results.json"), protocol, corrected["arms"], corrected=True)
    require(v2["arms"]["scoped_release"]["kernel_targets"] == 7 and v2["pruned_candidates"] == 20 and
            v2["minimum_certificate_counts"] == {"0": 1, "1": 4, "2": 2}, "Corrected structural ledger differs")
    batched = load("batched_release_baseline_results.json")
    require(batched["status"] == "PASS" and batched["input_freeze_sha256"] == digest((ROOT / "D38_STRUCTURAL_CONTROL_FREEZE.json").read_bytes()),
            "Batched direct solver is not bound to the same controls")
    modes = {}
    for name in ("matched_finite_support", "whole_bounded_domain"):
        rows = [r for r in batched["rows"] if r["scope"] == name]
        require(len(rows) == 8 and [r["case"] for r in rows] == [r["id"] for r in protocol["cases"]], "Batched control set differs")
        accepted = [r for r in rows if r["status"] == "KERNEL_ACCEPTED"]
        for row in accepted:
            inspect_proof(row["kernel"])
            release = len(row["released_slots"])
            require(row["lean_calls"] == 1 and len(row["independently_refuted_smaller_lock_sets"]) == (0, 1, 3)[release],
                    "Batched proof lacks exact minimum scope")
        modes[name] = {"kernel_targets": len(accepted), "lean_calls": sum(r["lean_calls"] for r in rows),
                       "seconds": sum(r["end_to_end_seconds"] for r in rows)}
    require(modes["matched_finite_support"]["kernel_targets"] == 7 and modes["whole_bounded_domain"]["kernel_targets"] == 8,
            "Direct minimum-release controls do not support the same-target decision")
    for row in load("context_identity_results.json")["cases"]:
        inspect_proof(row["kernel"])
        require(row["matches"], "Context safety control failed")
    core, mathlib = load("lean_runtime_controls.json"), load("lean_runtime_benchmark_controls.json")
    require(core["status"] == mathlib["status"] == "PASS" and core["passed"] == core["total"] == 9 and
            len(mathlib["controls"]) == 10 and len(mathlib["source_identity"]["packages"]) == 10,
            "Runtime or benchmark dependency validation incomplete")
    intake, std = load("proof_intake_manifest.json"), load("proof_intake_std_kernel.json")
    require(intake["natural_public_statements_count"] == 12 and std["natural_source_proofs_checked"] == 3 and
            std["controlled_skip_mutations_rejected"] == 3 and intake["std_kernel_receipt_sha256"] ==
            digest((ROOT / "proof_intake_std_kernel.json").read_bytes()), "Public proof intake receipts disagree")
    proof = load("competition_residue_results.json")
    require(proof["status"] == "PASS" and not proof["first_attempt"]["kernel_accepted"] and
            proof["one_line_repair"]["kernel_accepted"], "Competition proof repair was not reproduced")
    traces = load("blueprint_trace_intake.json")
    require(len(traces["states"]) == 6 and traces["episodes_count"] == 36 and traces["model_attempts_count"] == 60,
            "External archived trajectories are incomplete")
    preservation = load("blueprint_trace_preservation.json")
    require(preservation["status"] == "THREE_INITIAL_PROVED_DECLARATIONS_RETAINED" and
            preservation["state_id"] == "p159_bad.state0" and len(preservation["verified_source_spans"]) == 3,
            "Archived prior proof preservation control is missing")
    files = ("D38_MODEL_ADMISSION.json", "D38_SOURCE_PROBE.json", "D38_STRUCTURAL_CONTROL_FREEZE.json",
             "D38_STRUCTURAL_V2_FREEZE.json", "lean_runtime_controls.json", "lean_runtime_benchmark_controls.json",
             "lean_runtime_benchmark_sources.json", "proof_intake_manifest.json", "proof_intake_std_kernel.json",
             "competition_residue_results.json", "context_identity_initial_results.json", "context_identity_results.json",
             "structural_control_results.json", "structural_control_v2_results.json", "batched_release_baseline_results.json",
             "prior_art_sources.json", "blueprint_trace_freeze.json", "blueprint_trace_intake.json",
             "blueprint_trace_preservation.json")
    result = {"status": "COMPLETE_CPU_ADMISSION_NO_GO", "baseline_commit": BASELINE,
              "structural_controls": {"v1": v1, "corrected": v2, "strong_direct_with_minimum_certificate": modes},
              "verified_runtime_controls": {"core": [9, 9], "official_miniF2F": [10, 10], "source_std_proofs": [3, 3]},
              "archived_provider_attempts": {"states": 6, "episodes": 36, "attempts": 60, "author_scope_only": True},
              "model_pilot_admitted": False, "independent_model_test_denominator": 0, "model_tokens": 0, "gpu_seconds": 0,
              "reason": "Kernel-checked minimum release is operational on eight synthetic controls. A strong bundled solver gives the same certificates under the matched support at lower work, and no source failure provides replicated increment over known typed/whole/local baselines.",
              "evidence_sha256": {name: digest((ROOT / name).read_bytes()) for name in files}}
    output = ROOT / "D38_DELIVERY_AUDIT.json"
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    if output.exists():
        require(output.read_bytes() == raw, "Delivery audit differs on replay")
    else:
        output.write_bytes(raw)
    return result


if __name__ == "__main__":
    data = run()
    print(json.dumps({k: data[k] for k in ("status", "verified_runtime_controls", "archived_provider_attempts", "model_pilot_admitted")}, indent=2))
