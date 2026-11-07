"""Bounded, exact checks on structured statements from an owned evidence snapshot.

The adapter owns target and premises. Request data supplies an exact snapshot
binding and, for a counterexample, a point to check. The output certifies the
scoped statement represented by the target.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from math import gcd
import re


CHECKER_ID = "restricted-math-json-v1"
LIMITS = {
    "input_nodes": 4096,
    "input_depth": 32,
    "input_text_characters": 65536,
    "input_integer_bits": 256,
    "variables": 4,
    "premises": 16,
    "constraints": 24,
    "domain_values": 64,
    "exponent": 12,
    "polynomial_degree": 24,
    "polynomial_terms": 256,
    "coefficient_bits": 1024,
    "original_guards": 48,
    "witness_points": 128,
    "work_units": 60000,
}
CERTIFICATE_TYPES = frozenset({
    "ARITHMETIC_EQ", "POLYNOMIAL_IDENTITY", "POLYNOMIAL_DIVISIBILITY",
    "SUBSTITUTION", "DOMAIN_PREDICATE",
})
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.:@-]{0,95}\Z")
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}\Z")
RELATIONS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})


class Unresolved(ValueError):
    def __init__(self, reason, detail=None):
        self.reason = reason
        self.detail = detail
        super().__init__(reason)


class Undefined(Unresolved):
    pass


@dataclass
class WorkBudget:
    used: int = 0

    def charge(self, units=1):
        self.used += units
        if self.used > LIMITS["work_units"]:
            raise Unresolved("work_limit")


def _digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256(data.encode("ascii")).hexdigest()


def _keys(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) <= set(required) | set(optional):
        raise Unresolved("schema_mismatch")


def _bounded_json(*roots):
    remaining = LIMITS["input_nodes"]
    text_remaining = LIMITS["input_text_characters"]

    def visit(value, depth):
        nonlocal remaining, text_remaining
        remaining -= 1
        if remaining < 0 or depth > LIMITS["input_depth"]:
            raise Unresolved("input_structure_limit")
        if type(value) in (list, tuple):
            if len(value) > remaining:
                raise Unresolved("input_structure_limit")
            for item in value:
                visit(item, depth + 1)
        elif type(value) is dict:
            if len(value) > remaining:
                raise Unresolved("input_structure_limit")
            for key, item in value.items():
                if type(key) is not str or len(key) > 96:
                    raise Unresolved("invalid_key")
                text_remaining -= len(key)
                visit(item, depth + 1)
        elif type(value) is int:
            if abs(value).bit_length() > LIMITS["input_integer_bits"]:
                raise Unresolved("input_integer_limit")
        elif type(value) is str:
            if len(value) > 2048:
                raise Unresolved("input_text_limit")
            text_remaining -= len(value)
        elif value is not None and type(value) is not bool:
            raise Unresolved("non_json_value")
        if text_remaining < 0:
            raise Unresolved("input_text_limit")

    for root in roots:
        visit(root, 0)


def _id(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise Unresolved("invalid_identity")


def _version(value):
    if type(value) is not int or value < 0:
        raise Unresolved("invalid_version")


def _fraction(value):
    if type(value) is int:
        return Fraction(value)
    _keys(value, ("op", "num", "den"))
    if value["op"] != "rat" or type(value["num"]) is not int or type(value["den"]) is not int:
        raise Unresolved("exact_rational_required")
    if value["den"] == 0:
        raise Undefined("zero_denominator")
    return Fraction(value["num"], value["den"])


def _bound_coefficient(value):
    if max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > LIMITS["coefficient_bits"]:
        raise Unresolved("coefficient_limit")
    return value


@dataclass(frozen=True)
class Domain:
    kind: str
    lower: Fraction | None
    upper: Fraction | None
    lower_closed: bool
    upper_closed: bool
    exclude: tuple[Fraction, ...]
    values: tuple[Fraction, ...] | None

    def permits(self, value):
        if self.kind == "integer" and value.denominator != 1:
            return False
        if self.lower is not None and (value < self.lower or value == self.lower and not self.lower_closed):
            return False
        if self.upper is not None and (value > self.upper or value == self.upper and not self.upper_closed):
            return False
        return value not in self.exclude and (self.values is None or value in self.values)

    def samples(self):
        """Return deterministic rational samples and exact finite-coverage flag."""
        if self.values is not None:
            return tuple(value for value in self.values if self.permits(value)), True
        if self.lower is not None and self.lower == self.upper:
            return (self.lower,) if self.permits(self.lower) else (), True
        if self.kind == "integer" and self.lower is not None and self.upper is not None:
            first = -((-self.lower.numerator) // self.lower.denominator)
            last = self.upper.numerator // self.upper.denominator
            first += int(self.lower == first and not self.lower_closed)
            last -= int(self.upper == last and not self.upper_closed)
            if last - first + 1 <= LIMITS["witness_points"]:
                return tuple(Fraction(value) for value in range(first, last + 1) if self.permits(Fraction(value))), True
        candidates = [Fraction(0)]
        for n in range(1, 17):
            candidates.extend((Fraction(n), Fraction(-n)))
        candidates.extend((Fraction(1, 2), Fraction(-1, 2)))
        if self.lower is not None:
            floor = self.lower.numerator // self.lower.denominator
            candidates.extend(Fraction(floor + n) for n in range(18))
            candidates.extend((self.lower, self.lower + Fraction(1, 2)))
        if self.upper is not None:
            floor = self.upper.numerator // self.upper.denominator
            candidates.extend(Fraction(floor - n) for n in range(18))
            candidates.extend((self.upper, self.upper - Fraction(1, 2)))
        if self.lower is not None and self.upper is not None:
            candidates.extend(self.lower + (self.upper - self.lower) * Fraction(n, 17) for n in range(1, 17))
        return tuple(dict.fromkeys(value for value in candidates if self.permits(value))), False


def _domain(value):
    _keys(value, ("kind",), ("lower", "upper", "lower_closed", "upper_closed", "exclude", "values"))
    if value["kind"] not in ("integer", "rational", "real"):
        raise Unresolved("unsupported_domain")
    lower = _fraction(value["lower"]) if "lower" in value else None
    upper = _fraction(value["upper"]) if "upper" in value else None
    lower_closed = value.get("lower_closed", True)
    upper_closed = value.get("upper_closed", True)
    if type(lower_closed) is not bool or type(upper_closed) is not bool:
        raise Unresolved("invalid_domain_endpoint")
    if lower is not None and upper is not None and lower > upper:
        raise Unresolved("inconsistent_domain_bounds")

    def finite_list(items):
        if type(items) is not list or len(items) > LIMITS["domain_values"]:
            raise Unresolved("domain_list_limit")
        return tuple(sorted({_fraction(item) for item in items}))

    return Domain(value["kind"], lower, upper, lower_closed, upper_closed,
                  finite_list(value.get("exclude", [])),
                  finite_list(value["values"]) if "values" in value else None)


def _premise_ref(record):
    ref = {field: record[field] for field in ("id", "version", "scope_id", "scope_version")}
    _id(ref["id"])
    _id(ref["scope_id"])
    _version(ref["version"])
    _version(ref["scope_version"])
    return ref


def _snapshot(target, premises):
    _keys(target, ("id", "version", "kind", "scope", "certificate_type", "statement", "required_premises"),
          ("source_span", "observed_prefix_sha256"))
    _id(target["id"])
    _version(target["version"])
    if target["kind"] not in ("claim", "justification") or target["certificate_type"] not in CERTIFICATE_TYPES:
        raise Unresolved("unsupported_target")
    scope = target["scope"]
    _keys(scope, ("id", "version", "coefficient_domain", "domains"))
    _id(scope["id"])
    _version(scope["version"])
    if scope["coefficient_domain"] not in ("Q", "Z"):
        raise Unresolved("unsupported_coefficient_domain")
    if type(scope["domains"]) is not dict or len(scope["domains"]) > LIMITS["variables"]:
        raise Unresolved("domain_variable_limit")
    for name in scope["domains"]:
        if not VARIABLE.fullmatch(name):
            raise Unresolved("invalid_variable")
    domains = {name: _domain(value) for name, value in sorted(scope["domains"].items())}
    if "source_span" in target:
        span = target["source_span"]
        if type(span) is not list or len(span) != 2 or any(type(n) is not int or n < 0 for n in span) or span[1] < span[0]:
            raise Unresolved("invalid_source_span")
    if "observed_prefix_sha256" in target:
        prefix_hash = target["observed_prefix_sha256"]
        if type(prefix_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", prefix_hash):
            raise Unresolved("invalid_prefix_binding")
    required = target["required_premises"]
    if type(required) is not list or len(required) > LIMITS["premises"] or type(premises) not in (list, tuple) or len(premises) > LIMITS["premises"]:
        raise Unresolved("premise_limit")
    ref_fields = ("id", "version", "scope_id", "scope_version")
    required_refs = {}
    for ref in required:
        _keys(ref, ref_fields)
        checked = _premise_ref(ref)
        if checked["id"] in required_refs:
            raise Unresolved("duplicate_required_premise")
        required_refs[checked["id"]] = checked
    supplied_refs = {}
    records = {}
    for premise in premises:
        _keys(premise, (*ref_fields, "predicate"), ("evidence_id",))
        ref = _premise_ref(premise)
        if ref["id"] in supplied_refs:
            raise Unresolved("duplicate_premise")
        supplied_refs[ref["id"]] = ref
        records[ref["id"]] = premise
    if supplied_refs != required_refs:
        raise Unresolved("premise_set_or_version_mismatch")
    for ref in supplied_refs.values():
        if (ref["scope_id"], ref["scope_version"]) != (scope["id"], scope["version"]):
            raise Unresolved("premise_scope_mismatch")
    ordered = [records[name] for name in sorted(records)]
    binding = {
        "target": {"id": target["id"], "version": target["version"], "sha256": _digest(target)},
        "scope": {"id": scope["id"], "version": scope["version"], "sha256": _digest(scope)},
        "premises": [{**_premise_ref(record), "sha256": _digest(record)} for record in ordered],
    }
    return binding, domains, ordered


def make_request(target, premises=(), *, mode="verify", assignment=None):
    """Build a request from a caller-owned snapshot after resolving source spans."""
    _bounded_json(target, premises, mode, assignment)
    binding, _, _ = _snapshot(target, premises)
    request = {"binding": binding, "mode": mode}
    if assignment is not None:
        request["assignment"] = assignment
    return request


def _expression(node, algebra, budget, depth=0):
    budget.charge()
    if depth > LIMITS["input_depth"]:
        raise Unresolved("expression_depth")
    if type(node) is int or type(node) is dict and node.get("op") == "rat":
        return algebra.constant(_fraction(node))
    if type(node) is not dict or type(node.get("op")) is not str:
        raise Unresolved("structured_expression_required")
    op = node["op"]

    def child(value):
        return _expression(value, algebra, budget, depth + 1)

    if op == "var":
        _keys(node, ("op", "name"))
        if type(node["name"]) is not str:
            raise Unresolved("invalid_variable")
        return algebra.variable(node["name"])
    if op == "neg":
        _keys(node, ("op", "arg"))
        return algebra.multiply(algebra.constant(Fraction(-1)), child(node["arg"]))
    if op in ("add", "mul"):
        _keys(node, ("op", "args"))
        if type(node["args"]) is not list or not 2 <= len(node["args"]) <= 8:
            raise Unresolved("expression_arity")
        operation = algebra.add if op == "add" else algebra.multiply
        values = [child(arg) for arg in node["args"]]
        result = values[0]
        for value in values[1:]:
            result = operation(result, value)
        return result
    if op in ("sub", "div"):
        _keys(node, ("op", "lhs", "rhs"))
        left, right = child(node["lhs"]), child(node["rhs"])
        if op == "div":
            return algebra.divide(left, right)
        return algebra.add(left, algebra.multiply(algebra.constant(Fraction(-1)), right))
    if op == "pow":
        _keys(node, ("op", "base", "exp"))
        if type(node["exp"]) is not int or abs(node["exp"]) > LIMITS["exponent"]:
            raise Unresolved("exponent_limit")
        return algebra.power(child(node["base"]), node["exp"])
    raise Unresolved("unsupported_expression_operator")


class ScalarAlgebra:
    def __init__(self, values, budget):
        self.values = values
        self.budget = budget

    def constant(self, value):
        return value

    def variable(self, name):
        if name not in self.values:
            raise Unresolved("unbound_variable")
        return self.values[name]

    def add(self, left, right):
        self.budget.charge()
        return _bound_coefficient(left + right)

    def multiply(self, left, right):
        self.budget.charge()
        return _bound_coefficient(left * right)

    def divide(self, left, right):
        self.budget.charge()
        if not right:
            raise Undefined("zero_denominator")
        return _bound_coefficient(left / right)

    def power(self, base, exponent):
        self.budget.charge(max(1, abs(exponent)))
        if not base and exponent <= 0:
            raise Undefined("zero_to_nonpositive_power")
        magnitude = max(abs(base.numerator).bit_length(), base.denominator.bit_length())
        if magnitude * abs(exponent) > LIMITS["coefficient_bits"]:
            raise Unresolved("coefficient_limit")
        return _bound_coefficient(base ** exponent)


def _relation(op, left, right):
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    return left >= right


def _predicate(predicate, values, budget):
    if type(predicate) is not dict or type(predicate.get("op")) is not str:
        raise Unresolved("structured_predicate_required")
    op = predicate["op"]
    algebra = ScalarAlgebra(values, budget)

    def expression(node):
        return _expression(node, algebra, budget)

    if op in RELATIONS:
        _keys(predicate, ("op", "lhs", "rhs"))
        left, right = expression(predicate["lhs"]), expression(predicate["rhs"])
        return _relation(op, left, right), {"lhs": str(left), "rhs": str(right), "op": op}
    if op in ("is_integer", "positive", "nonnegative"):
        _keys(predicate, ("op", "arg"))
        value = expression(predicate["arg"])
        if op == "is_integer": truth = value.denominator == 1
        elif op == "positive": truth = value > 0
        else: truth = value >= 0
        return truth, {"value": str(value), "op": op}
    if op == "in_domain":
        _keys(predicate, ("op", "arg", "domain"))
        value = expression(predicate["arg"])
        return _domain(predicate["domain"]).permits(value), {"value": str(value), "op": op}
    if op == "coprime":
        _keys(predicate, ("op", "lhs", "rhs"))
        left, right = expression(predicate["lhs"]), expression(predicate["rhs"])
        if left.denominator != 1 or right.denominator != 1:
            raise Undefined("coprime_requires_integers")
        common = gcd(left.numerator, right.numerator)
        return common == 1, {"lhs": str(left), "rhs": str(right), "gcd": common, "op": op}
    if op == "distinct":
        _keys(predicate, ("op", "args"))
        if type(predicate["args"]) is not list or not 2 <= len(predicate["args"]) <= 16:
            raise Unresolved("predicate_arity")
        points = [expression(node) for node in predicate["args"]]
        return len(set(points)) == len(points), {"values": [str(point) for point in points], "op": op}
    if op == "vector_dimension":
        _keys(predicate, ("op", "items", "size"))
        if type(predicate["items"]) is not list or len(predicate["items"]) > 16 or type(predicate["size"]) is not int or not 0 <= predicate["size"] <= 16:
            raise Unresolved("invalid_vector_shape")
        for node in predicate["items"]:
            expression(node)
        size = len(predicate["items"])
        return size == predicate["size"], {"observed": size, "required": predicate["size"], "op": op}
    raise Unresolved("unsupported_predicate_operator")


def _poly_key(polynomial):
    return tuple(sorted(polynomial.items()))


def _poly_summary(polynomial):
    terms = [{"exponents": list(key), "coefficient": str(value)} for key, value in _poly_key(polynomial)]
    return {"term_count": len(terms), "terms": terms[:16], "sha256": _digest(terms)}


@dataclass(frozen=True)
class RationalPolynomial:
    numerator: dict
    denominator: dict
    guards: tuple[dict, ...] = ()


class PolynomialAlgebra:
    def __init__(self, variables, budget):
        self.variables = tuple(variables)
        self.zero_exponents = (0,) * len(self.variables)
        self.unit = {self.zero_exponents: Fraction(1)}
        self.budget = budget

    def polynomial_constant(self, value):
        return {self.zero_exponents: value} if value else {}

    def constant(self, value):
        return RationalPolynomial(self.polynomial_constant(value), self.unit)

    def variable(self, name):
        if name not in self.variables:
            raise Unresolved("undeclared_symbol")
        exponents = tuple(int(variable == name) for variable in self.variables)
        return RationalPolynomial({exponents: Fraction(1)}, self.unit)

    def _put(self, result, key, value):
        value = _bound_coefficient(value)
        if value:
            if sum(key) > LIMITS["polynomial_degree"]:
                raise Unresolved("polynomial_degree_limit")
            result[key] = value
            if len(result) > LIMITS["polynomial_terms"]:
                raise Unresolved("polynomial_term_limit")
        else:
            result.pop(key, None)

    def polynomial_add(self, left, right, sign=1):
        self.budget.charge(len(left) + len(right))
        result = dict(left)
        for key, value in right.items():
            self._put(result, key, result.get(key, Fraction(0)) + sign * value)
        return result

    def polynomial_multiply(self, left, right):
        self.budget.charge(len(left) * len(right))
        result = {}
        for a, coefficient_a in left.items():
            for b, coefficient_b in right.items():
                key = tuple(x + y for x, y in zip(a, b))
                self._put(result, key, result.get(key, Fraction(0)) + coefficient_a * coefficient_b)
        return result

    def _guards(self, *groups):
        unique = {}
        for group in groups:
            for polynomial in group:
                self.budget.charge(1 + len(polynomial))
                unique.setdefault(_poly_key(polynomial), polynomial)
        if len(unique) > LIMITS["original_guards"]:
            raise Unresolved("original_guard_limit")
        return tuple(unique.values())

    def _rational(self, numerator, denominator, guards):
        if not denominator:
            raise Undefined("identically_zero_denominator")
        if set(denominator) == {self.zero_exponents}:
            factor = denominator[self.zero_exponents]
            self.budget.charge(len(numerator))
            numerator = {key: _bound_coefficient(value / factor) for key, value in numerator.items()}
            denominator = self.unit
        return RationalPolynomial(numerator, denominator, guards)

    def add(self, left, right):
        first = self.polynomial_multiply(left.numerator, right.denominator)
        second = self.polynomial_multiply(right.numerator, left.denominator)
        denominator = self.polynomial_multiply(left.denominator, right.denominator)
        return self._rational(self.polynomial_add(first, second), denominator, self._guards(left.guards, right.guards))

    def multiply(self, left, right):
        numerator = self.polynomial_multiply(left.numerator, right.numerator)
        denominator = self.polynomial_multiply(left.denominator, right.denominator)
        return self._rational(numerator, denominator, self._guards(left.guards, right.guards))

    def divide(self, left, right):
        numerator = self.polynomial_multiply(left.numerator, right.denominator)
        denominator = self.polynomial_multiply(left.denominator, right.numerator)
        return self._rational(numerator, denominator, self._guards(left.guards, right.guards, (right.numerator,)))

    def power(self, base, exponent):
        if exponent == 0:
            return RationalPolynomial(self.unit, self.unit, self._guards(base.guards, (base.numerator,)))
        if exponent < 0:
            base = self.divide(self.constant(Fraction(1)), base)
            exponent = -exponent
        result = self.constant(Fraction(1))
        for _ in range(exponent):
            result = self.multiply(result, base)
        return result

    def evaluate(self, polynomial, assignment):
        value = Fraction(0)
        scalar = ScalarAlgebra(assignment, self.budget)
        for key, coefficient in polynomial.items():
            term = coefficient
            for variable, exponent in zip(self.variables, key):
                if exponent:
                    term = scalar.multiply(term, scalar.power(assignment[variable], exponent))
            value = scalar.add(value, term)
        return value

    def substitute(self, polynomial, fixed):
        self.budget.charge(len(polynomial))
        result = {}
        scalar = ScalarAlgebra(fixed, self.budget)
        for key, value in polynomial.items():
            powers = list(key)
            for i, variable in enumerate(self.variables):
                if variable in fixed and powers[i]:
                    value = scalar.multiply(value, scalar.power(fixed[variable], powers[i]))
                    powers[i] = 0
            new_key = tuple(powers)
            self._put(result, new_key, result.get(new_key, Fraction(0)) + value)
        return result

    def divide_polynomials(self, dividend, divisor):
        if not divisor:
            raise Undefined("zero_polynomial_divisor")
        quotient, remainder = {}, {}
        working = dict(dividend)
        lead_divisor = max(divisor)
        while working:
            self.budget.charge(len(working))
            lead = max(working)
            exponent_delta = tuple(a - b for a, b in zip(lead, lead_divisor))
            if min(exponent_delta, default=0) < 0:
                self._put(remainder, lead, working.pop(lead))
                continue
            factor = _bound_coefficient(working[lead] / divisor[lead_divisor])
            term = {exponent_delta: factor}
            quotient = self.polynomial_add(quotient, term)
            working = self.polynomial_add(working, self.polynomial_multiply(term, divisor), sign=-1)
        return quotient, remainder


def _point_values(value, domains):
    if type(value) is not dict or set(value) != set(domains):
        raise Unresolved("complete_assignment_required")
    return {key: _fraction(value[key]) for key in sorted(value)}


def _scope_at(values, domains, premises, budget):
    excluded = [name for name, domain in domains.items() if not domain.permits(values[name])]
    if excluded:
        return False, {"outside_domains": excluded}
    failed = []
    for record in premises:
        truth, _ = _predicate(record["predicate"], values, budget)
        if not truth:
            failed.append(record["id"])
    return not failed, {"violated_premises": failed}


def _grounded_values(domains, premises, budget):
    fixed = {}
    for name, domain in domains.items():
        values, complete = domain.samples()
        if complete and len(values) == 1:
            fixed[name] = values[0]
    while True:
        before = len(fixed)
        for premise in premises:
            predicate = premise["predicate"]
            if type(predicate) is not dict or predicate.get("op") != "eq":
                continue
            _keys(predicate, ("op", "lhs", "rhs"))
            for variable, expression in ((predicate["lhs"], predicate["rhs"]), (predicate["rhs"], predicate["lhs"])):
                if type(variable) is not dict or variable.get("op") != "var":
                    continue
                _keys(variable, ("op", "name"))
                name = variable["name"]
                if name not in domains:
                    raise Unresolved("undeclared_symbol")
                try:
                    value = _expression(expression, ScalarAlgebra(fixed, budget), budget)
                except Unresolved as exc:
                    if exc.reason == "unbound_variable":
                        continue
                    raise
                if (name in fixed and fixed[name] != value) or not domains[name].permits(value):
                    raise Unresolved("inconsistent_grounding")
                fixed[name] = value
        if before == len(fixed):
            return fixed


def _ordered_points(domains, fixed):
    names = tuple(domains)
    choices = []
    exhaustive = True
    combinations = 1
    for name in names:
        values, complete = ((fixed[name],), True) if name in fixed else domains[name].samples()
        choices.append(values)
        exhaustive = exhaustive and complete
        combinations *= len(values)
    if not combinations:
        return [], exhaustive
    if exhaustive and combinations <= LIMITS["witness_points"]:
        return [dict(zip(names, values)) for values in product(*choices)], True
    # Breadth first over index tuples so early variables vary as well as late ones.
    zero = (0,) * len(names)
    queued = [zero]
    seen = {zero}
    points = []
    for indices in queued:
        points.append({name: choices[i][index] for i, (name, index) in enumerate(zip(names, indices))})
        if len(points) >= LIMITS["witness_points"]:
            break
        for i, index in enumerate(indices):
            if index + 1 < len(choices[i]):
                neighbor = indices[:i] + (index + 1,) + indices[i + 1:]
                if neighbor not in seen:
                    seen.add(neighbor)
                    queued.append(neighbor)
    return points, False


def _feasible_points(domains, premises, fixed, budget):
    points, complete = _ordered_points(domains, fixed)
    feasible = []
    for point in points:
        try:
            valid, _ = _scope_at(point, domains, premises, budget)
        except Undefined:
            if complete:
                raise Unresolved("undefined_premise_in_finite_scope")
            continue
        if valid:
            feasible.append(point)
    if not feasible:
        raise Unresolved("no_feasible_scope_witness")
    return feasible, complete


def _nonzero_key(polynomial):
    if not polynomial:
        return ()
    scale = polynomial[max(polynomial)]
    return tuple(sorted((key, _bound_coefficient(value / scale)) for key, value in polynomial.items()))


def _domain_guard(polynomial, algebra, domains, fixed):
    reduced = algebra.substitute(polynomial, fixed)
    if set(reduced) == {algebra.zero_exponents}:
        return {"type": "nonzero_constant_after_grounding"}
    nonconstant = [(key, coefficient) for key, coefficient in reduced.items() if key != algebra.zero_exponents]
    if len(nonconstant) == 1 and sum(nonconstant[0][0]) == 1:
        exponents, coefficient = nonconstant[0]
        variable = algebra.variables[exponents.index(1)]
        root = _bound_coefficient(-reduced.get(algebra.zero_exponents, Fraction(0)) / coefficient)
        if not domains[variable].permits(root):
            return {"type": "linear_root_excluded_by_domain", "variable": variable, "root": str(root)}
    return None


def _check_guards(guards, algebra, domains, fixed, premises, points, exhaustive):
    premise_guards = {}
    for record in premises:
        predicate = record["predicate"]
        op = predicate.get("op") if type(predicate) is dict else None
        if op in ("ne", "lt", "gt"):
            left = _expression(predicate["lhs"], algebra, algebra.budget)
            right = _expression(predicate["rhs"], algebra, algebra.budget)
        elif op == "positive":
            left = _expression(predicate["arg"], algebra, algebra.budget)
            right = algebra.constant(Fraction(0))
        else:
            continue
        if left.denominator != algebra.unit or right.denominator != algebra.unit:
            continue
        # A premise with its own unresolved denominator cannot discharge a guard.
        if any(_domain_guard(guard, algebra, domains, fixed) is None for guard in (*left.guards, *right.guards)):
            continue
        difference = algebra.polynomial_add(left.numerator, right.numerator, sign=-1)
        if difference:
            premise_guards[_nonzero_key(difference)] = record["id"]
    checked = []
    for guard in algebra._guards(guards):
        proof = _domain_guard(guard, algebra, domains, fixed)
        if proof is None and _nonzero_key(guard) in premise_guards:
            proof = {"type": "explicit_nonzero_premise", "premise": premise_guards[_nonzero_key(guard)]}
        if proof is None and exhaustive and all(algebra.evaluate(guard, point) != 0 for point in points):
            proof = {"type": "exhaustive_scope", "points": len(points)}
        if proof is None:
            raise Unresolved("original_denominator_guard_unproven", {"unproven_guard": _poly_summary(guard)})
        checked.append({"polynomial": _poly_summary(guard), **proof})
    return checked


def _coefficient_membership(polynomials, domain):
    if domain == "Z" and any(value.denominator != 1 for polynomial in polynomials for value in polynomial.values()):
        raise Unresolved("outside_integer_coefficient_ring")


def _equality_at(statement, values, budget):
    algebra = ScalarAlgebra(values, budget)
    left = _expression(statement["lhs"], algebra, budget)
    right = _expression(statement["rhs"], algebra, budget)
    return left == right, {"lhs": str(left), "rhs": str(right)}


def _assignment_summary(values):
    return {name: str(value) for name, value in sorted(values.items())}


def _point_assertion(target, values, budget):
    statement = target["statement"]
    kind = target["certificate_type"]
    if kind in ("ARITHMETIC_EQ", "POLYNOMIAL_IDENTITY"):
        return _equality_at(statement, values, budget)
    if kind == "DOMAIN_PREDICATE":
        return _predicate(statement["predicate"], values, budget)
    checks = []
    for constraint in statement["constraints"]:
        truth, witness = _predicate(constraint, values, budget)
        checks.append({"satisfied": truth, **witness})
    return all(check["satisfied"] for check in checks), {"constraints": checks}


def _statement_shape(target):
    kind = target["certificate_type"]
    statement = target["statement"]
    if kind == "ARITHMETIC_EQ":
        _keys(statement, ("lhs", "rhs"))
    elif kind == "POLYNOMIAL_IDENTITY":
        _keys(statement, ("lhs", "rhs"), ("semantics",))
        if statement.get("semantics", "scoped") not in ("scoped", "formal"):
            raise Unresolved("unsupported_identity_semantics")
    elif kind == "POLYNOMIAL_DIVISIBILITY":
        _keys(statement, ("dividend", "divisor"))
    elif kind == "SUBSTITUTION":
        _keys(statement, ("assignment", "constraints"))
        if type(statement["constraints"]) is not list or not 1 <= len(statement["constraints"]) <= LIMITS["constraints"]:
            raise Unresolved("complete_constraints_required")
    else:
        _keys(statement, ("predicate",), ("assignment",))


def _symbolic_assertion(target, domains, premises, budget):
    fixed = _grounded_values(domains, premises, budget)
    points, exhaustive = _feasible_points(domains, premises, fixed, budget)
    algebra = PolynomialAlgebra(domains, budget)
    statement = target["statement"]
    ring = target["scope"]["coefficient_domain"]
    divisibility = target["certificate_type"] == "POLYNOMIAL_DIVISIBILITY"
    names = ("dividend", "divisor") if divisibility else ("lhs", "rhs")
    left = _expression(statement[names[0]], algebra, budget)
    right = _expression(statement[names[1]], algebra, budget)
    guards = _check_guards((*left.guards, *right.guards), algebra, domains, fixed, premises, points, exhaustive)
    witness = {"variables": list(domains), "coefficient_domain": ring, "original_denominator_checks": guards}
    _coefficient_membership((left.numerator, left.denominator, right.numerator, right.denominator), ring)
    if divisibility:
        if left.denominator != algebra.unit or right.denominator != algebra.unit:
            raise Unresolved("polynomial_expression_required")
        quotient, remainder = algebra.divide_polynomials(left.numerator, right.numerator)
        in_ring = ring == "Q" or all(value.denominator == 1 for value in quotient.values())
        witness.update(semantics="formal_polynomial_divisibility", quotient=_poly_summary(quotient),
                       remainder=_poly_summary(remainder), quotient_in_coefficient_ring=in_ring)
        return not remainder and in_ring, witness

    formal = statement.get("semantics", "scoped") == "formal"
    if formal and (left.denominator != algebra.unit or right.denominator != algebra.unit):
        raise Unresolved("polynomial_expression_required")
    cross_left = algebra.polynomial_multiply(left.numerator, right.denominator)
    cross_right = algebra.polynomial_multiply(right.numerator, left.denominator)
    difference = algebra.polynomial_add(cross_left, cross_right, sign=-1)
    witness["normalized_difference"] = _poly_summary(difference)
    if formal:
        witness["semantics"] = "formal_polynomial_coefficients"
        return not difference, witness
    witness["semantics"] = "scoped_equality_with_original_definedness"
    if not difference:
        return True, witness
    # A nonzero formal difference may vanish on a restricted scope. Check a
    # feasible point against the original expression before classifying it.
    for point in points:
        truth, values = _equality_at(statement, point, budget)
        if not truth:
            witness["counterexample"] = {"assignment": _assignment_summary(point), **values}
            return False, witness
    if exhaustive:
        witness["exhaustive_scope_points"] = len(points)
        return True, witness
    raise Unresolved("no_scoped_counterexample_within_witness_bound")


def _evaluate(request, target, domains, premises, budget):
    _statement_shape(target)
    mode, kind, statement = request["mode"], target["certificate_type"], target["statement"]
    if mode == "counterexample":
        if kind == "POLYNOMIAL_DIVISIBILITY":
            raise Unresolved("point_is_not_ring_divisibility_evidence")
        values = _point_values(request.get("assignment"), domains)
        if "assignment" in statement and values != _point_values(statement["assignment"], domains):
            return None, {"assignment": _assignment_summary(values)}, "different_frozen_candidate"
        in_scope, detail = _scope_at(values, domains, premises, budget)
        if not in_scope:
            return None, {"assignment": _assignment_summary(values), **detail}, "counterexample_outside_scope"
        if kind == "POLYNOMIAL_IDENTITY":
            algebra = PolynomialAlgebra(domains, budget)
            left = _expression(statement["lhs"], algebra, budget)
            right = _expression(statement["rhs"], algebra, budget)
            _coefficient_membership((left.numerator, left.denominator, right.numerator, right.denominator),
                                    target["scope"]["coefficient_domain"])
            if statement.get("semantics", "scoped") == "formal" and (left.denominator != algebra.unit or right.denominator != algebra.unit):
                raise Unresolved("polynomial_expression_required")
        truth, witness = _point_assertion(target, values, budget)
        witness["assignment"] = _assignment_summary(values)
        if truth:
            return None, witness, "counterexample_satisfies_statement"
        return False, witness, "checked_scoped_counterexample"

    if kind in ("POLYNOMIAL_IDENTITY", "POLYNOMIAL_DIVISIBILITY"):
        if "assignment" in request:
            raise Unresolved("assignment_only_for_point_check")
        truth, witness = _symbolic_assertion(target, domains, premises, budget)
        return truth, witness, "checked_exact_symbolic_statement"

    frozen_candidate = "assignment" in statement
    if frozen_candidate:
        values = _point_values(statement["assignment"], domains)
    else:
        values = _grounded_values(domains, premises, budget)
        if set(values) != set(domains):
            raise Unresolved("point_values_need_trusted_grounding")
    if "assignment" in request and _point_values(request["assignment"], domains) != values:
        raise Unresolved("assignment_binding_mismatch")
    in_scope, detail = _scope_at(values, domains, premises, budget)
    if not in_scope:
        if frozen_candidate:
            return False, {"assignment": _assignment_summary(values), **detail}, "frozen_candidate_violates_scope"
        raise Unresolved("inconsistent_grounded_scope")
    truth, witness = _point_assertion(target, values, budget)
    witness["assignment"] = _assignment_summary(values)
    witness["semantics"] = "declared_constraint_conjunction" if kind == "SUBSTITUTION" else "scoped_point_statement"
    return truth, witness, "checked_exact_point_statement"


def verify(request, *, target, premises=()):
    """Verify against the caller-owned complete target/scope/premise snapshot.

    PASS denotes an established scoped result or valid refutation. FAIL denotes
    a rejected counterexample proposal. Truth and status specify the distinction.
    """
    budget = WorkBudget()
    trace = []
    binding = None
    detail = None
    try:
        _bounded_json(request, target, premises)
        # Hold a detached snapshot throughout the binding check and arithmetic.
        request, target, premises = json.loads(json.dumps([request, target, premises]))
        _keys(request, ("binding", "mode"), ("assignment",))
        if request["mode"] not in ("verify", "counterexample"):
            raise Unresolved("unsupported_request_mode")
        binding, domains, ordered = _snapshot(target, premises)
        if _digest(request["binding"]) != _digest(binding):
            raise Unresolved("snapshot_binding_mismatch")
        trace.append({"stage": "snapshot", "premises_bound": len(ordered), "result": "matched"})
        truth, witness, reason = _evaluate(request, target, domains, ordered, budget)
        if truth is None:
            status, verdict = "INVALID_COUNTEREXAMPLE", "FAIL"
        elif truth:
            status, verdict = "VERIFIED", "PASS"
        elif target["kind"] == "justification":
            status, verdict = "INVALID_JUSTIFICATION", "PASS"
        else:
            status, verdict = "REFUTED_CLAIM", "PASS"
        trace.append({"stage": "exact_check", "result": status, "reason": reason})
        receipt = {"checker_id": CHECKER_ID, "certificate_type": target["certificate_type"],
                   "binding_sha256": _digest(binding), "request_sha256": _digest(request),
                   "status": status, "truth": truth, "witness_sha256": _digest(witness),
                   "limits_sha256": _digest(LIMITS)}
        return {"status": status, "verdict": verdict, "truth": truth, "reason": reason,
                "binding": binding, "witness": witness, "trace": trace, "work_units": budget.used,
                "certificate": {**receipt, "sha256": _digest(receipt)}}
    except Unresolved as error:
        reason = error.reason
        detail = error.detail
    except (TypeError, KeyError, ValueError, ZeroDivisionError):
        reason = "malformed_structured_input"
    trace.append({"stage": "abstain", "reason": reason, **(detail or {})})
    return {"status": "UNKNOWN", "verdict": "UNKNOWN", "truth": None, "reason": reason,
            "binding": binding, "witness": None, "trace": trace, "work_units": budget.used, "certificate": None}


def replay_certificate(certificate, request, *, target, premises=()):
    """Recompute the evidence instead of trusting an externally supplied digest."""
    try:
        _bounded_json(certificate)
    except Unresolved:
        return False
    result = verify(request, target=target, premises=premises)
    return result["certificate"] is not None and _digest(result["certificate"]) == _digest(certificate)
