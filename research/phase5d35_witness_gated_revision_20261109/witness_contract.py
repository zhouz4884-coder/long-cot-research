"""Source-bound task templates and a bounded exact witness DSL."""

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from math import isqrt, lcm
import json
from pathlib import Path
import re


VERSION = "wgr-witness-contract-v1"
CHECKER_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
SEQUENCE = "arithmetic_geometric_sequence_v1"
DIGITS = "fibbish_max_v1"
PRIME = "least_prime_square_residue_v1"
DIVISORS = "lcm_divisor_count_v1"
COINS = "greedy_coin_count_v1"
MAX_BUDGET = 1_000_000
MAX_PRIME = 256
MAX_INTEGER_BITS = 256


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def bounded_payload(value):
    encoded = canonical(value)
    if len(encoded) > 8192:
        raise ValueError("witness_payload_limit")
    return json.loads(encoded)


def _template(text, **captures):
    return re.compile("".join(captures.get(part[1:-1], re.escape(part)) if part.startswith("<") else re.escape(part)
                              for part in re.split(r"(<[a-z0-9_]+>)", text)))


_SEQUENCE = _template(
    r"Let $a_{1}, a_{2}, a_{3}, \ldots$ be an arithmetic sequence, and let $b_{1}, b_{2}, b_{3}, \ldots$ be a geometric sequence. "
    r"The sequence $c_{1}, c_{2}, c_{3}, \ldots$ has $c_{n}=a_{n}+b_{n}$ for each positive integer $n$. "
    r"If $c_{1}=<c1>, c_{2}=<c2>, c_{3}=<c3>$, and $c_{4}=<c4>$, compute $c_{<target>}$.",
    **{name: rf"(?P<{name}>[+-]?\d{{1,8}})" for name in ("c1", "c2", "c3", "c4")}, target=r"(?P<target>\d{1,2})",
)
_DIGITS = "Call a positive integer fibbish if each digit, after the leftmost two, is at least the sum of the previous two digits. Compute the greatest fibbish number."
_PRIME = _template(
    r"Let $p$ be the least prime number for which there exists a positive integer $n$ such that $n^{<power>}+<offset>$ is divisible by $p^{2}$. "
    r"Find the least positive integer $m$ such that $m^{<same_power>}+<same_offset>$ is divisible by $p^{2}$.",
    power=r"(?P<power>\d{1,2})", offset=r"(?P<offset>\d{1,4})", same_power=r"(?P=power)", same_offset=r"(?P=offset)",
)
_DIVISORS = _template(
    r"Let $k$ be the least common multiple of the numbers in the set $\mathcal{S}=\{1,2, \ldots, <upper>\}$. "
    r"Determine the number of positive integer divisors of $k$ that are divisible by exactly <count> of the numbers in the set $\mathcal{S}$.",
    upper=r"(?P<upper>\d{1,3})", count=r"(?P<count>\d{1,3})",
)
_COINS = _template(
    "From an unlimited supply of 1-cent coins, 10-cent coins, and 25-cent coins, Silas wants to find a collection of coins that has a total value of $ N $ cents, where $ N $ is a positive integer. "
    "He uses the so-called **greedy algorithm**, successively choosing the coin of greatest value that does not cause the value of his collection to exceed $ N $. "
    "For example, to get 42 cents, Silas will choose a 25-cent coin, then a 10-cent coin, then 7 1-cent coins. "
    "However, this collection of 9 coins uses more coins than necessary to get a total of 42 cents; indeed, choosing 4 10-cent coins and 2 1-cent coins achieves the same total value with only 6 coins. "
    "In general, the greedy algorithm succeeds for a given $ N $ if no other collection of 1-cent, 10-cent, and 25-cent coins gives a total value of $ N $ cents using strictly fewer coins than the collection given by the greedy algorithm. "
    "Find the number of values of $ N $ between 1 and <upper> inclusive for which the greedy algorithm succeeds.",
    upper=r"(?P<upper>\d{1,5})",
)


@dataclass(frozen=True)
class WitnessContract:
    template_id: str
    goal: str
    question: str
    question_sha256: str
    program_json: str

    @property
    def program(self):
        return json.loads(self.program_json)

    @property
    def contract_id(self):
        return "wc_" + digest([VERSION, self.template_id, self.goal, self.question_sha256, self.program])[:40]

    def as_dict(self):
        return {"contract_id": self.contract_id, "compiler_version": VERSION, "template_id": self.template_id,
                "goal": self.goal, "question_sha256": self.question_sha256, "source_char_span": [0, len(self.question)],
                "program": self.program}


