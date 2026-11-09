"""Deterministic bounded witness search from a compiled original problem."""

from collections import Counter
from itertools import combinations, product
from hashlib import sha256
from math import prod
from pathlib import Path

from witness_contract import (BudgetExhausted, COINS, DIGITS, DIVISORS, PRIME, SEQUENCE, WorkMeter,
                              _lcm_range, authentic, bounded_payload, candidate_math, claim_math, coin_point,
                              digest, divisor_point, finalize, least_prime_certificate, rational_json,
                              residue_holds, result, sequence_solution, valid_claim)


ALGORITHM = "wgr-bounded-online-search-v1"
ALGORITHM_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def _digit_candidates(meter):
    frontier = [()]
    while frontier:
        following = []
        for prefix in frontier:
            for digit in range(1 if not prefix else 0, 10):
                meter.charge("digit_extension", [prefix, digit])
                if len(prefix) < 2 or digit >= prefix[-1] + prefix[-2]:
                    extended = (*prefix, digit)
                    following.append(extended)
                    yield int("".join(map(str, extended))), len(extended)
        frontier = following


def _divisor_candidates(k, upper, meter):
    factors = []
    remaining = k
    for p in range(2, upper+1):
        exponent = 0
        while remaining > 1:
            meter.charge("factor_trial", [p, exponent])
            if remaining % p:
                break
            remaining //= p
            exponent += 1
        if exponent:
            factors.append((p, exponent))
    if remaining != 1:
        raise ValueError("incomplete_lcm_factorization")
    for powers in product(*(range(exponent+1) for _, exponent in factors)):
        meter.charge("divisor_candidate", powers)
        yield prod(p**power for (p, _), power in zip(factors, powers))


def _solve(contract, meter, prerequisite):
    program = contract.program
    if contract.template_id == SEQUENCE:
        solution, _ = sequence_solution(program, meter)
        if solution is None:
            return result("UNKNOWN", "sequence_uniqueness_not_established")
        return candidate_math(contract, {key: rational_json(value) for key, value in solution.items()}, meter)
    if contract.template_id == DIGITS:
        maximum = 0
        levels = Counter()
        for value, length in _digit_candidates(meter):
            maximum = max(maximum, value)
            levels[str(length)] += 1
        return result("CERTIFIED_EXACT", "exhausted_all_feasible_digit_extensions", proof_scope="FULL_OBJECTIVE",
                      value=maximum, witness=maximum, evidence={"feasible_by_length": dict(levels),
                                                                "first_empty_length": max(map(int, levels)) + 1})
    if contract.template_id == PRIME:
        p = prerequisite["prime"]
        for m in range(1, p**program["modulus_exponent"] + 1):
            if residue_holds(program, p, m, meter):
                return result("CERTIFIED_EXACT", "least_prime_and_all_smaller_positive_values_checked",
                              proof_scope="FULL_OBJECTIVE", value=m, witness={"p": p, "m": m},
                              evidence={"smaller_positive_values_checked": m-1})
        return result("UNKNOWN", "certified_prime_without_residue")
    if contract.template_id == DIVISORS:
        k = _lcm_range(program["set_upper"], meter)
        count, examined = 0, 0
        for d in _divisor_candidates(k, program["set_upper"], meter):
            count += divisor_point(program, d, k, meter)[0]
            examined += 1
        return result("CERTIFIED_EXACT", "exhausted_all_divisors_of_lcm", proof_scope="FULL_OBJECTIVE", value=count,
                      evidence={"divisors_examined": examined})
    count = sum(coin_point(program, n, meter)[0] for n in range(program["lower"], program["upper"]+1))
    return result("CERTIFIED_EXACT", "exhausted_all_coin_amounts", proof_scope="FULL_OBJECTIVE", value=count,
                  evidence={"amounts_examined": program["upper"] - program["lower"] + 1})


