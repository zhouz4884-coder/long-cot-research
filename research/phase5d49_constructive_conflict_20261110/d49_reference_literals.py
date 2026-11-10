"""Decode inert reference literals and bounded integer grid comprehensions."""
from __future__ import annotations

import ast
import operator


MAX_TEXT = 500_000
MAX_INTEGER = 2**31 - 1
MAX_RANGE = 50_000
MAX_VISITS = 2_000_000
MAX_DEPTH = 32
ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
COMPARISONS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
               ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}


class UnsupportedReference(ValueError):
    pass


class Decoder:
    def __init__(self):
        self.visits = 0

    def charge(self, count=1):
        self.visits += count
        if self.visits > MAX_VISITS:
            raise UnsupportedReference("reference expansion limit")

    def bounded_integer(self, value):
        if type(value) is not int or abs(value) > MAX_INTEGER:
            raise UnsupportedReference("reference integer bound")
        return value

    def decode(self, node, names, depth=0):
        self.charge()
        if depth > MAX_DEPTH:
            raise UnsupportedReference("reference nesting bound")

        def part(child):
            return self.decode(child, names, depth + 1)

        match node:
            case ast.Constant(value=v):
                if type(v) is str and len(v) <= 128 or type(v) is bool:
                    return v
                return self.bounded_integer(v)
            case ast.List(elts=values):
                return [part(x) for x in values]
            case ast.Tuple(elts=values):
                return tuple(part(x) for x in values)
            case ast.Name(id=name) if name in names:
                return names[name]
            case ast.ListComp(elt=elt, generators=generators):
                return list(self.comprehension(elt, generators, names, depth + 1))
            case ast.IfExp(test=test, body=body, orelse=other):
                return part(body if part(test) else other)
            case ast.BinOp(left=left, op=op, right=right) if type(op) in ARITHMETIC:
                return self.binary(type(op), part(left), part(right))
            case ast.UnaryOp(op=ast.USub(), operand=value):
                return self.bounded_integer(-self.bounded_integer(part(value)))
            case ast.UnaryOp(op=ast.Not(), operand=value):
                return not part(value)
            case ast.BoolOp(op=ast.And(), values=values):
                for operand in values:
                    value = part(operand)
                    if not value:
                        break
                return value
            case ast.BoolOp(op=ast.Or(), values=values):
                for operand in values:
                    value = part(operand)
                    if value:
                        break
                return value
            case ast.Compare(left=left, ops=ops, comparators=others):
                value = part(left)
                for op, other in zip(ops, others):
                    rhs = part(other)
                    if type(op) not in COMPARISONS or type(value) not in (int, str, bool) or type(rhs) not in (int, str, bool):
                        raise UnsupportedReference("unsupported comparison")
                    if not COMPARISONS[type(op)](value, rhs):
                        return False
                    value = rhs
                return True
            case ast.Call(func=ast.Name(id="range"), args=args, keywords=[]) if 1 <= len(args) <= 3:
                sequence = range(*(self.bounded_integer(part(arg)) for arg in args))
                if len(sequence) > MAX_RANGE:
                    raise UnsupportedReference("reference range bound")
                return sequence
            case ast.Call(func=ast.Name(id="int"), args=[arg], keywords=[]):
                value = part(arg)
                if type(value) in (int, bool):
                    return self.bounded_integer(int(value))
                raise UnsupportedReference("unsupported integer conversion")
            case ast.Subscript(value=container, slice=offset):
                obj, index = part(container), self.bounded_integer(part(offset))
                if type(obj) not in (tuple, list, range) or not -len(obj) <= index < len(obj):
                    raise UnsupportedReference("unsupported reference subscript")
                return obj[index]
            case _:
                raise UnsupportedReference("unsupported reference expression: " + type(node).__name__)

    def binary(self, op, left, right):
        if type(left) is type(right) and type(left) in (list, tuple) and op is ast.Add:
            self.charge(len(left) + len(right))
            return left + right
        if op is ast.Mult:
            if type(right) in (list, tuple) and type(left) is int:
                left, right = right, left
            if type(left) in (list, tuple) and type(right) is int:
                self.charge(len(left) * max(0, right))
                return left * right
        return self.bounded_integer(ARITHMETIC[op](self.bounded_integer(left), self.bounded_integer(right)))

    def comprehension(self, elt, generators, names, depth):
        if depth > MAX_DEPTH:
            raise UnsupportedReference("reference nesting bound")
        if not generators:
            yield self.decode(elt, names, depth)
            return
        first, *rest = generators
        if first.is_async or not isinstance(first.target, ast.Name):
            raise UnsupportedReference("unsupported comprehension target")
        iterable = self.decode(first.iter, names, depth)
        if type(iterable) not in (range, tuple, list):
            raise UnsupportedReference("unsupported comprehension iterable")
        for value in iterable:
            self.charge()
            nested = {**names, first.target.id: value}
            if all(self.decode(condition, nested, depth) for condition in first.ifs):
                yield from self.comprehension(elt, rest, nested, depth + 1)


def decode_reference(text):
    if type(text) is not str or len(text) > MAX_TEXT:
        raise UnsupportedReference("invalid reference source")
    text = text.strip()
    if text.startswith("<construct>") and text.endswith("</construct>"):
        text = text[len("<construct>"):-len("</construct>")].strip()
    try:
        node = ast.parse(text, mode="eval")
        checker = Decoder()
        result = checker.decode(node.body, {})
    except (ArithmeticError, SyntaxError, RecursionError, TypeError) as error:
        raise UnsupportedReference(type(error).__name__) from None
    if type(result) not in (list, tuple):
        raise UnsupportedReference("reference must decode to explicit list or tuple data")
    return result, checker.visits