def compile_contract(question):
    """Recognize the entire source question under a fixed template, or abstain."""
    if type(question) is not str or not 0 < len(question) <= 8192:
        return None
    text = " ".join(question.split())
    if (m := _SEQUENCE.fullmatch(text)) is not None and 5 <= int(m["target"]) <= 16:
        template, goal = SEQUENCE, "EXACT"
        program = {"op": "arithmetic_plus_geometric", "given_terms": [int(m[f"c{i}"]) for i in range(1, 5)],
                   "target_index": int(m["target"]), "parameters": ["a1", "d", "b1", "r"]}
    elif text == _DIGITS:
        template, goal = DIGITS, "MAX"
        program = {"op": "positive_decimal_digit_recurrence", "base": 10, "prefix_unrestricted_digits": 2,
                   "recurrence": "digit_at_least_sum_of_previous_two"}
    elif (m := _PRIME.fullmatch(text)) is not None and 1 <= int(m["power"]) <= 12:
        template, goal = PRIME, "MIN"
        program = {"op": "least_prime_square_residue", "power": int(m["power"]), "offset": int(m["offset"]),
                   "modulus_exponent": 2, "positive_integer_variables": ["n", "m"]}
    elif (m := _DIVISORS.fullmatch(text)) is not None and 1 <= int(m["count"]) <= int(m["upper"]) <= 100:
        template, goal = DIVISORS, "COUNT"
        program = {"op": "lcm_divisor_count", "set_lower": 1, "set_upper": int(m["upper"]),
                   "required_divisibility_count": int(m["count"])}
    elif (m := _COINS.fullmatch(text)) is not None and 1 <= int(m["upper"]) <= 10_000:
        template, goal = COINS, "COUNT"
        program = {"op": "greedy_coin_optimum_count", "denominations": [1, 10, 25], "lower": 1, "upper": int(m["upper"])}
    else:
        return None
    return WitnessContract(template, goal, question, sha256(question.encode("utf-8")).hexdigest(), canonical(program))


def authentic(contract):
    return isinstance(contract, WitnessContract) and compile_contract(contract.question) == contract


class BudgetExhausted(RuntimeError):
    pass


class WorkMeter:
    def __init__(self, limit):
        if type(limit) is not int or not 0 <= limit <= MAX_BUDGET:
            raise ValueError("invalid_work_budget")
        self.limit = limit
        self.used = 0
        self.by_operation = {}
        self.trace = sha256()

    def charge(self, operation, value):
        if self.used == self.limit:
            raise BudgetExhausted("budget_exhausted")
        self.used += 1
        self.by_operation[operation] = self.by_operation.get(operation, 0) + 1
        self.trace.update((canonical([operation, value]) + "\n").encode("utf-8"))

    def snapshot(self):
        return {"used": self.used, "by_operation": dict(self.by_operation), "trace_sha256": self.trace.hexdigest()}


def integer(value):
    return type(value) is int and abs(value).bit_length() <= MAX_INTEGER_BITS


def _positive(value):
    return integer(value) and value > 0


def rational(value):
    if integer(value):
        return Fraction(value)
    if (type(value) is dict and set(value) == {"op", "num", "den"} and value["op"] == "rat"
            and integer(value["num"]) and integer(value["den"]) and value["den"] != 0):
        return Fraction(value["num"], value["den"])
    raise ValueError("bounded_exact_rational_required")


def rational_json(value):
    return value.numerator if value.denominator == 1 else {"op": "rat", "num": value.numerator, "den": value.denominator}


def result(status, reason, *, proof_scope="UNKNOWN", witness=None, value=None, evidence=None):
    return {"status": status, "reason": reason, "proof_scope": proof_scope, "certified_value": value,
            "witness": witness, "evidence": evidence}


def finalize(contract, check, meter, request):
    record = {**check, "checker_version": VERSION, "checker_sha256": CHECKER_SHA256,
              "paid_check_count": meter.used, "work": meter.snapshot()}
    certificate = None
    if check["status"] != "UNKNOWN":
        certificate = digest({"contract": contract.as_dict(), "request": request, "result": record})
    return {**record, "certificate_sha256": certificate}


