"""Exact feasibility checks for reviewed direct arithmetic objectives."""
from __future__ import annotations

from fractions import Fraction

from d45_problem_specs import PROBLEMS
from feasible_witness import Feasibility


MAX_WITNESS_ABS = 1_000_000


def integer(value: object) -> int:
    if type(value) is not int or abs(value) > MAX_WITNESS_ABS:
        raise ValueError("Unsupported integer witness")
    return value


def integers(values: object, minimum: int, maximum: int) -> tuple[int, ...]:
    if not isinstance(values, list) or not minimum <= len(values) <= maximum:
        raise ValueError("Unexpected witness list length")
    return tuple(integer(v) for v in values)


def digit_sum(n: int, meter) -> int:
    total = 0
    while n > 0:
        meter.charge("decimal_digit_steps")
        n, digit = divmod(n, 10)
        total += digit
    return total


def gcd(a: int, b: int, meter) -> int:
    while b:
        meter.charge("gcd_division_steps")
        a, b = b, a % b
    return abs(a)


def factors(n: int, meter) -> dict[int, int]:
    result = {}
    p = 2
    while p * p <= n:
        meter.charge("trial_division_steps")
        quotient, remainder = divmod(n, p)
        if remainder:
            p = 3 if p == 2 else p + 2
        else:
            result[p] = result.get(p, 0) + 1
            n = quotient
    if n > 1:
        result[n] = result.get(n, 0) + 1
    return result


def prime(n: int, meter) -> bool:
    return n >= 2 and factors(n, meter) == {n: 1}


def powmod(base: int, exponent: int, modulus: int, meter) -> int:
    result = 1
    while exponent > 0:
        if exponent & 1:
            meter.charge("modular_products")
            result = (result * base) % modulus
        exponent >>= 1
        if exponent:
            meter.charge("modular_products")
            base = (base * base) % modulus
    return result


def floor_log_sum(n: int, meter) -> int:
    total = 0
    for k in range(1, 101):
        meter.charge("floor_log_terms")
        x = k * n
        while x >= 10:
            meter.charge("decimal_floor_log_steps")
            x //= 10
            total += 1
    return total


def histogram(witness, meter):
    counts = integers(witness["counts"], 4, 4)
    meter.charge("histogram_terms", 16)
    weights = tuple(range(1, 5))
    return (
        all(c >= 0 for c in counts),
        sum(counts) == 350,
        sum(c * k for c, k in zip(counts, weights)) == 513,
        sum(c * k**4 for c, k in zip(counts, weights)) == 4745,
    ), sum(c * k**2 for c, k in zip(counts, weights))


def grapes(witness, meter):
    n, m = integer(witness["winner"]), integer(witness["children"])
    meter.charge("closed_form_grape_terms", 2)
    return (n > 0, m >= 2, n + 2 - 2 * m >= 0, m * (n + 1 - m) == 2009), n


def logarithm(witness, meter):
    n = integer(witness["n"])
    return (n > 0, n > 0 and floor_log_sum(n, meter) <= 300), n


def polynomial(witness, meter):
    n = integer(witness["n"])
    a, b = (integers(witness[key], 2, 4) for key in ("left", "right"))
    coeffs = [0] * (len(a) + len(b) - 1)
    for i, left in enumerate(a):
        for j, right in enumerate(b):
            meter.charge("polynomial_product_terms")
            coeffs[i + j] += left * right
    return (n > 0, a[-1] != 0 and b[-1] != 0, coeffs == [63, -n, 0, 0, 1]), n


def dual_digit(witness, meter):
    n = integer(witness["n"])
    return (n > 0, digit_sum(n, meter) == 20, digit_sum(n + 864, meter) == 20), n


def four_prime(witness, meter):
    m = integer(witness["m"])
    ps = integers(witness["primes"], 0, 32)
    all_prime = all(prime(p, meter) for p in ps)
    product = 1
    for p in ps:
        meter.charge("factor_product_terms")
        product *= p
    return (m > 0, len(ps) >= 4, all_prime, product == m * m - m + 11), m


def mixed_radix(witness, meter):
    a, b, c = (integer(witness[key]) for key in ("a", "b", "c"))
    meter.charge("radix_horner_steps", 5)
    base_eleven = (11 * a + b) * 11 + c
    base_eight = ((8 + b) * 8 + c) * 8 + a
    return (all(0 <= d <= 7 for d in (a, b, c)), a > 0, base_eight == base_eleven), base_eleven


def power_divisibility(witness, meter):
    m, n = (integer(witness[key]) for key in ("m", "n"))
    positive = m > 0 and n > 0
    total = m + n
    prime_m, prime_n = factors(m, meter), factors(n, meter)
    divides = True
    for p, v in prime_n.items():
        meter.charge("prime_valuation_comparisons")
        divides = divides and m * prime_m.get(p, 0) >= n * v
    return (positive, gcd(total, 210, meter) == 1, positive and divides, positive and m % n != 0), total


def modular_index(witness, meter):
    n = integer(witness["n"])
    result = (powmod(2, n, 1000, meter) + powmod(5, n, 1000, meter) - n) % 1000
    return (n > 0, result == 0), n


def adults(witness, meter):
    crowd, bus = (integer(witness[key]) for key in ("initial_crowd", "bus_adults"))
    meter.charge("exact_population_relations", 3)
    initial_adults, remainder = divmod(5 * crowd, 12)
    total = initial_adults + bus
    return (crowd > 0, remainder == 0, 0 <= bus <= 50, 25 * total == 11 * (crowd + 50)), total


def complex_prime(witness, meter):
    p, a, b = (integer(witness[key]) for key in ("p", "a", "b"))
    meter.charge("complex_cubic_components", 2)
    x, y = a**3 - 3 * a * b**2, 3 * a**2 * b - b**3
    return (2 <= p < 1000 and prime(p, meter), a*a + b*b == p,
            x > 0 and y > 0, p + x > y and p + y > x and x + y > p), p


FUNCTIONS = dict(zip(PROBLEMS, (
    histogram, grapes, logarithm, polynomial, dual_digit, four_prime, mixed_radix,
    power_divisibility, modular_index, adults, complex_prime,
), strict=True))
CASE_IDS = {spec["objective_id"]: cid for cid, spec in PROBLEMS.items()}


def check(binding, witness: dict, meter) -> Feasibility:
    cid = CASE_IDS[binding.objective_id]
    spec = PROBLEMS[cid]
    if binding.direction != spec["direction"] or set(witness) != set(spec["fields"]):
        raise ValueError("Wrong reviewed objective or witness fields")
    flags, value = FUNCTIONS[cid](witness, meter)
    constraints = tuple(zip(spec["constraints"], flags, strict=True))
    for name, _ in constraints:
        meter.charge(f"constraint:{name}")
    if not all(flags):
        return Feasibility(constraints, None)
    meter.charge("objective")
    return Feasibility(constraints, Fraction(value))
