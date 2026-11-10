"""Read sealed HMMT final channels after independent review; score separately."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from math import factorial
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FINAL_MAX_CHARS = 1_500_000
EXPRESSION_MAX_CHARS = 4096
TOKEN_LIMIT = 384
DIGIT_LIMIT = 128
RESULT_BITS = 8192
EXPONENT_LIMIT = 1024
FACTORIAL_LIMIT = 256
BOX = re.compile(r"(?<!\\)\\boxed(?![a-zA-Z])")
TOKEN = re.compile(
    r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?"
    r"|\\(?:dfrac|tfrac|frac|cdot|times|div|left|right|qquad|quad|displaystyle)(?![a-zA-Z])"
    r"|\\[,!;:]|[+−\-*/×·÷^!(){}]"
)
SPACE_COMMANDS = {r"\,", r"\!", r"\;", r"\:", r"\quad", r"\qquad", r"\left", r"\right", r"\displaystyle"}
TOKEN_ALIASES = {r"\dfrac": "FRAC", r"\tfrac": "FRAC", r"\frac": "FRAC",
                 r"\cdot": "*", r"\times": "*", r"\div": "/", "×": "*", "·": "*", "÷": "/", "−": "-"}


class InvalidExpression(ValueError):
    pass


class ArithmeticBound(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def pinned(path, expected):
    raw = path.read_bytes()
    require(digest(raw) == expected, f"Frozen hash differs for {path.name}")
    return json.loads(raw)


def write_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def _bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > RESULT_BITS:
        raise ArithmeticBound("Exact rational exceeds bit bound")
    return value


def _outer_math(text):
    text = text.strip()
    for opening, closing in (("$$", "$$"), ("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")):
        if text.startswith(opening) and text.endswith(closing) and len(text) >= len(opening) + len(closing):
            return text[len(opening):len(text) - len(closing)].strip()
    return text


def _tokens(raw):
    if len(raw) > EXPRESSION_MAX_CHARS:
        raise ArithmeticBound("Expression exceeds character bound")
    text = _outer_math(raw)
    result = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        match = TOKEN.match(text, i)
        if not match:
            raise InvalidExpression("Unexpected expression character")
        token = match[0]
        i = match.end()
        if token in SPACE_COMMANDS:
            continue
        result.append(TOKEN_ALIASES.get(token, token))
        if len(result) > TOKEN_LIMIT:
            raise ArithmeticBound("Expression exceeds token bound")
    return result


def _number(token):
    return bool(token and "0" <= token[0] <= "9")


class Parser:
    """Restricted exact arithmetic, with no symbolic simplifier or eval."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def pop(self):
        token = self.peek()
        if token is None:
            raise InvalidExpression("Unexpected expression end")
        self.i += 1
        return token

    def group(self, opening, closing):
        if self.pop() != opening:
            raise InvalidExpression("Expected exact group")
        value = self.expression()
        if self.pop() != closing:
            raise InvalidExpression("Mismatched closing group")
        return value

    def atom(self):
        token = self.peek()
        if token == "(":
            return self.group("(", ")")
        if token == "{":
            return self.group("{", "}")
        if token == "FRAC":
            self.pop()
            numerator = self.group("{", "}")
            denominator = self.group("{", "}")
            return _bounded(numerator / denominator)
        if not _number(token):
            raise InvalidExpression("Expected a number or group")
        text = self.pop().replace(",", "")
        if len(text.replace(".", "")) > DIGIT_LIMIT:
            raise ArithmeticBound("Literal exceeds digit bound")
        return _bounded(Fraction(text))

    def power(self):
        value = self.atom()
        if self.peek() == "!":
            self.pop()
            if value.denominator != 1 or value < 0:
                raise InvalidExpression("Factorial requires a nonnegative integer")
            if value > FACTORIAL_LIMIT:
                raise ArithmeticBound("Factorial exceeds argument bound")
            value = _bounded(Fraction(factorial(value.numerator)))
        if self.peek() == "^":
            self.pop()
            sign = 1
            if self.peek() in {"+", "-"}:
                sign = -1 if self.pop() == "-" else 1
            exponent = sign * self.atom()
            if exponent.denominator != 1:
                raise InvalidExpression("Power requires an integral exponent")
            n = exponent.numerator
            if abs(n) > EXPONENT_LIMIT or abs(n) * max(
                value.numerator.bit_length(), value.denominator.bit_length()
            ) > RESULT_BITS:
                raise ArithmeticBound("Power exceeds bounded exact arithmetic")
            if value == 0 and n == 0:
                raise InvalidExpression("Undefined zero to zero power")
            value = _bounded(value**n)
            if self.peek() in {"^", "!"}:
                raise InvalidExpression("Unparenthesized chained power or factorial")
        return value

    def signed(self):
        if self.peek() in {"+", "-"}:
            sign = -1 if self.pop() == "-" else 1
            return sign * self.signed()
        return self.power()

    def product(self):
        start = self.i
        value = self.signed()
        structured = self._structured(start)
        previous_operator = None
        while True:
            token = self.peek()
            if token in {"*", "/"}:
                operator = self.pop()
            elif token in {"(", "{"} or (structured and (_number(token) or token == "FRAC")):
                if previous_operator == "/":
                    raise InvalidExpression("Ambiguous implicit multiplication after division")
                operator = "*"
            else:
                return value
            start = self.i
            other = self.signed()
            structured = self._structured(start)
            value = _bounded(value * other if operator == "*" else value / other)
            previous_operator = operator

    def _structured(self, start):
        factor = self.tokens[start:self.i]
        return any(token in {"^", "!", ")", "}"} for token in factor)

    def expression(self):
        value = self.product()
        while self.peek() in {"+", "-"}:
            operator = self.pop()
            other = self.product()
            value = _bounded(value + other if operator == "+" else value - other)
        return value

    def parse(self):
        value = self.expression()
        if self.peek() is not None:
            raise InvalidExpression("Trailing or ambiguous arithmetic")
        return value