def sequence_solution(program, meter):
    c1, c2, c3, c4 = map(Fraction, program["given_terms"])
    meter.charge("sequence_second_difference", program["given_terms"])
    first, second = c3 - 2*c2 + c1, c4 - 2*c3 + c2
    if first == 0:
        return None, {"first_second_difference": 0, "second_second_difference": rational_json(second)}
    r = second / first
    evidence = {"first_second_difference": rational_json(first), "second_second_difference": rational_json(second),
                "rule": "nonzero_second_difference_fixes_common_ratio"}
    if r == 1:
        return None, evidence
    meter.charge("sequence_unique_parameters", [rational_json(first), rational_json(r)])
    b1 = first / (r-1)**2
    return {"a1": c1-b1, "d": c2-c1-b1*(r-1), "b1": b1, "r": r}, evidence


def _sequence_candidate(program, candidate, meter):
    fields = {"a1", "d", "b1", "r"}
    if type(candidate) is not dict or not fields <= set(candidate) <= fields | {"answer"}:
        return result("UNKNOWN", "complete_sequence_parameter_assignment_required")
    params = {name: rational(candidate[name]) for name in fields}
    a1, d, b1, r = (params[name] for name in ("a1", "d", "b1", "r"))
    tested = []
    for index, expected in enumerate(program["given_terms"], 1):
        meter.charge("sequence_constraint", index)
        tested.append({"index": index, "expected": expected, "actual": rational_json(a1+(index-1)*d+b1*r**(index-1))})
    evidence = {"constraints": tested}
    scope = "FULL_ORIGINAL_CONSTRAINTS"
    if any(row["expected"] != row["actual"] for row in tested):
        return result("INVALID_CANDIDATE", "original_sequence_terms_violated", proof_scope=scope, witness=candidate, evidence=evidence)
    index = program["target_index"]
    meter.charge("sequence_target", index)
    actual = a1+(index-1)*d+b1*r**(index-1)
    unique, proof = sequence_solution(program, meter)
    if "answer" in candidate and rational(candidate["answer"]) != actual:
        return result("INVALID_CANDIDATE", "proposed_value_disagrees_with_verified_parameters",
                      proof_scope="FULL_OBJECTIVE" if unique == params else scope, witness=candidate,
                      evidence={**evidence, "computed_target": rational_json(actual),
                                "uniqueness": proof if unique == params else None})
    if unique != params:
        return result("FEASIBLE_ONLY", "valid_terms_without_uniqueness", proof_scope=scope, witness=candidate,
                      evidence={**evidence, "computed_target": rational_json(actual)})
    return result("CERTIFIED_EXACT", "unique_sequence_parameters_and_target", proof_scope="FULL_OBJECTIVE",
                  witness=candidate, value=rational_json(actual), evidence={**evidence, "uniqueness": proof})


def digit_feasible(value, meter):
    meter.charge("digit_candidate", value)
    if not _positive(value):
        return False, {"reason": "positive_integer_required"}
    digits = [int(ch) for ch in str(value)]
    for index in range(2, len(digits)):
        meter.charge("digit_recurrence", [index, *digits[index-2:index+1]])
        if digits[index] < digits[index-1] + digits[index-2]:
            return False, {"digits": digits, "violated_index": index}
    return True, {"digits": digits}


def is_prime(value, meter):
    if type(value) is not int or value < 2:
        return False
    for divisor in range(2, isqrt(value) + 1):
        meter.charge("prime_trial_division", [value, divisor])
        if value % divisor == 0:
            return False
    return True


def residue_holds(program, p, n, meter):
    meter.charge("modular_residue", [p, n])
    modulus = p ** program["modulus_exponent"]
    return (pow(n, program["power"], modulus) + program["offset"]) % modulus == 0


def least_prime_certificate(contract, meter):
    program = contract.program
    excluded = []
    for p in range(2, MAX_PRIME + 1):
        meter.charge("prime_candidate", p)
        if not is_prime(p, meter):
            continue
        modulus = p ** program["modulus_exponent"]
        # Existence only. Descending positive representatives avoid encoding a minimum-m result.
        for n in range(modulus, 0, -1):
            if residue_holds(program, p, n, meter):
                proof = {"status": "LEAST_PRIME_CERTIFIED", "contract_id": contract.contract_id, "prime": p,
                         "positive_residue_witness": n, "exhausted_smaller_primes": excluded, "work": meter.snapshot()}
                return {**proof, "certificate_sha256": digest(proof)}
        excluded.append(p)
    return None


