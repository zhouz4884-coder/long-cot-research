"""Independent CPU-authored arithmetic controls, not upstream proof retrieval."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
sys.path.append(str(D39))
from author_runtime_setup import PROJECT, clean_env
from lean_resident_probe import ResidentLean
from measure_p159_replay_cost import check_environment


SOURCE_RECEIPT_SHA256 = "ed36404c9cdf405cc6b0ccb71daf0b915d6bfed6691aa21db04168ff9fa3dc1c"
IMPORTS = {
    "p14": ("Architect", "Mathlib.Tactic.Ring", "Mathlib.Tactic.Linarith", "Mathlib.Tactic.NormNum",
            "Mathlib.Tactic.LinearCombination"),
    "p41": ("Architect", "Mathlib.Tactic.Ring", "Mathlib.Tactic.Linarith", "Mathlib.Tactic.NormNum"),
    "p138": ("Architect", "Mathlib"),
}
EXPECTED = {
    "p14": "∀ n : ℕ, (11 : ℤ) ∣ ((10 : ℤ)^n - (-1 : ℤ)^n)",
    "p41": "∀ n : ℕ, 0 < n → 9 ∣ (10 : ℕ)^n - 1",
    "p138": "∀ a : ℕ, a = (∑ k ∈ Nat.divisors 500, k) → (∑ k ∈ Finset.filter (fun x => Nat.Prime x) (Nat.divisors a), k) = 25",
}


P14_FACTOR = """(10 : ℤ)^(n + 1) - (-1 : ℤ)^(n + 1) =
    10 * ((10 : ℤ)^n - (-1 : ℤ)^n) + 11 * (-1 : ℤ)^n"""
P14_INDUCTION = """  induction n with
  | zero => norm_num
  | succ n ih =>
    rcases ih with ⟨q, hq⟩
    refine ⟨10 * q + (-1 : ℤ)^n, ?_⟩
    rw [FACTOR, hq]
    ring"""
P41_GROWTH_TYPE = "∀ m : ℕ, ∃ q : ℕ, (10 : ℕ)^m = 9 * q + 1"
P41_GROWTH_PROOF = """  intro m
  induction m with
  | zero => exact ⟨0, by norm_num⟩
  | succ m ih =>
    rcases ih with ⟨q, hq⟩
    refine ⟨10 * q + 1, ?_⟩
    rw [pow_succ, hq]
    ring"""
P41_FINISH = """  rcases GROWTH n with ⟨q, hq⟩
  refine ⟨q, ?_⟩
  omega"""


def indent(text, count):
    return "\n".join(" " * count + line for line in text.splitlines())


def p14():
    factor_type = "theorem d40_p14_factor (n : ℕ) : " + P14_FACTOR
    split = factor_type + " := by\n  rw [pow_succ, pow_succ]\n  ring\n"
    inline = P14_INDUCTION.replace("    rw [FACTOR, hq]", "    have factor : " + P14_FACTOR.replace("\n    ", "\n        ") +
                                   " := by\n      rw [pow_succ, pow_succ]\n      ring\n    rw [factor, hq]")
    return [("direct_library_specialization", "", "  exact sub_dvd_pow_sub_pow (10 : ℤ) (-1 : ℤ) n"),
            ("ordinary_inline_induction", "", inline),
            ("ordinary_one_auxiliary_split", split, P14_INDUCTION.replace("FACTOR", "d40_p14_factor"))]


def p41(*, use_positive_binder=False):
    split = "theorem d40_p41_growth : " + P41_GROWTH_TYPE + " := by\n" + P41_GROWTH_PROOF + "\n"
    finish = P41_FINISH
    suffix = ""
    if use_positive_binder:
        finish = ("  cases n with\n  | zero => exact False.elim (Nat.lt_irrefl 0 h₀)\n  | succ n =>\n"
                  + indent(P41_FINISH.replace("GROWTH n with", "GROWTH (n + 1) with"), 2))
        suffix = "_use_positive_binder"
    inline = ("  have growth : " + P41_GROWTH_TYPE + " := by\n" + indent(P41_GROWTH_PROOF, 2) + "\n"
              + finish.replace("GROWTH", "growth"))
    return [("direct_library_specialization", "", "  exact Nat.sub_one_dvd_pow_sub_one 10 n"),
            ("ordinary_inline_induction" + suffix, "", inline),
            ("ordinary_one_auxiliary_split" + suffix, split, finish.replace("GROWTH", "d40_p41_growth"))]


def p138():
    inline = ("  have sum_divisors : (∑ k ∈ Nat.divisors 500, k) = 1092 := by decide\n"
              "  have value : a = 1092 := h₀.trans sum_divisors\n  subst a\n  decide")
    split = "theorem d40_p138_sum : (∑ k ∈ Nat.divisors 500, k) = 1092 := by decide\n"
    return [("direct_bounded_decide", "", "  subst a\n  decide"),
            ("ordinary_inline_arithmetic_split", "", inline),
            ("ordinary_one_auxiliary_split", split, "  have value : a = 1092 := h₀.trans d40_p138_sum\n  subst a\n  decide")]


PROPOSALS = {"p14": p14, "p41": p41, "p138": p138}


def retry_proposals(case):
    if case == "p41":
        return p41(use_positive_binder=True)[1:]
    if case == "p138":
        factor = """  have sum_divisors : (∑ k ∈ Nat.divisors 500, k) = 1092 := by decide
  have value : a = 1092 := h₀.trans sum_divisors
  subst a
  have filter_eq : (Nat.divisors 1092).filter Nat.Prime = (1092 : ℕ).primeFactors := by
    ext p
    simp [Nat.mem_divisors, Nat.mem_primeFactors, and_assoc, and_comm, and_left_comm]
  have factors : (1092 : ℕ).primeFactors = {2, 3, 7, 13} := by decide
  rw [filter_eq, factors]
  decide"""
        return p138() + [("ordinary_prime_factorization", "", factor)]
    raise ValueError("No retry was declared for this source")


def compile_source(case, slot, helper, tactic, *, retry=False):
    namespace = case.upper() + "Bad"
    original_annotation = f'@[blueprint "thm:{case}bad-target"]'
    options = "set_option warningAsError true\nset_option maxHeartbeats 200000\n"
    if retry and case == "p138":
        options += "set_option maxRecDepth 4096\n"
    source = slot.replace(f"namespace {namespace}\n", options + f"\nnamespace {namespace}\n", 1)
    source = source.replace("  d40_slot\n", tactic + "\n", 1)
    target = f"{namespace}.{case}_target"
    targets = [target]
    if helper:
        helper_name = helper.split()[1]
        annotated = f'@[blueprint "lem:{case}bad-d40-control"]\n' + helper + "\n"
        annotated += f'@[blueprint "thm:{case}bad-target" (proofUses := [{helper_name}])]'
        source = source.replace(original_annotation, annotated, 1)
        targets.append(namespace + "." + helper_name)
    source += f"\n#check ({target} : {EXPECTED[case]})\n"
    source += "".join(f"#print axioms {name}\n" for name in targets)
    return source, targets


def run(lean, lake, project, input_path, slots, output, *, retry=False):
    # This packet is emitted only from reviewed archive source and includes no proof bodies.
    packet_raw = input_path.read_bytes()
    packet = json.loads(packet_raw)
    if hashlib.sha256(packet_raw).hexdigest() != SOURCE_RECEIPT_SHA256 or packet["status"] != "ARCHIVE_BOUND_TARGET_SLOTS_ONLY":
        raise ValueError("Review receipt differs from the pinned source-slot review")
    binding = json.loads((D39 / "D39_EVIDENCE_INPUTS.json").read_bytes())
    version = check_environment(lean, lake, project, binding)
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env["PATH"]
    command = [str(lake), "env", str(lean)]
    rows = {}
    with tempfile.TemporaryDirectory(prefix="d40_expert_", dir=project) as directory:
        for case in ("p41", "p138") if retry else PROPOSALS:
            inputs = packet["source_cases"][case]
            header = inputs["exact_target_header"]
            imports = tuple(inputs["exact_imports"])
            spec = inputs["local_slot"]["author_target_slot"]
            if spec["name"] != f"{case}_author_target_slot.lean" or imports != IMPORTS[case]:
                raise ValueError("Named slot or import scope differs")
            raw = (slots / spec["name"]).read_bytes()
            namespace = case.upper() + "Bad"
            exact = ("".join(f"import {name}\n" for name in imports) + f"\nnamespace {namespace}\n\n"
                     + f'@[blueprint "thm:{case}bad-target"]\n' + header + f" := by\n  d40_slot\n\nend {namespace}\n")
            if raw != exact.encode() or len(raw) != spec["bytes"] or hashlib.sha256(raw).hexdigest() != spec["sha256"]:
                raise ValueError("Target slot is not the exact reviewed inert template")
            lean_server = ResidentLean(command, project, timeout=100, env=env)
            results = []
            try:
                candidates = retry_proposals(case) if retry else PROPOSALS[case]()
                for method, helper, tactic in candidates:
                    source, targets = compile_source(case, exact, helper, tactic, retry=retry)
                    result = lean_server.check(Path(directory) / f"{case}_control.lean", source, targets)
                    results.append({"method": method, "source": source, **result})
            finally:
                began = time.perf_counter()
                lean_server.close()
                shutdown = time.perf_counter() - began
            rows[case] = {"imports": imports, "startup_seconds": lean_server.startup_seconds,
                          "shutdown_seconds": shutdown, "attempts": results}
            print(case, [(row["method"], row["status"]) for row in results], flush=True)
    report = {"status": "COMPLETE_CPU_AUTHORED_CONTROLS", "scope": "Actual independent ordinary arithmetic proofs in matched imports. Expert designs are offline controls, not new model generations or a candidate discovery algorithm.",
              "lean_version": version, "input_sha256": hashlib.sha256(packet_raw).hexdigest(), "per_case": rows,
              "retry": retry, "retry_freeze_sha256": hashlib.sha256((ROOT / "D40_EXPERT_RETRY_FREEZE.json").read_bytes()).hexdigest() if retry else None,
              "new_model_tokens": 0, "gpu_seconds": 0}
    with output.open("xb") as out:
        out.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("lean", "lake", "inputs", "slots", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    run(args.lean.resolve(), args.lake.resolve(), PROJECT.resolve(), args.inputs, args.slots, args.output, retry=args.retry)