def exact(raw):
    """Parse an exact rational or return an explicit UNKNOWN reason."""
    if type(raw) is int:
        if raw.bit_length() > RESULT_BITS:
            return None, "ARITHMETIC_LIMIT"
        return Fraction(raw), "EXACT_VALUE"
    if type(raw) is not str:
        return None, "UNSUPPORTED_EXPRESSION"
    try:
        return Parser(_tokens(raw)).parse(), "EXACT_VALUE"
    except (ArithmeticBound, RecursionError):
        return None, "ARITHMETIC_LIMIT"
    except ZeroDivisionError:
        return None, "UNDEFINED_ARITHMETIC"
    except (InvalidExpression, ValueError):
        return None, "UNSUPPORTED_EXPRESSION"


def _last_box(text):
    position = 0
    last = None
    while match := BOX.search(text, position):
        opening = match.end()
        while opening < len(text) and text[opening].isspace():
            opening += 1
        if opening == len(text) or text[opening] != "{":
            last = ("MALFORMED_LAST_BOX", match.start(), opening, None)
            position = match.end()
            continue
        i = opening + 1
        depth = 1
        while i < len(text) and depth:
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in "{}":
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth:
            return "UNCLOSED_LAST_BOX", match.start(), len(text), None
        inner = text[opening + 1:i - 1]
        status = "NESTED_LAST_BOX" if BOX.search(inner) else "COMPLETE_LAST_BOX"
        last = (status, match.start(), i, inner)
        position = i
    return last