def _verified_prime(contract, prerequisite, meter):
    if (type(prerequisite) is not dict or prerequisite.get("status") != "LEAST_PRIME_CERTIFIED"
            or prerequisite.get("contract_id") != contract.contract_id):
        return None
    expected = least_prime_certificate(contract, meter)
    return expected["prime"] if expected is not None and expected == prerequisite else None


def _lcm_range(upper, meter, removed=()):
    value = 1
    for n in range(1, upper+1):
        if n not in removed:
            meter.charge("lcm_member", n)
            value = lcm(value, n)
    return value


def divisor_point(program, divisor, k, meter):
    if not _positive(divisor):
        return False, {"reason": "positive_divisor_required"}
    meter.charge("divisor_membership", divisor)
    if k % divisor:
        return False, {"reason": "does_not_divide_lcm", "lcm": k}
    divisible = []
    for n in range(program["set_lower"], program["set_upper"]+1):
        meter.charge("divisibility_point", [divisor, n])
        if divisor % n == 0:
            divisible.append(n)
    return len(divisible) == program["required_divisibility_count"], {"lcm": k, "divisible_members": divisible}


def coin_point(program, n, meter):
    if not _positive(n) or not program["lower"] <= n <= program["upper"]:
        raise ValueError("coin_point_outside_original_range")
    one, medium, large = program["denominations"]
    if one != 1:
        raise ValueError("unsupported_coin_system")
    greedy_large, left = divmod(n, large)
    greedy_middle, greedy_one = divmod(left, medium)
    greedy_count = greedy_large + greedy_middle + greedy_one
    best = None
    for large_count in range(greedy_large+1):
        meter.charge("coin_allocation", [n, large_count])
        medium_count, ones = divmod(n-large*large_count, medium)
        count = large_count + medium_count + ones
        if best is None or count < best[0]:
            best = count, (ones, medium_count, large_count)
    return greedy_count == best[0], {"n": n, "greedy_coins": greedy_count, "minimum_coins": best[0],
                                    "optimal_counts_by_denomination": list(best[1])}


def candidate_math(contract, candidate, meter, prerequisite=None):
    program = contract.program
    if contract.template_id == SEQUENCE:
        return _sequence_candidate(program, candidate, meter)
    if contract.template_id == DIGITS:
        if not integer(candidate):
            return result("UNKNOWN", "bounded_integer_candidate_required")
        ok, evidence = digit_feasible(candidate, meter)
        return result("FEASIBLE_ONLY" if ok else "INVALID_CANDIDATE", "digit_feasibility",
                      proof_scope="FULL_ORIGINAL_CONSTRAINTS", witness=candidate, evidence=evidence)
    if contract.template_id == PRIME:
        if type(candidate) is not dict or set(candidate) != {"p", "m"} or not all(_positive(candidate[k]) for k in ("p", "m")):
            return result("UNKNOWN", "complete_positive_prime_residue_candidate_required")
        p, m = candidate["p"], candidate["m"]
        certified = _verified_prime(contract, prerequisite, meter)
        if certified is None:
            if prerequisite is not None:
                return result("UNKNOWN", "least_prime_proof_not_replayable")
            if p <= MAX_PRIME and is_prime(p, meter) and residue_holds(program, p, m, meter):
                return result("FEASIBLE_ONLY", "conditional_on_unproved_least_prime", proof_scope="CONDITIONAL_DOMAIN", witness=candidate)
            return result("UNKNOWN", "least_prime_proof_required")
        ok = p == certified and residue_holds(program, p, m, meter)
        return result("FEASIBLE_ONLY" if ok else "INVALID_CANDIDATE", "checked_prime_and_residue_constraints",
                      proof_scope="FULL_ORIGINAL_CONSTRAINTS", witness=candidate, evidence={"certified_prime": certified})
    if contract.template_id == DIVISORS and type(candidate) is dict and set(candidate) == {"divisor"}:
        k = _lcm_range(program["set_upper"], meter)
        ok, evidence = divisor_point(program, candidate["divisor"], k, meter)
    elif contract.template_id == COINS and type(candidate) is dict and set(candidate) == {"n"}:
        ok, evidence = coin_point(program, candidate["n"], meter)
    else:
        return result("UNKNOWN", "count_requires_exhaustive_program_not_scalar_point")
    return result("FEASIBLE_ONLY" if ok else "INVALID_CANDIDATE", "checked_count_membership_point",
                  proof_scope="COUNT_POINT_ONLY", witness=candidate, evidence=evidence)


