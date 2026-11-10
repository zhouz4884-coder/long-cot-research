"""Run D4.6 source custody and exact point controls on three old development traces."""
from __future__ import annotations

import argparse
from dataclasses import replace
from fractions import Fraction
from math import gcd, isqrt
import json
from pathlib import Path
import re
import subprocess
from time import perf_counter_ns, thread_time_ns

from extract_d46_points import BOUND, RULES_SHA, digest, extract_row, load_author_scorer, observation, require, write_exclusive
from point_verifier import (
    ASSERTED_ORIGINAL_CANDIDATE, EXACT_CONTRADICTION, PROVEN_INFEASIBLE, UNKNOWN,
    CandidateReceipt, ObjectiveBinding, PointEvidence, PointVerifier, ReviewedPointContract,
    WorkMeter, checker_source_sha256, exact_literal,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
D45 = HERE.parent / "phase5d45_feasible_witness_20261110"
BASE = "efedfee0bb10ffbb778cec05f7e778622f404970"
BLIND = REPO / "outputs" / "d45_aime_source_20261110" / "d45_gold_blind_trajectories.json"
AUTHOR = REPO / "outputs" / "d43_aime_source_20261110" / "aime_scorer.py"
SELECTED = {"2020-I-10:draw-03", "2021-II-13:draw-07", "2010-I-14:draw-02"}
ALIASES = {"2020-I-10": [r"m\s*\+\s*n", r"sum of m and n"],
           "2021-II-13": [r"(?:positive integer )?n", r"(?:valid )?index"],
           "2010-I-14": [r"(?:positive integer )?n", r"(?:valid )?index"]}
OLD_INDEX_ASSERTION = re.compile(r"(?i)\bn\s*=\s*(?P<value>[0-9]+)\s+is the least positive integer\.")
PINNED_EXTRA = {"D45_CLAIM_READOUT_FREEZE.json": "0d826046686b427434e27304bde07ad253cea3645ae9f947af0d0ca790429bb5",
                "D45_SCOPE_SENSITIVITY_AUDIT.json": "7c8ad12b990ccab3f58098b077ed299c40c3d84ad7d45567555004ef036527ae",
                "D45_SCOPE_SENSITIVITY_READOUT.json": "037ff68f6f9b2c86a81c1a52f7a016c50165d77868e2a7645d30954ce848cd3f"}


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def inputs(blind_path):
    base = json.loads((HERE / "D46_BASELINE_FREEZE.json").read_bytes())
    require(base["baseline_commit"] == BASE and {r["case_id"] for r in base["development_only"]} == set(ALIASES),
            "Unapproved development scope")
    cohort_raw = (HERE / "D46_COHORT_FREEZE.json").read_bytes()
    cohort = json.loads(cohort_raw)
    require(len(cohort["rows"]) == 11 and not ({row["case_id"] for row in cohort["rows"]} & set(ALIASES)),
            "Older development cases overlap the heldout cohort")
    source, hashes = {}, {}
    for name, expected in {**base["d45_evidence_sha256"], **PINNED_EXTRA}.items():
        path = D45 / name
        raw = subprocess.check_output(["git", "show", f"{BASE}:{path.relative_to(REPO).as_posix()}"], cwd=REPO, timeout=15)
        require(digest(raw) == expected and path.read_bytes() == raw, f"Published {name} differs")
        hashes[name] = expected
        if name not in {"D45_RESULTS.json", "D45_DELIVERY_AUDIT.json"}:
            source[name] = json.loads(raw)
    blind_raw = blind_path.read_bytes()
    strict = source["D45_CLAIM_READOUT_FREEZE.json"]
    require(digest(blind_raw) == strict["blind_input_sha256"], "Wrong old label-blind projection")
    blind = json.loads(blind_raw)
    require(blind["cohort_freeze_sha256"] == hashes["D45_COHORT_FREEZE.json"], "Old trace cohort changed")
    samples = {r["sample_id"]: r for r in blind["rows"] if r["sample_id"] in SELECTED}
    require(set(samples) == SELECTED, "Old development traces are incomplete")
    old_cases = {r["case_id"]: r for r in source["D45_COHORT_FREEZE.json"]["rows"] if r["case_id"] in ALIASES}
    for sample in samples.values():
        case = old_cases[sample["problem_id"]]
        frozen, = (r for r in case["draws"] if r["draw_index"] == sample["draw_index"])
        require(all(sample[key] == frozen[key] for key in ("sample_id", "seed", "response_sha256")), "Old response identity differs")
    return source, samples, old_cases, {"baseline_commit": BASE, "published_d45_sha256": hashes,
                                        "old_blind_projection_sha256": digest(blind_raw),
                                        "heldout_identity_only_sha256": digest(cohort_raw), "heldout_disjoint": True}


def prime_sum(binding, value, meter):
    require(binding.objective_id == "minimum-power-divisibility-sum", "Wrong old point checker dispatch")
    meter.charge("integer_comparison")
    if value.denominator != 1 or value.numerator <= 2:
        return PointEvidence(UNKNOWN)
    s = value.numerator
    meter.charge("integer_square_root")
    limit = isqrt(s)
    remainders = []
    for d in range(2, limit + 1):
        meter.charge("integer_remainder")
        meter.charge("integer_nonzero_comparison")
        r = s % d
        if r == 0:
            return PointEvidence(UNKNOWN)
        remainders.append(str(r))
    meter.charge("exclusion_proof")
    return PointEvidence(PROVEN_INFEASIBLE, EXACT_CONTRADICTION,
                         (("prime_sum", s), ("trial_limit", limit), ("trial_remainders", ",".join(remainders)),
                          ("proof", "A prime divisor of n>1 also divides m and hence prime m+n, impossible with n<m+n. n=1 violates nondivisibility.")),
                         True, ("positive_pair", "power_divisibility", "ordinary_nondivisibility"))


def modular_index(binding, value, meter):
    require(binding.objective_id == "minimum-modular-sequence-index", "Wrong old point checker dispatch")
    meter.charge("integer_comparison")
    if value.denominator != 1 or value.numerator < 3:
        return PointEvidence(UNKNOWN)
    n = value.numerator
    meter.charge("integer_addition")
    meter.charge("integer_remainder")
    meter.charge("integer_comparison")
    if (n + 3) % 100:
        return PointEvidence(UNKNOWN)
    meter.charge("integer_remainder")
    residue = n % 125
    meter.charge("integer_multiplication")
    meter.charge("integer_remainder")
    meter.charge("integer_comparison")
    scaled = (8 * residue) % 125
    if scaled == 1:
        return PointEvidence(UNKNOWN)
    meter.charge("exclusion_proof")
    return PointEvidence(PROVEN_INFEASIBLE, EXACT_CONTRADICTION,
                         (("n_mod125", residue), ("eight_n_mod125", scaled), ("necessary_scaled_residue", 1),
                          ("proof", "For n>=3 the 5-power vanishes modulo 125. Euler gives 2^100=1, so 8*2^n=1 when n+3 is a multiple of 100.")),
                         True, ("positive_n", "residue_zero"))


def contract_for(case, checker, prior_diagnostic):
    binding = ObjectiveBinding(case["question_sha256"], case["objective_id"],
                               canonical({k: case[k] for k in ("direction", "objective_id", "description")}),
                               canonical(case["constraints"]), case["direction"])
    return ReviewedPointContract(binding, tuple(case["constraints"]), "d46.old-development", 1,
                                 checker.__name__, checker_source_sha256(checker), EXACT_CONTRADICTION,
                                 canonical(prior_diagnostic["proof"] if "proof" in prior_diagnostic else
                                           "Original congruence modulo 125, Euler period and exact residual."),
                                 canonical(prior_diagnostic))


def bind_strict(contract, sample, late, prefix, old_readout):
    require(late["status"] == BOUND and late["value"] == 23 and late["assertion_role"] == ASSERTED_ORIGINAL_CANDIDATE,
            "Old asserted sum no longer binds in strict mode")
    a, b = late["assertion_span"]
    # Independent development role check on the exact source span, never on other trace text.
    require(re.fullmatch(r"(?i)\s*the least possible value of \$\s*m\s*\+\s*n\s*\$ is \\boxed\{23\}", prefix[a:b])
            and old_readout["late"]["value"] == 23 and old_readout["late"]["observation_prefix_sha256"] == digest(prefix.encode()),
            "Old asserted sum lacks exact original-object corroboration")
    review = {"basis": "D46 independent old-span role check and D45 strict receipt", "sample_id": sample["sample_id"],
              "old_declared_span_sha256": old_readout["late"]["source_excerpt_sha256"],
              "assertion_sha256": late["assertion_sha256"], "prefix_sha256": late["observation_prefix_sha256"]}
    return CandidateReceipt(contract.binding, sample["sample_id"], sample["response_sha256"], late["observation_prefix_sha256"],
                            tuple(late["numeric_span"]), late["numeric_text"], (a, b), late["assertion_sha256"],
                            ASSERTED_ORIGINAL_CANDIDATE, canonical(review)), review


def bind_prior_review(contract, sample, late, prefix, scope_audit, scope_readout):
    require(late["status"] == "LATER_UNSCOPED_BOX" and late["value"] is None,
            "Keep the old-index corroboration separate from strict scope")
    audited, = (r for r in scope_audit["rows"] if r["job_id"] == sample["sample_id"] + "@late")
    reviewed, = (r["late"] for r in scope_readout["rows"] if r["sample_id"] == sample["sample_id"])
    require(audited["decision"] == "BOUND" and audited["reason"] == "FINAL_FIRST_VALID_INDEX" and audited["value"] == 397
            and reviewed["evidence_source"] == "GOLD_BLIND_SCOPE_SENSITIVITY_ONLY" and reviewed["value"] == 397
            and audited["source_box_sha256"] == late["source_excerpt_sha256"] == reviewed["source_excerpt_sha256"]
            and audited["observation_prefix_sha256"] == late["observation_prefix_sha256"] == digest(prefix.encode()),
            "The old blind review does not corroborate this observed box")
    box_start = late["char_span_in_response"][0] - late["observation_char_span_in_response"][0]
    matches = list(OLD_INDEX_ASSERTION.finditer(prefix, max(0, box_start - 1000), box_start))
    require(bool(matches), "Old scope verdict has no located explicit original-index assertion")
    match = matches[-1]
    require(exact_literal(match["value"]) == 397, "Old explicit index differs from its reviewed box")
    return CandidateReceipt(contract.binding, sample["sample_id"], sample["response_sha256"], late["observation_prefix_sha256"],
                            match.span("value"), match["value"], match.span(), digest(match[0].encode()),
                            ASSERTED_ORIGINAL_CANDIDATE, audited["review_output_sha256"]), {
                                "basis": "D45 frozen gold-blind role review, development only", "job_id": audited["job_id"],
                                "review_reason": audited["reason"], "review_output_sha256": audited["review_output_sha256"],
                                "reviewed_box_sha256": audited["source_box_sha256"]}


def verifier_for(contract, checker, candidate, *, permit=True, work=256):
    return PointVerifier(contract, contract.sha256, checker, approved_candidate_sha256=(candidate.sha256,) if permit else (),
                         call_budget=1, work_budget=work)


def point_profile(contract, checker, candidate, prefix):
    verifier = verifier_for(contract, checker, candidate)
    result = verifier.check(candidate, prefix)
    require(result.status == PROVEN_INFEASIBLE and verifier.authorizes_exclusion(candidate, result), "Old point must reject exactly")
    start, cpu = perf_counter_ns(), thread_time_ns()
    repetitions, batch = 0, 128
    value = exact_literal(candidate.numeric_text)
    while repetitions < 16384 and thread_time_ns() - cpu < 31_250_000:
        count = min(batch, 16384 - repetitions)
        for _ in range(count):
            meter = WorkMeter(256)
            require(checker(contract.binding, value, meter) == result.evidence
                    and tuple(meter._charges.items()) == result.operation_charges, "Repeated arithmetic evidence differs")
        repetitions += count
        batch *= 2
    return result.as_dict(), {"repetitions": repetitions, "thread_cpu_ns": thread_time_ns() - cpu,
                              "wall_ns": perf_counter_ns() - start,
                              "scope": "Exact arithmetic plus repeat consistency only. Separate from the single full verifier receipt."}


def ordinary_checks():
    start, cpu = perf_counter_ns(), thread_time_ns()
    outcomes = [gcd(n, 23 - n) for n in range(2, 23)]
    require(all(g == 1 for g in outcomes), "Independent fixed-sum check found a shared prime")
    sum_check = {"fixed_positive_pairs_considered": 22, "unit_n_rejections": 1, "gcd_calls": 21,
                 "feasible_pairs": 0, "wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}
    start, cpu = perf_counter_ns(), thread_time_ns()
    first, second = pow(2, 397, 1000), pow(5, 397, 1000)
    residual = (first + second - 397) % 1000
    require((first, second, residual) == (672, 125, 400), "Independent full-modulus proof differs")
    return {"2020-I-10": sum_check, "2021-II-13": {"modular_power_calls": 2, "residual": residual,
            "wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}}


def adversaries(scorer, old_cases, contract, checker, candidate, prefix):
    controls = []
    examples = (("incomplete_comparison", "The maximum n <=", "2010-I-14"),
                ("equality_threshold_not_input", "The maximum n where f(n) = 300.", "2010-I-14"),
                ("wrong_original_object", "The least m is 23.", "2020-I-10"),
                ("function_value_not_index", "The least f(n) is 397.", "2021-II-13"),
                ("malformed_sign", "The least n is --397.", "2021-II-13"))
    for name, text, cid in examples:
        start, cpu = perf_counter_ns(), thread_time_ns()
        readout = observation(scorer, text, 0, {**old_cases[cid], "subject_patterns": ALIASES[cid]}, 3000, True)
        require(readout["status"] != BOUND and readout["value"] is None, "Malformed or wrong-scope text was authorized")
        controls.append({"control": name, "status": readout["status"], "synthetic_source_sha256": digest(text.encode()),
                         "candidate_issued": False, "checker_calls": 0, "work": 0,
                         "wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu})
    wrong_constraints = replace(contract.binding, constraints_sha256=canonical(["positive_pair", "power_divisibility"]))
    for name, forged, expected, supplied in (
        ("changed_constraints", replace(candidate, binding=wrong_constraints), "ORIGINAL_BINDING_MISMATCH", prefix),
        ("changed_objective", replace(candidate, binding=replace(contract.binding, objective_id="minimum-m")),
         "ORIGINAL_BINDING_MISMATCH", prefix),
        ("changed_numeric_symbol", replace(candidate, numeric_text="24"), "ASSERTION_OR_NUMERIC_SPAN_MISMATCH", prefix),
        ("changed_prefix", candidate, "OBSERVED_PREFIX_MISMATCH", prefix + " "),
    ):
        verifier = verifier_for(contract, checker, forged)
        outcome = verifier.check(forged, supplied)
        require(outcome.status == UNKNOWN and outcome.reason == expected and outcome.checker_calls == outcome.work == 0
                and not verifier.authorizes_exclusion(forged, outcome), "Adversarial custody control was not fail-closed")
        controls.append({"control": name, **outcome.as_dict()})
    return controls


def run(blind_path, author_path):
    source, samples, old_cases, hashes = inputs(blind_path)
    rule_raw = (HERE / "D46_OBSERVATION_RULES.json").read_bytes()
    require(digest(rule_raw) == RULES_SHA, "D46 rules changed")
    rules = json.loads(rule_raw)
    scorer = load_author_scorer(author_path)
    diagnostics = source["D45_POSTSCORE_DIAGNOSTICS.json"]
    old_strict = {r["sample_id"]: r for r in source["D45_CLAIM_READOUT_FREEZE.json"]["rows"] if r["sample_id"] in SELECTED}
    old_diag = {r["sample_id"]: r for r in diagnostics["true_persistent_wrong_candidates"]}
    controls = []
    for sample_id in sorted(SELECTED):
        sample = samples[sample_id]
        cid = sample["problem_id"]
        case = {**old_cases[cid], "subject_patterns": ALIASES[cid]}
        start, cpu = perf_counter_ns(), thread_time_ns()
        readout = extract_row(scorer, sample, case, rules)
        readout_timing = {"wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}
        require(all(readout[when]["observation_prefix_sha256"] == old_strict[sample_id][when]["observation_prefix_sha256"]
                    for when in ("early", "late")), "D46 replay changes an old observation coordinate")
        common = {"sample_id": sample_id, "question_sha256": case["question_sha256"], "response_sha256": sample["response_sha256"],
                  "strict_readout": {key: readout[key] for key in ("early", "late", "termination", "final", "native_final_eligible")},
                  "binding_elapsed": readout_timing, "paid_historical_input_tokens": readout["input_tokens"],
                  "paid_historical_output_tokens": readout["output_tokens"]}
        if cid == "2010-I-14":
            prior = diagnostics["early_false_binding"]
            lo, hi = prior["span"]
            require(sample_id == prior["sample_id"] and digest(sample["response"][lo:hi].encode()) == prior["source_excerpt_sha256"]
                    and readout["early"]["value"] is None and readout["early"]["status"] != BOUND,
                    "The old threshold became a D46 point")
            controls.append({**common, "status": "THRESHOLD_REJECTED_AT_BINDING", "candidate_issued": False,
                             "checker_calls": 0, "work": 0, "old_threshold_span": prior["span"],
                             "old_threshold_excerpt_sha256": prior["source_excerpt_sha256"]})
            continue
        late = readout["late"]
        lo, hi = late["observation_char_span_in_response"]
        prefix = sample["response"][lo:hi]
        checker = prime_sum if cid == "2020-I-10" else modular_index
        contract = contract_for(case, checker, old_diag[sample_id])
        if cid == "2020-I-10":
            candidate, review = bind_strict(contract, sample, late, prefix, old_strict[sample_id])
            route = "D46_STRICT_ACTUAL_OLD_SCOPE"
            negative = adversaries(scorer, old_cases, contract, checker, candidate, prefix)
        else:
            candidate, review = bind_prior_review(contract, sample, late, prefix, source["D45_SCOPE_SENSITIVITY_AUDIT.json"],
                                                  source["D45_SCOPE_SENSITIVITY_READOUT.json"])
            route = "D45_INDEPENDENT_BLIND_ROLE_REVIEW_ONLY"
        checked, profile = point_profile(contract, checker, candidate, prefix)
        controls.append({**common, "status": "OLD_BOUND_POINT_REFUTED", "binding_route": route, "role_review": review,
                         "candidate_issued": True, "point_receipt": checked, "batch_cpu_profile": profile})
    return {"status": "PASS_D46_ACTUAL_OLD_DEVELOPMENT_CALIBRATION", "sources": hashes,
            "observation_rules_sha256": RULES_SHA,
            "extractor_sha256": digest((HERE / "extract_d46_points.py").read_bytes()),
            "point_verifier_sha256": digest((HERE / "point_verifier.py").read_bytes()),
            "calibration_code_sha256": digest(Path(__file__).read_bytes()), "controls": controls,
            "adversarial_controls": negative, "ordinary_same_point_controls": ordinary_checks(),
            "counts": {"old_cases": 3, "strict_old_positive": 1, "prior_blind_review_positive": 1,
                       "threshold_without_candidate_or_call": 1, "adversarial_controls_without_call": len(negative)},
            "scope": "Old development only. No fresh heldout trace, label, new model tokens or gate contribution. The 397 role is prior independently reviewed sensitivity, not a D46 strict binding."}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--old-blind", type=Path, default=BLIND)
    cli.add_argument("--author-scorer", type=Path, default=AUTHOR)
    cli.add_argument("--output", type=Path, default=HERE / "D46_DEVELOPMENT_CALIBRATION.json")
    args = cli.parse_args()
    require(not args.output.exists(), "Refuse to overwrite calibration")
    report = run(args.old_blind, args.author_scorer)
    write_exclusive(args.output, report)
    print(json.dumps({"status": report["status"], "sha256": digest(args.output.read_bytes()), "counts": report["counts"]}))