def _refute(contract, claim, meter, prerequisite):
    kind = claim["kind"]
    if kind == "MAX":
        for candidate, _ in _digit_candidates(meter):
            if candidate > claim["value"]:
                return claim_math(contract, claim, candidate, meter)
    elif kind == "MIN":
        p = prerequisite["prime"]
        if p != claim["p"]:
            return result("UNKNOWN", "claim_prime_differs_from_certified_least_prime")
        upper = min(p**contract.program["modulus_exponent"], claim["value"] - 1)
        # A refutation only requires a smaller feasible value. Scan downward.
        for m in range(upper, 0, -1):
            checked = claim_math(contract, claim, {"p": p, "m": m}, meter, certified_prime=p)
            if checked["status"] == "DOMINATED_CANDIDATE":
                return checked
    elif kind == "COMPLETE_SOLUTIONS":
        p = prerequisite["prime"]
        modulus = p ** contract.program["modulus_exponent"]
        if claim["modulus"] != modulus:
            return result("UNKNOWN", "claim_modulus_differs_from_certified_prime_square")
        listed = set(claim["values"])
        for m in range(modulus):
            if m in listed:
                continue
            checked = claim_math(contract, claim, {"p": p, "m": m}, meter, certified_prime=p)
            if checked["status"] == "UNIVERSAL_REFUTATION":
                return checked
    elif kind == "ALL_REMOVED_PAIR_LCM_FAILS_BOTH":
        for a, b in combinations(range(claim["lower"], claim["upper"]+1), 2):
            checked = claim_math(contract, claim, {"pair": [a, b]}, meter)
            if checked["status"] == "UNIVERSAL_REFUTATION":
                return checked
    else:
        for n in range(claim["lower"], claim["upper"]+1):
            checked = claim_math(contract, claim, {"n": n}, meter)
            if checked["status"] == "UNIVERSAL_REFUTATION":
                return checked
    return result("UNKNOWN", "no_counterexample_found_in_exhausted_search_domain")


def search_witness(contract, claim=None, *, budget, purpose="COUNTEREXAMPLE"):
    """Search only an owned problem and optional incumbent under a work-unit limit."""
    meter = WorkMeter(budget)
    contract_id = contract.contract_id if authentic(contract) else None
    request = {"contract_id": contract_id, "claim": claim, "budget": budget, "purpose": purpose, "algorithm": ALGORITHM}
    prerequisite = None
    try:
        request = bounded_payload(request)
        claim = request["claim"]
        if contract_id is None:
            check = result("UNKNOWN", "unrecognized_contract")
        elif purpose not in ("COUNTEREXAMPLE", "SOLVE") or (purpose == "SOLVE" and claim is not None):
            check = result("UNKNOWN", "unsupported_search_request")
        elif purpose == "COUNTEREXAMPLE" and not valid_claim(contract, claim):
            check = result("UNKNOWN", "unsupported_or_unbound_claim")
        else:
            if contract.template_id == PRIME:
                prerequisite = least_prime_certificate(contract, meter)
            if contract.template_id == PRIME and prerequisite is None:
                check = result("UNKNOWN", "least_prime_not_found_in_supported_bound")
            elif purpose == "SOLVE":
                check = _solve(contract, meter, prerequisite)
            else:
                check = _refute(contract, claim, meter, prerequisite)
    except BudgetExhausted:
        check = result("UNKNOWN", "budget_exhausted")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        # Non-JSON input cannot enter a replayable receipt.
        check = result("UNKNOWN", str(error))
        request = {**request, "claim": None}
    payload = {**finalize(contract, check, meter, {"search": request, "prerequisite": prerequisite}),
               "request": request, "prerequisite": prerequisite, "algorithm_sha256": ALGORITHM_SHA256,
               "witness_source": "ONLINE_SEARCH" if check["witness"] is not None else None}
    return {**payload, "receipt_sha256": digest(payload)}


def replay_search(contract, receipt):
    """Recompute all paid work, prerequisite proofs, and result from the request."""
    if type(receipt) is not dict or type(receipt.get("request")) is not dict:
        return False
    request = receipt["request"]
    if (set(request) != {"contract_id", "claim", "budget", "purpose", "algorithm"}
            or not authentic(contract) or request["contract_id"] != contract.contract_id or request["algorithm"] != ALGORITHM):
        return False
    try:
        return receipt == search_witness(contract, request["claim"], budget=request["budget"], purpose=request["purpose"])
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