def valid_claim(contract, claim):
    if type(claim) is not dict:
        return False
    kind = claim.get("kind")
    if contract.template_id == DIGITS:
        return kind == "MAX" and set(claim) == {"kind", "value"} and _positive(claim["value"])
    if contract.template_id == PRIME:
        if kind == "COMPLETE_SOLUTIONS":
            if set(claim) != {"kind", "values", "modulus"}:
                return False
            modulus, values = claim["modulus"], claim["values"]
            return (integer(modulus) and 2 <= modulus <= MAX_PRIME**2 and type(values) is list
                    and 1 <= len(values) <= min(modulus, 256)
                    and all(integer(value) and 0 <= value < modulus for value in values)
                    and len(set(values)) == len(values))
        return kind == "MIN" and set(claim) == {"kind", "value", "p"} and all(_positive(claim[key]) for key in ("value", "p"))
    program = contract.program
    if contract.template_id == DIVISORS:
        return (kind == "ALL_REMOVED_PAIR_LCM_FAILS_BOTH" and set(claim) == {"kind", "lower", "upper"}
                and integer(claim["lower"]) and integer(claim["upper"])
                and program["set_lower"] <= claim["lower"] < claim["upper"] <= program["set_upper"])
    if contract.template_id == COINS:
        return (kind == "GREEDY_RESIDUE_CLASS" and set(claim) == {"kind", "lower", "upper", "modulus", "residues", "relation"}
                and integer(claim["lower"]) and integer(claim["upper"]) and integer(claim["modulus"])
                and program["lower"] <= claim["lower"] <= claim["upper"] <= program["upper"]
                and 1 <= claim["modulus"] <= 100 and type(claim["residues"]) is list and len(claim["residues"]) <= 100
                and all(integer(r) and 0 <= r < claim["modulus"] for r in claim["residues"])
                and len(set(claim["residues"])) == len(claim["residues"]) and claim["relation"] in ("IFF", "IF", "ONLY_IF"))
    return False