def as_fraction(value):
    if value is None:
        return None
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def readout(text):
    empty = {"exact_value": None, "box_span": None, "box_sha256": None}
    if text is None:
        return {**empty, "status": "NO_FINAL_CHANNEL"}
    if type(text) is not str:
        return {**empty, "status": "INVALID_FINAL_CHANNEL"}
    if not text.strip():
        return {**empty, "status": "EMPTY_FINAL_CHANNEL"}
    if len(text) > FINAL_MAX_CHARS:
        return {**empty, "status": "FINAL_CHANNEL_LIMIT"}
    box = _last_box(text)
    if box is None:
        return {**empty, "status": "NO_EXPLICIT_BOX"}
    status, start, end, inner = box
    evidence = {"box_span": [start, end], "box_sha256": digest(text[start:end].encode())}
    if status != "COMPLETE_LAST_BOX":
        return {**evidence, "status": status, "exact_value": None}
    if not inner.strip():
        return {**evidence, "status": "EMPTY_LAST_BOX", "exact_value": None}
    value, status = exact(inner)
    return {**evidence, "status": "EXACT_LAST_BOX" if value is not None else status,
            "exact_value": as_fraction(value)}


def _index(rows, field):
    indexed = {row[field]: row for row in rows}
    require(len(rows) == len(indexed), f"Duplicate {field}")
    return indexed


def _private(path):
    require(path.resolve().is_relative_to((ROOT / "outputs").resolve()), "Keep sensitive readout in local outputs")


def reviewer_gate(channels, reviews, review_shas):
    require(len(reviews) == len(review_shas) == 2 and len({p.resolve() for p in reviews}) == 2
            and len(set(review_shas)) == 2, "Both independent review freezes are required")
    expected = {
        year: {(r["case_id"], r["sample_uid"]) for r in channels["rows"] if r["year"] == year}
        for year in (2025, 2026)
    }
    require({year: len(rows) for year, rows in expected.items()} == {2025: 5, 2026: 4},
            "Channel receipt has wrong case scope")
    accepted = {}
    for path, sha in zip(reviews, review_shas):
        artifact = pinned(path, sha)
        rows = artifact["rows"]
        identity = {(r["case_id"], r["sample_uid"]) for r in rows}
        require(len(rows) == len(identity), "Duplicate scope reviewer case")
        year = next((year for year, wanted in expected.items() if identity == wanted), None)
        require(year is not None and year not in accepted, "Reviewer scopes do not cover separate exact year strata")
        accepted[year] = sha
    require(set(accepted) == set(expected), "Missing independently frozen reviewer scope")
    return accepted


def extract_final(channel_path, channel_sha, sealed_final, reviews, review_shas, output, receipt):
    _private(output)
    require(output.resolve() != receipt.resolve() and not output.exists() and not receipt.exists(),
            "Readout outputs already exist or collide")
    channels = pinned(channel_path, channel_sha)
    require(channels["status"] == "D48_DRAW0_CHANNELS_SEPARATED_WITHOUT_GOLD" and channels["draw_index"] == 0,
            "Unexpected source channel status")
    review_hashes = reviewer_gate(channels, reviews, review_shas)
    # Only now may any final-channel byte be opened.
    sealed = pinned(sealed_final, channels["final_local_sealed_sha256"])
    require(sealed["status"] == "D48_LOCAL_FINAL_ONLY_SEALED"
            and all(sealed[key] == channels[key] for key in ("method_sha256", "cohort_sha256", "draw_index")),
            "Final seal does not match the frozen channels")
    public = _index(channels["rows"], "sample_uid")
    finals = _index(sealed["rows"], "sample_uid")
    require(set(finals) == set(public) and len(finals) == 9, "Changed final-channel scope")
    keys = ("case_id", "year", "problem_idx", "model_name", "model_config", "draw_index", "archive_revision",
            "sample_uid", "archive_problem_sha256")
    observations = []
    for uid, row in finals.items():
        source = public[uid]
        require(all(row[k] == source[k] for k in (*keys, "finish", "prompt_binding", "status"))
                and (row["final_text"] is not None) == source["final_available"]
                and not source["exact_native_eos_proven"], "Final channel identity or finish differs")
        observations.append({
            **{k: row[k] for k in keys}, "finish": row["finish"], "exact_native_eos_proven": False,
            **readout(row["final_text"]),
        })
    common = {
        "method_sha256": channels["method_sha256"], "cohort_sha256": channels["cohort_sha256"],
        "channels_receipt_sha256": channel_sha, "sealed_final_sha256": channels["final_local_sealed_sha256"],
        "reviewer_freeze_sha256": review_hashes, "readout_code_sha256": digest(Path(__file__).read_bytes()),
    }
    readout_sha = write_once(output, {
        "status": "D48_FINAL_ONLY_READOUT_FROZEN_WITHOUT_GOLD", **common, "rows": observations,
    })
    return write_once(receipt, {
        "status": "D48_PUBLIC_FINAL_ONLY_READOUT_RECEIPT", **common, "final_readout_sha256": readout_sha,
        "status_counts": dict(sorted(Counter(row["status"] for row in observations).items())),
        "rows": [{k: row[k] for k in ("case_id", "year", "sample_uid", "finish", "status",
                                      "exact_native_eos_proven")} for row in observations],
        "scope": "A final-channel last box only. Bounded exact arithmetic; no unboxed or prior-box fallback. "
                 "Archived finish is separate and native EOS was not proven.",
    })


