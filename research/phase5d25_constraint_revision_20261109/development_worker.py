"""One source-verified historical coefficient-conflict development case."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

from paired_d2_worker import D1, NativeEngine, NativeState, load_runtime, prompt_for, reference_runtime, replay_schedule, verify_inputs, write
from independent_audit import work

SUPPORT = D1 / "support_engine"
if SUPPORT.is_dir():
    sys.path.append(str(SUPPORT))
from scope_rebase_hardened import Claim, EvidenceLedger, Scope
from dual_frontier_rebase import bind_observed_thinking, plan_rebase, replay_rebase
from restricted_math_checker import make_request, replay_certificate, verify


SEED = 20261109
ARMS = ("GenericRewind", "ScopedRebaseNoCarry", "ScopedRebaseCarry")


def digest_ids(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def product(left, right):
    output = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            output[i + j] += a * b
    return output


def polynomial_ast(coefficients):
    variable = {"op": "var", "name": "x"}
    terms = []
    for exponent, value in enumerate(coefficients):
        if not value:
            continue
        if exponent == 0:
            terms.append(value)
        else:
            power = variable if exponent == 1 else {"op": "pow", "base": variable, "exp": exponent}
            terms.append(power if value == 1 else {"op": "mul", "args": [value, power]})
    return terms[0] if len(terms) == 1 else {"op": "add", "args": terms}


def verify_math(packet):
    """Recompute the observed quotient coefficients and the earlier feasible triple."""
    divisor = [-1, 4, -3, 1]
    base, column_a, column_b = (product(divisor, quotient) for quotient in (
        [0, 0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 1]))
    x8 = (base[8], column_a[8], 0)
    x7 = (base[7], column_a[7], column_b[7])
    if x8 != (-3, 1, 0) or x7 != (4, -3, 1):
        raise ValueError("Recorded coefficient evidence does not match the original product")
    # The original target polynomial has no x^8 coefficient. This determines a.
    a = -x8[0]
    difference = x7[0] + (x7[1] - 1) * a
    if difference != -8:
        raise ValueError("The local coefficient refutation failed")
    p, q, r = packet["candidate"]
    dividend = [r, 0, 0, q, 0, 0, p, 0, 0, 1]
    target = {"id": "rank88_feasible_triple", "version": 0, "kind": "claim",
              "scope": {"id": "rank88_Qx", "version": 0, "coefficient_domain": "Q", "domains": {"x": {"kind": "rational"}}},
              "certificate_type": "POLYNOMIAL_DIVISIBILITY",
              "statement": {"dividend": polynomial_ast(dividend), "divisor": polynomial_ast(divisor)},
              "required_premises": [], "source_span": packet["candidate_span"],
              "observed_prefix_sha256": packet["generated_prefix_sha256"]}
    request = make_request(target)
    checked = verify(request, target=target)
    if checked["status"] != "VERIFIED" or not replay_certificate(checked["certificate"], request, target=target):
        raise ValueError("Earlier candidate does not have a replayable divisibility certificate")
    return {"x8_affine_constant_a_b": x8, "x7_affine_constant_a_b": x7, "derived_a": a,
            "difference_from_claim_at_derived_a": difference, "verified_feasibility": checked,
            "feasibility_target": target, "feasibility_request": request}


def prepare_plan(packet, tokenizer, prompt):
    ids = packet["generated_ids"]
    if digest_ids(ids) != packet["generated_prefix_sha256"]:
        raise ValueError("Historical observed prefix token hash changed")
    for kind in ("invalid", "candidate", "conflict", "derived_a"):
        start, end = packet[kind + "_span"]
        decoded = tokenizer.decode(ids[start:end], skip_special_tokens=False)
        if hashlib.sha256(decoded.encode()).hexdigest() != packet[kind + "_span_sha256"]:
            raise ValueError(f"Source role span changed for {kind}")
    math = verify_math(packet)
    scope = Scope("rank88_quotient", "rational", (
        "a and b are coefficients of the displayed quotient x^6+a*x^5+b*x^4+... .",
        "The original target has zero x^8 coefficient. Product coefficient x^8=a-3 fixes a=3.",
    ))
    bound = packet["invalid_span"]
    step_bound = packet["invalid_step_span"]
    earlier = packet["candidate_span"]
    a_span = packet["derived_a_span"]
    latest = packet["conflict_step_span"][0]
    proposed_boundaries = (0, step_bound[0], latest, len(ids))
    ledger = EvidenceLedger([scope], legal_token_boundaries=proposed_boundaries, observed_token_length=len(ids))
    ledger.add_claim(Claim("a_from_x8", "a", math["derived_a"], scope.id, token_start=a_span[0], token_end=a_span[1]))
    ledger.trust_constraint("exact_x8_comparison", scope.id, "a", "3")
    result = ledger.prove_arithmetic("licensed_a_from_x8", "a_from_x8", "3", constraint_id="exact_x8_comparison",
                                    token_start=a_span[0], token_end=a_span[1])
    if result.verdict != "PASS":
        raise ValueError("Failed to establish the checked independent a=3 support")
    ledger.add_claim(Claim("candidate_feasible", "candidate_feasible", 1, scope.id, token_start=earlier[0], token_end=earlier[1]))
    proof = math["verified_feasibility"]["certificate"]["sha256"]
    certified_rule = "polynomial_" + proof[:30]
    ledger.trust_constraint(certified_rule, scope.id, "candidate_feasible", "1")
    supported = ledger.prove_arithmetic("candidate_feasibility", "candidate_feasible", "1", constraint_id=certified_rule,
                                        token_start=earlier[0], token_end=earlier[1])
    if supported.verdict != "PASS":
        raise ValueError("Feasibility proof registration failed")
    ledger.add_claim(Claim("x7_coeff_difference_zero", "x7_difference", 0, scope.id, token_start=bound[0], token_end=bound[1]))
    ledger.prove_arithmetic("faulty_x7_identity", "x7_coeff_difference_zero", "4-4*a", (("a", "a_from_x8"),),
                            token_start=bound[0], token_end=bound[1])
    challenge = ledger.check_arithmetic_invalidation("revoke_rank88_x7", "faulty_x7_identity")
    if ledger.verify_challenge(challenge).verdict != "PASS":
        raise ValueError("Proof invalidation not grounded")
    observation = bind_observed_thinking(ledger, tokenizer, snapshot_id="rank88_conflict", source_version=1,
                                         prompt_ids=prompt, generated_ids=ids, boundary_offsets=proposed_boundaries)
    plans = {name: plan_rebase(ledger, challenge, observation, carry=name == "ScopedRebaseCarry") for name in ARMS[1:]}
    if (any(plan.status != "READY" or plan.cut_token != step_bound[0] for plan in plans.values())
            or plans["ScopedRebaseCarry"].carried_claims != ("a_from_x8",) or latest <= bound[0]):
        raise ValueError("The observed development cut or preserved-support hypothesis does not match")
    return math, ledger, observation, plans, latest


def run_case(engine, packet, folder, identity, reference):
    prompt = prompt_for(engine.tokenizer, packet["question"])
    ids = packet["generated_ids"]
    if engine.open_ids[0] not in prompt + ids:
        prompt = prompt + engine.open_ids
    math, ledger, observation, plans, latest = prepare_plan(packet, engine.tokenizer, prompt)
    common = "\n\nRecheck the displayed polynomial product using the original divisor. Its x^7 coefficient is b - 3*a + 4. Continue solving the original problem.\n\n"
    diagnostics = {"status": "READY", "source_prefix_sha256": observation.prefix_sha256, "math": math,
                   "common_checked_message": common, "generic_cut": latest,
                   "arms": {name: {"cut": plan.cut_token, "carried_claims": plan.carried_claims,
                                   "invalidated_text_spans": plan.invalidated_text_spans,
                                   "lost_support": sorted(plan.lost_support), "bridge_text": plan.bridge_text}
                            for name, plan in plans.items()}}
    write(folder / "SOURCE_BOUND_PLANS.json", diagnostics)
    results = []
    for arm in ARMS:
        engine.torch.cuda.reset_peak_memory_stats(engine.device)
        began = time.monotonic()
        first = len(engine.ledger)
        if arm == "GenericRewind":
            engine.stage = "generic_rewind_replay"
            cut = latest
            ids_after_replay = ids[:cut]
            cache, logits = replay_schedule(engine, prompt, ids_after_replay)
            bridge_tokens = 0
        else:
            plan = plans[arm]
            replay = replay_rebase(engine, plan, ledger, observation, snapshot_id=observation.snapshot_id,
                                   source_version=observation.source_version, current_prefix_ids=tuple(prompt + ids))
            cache, logits, cut = replay.cache, replay.next_logits, replay.retained_generated_tokens
            bridge_tokens = replay.appended_bridge_tokens
            ids_after_replay = list(replay.prefix_ids[len(prompt):])
            del replay
        state = NativeState(tuple(prompt), list(ids_after_replay), cache, logits, engine.rng(seed=SEED),
                            len(prompt) + len(ids_after_replay), True, "RUNNING", identity)
        del cache, logits
        injected = reference.append_checked_text(engine, state, common, "common_verified_evidence")
        if injected["status"] != "APPENDED":
            raise ValueError("Could not append the shared evidence")
        completed = reference.finish(engine, state, folder, arm)
        row = {**reference.state_result(engine, state), "arm": arm, "seed": SEED, "retained_historical_tokens": cut,
               "discarded_historical_tokens": len(ids) - cut, "certified_carry_tokens": bridge_tokens,
               "common_evidence_tokens": injected["tokens"], "sampled_continuation_tokens": completed["continuation_tokens"],
               "elapsed_seconds": time.monotonic() - began, "paid_work": work(engine.ledger[first:]),
               "ledger": engine.ledger[first:], "peak_allocated_bytes": engine.torch.cuda.max_memory_allocated(engine.device),
               "scope": "Historical generated prefix, reconstructed model input, newly seeded continuation; development only"}
        write(folder / f"{arm}.json", row)
        results.append({key: row[key] for key in ("arm", "EOS", "new_tokens", "elapsed_seconds", "paid_work")})
        del state
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--worker", type=int, required=True)
    args = ap.parse_args()
    if args.worker != 0:
        raise ValueError("Development arms are paired on a single physical GPU")
    verify_inputs(args.root, "development_freeze.json")
    packet = json.loads((args.root / "DEV_RANK88_PACKET.json").read_bytes())
    model, tokenizer, device, meta = load_runtime(D1, args.model, args.gpu)
    engine = NativeEngine(model, tokenizer, device)
    reference = reference_runtime()
    identity = reference.execution_identity(D1, engine, meta)
    folder = args.root / "development_results/worker_0/rank88"
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / "manifest.json", meta)
    with engine.torch.inference_mode():
        result = run_case(engine, packet, folder, identity, reference)
    write(folder / "summary.json", {"status": "COMPLETE", "arms": result})


if __name__ == "__main__":
    main()