def claim_math(contract, claim, witness, meter, *, certified_prime=None):
    program = contract.program
    kind = claim["kind"]
    if kind == "MAX":
        ok, evidence = digit_feasible(witness, meter)
        if ok and witness > claim["value"]:
            return result("DOMINATED_CANDIDATE", "strictly_larger_feasible_integer", proof_scope="ORIGINAL_OBJECTIVE_FALSIFICATION",
                          witness=witness, evidence=evidence)
        return result("INVALID_COUNTEREXAMPLE", "witness_does_not_dominate_maximum", witness=witness, evidence=evidence)
    if kind == "MIN":
        if certified_prime is None or claim["p"] != certified_prime:
            return result("UNKNOWN", "matching_least_prime_proof_required")
        if (type(witness) is dict and set(witness) == {"p", "m"} and integer(witness["p"]) and witness["p"] == certified_prime
                and _positive(witness["m"]) and witness["m"] < claim["value"]
                and residue_holds(program, certified_prime, witness["m"], meter)):
            return result("DOMINATED_CANDIDATE", "strictly_smaller_feasible_residue", proof_scope="ORIGINAL_OBJECTIVE_FALSIFICATION",
                          witness=witness, evidence={"certified_prime": certified_prime})
        return result("INVALID_COUNTEREXAMPLE", "witness_does_not_dominate_minimum", witness=witness)
    if kind == "COMPLETE_SOLUTIONS":
        if certified_prime is None:
            return result("UNKNOWN", "least_prime_proof_required_for_residue_completeness")
        modulus = certified_prime ** program["modulus_exponent"]
        if claim["modulus"] != modulus:
            return result("UNKNOWN", "claim_modulus_differs_from_certified_prime_square")
        if (type(witness) is not dict or set(witness) != {"p", "m"}
                or not integer(witness["p"]) or witness["p"] != certified_prime
                or not integer(witness["m"]) or not 0 <= witness["m"] < modulus):
            return result("INVALID_COUNTEREXAMPLE", "witness_outside_canonical_residue_domain", witness=witness)
        residue = witness["m"]
        if residue in claim["values"]:
            return result("INVALID_COUNTEREXAMPLE", "witness_already_listed", witness=witness)
        if not residue_holds(program, certified_prime, residue, meter):
            return result("INVALID_COUNTEREXAMPLE", "witness_does_not_satisfy_residue_equation", witness=witness)
        return result("UNIVERSAL_REFUTATION", "satisfying_residue_omitted_from_asserted_complete_set",
                      proof_scope="PARTIAL_CLAIM_REFUTATION", witness=witness,
                      evidence={"certified_prime": certified_prime, "modulus": modulus,
                                "canonical_residue_interval": [0, modulus-1], "checked_residue": residue})
    if kind == "ALL_REMOVED_PAIR_LCM_FAILS_BOTH":
        pair = witness.get("pair") if type(witness) is dict and set(witness) == {"pair"} else None
        if (type(pair) is not list or len(pair) != 2 or not all(integer(n) and claim["lower"] <= n <= claim["upper"] for n in pair)
                or pair[0] == pair[1]):
            return result("INVALID_COUNTEREXAMPLE", "removed_pair_outside_claim_domain", witness=witness)
        remainder_lcm = _lcm_range(program["set_upper"], meter, pair)
        still_divides = []
        for member in pair:
            meter.charge("removed_pair_divisibility", [remainder_lcm, member])
            if remainder_lcm % member == 0:
                still_divides.append(member)
        evidence = {"retained_lcm": remainder_lcm, "removed_members_still_dividing": still_divides}
        if still_divides:
            return result("UNIVERSAL_REFUTATION", "removed_member_still_divides_retained_lcm",
                          proof_scope="PARTIAL_CLAIM_REFUTATION", witness=witness, evidence=evidence)
        return result("INVALID_COUNTEREXAMPLE", "both_removed_members_fail_divisibility", witness=witness, evidence=evidence)
    n = witness.get("n") if type(witness) is dict and set(witness) == {"n"} else None
    if not _positive(n) or not claim["lower"] <= n <= claim["upper"]:
        return result("INVALID_COUNTEREXAMPLE", "coin_point_outside_claim_domain", witness=witness)
    optimal, evidence = coin_point(program, n, meter)
    in_class = n % claim["modulus"] in claim["residues"]
    counterexample = {"IFF": optimal != in_class, "IF": in_class and not optimal,
                      "ONLY_IF": optimal and not in_class}[claim["relation"]]
    if counterexample:
        return result("UNIVERSAL_REFUTATION", "greedy_residue_claim_violated", proof_scope="PARTIAL_CLAIM_REFUTATION",
                      witness=witness, evidence={**evidence, "in_claimed_residue_class": in_class})
    return result("INVALID_COUNTEREXAMPLE", "coin_point_does_not_refute_claim", witness=witness, evidence=evidence)


def check_candidate(contract, candidate, *, prerequisite=None, budget=MAX_BUDGET):
    meter = WorkMeter(budget)
    try:
        candidate, prerequisite = bounded_payload([candidate, prerequisite])
        check = candidate_math(contract, candidate, meter, prerequisite) if authentic(contract) else result("UNKNOWN", "unrecognized_contract")
        return finalize(contract, check, meter, {"candidate": candidate, "prerequisite": prerequisite, "budget": budget})
    except (BudgetExhausted, TypeError, ValueError, OverflowError, RecursionError) as error:
        return finalize(contract, result("UNKNOWN", str(error)), meter, None)


def check_claim_witness(contract, claim, witness, *, prerequisite=None, budget=MAX_BUDGET):
    meter = WorkMeter(budget)
    try:
        claim, witness, prerequisite = bounded_payload([claim, witness, prerequisite])
        if not authentic(contract) or not valid_claim(contract, claim):
            return finalize(contract, result("UNKNOWN", "unsupported_or_unbound_claim"), meter, None)
        p = _verified_prime(contract, prerequisite, meter) if contract.template_id == PRIME else None
        check = claim_math(contract, claim, witness, meter, certified_prime=p)
        return finalize(contract, check, meter, {"claim": claim, "witness": witness, "prerequisite": prerequisite, "budget": budget})
    except (BudgetExhausted, TypeError, ValueError, OverflowError, RecursionError) as error:
        return finalize(contract, result("UNKNOWN", str(error)), meter, None)
