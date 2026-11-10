"""Exercise exact D4.7 delivery custody on the old feasible regression only."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
from time import perf_counter_ns, thread_time_ns

from extract_d47_delivery import RULES_SHA, final_point, prior, thinking_rules
from delivery_preservation import (
    ELIGIBLE_NATIVE_EOS, FINAL, KEEP_NATIVE, RETAIN_CERTIFIED_INCUMBENT, THINKING,
    DeliveryPreserver, DeliveryScope, Observation, PointCustody, naive_best_verified, point,
)
from d46_contracts import reconstruct
from d46_point_domains import check


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
D46 = HERE.parent / "phase5d46_point_infeasibility_20261110"
D45 = HERE.parent / "phase5d45_feasible_witness_20261110"
BASE = "97af21cfb0b8995a5cc50dbd82924da83e0a11d6"
REGRESSION_ID = "2017-II-5:draw-05"
THRESHOLD_ID = "2010-I-14:draw-02"
OLD46 = REPO / "outputs" / "d46_aime_source_20261110" / "d46_gold_blind_trajectories.json"
OLD45 = REPO / "outputs" / "d45_aime_source_20261110" / "d45_gold_blind_trajectories.json"
AUTHOR = REPO / "outputs" / "d43_aime_source_20261110" / "aime_scorer.py"
UNIT = "missing-edge-sum"
FINAL_ROLE = re.compile(r"(?is)\bx\s*\+\s*y\s*=\s*[0-9]+\s*\+\s*[0-9]+\s*=\s*"
                        r"\\boxed\{(?P<value>[0-9]+)\}\s*\$\$\s*[^\r\n]{0,100}?"
                        r"\bmaximum\b[^\r\n]{0,100}?\bx\s*\+\s*y\b[^\r\n]*\.")
D46_PINS = {"D46_CONTRACTS_FREEZE.json": "0aa9f4a1addb5db55728ee360d2bd66231dbcc39fa349ed18934652b0c5d1d56",
            "D46_CLAIM_READOUT_FREEZE.json": "5507d9055fc7cab5f2cbada859ad4cb2a4c8a9ac55b508e95702041d7a13cfaf",
            "D46_SCOPE_AUDIT.json": "6a954d5193a8730ec1b05c1b8058149bbd51a5a8563d3b498b42128c1463ede9"}
D45_PINS = {"D45_POSTSCORE_DIAGNOSTICS.json": "c0fc3355d2b586b0af11e7eb295ae74a4f6cf050f408d9ba0468ec53d2ee0fc6",
            "D45_CLAIM_READOUT_FREEZE.json": "0d826046686b427434e27304bde07ad253cea3645ae9f947af0d0ca790429bb5",
            "D45_COHORT_FREEZE.json": "f6e2c37da342ac2dfe3893fedb0551034ce1ed9d2b5a3f3dd1c0a3833c06918b"}


def canonical(value):
    return prior.digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def source_receipts():
    baseline = json.loads((HERE / "D47_BASELINE_FREEZE.json").read_bytes())
    prior.require(baseline["baseline_commit"] == BASE and baseline["development_only"][0]["sample_id"] == REGRESSION_ID,
                  "Unexpected D47 old-development scope")
    cohort_raw = (HERE / "D47_COHORT_FREEZE.json").read_bytes()
    cohort = json.loads(cohort_raw)
    old_ids = {REGRESSION_ID.split(":")[0], THRESHOLD_ID.split(":")[0]}
    admitted = {row["case_id"] for row in cohort["rows"]}
    prior.require(len(admitted) == cohort["selected_question_count"] and admitted.isdisjoint(old_ids),
                  "Development examples overlap the heldout identities")
    sources, hashes = {}, {}
    paths = {D46 / name: sha for name, sha in {**baseline["d46_evidence_sha256"], **D46_PINS}.items()}
    paths.update({D45 / name: sha for name, sha in D45_PINS.items()})
    for path, expected in paths.items():
        relative = path.relative_to(REPO).as_posix()
        raw = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=REPO, timeout=15)
        prior.require(prior.digest(raw) == expected and path.read_bytes() == raw, "Old public evidence differs")
        hashes[relative] = expected
        if path.name not in {"D46_RESULTS.json", "D46_DELIVERY_AUDIT.json"}:
            sources[path.name] = json.loads(raw)
    return sources, {"baseline_commit": BASE, "d47_heldout_identity_only_sha256": prior.digest(cohort_raw),
                     "old_cases_disjoint": True, "old_published_sha256": hashes}


def old_trace(path, sample_id, cohort, readout):
    raw = path.read_bytes()
    prior.require(prior.digest(raw) == readout["blind_input_sha256"], "Wrong old label-blind trace projection")
    source, = (r for r in json.loads(raw)["rows"] if r["sample_id"] == sample_id)
    case, = (r for r in cohort["rows"] if r["case_id"] == source["problem_id"])
    sample, = (r for r in case["draws"] if r["draw_index"] == source["draw_index"])
    prior.require(all(sample[key] == source[key] for key in ("sample_id", "seed", "response_sha256"))
                  and prior.digest(source["response"].encode()) == source["response_sha256"], "Wrong old trace identity")
    return source, case, prior.digest(raw)


def make_candidate(contract, sample, prefix, assertion_span, numeric_span, review_sha):
    a, b = assertion_span
    n0, n1 = numeric_span
    prior.require(0 <= a <= n0 < n1 <= b <= len(prefix), "Malformed assertion custody span")
    return point.CandidateReceipt(contract.binding, sample["sample_id"], sample["response_sha256"],
                                  prior.digest(prefix.encode()), tuple(numeric_span), prefix[n0:n1], tuple(assertion_span),
                                  prior.digest(prefix[a:b].encode()), point.ASSERTED_ORIGINAL_CANDIDATE, review_sha)


def candidate_from_readout(contract, sample, observed, review_sha):
    prior.require(observed["status"] == prior.BOUND, "No strict observed candidate")
    lo, hi = observed["observation_char_span_in_response"]
    prefix = sample["response"][lo:hi]
    candidate = make_candidate(contract, sample, prefix, observed["assertion_span"], observed["numeric_span"], review_sha)
    prior.require(candidate.assertion_sha256 == observed["assertion_sha256"] and candidate.numeric_text == observed["numeric_text"]
                  and candidate.observed_prefix_sha256 == observed["observation_prefix_sha256"], "Scope custody differs from readout")
    return candidate, prefix


def old_final_role(contract, sample, strict, prior_diagnosis):
    prior.require(strict["status"] == "LATER_UNSCOPED_BOX" and strict["official_final_box_receipt"]["value"] == 533,
                  "Keep the old final role corroboration separate from strict binding")
    lo, hi = strict["observation_char_span_in_response"]
    prefix = sample["response"][lo:hi]
    terminal = strict["official_final_box_receipt"]
    t0, t1 = [i - lo for i in terminal["char_span_in_response"]]
    prior.require(prior.digest(prefix[t0:t1].encode()) == terminal["source_excerpt_sha256"]
                  and prior.digest(prefix.encode()) == strict["observation_prefix_sha256"], "Old final box identity differs")
    matches = list(FINAL_ROLE.finditer(prefix, max(0, t0 - 600), t0))
    prior.require(bool(matches), "Old final lacks a same-object local assertion")
    match = matches[-1]
    prior.require(point.exact_literal(match["value"]) == 533 and prior_diagnosis["wrong_native_final"] == 533
                  and prior_diagnosis["response_sha256"] == sample["response_sha256"], "Old final role differs from diagnosis")
    edge_start, arithmetic_start = prefix.rfind("c + d = 418"), prefix.rfind("123 + 209 = 332")
    prior.require(0 <= edge_start < arithmetic_start < match.start()
                  and prior.digest(prefix[edge_start:edge_start + len("c + d = 418")].encode())
                  == prior_diagnosis["later_edge_assertion_sha256"]
                  and prior.digest(prefix[arithmetic_start:arithmetic_start + len("123 + 209 = 332")].encode())
                  == prior_diagnosis["conflicting_final_edge_arithmetic_sha256"], "Old final diagnosis anchors differ")
    role = {"basis": "D46 published postscore final diagnosis plus exact old D47 original-object role check",
            "sample_id": sample["sample_id"], "source_assertion_sha256": prior.digest(match[0].encode()),
            "final_box_sha256": terminal["source_excerpt_sha256"], "final_prefix_sha256": strict["observation_prefix_sha256"],
            "d46_final_diagnosis_sha256": canonical(prior_diagnosis), "prior_blind_final_review": False}
    return make_candidate(contract, sample, prefix, match.span(), match.span("value"), canonical(role)), prefix, role


def custody_for(contract, *observations):
    first = observations[0].candidate
    engine = point.PointVerifier(contract, contract.sha256, check,
                                 approved_candidate_sha256=[o.candidate.sha256 for o in observations],
                                 call_budget=4, work_budget=2000)
    scope = DeliveryScope(contract.binding, UNIT, contract.sha256, contract.checker_source_sha256,
                          first.sample_id, first.response_sha256)
    return PointCustody(scope, scope.sha256, engine, approved_observation_sha256=[o.sha256 for o in observations])


def decide(contract, thought, thought_prefix, final=None, final_prefix=None, *, native):
    custody = custody_for(contract, thought, *((final,) if final else ()))
    thought_ticket = custody.check(thought, thought_prefix)
    prior.require(custody.authentic(thought_ticket) and thought_ticket.point_receipt.status == point.PROVEN_FEASIBLE,
                  "Old thinking point must have a genuine feasible certificate")
    preserver = DeliveryPreserver(custody)
    update = preserver.observe(thought_ticket)
    final_ticket = custody.check(final, final_prefix) if final is not None else None
    if final_ticket is not None:
        prior.require(custody.authentic(final_ticket) and final_ticket.point_receipt.status == point.PROVEN_FEASIBLE,
                      "Old final point must have a genuine feasible certificate")
    result = preserver.finish(ELIGIBLE_NATIVE_EOS, final_ticket, native_value=native)
    before = custody.report()
    naive = naive_best_verified(custody, [thought_ticket], ELIGIBLE_NATIVE_EOS, final_ticket, native_value=native)
    after = custody.report()
    equal = all(getattr(result, field) == getattr(naive, field) for field in ("status", "action", "proposed_value", "native_value"))
    prior.require(equal and before == after, "Same-evidence naive control changed action or checker work")
    return {"preserver": preserver.report(), "naive_same_verified_evidence": naive.as_dict(),
            "same_scalar_decision": equal, "naive_additional_point_calls": 0,
            "custody": after, "first_update_status": update.status,
            "global_optimum_authority": False}


def custody_negatives(contract, observed, prefix):
    c = observed.candidate
    wrong_scope = replace(c.binding, constraints_sha256=canonical(["fixed_missing_pair_sum"]))
    values = (("wrong_unit", replace(observed, unit_id="perimeter")),
              ("wrong_direction", replace(observed, candidate=replace(c, binding=replace(c.binding, direction="MIN")))),
              ("changed_constraint_binding", replace(observed, candidate=replace(c, binding=wrong_scope))),
              ("another_draw", replace(observed, candidate=replace(c, sample_id="2017-II-5:draw-04"))))
    rows = []
    for name, bad in values:
        custody = custody_for(contract, observed, bad)
        result = custody.check(bad, prefix)
        after = custody.report()
        prior.require(result.status == "DELIVERY_SCOPE_MISMATCH" and not custody.authentic(result)
                      and after["point_checker_calls"] == after["point_work"] == 0, "Bad custody issued work or authority")
        rows.append({"control": name, "receipt": result.as_dict(), "point_checker_calls": 0, "point_work": 0})
    return rows


def better_final(scorer, contract, case, sample, rules):
    case = {**case, "case_id": "synthetic-better"}
    text = r"<think>The greatest value of x+y is \boxed{533}.</think>The greatest value of x+y is \boxed{791}."
    sample = {**sample, "response": text, "response_sha256": prior.digest(text.encode()),
              "sample_id": "synthetic-better:draw-00", "problem_id": case["case_id"], "draw_index": 0}
    row = prior.extract_row(scorer, sample, case, rules)
    final = final_point(scorer, sample, row, case, 3000)
    t, tp = candidate_from_readout(contract, sample, row["late"], canonical("Synthetic explicit original-object thinking control"))
    f, fp = candidate_from_readout(contract, sample, final, canonical("Synthetic explicit original-object final control"))
    result = decide(contract, Observation(t, UNIT, THINKING, 2), tp, Observation(f, UNIT, FINAL, 3), fp, native=791)
    prior.require(result["preserver"]["decision"]["status"] == "FEASIBLE_IMPROVEMENT"
                  and result["preserver"]["decision"]["action"] == KEEP_NATIVE, "Genuine improved final must remain")
    return result


def profile(contract, thought, tp, final, fp, expected):
    start, cpu = perf_counter_ns(), thread_time_ns()
    repeats = 0
    while repeats < 512 and thread_time_ns() - cpu < 31_250_000:
        observed = decide(contract, thought, tp, final, fp, native=533)
        prior.require(observed["preserver"]["decision"]["proposed_value"] == expected and observed["custody"]["point_work"] == 32,
                      "Repeated exact custody control differs")
        repeats += 1
    return {"repetitions": repeats, "cpu_ns": thread_time_ns() - cpu, "wall_ns": perf_counter_ns() - start,
            "repeated_point_work": 32 * repeats,
            "scope": "Includes new custody engines, checks and both decisions each repetition. Separate from one-shot receipts."}


def run(old46, old45, author):
    source, hashes = source_receipts()
    raw_rules = (HERE / "D47_OBSERVATION_RULES.json").read_bytes()
    prior.require(prior.digest(raw_rules) == RULES_SHA, "D47 observation rules changed")
    rules = thinking_rules(json.loads(raw_rules))
    scorer = prior.load_author_scorer(author)
    sample, case, old46_hash = old_trace(old46, REGRESSION_ID, source["D46_COHORT_FREEZE.json"], source["D46_CLAIM_READOUT_FREEZE.json"])
    case = {**case, "unit": UNIT}
    start, cpu = perf_counter_ns(), thread_time_ns()
    read = prior.extract_row(scorer, sample, case, rules)
    strict = final_point(scorer, sample, read, case, 3000)
    read_cost = {"wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}
    old_readout, = (r for r in source["D46_CLAIM_READOUT_FREEZE.json"]["rows"] if r["sample_id"] == REGRESSION_ID)
    prior.require(all(old_readout[k] == read[k] for k in ("early", "late", "final", "native_final_eligible"))
                  and read["early"]["status"] != prior.BOUND and read["final"]["value"] == 533,
                  "D47 changes the old native or thinking receipts")
    late_review, = (r for r in source["D46_SCOPE_AUDIT.json"]["rows"] if r["job_id"] == REGRESSION_ID + "@late")
    prior.require(late_review["decision"] == "BOUND" and late_review["value"] == 791
                  and late_review["numeric_sha256"] == read["late"]["numeric_sha256"], "No prior independent old thinking role")
    contract = reconstruct(next(r for r in source["D46_CONTRACTS_FREEZE.json"]["rows"] if r["case_id"] == case["case_id"]))
    t, tp = candidate_from_readout(contract, sample, read["late"], late_review["review_output_sha256"])
    t_obs = Observation(t, UNIT, THINKING, 2)
    strict_only = decide(contract, t_obs, tp, native=533)
    prior.require(strict_only["preserver"]["decision"]["status"] == "FINAL_SCOPE_UNKNOWN"
                  and strict_only["preserver"]["decision"]["proposed_value"] == "533", "Strict unknown final must stay native")
    f, fp, role = old_final_role(contract, sample, strict, source["D46_POSTSCORE_FAILURE_MODES.json"]["feasible_final_regression"])
    f_obs = Observation(f, UNIT, FINAL, 3)
    reproduced = decide(contract, t_obs, tp, f_obs, fp, native=533)
    decision = reproduced["preserver"]["decision"]
    prior.require(decision["status"] == "FEASIBLE_REGRESSION" and decision["action"] == RETAIN_CERTIFIED_INCUMBENT
                  and decision["proposed_value"] == "791" and reproduced["custody"]["point_checker_calls"] == 2
                  and reproduced["custody"]["point_work"] == 32, "Old retained value or paid work differs")

    threshold, case45, old45_hash = old_trace(old45, THRESHOLD_ID, source["D45_COHORT_FREEZE.json"], source["D45_CLAIM_READOUT_FREEZE.json"])
    diag = source["D45_POSTSCORE_DIAGNOSTICS.json"]["early_false_binding"]
    a, b = diag["span"]
    prior.require(prior.digest(threshold["response"][a:b].encode()) == diag["source_excerpt_sha256"], "Old threshold span differs")
    start, cpu = perf_counter_ns(), thread_time_ns()
    early = prior.extract_row(scorer, threshold, {**case45, "subject_patterns": [r"n", r"(?:positive integer )?index"]}, rules)["early"]
    threshold_cost = {"wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}
    prior.require(early["status"] != prior.BOUND and early["value"] is None, "Old threshold became a certified observation")
    return {"status": "PASS_D47_ACTUAL_OLD_DELIVERY_CALIBRATION", "sources": {**hashes,
                 "old_d46_blind_projection_sha256": old46_hash, "old_d45_blind_projection_sha256": old45_hash},
            "observation_rules_sha256": RULES_SHA,
            "calibration_code_sha256": prior.digest(Path(__file__).read_bytes()),
            "delivery_preservation_source_sha256": prior.digest((HERE / "delivery_preservation.py").read_bytes()),
            "old_regression": {"sample_id": REGRESSION_ID, "response_sha256": sample["response_sha256"],
                               "paid_archived_tokens": {key: sample[key] for key in ("input_tokens", "output_tokens")},
                               "strict_early": read["early"], "strict_late": read["late"], "ordinary_native_final": read["final"],
                               "strict_final": strict, "strict_readout_cost": read_cost, "strict_policy": strict_only,
                               "independent_old_late_role": late_review, "postscore_old_final_role": role,
                               "development_corroboration_only": reproduced,
                               "batch_cpu_profile": profile(contract, t_obs, tp, f_obs, fp, "791")},
            "old_threshold": {"sample_id": THRESHOLD_ID, "strict_early": early, "diagnosed_threshold_excerpt_sha256": diag["source_excerpt_sha256"],
                              "paid_archived_tokens": {key: threshold[key] for key in ("input_tokens", "output_tokens")},
                              "issued_observations": 0, "point_checker_calls": 0, "point_work": 0, **threshold_cost},
            "adversarial_custody_controls": custody_negatives(contract, t_obs, tp),
            "synthetic_better_final": better_final(scorer, contract, case, sample, rules),
            "scope": "Old development and synthetic controls only. Strict final abstention retained. Postscore role corroboration is not a strict or fresh heldout authorization. No labels loaded, no new model work, and no global optimum authority."}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--old-d46-blind", type=Path, default=OLD46)
    cli.add_argument("--old-d45-blind", type=Path, default=OLD45)
    cli.add_argument("--author-scorer", type=Path, default=AUTHOR)
    cli.add_argument("--output", type=Path, default=HERE / "D47_DEVELOPMENT_CALIBRATION.json")
    args = cli.parse_args()
    prior.require(not args.output.exists(), "Refuse to overwrite calibration")
    report = run(args.old_d46_blind, args.old_d45_blind, args.author_scorer)
    prior.write_exclusive(args.output, report)
    print(json.dumps({"status": report["status"], "sha256": prior.digest(args.output.read_bytes())}))