def _readout_value(row):
    value = row["exact_value"]
    if value is None:
        require(row["status"] != "EXACT_LAST_BOX", "Missing exact readout value")
        return None
    require(row["status"] == "EXACT_LAST_BOX" and type(value) is dict
            and set(value) == {"numerator", "denominator"}
            and all(type(value[k]) is str and re.fullmatch(r"-?[0-9]+", value[k])
                    and len(value[k]) < 2500 for k in value), "Malformed exact readout value")
    result = _bounded(Fraction(int(value["numerator"]), int(value["denominator"])))
    require(as_fraction(result) == value, "Noncanonical exact readout value")
    return result


def _match(a, b):
    return a == b if a is not None and b is not None else None


def compare(outcomes_path, outcomes_sha, final_readout_path, gold_path, gold_sha,
            official_path, official_sha, output):
    require(not output.exists(), "Existing comparison is immutable")
    outcomes = pinned(outcomes_path, outcomes_sha)
    require(outcomes["status"] == "D48_BLIND_LOCAL_CHECKS_AND_FINAL_READOUT_FROZEN_BEFORE_GOLD",
            "Blind checks and final readouts must be frozen first")
    readout_sha = outcomes["final_readout_sha256"]
    archive = pinned(final_readout_path, readout_sha)
    require(archive["status"] == "D48_FINAL_ONLY_READOUT_FROZEN_WITHOUT_GOLD"
            and archive["method_sha256"] == outcomes["method_sha256"], "Readout belongs to another method freeze")
    readouts = _index(archive["rows"], "sample_uid")
    require(len(readouts) == 9 and len(outcomes["sample_uids"]) == 9
            and set(readouts) == set(outcomes["sample_uids"]), "Changed frozen readout denominator")
    # The source and official values have separately pinned authorities.
    gold = pinned(gold_path, gold_sha)
    official = pinned(official_path, official_sha)
    require(gold["status"] == "D48_PRIVATE_GOLD_ONLY" and gold["method_sha256"] == archive["method_sha256"]
            and gold["blind_outcomes_sha256"] == outcomes_sha, "Gold belongs to another frozen study")
    require(official["status"] == "D48_OFFICIAL_REFERENCE_VALUES_REVIEWED_AFTER_BLIND_FREEZE"
            and official["blind_outcomes_sha256"] == outcomes_sha, "Official reference review is not bound")
    source_values = _index(gold["rows"], "sample_uid")
    references = _index(official["rows"], "case_id")
    require(set(readouts) == set(source_values)
            and {row["case_id"] for row in readouts.values()} == set(references), "Changed reference coverage")
    comparisons = []
    per_year_source = {}
    for uid, row in readouts.items():
        source = source_values[uid]
        ref = references[row["case_id"]]
        require(all(source[key] == row[key] for key in (
            "case_id", "year", "problem_idx", "model_name", "model_config", "draw_index",
            "archive_revision", "archive_problem_sha256")), "Gold row does not bind the exact archived response")
        expected_url = f"https://hmmt-archive.s3.amazonaws.com/tournaments/{row['year']}/feb/comb/solutions.pdf"
        require(type(ref["solution_url"]) is str and ref["solution_url"].split("#", 1)[0] == expected_url
                and type(ref["solution_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", ref["solution_sha256"]),
                "Official reference provenance differs from the tournament source")
        authority = (expected_url, ref["solution_sha256"])
        require(row["year"] not in per_year_source or per_year_source[row["year"]] == authority,
                "Official solution bytes differ within one year")
        per_year_source[row["year"]] = authority
        picked = _readout_value(row)
        source_value, source_status = exact(source["gold_answer"])
        official_value, official_status = exact(ref["value"])
        agreement = _match(source_value, official_value)
        comparisons.append({
            "case_id": row["case_id"], "sample_uid": uid, "year": row["year"],
            "readout_status": row["status"], "source_gold_parse_status": source_status,
            "official_reference_parse_status": official_status, "source_gold_equals_official_reference": agreement,
            "archive_last_box_matches_source_gold": _match(picked, source_value),
            "archive_last_box_matches_official_reference": _match(picked, official_value),
            "reference_conflict": agreement is False,
        })
    return write_once(output, {
        "status": "D48_ARCHIVE_LAST_BOX_COMPARED_WITH_SEPARATE_REFERENCES",
        "blind_outcomes_sha256": outcomes_sha, "final_readout_sha256": readout_sha,
        "source_gold_sha256": gold_sha, "official_reference_manifest_sha256": official_sha,
        "comparison_code_sha256": digest(Path(__file__).read_bytes()),
        "official_solution_assets": {year: {"url": url, "sha256": sha}
                                     for year, (url, sha) in sorted(per_year_source.items())},
        "denominator": len(comparisons),
        "source_gold_matches": sum(row["archive_last_box_matches_source_gold"] is True for row in comparisons),
        "official_reference_matches": sum(row["archive_last_box_matches_official_reference"] is True for row in comparisons),
        "source_gold_unresolved": sum(row["archive_last_box_matches_source_gold"] is None for row in comparisons),
        "official_reference_unresolved": sum(row["archive_last_box_matches_official_reference"] is None for row in comparisons),
        "reference_conflicts": sum(row["reference_conflict"] for row in comparisons),
        "scope": "No raw values or solution text. Both authorities are compared independently. "
                 "An unsupported expression remains unresolved; no provider stop or native EOS is inferred.",
        "rows": comparisons,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    final = modes.add_parser("readout")
    for key in ("channels", "sealed-final", "output", "receipt"):
        final.add_argument("--" + key, required=True, type=Path)
    final.add_argument("--expected-channels-sha256", required=True)
    final.add_argument("--review-freeze", action="append", required=True, type=Path)
    final.add_argument("--expected-review-sha256", action="append", required=True)
    score = modes.add_parser("compare")
    for key in ("outcomes", "final-readout", "source-gold", "official", "output"):
        score.add_argument("--" + key, required=True, type=Path)
    for key in ("outcomes", "source-gold", "official"):
        score.add_argument("--expected-" + key + "-sha256", required=True)
    args = parser.parse_args()
    if args.mode == "readout":
        sha = extract_final(args.channels, args.expected_channels_sha256, args.sealed_final,
                            args.review_freeze, args.expected_review_sha256, args.output, args.receipt)
    else:
        sha = compare(args.outcomes, args.expected_outcomes_sha256, args.final_readout,
                      args.source_gold, args.expected_source_gold_sha256, args.official,
                      args.expected_official_sha256, args.output)
    print(args.mode, "receipt_sha256", sha)


if __name__ == "__main__":
    main()
