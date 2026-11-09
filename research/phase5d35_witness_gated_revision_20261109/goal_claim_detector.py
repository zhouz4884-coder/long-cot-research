"""Conservative, contract-aware claims from decoded observation prefixes."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re

from candidate_archive import SourceSpan, digest, observe

_INT = r"[+\-−]?\d{1,24}"
_UINT = r"\d{1,24}"
_NUMBER = rf"(?:[+\-−]?\\(?:dfrac|tfrac|frac)\{{{_INT}\}}\{{{_INT}\}}|{_INT}(?:\s*/\s*{_INT}|\.\d{{1,24}})?)"
_BOUND = r"(?:^|(?<=[.!?])\s+|(?<=\n))"
_FINISH = r"(?:[.!](?=\s|$)|(?=\n|$))"
_MATH_GAP = r"[\s$]*(?:\\\[\s*)?"
_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:✅[ \t]*)?(?:\*\*)?"
    r"(?:step[ \t]+\d+[ \t]*:[ \t]*)?final[ \t]+(?:answer|conclusion|count)"
    r"(?:\*\*)?[ \t]*:?[ \t]*(?:\*\*)?[ \t]*(?=\n|$)"
)
_BOX = re.compile(rf"(?<!\\)\\boxed\s*\{{\s*(?P<value>{_NUMBER})\s*\}}")
_EXACT = re.compile(
    rf"{_BOUND}(?:(?:therefore|thus|so|hence),?\s+)?(?:the\s+)?(?:final\s+)?answer\s+is\s*"
    rf"(?:\$\s*)?(?P<value>{_NUMBER})(?:\s*\$)?{_FINISH}",
    re.I,
)
_JOINT = re.compile(
    rf"{_BOUND}(?:so|therefore|thus),\s*(?P<body>(?:[ab]_(?:1|\{{1\}})|[dr])\s*=\s*"
    rf"{_NUMBER}(?:(?:\s*,\s*|\s+and\s+)(?:[ab]_(?:1|\{{1\}})|[dr])\s*=\s*{_NUMBER}){{3}}){_FINISH}",
    re.I,
)
_ASSIGN = re.compile(rf"(?<![A-Za-z0-9_])(?P<name>[ab]_(?:1|\{{1\}})|[dr])\s*=\s*(?P<value>{_NUMBER})", re.I)
_CONSTRUCT = re.compile(
    rf"{_BOUND}(?:(?:therefore|thus|so),\s+)?the\s+(?:[a-z0-9]+-digit\s+)?number\s+"
    rf"(?:is\s+(?P<value>{_UINT})|(?P<valid>{_UINT})\s+is\s+valid){_FINISH}",
    re.I,
)
_DIGIT_LIST = re.compile(
    rf"{_BOUND}(?:alternatively,\s+)?start\s+with\s+(?P<digits>[1-9](?:\s*,\s*\d){{2,15}})"
    rf"\.(?=\s|$)", re.I,
)
_EXTREMUM = re.compile(
    rf"{_BOUND}(?:(?:therefore|thus|hence|so),?\s+)?(?P<hedge>I think\s+)?"
    rf"(?P<value>{_UINT})\s+is\s+the\s+(?P<direction>maximum|minimal|minimum){_FINISH}",
    re.I,
)
_GLOBAL_MAX = re.compile(
    rf"{_BOUND}(?:(?:therefore|thus|hence|so),?\s+)?(?:the\s+)?"
    rf"(?:global\s+maximum|largest\s+valid\s+fibbish\s+number)\s+is\s+(?P<value>{_UINT}){_FINISH}", re.I,
)
_LENGTH_SEARCH = re.compile(r"\b(?:try\s+to\s+build|(?:if|whether)\s+there\s+is)\s+a\s+[a-z0-9]+-digit\s+number\b", re.I)
_MINIMAL_M = re.compile(
    rf"{_BOUND}(?:therefore,\s+)?m\s*=\s*(?P<value>{_UINT})\s+is\s+the\s+minimal{_FINISH}"
    rf"|\bthen\s+(?P<then>{_UINT})\s+is\s+the\s+minimal{_FINISH}"
    rf"|\bthe\s+minimal\s+positive\s+integer\s+is\s+the\s+smaller\s+of\s+the\s+two,"
    rf"\s+which\s+is\s+(?P<smaller>{_UINT}){_FINISH}", re.I,
)
_PRIME = re.compile(
    rf"(?:the\s+)?\*{{0,2}}(?:smallest|least)(?:\s+such)?\s+prime\*{{0,2}}\s+is\s*(?:\$\s*)?p\s*=\s*(?P<first>{_UINT})"
    rf"|\bp\s*=\s*(?P<second>{_UINT})\s+is\s+(?:indeed\s+)?the\s+(?:first|minimal|smallest)\s+prime",
    re.I,
)
_COMPLETE_MOD = re.compile(
    rf"\bthe\s+(?:(?:two|complete)\s+)?solutions\s+"
    rf"(?:are\s+(?P<first>{_UINT}\s+and\s+{_UINT})\s+mod\s+(?P<m1>{_UINT})"
    rf"|mod\s+(?P<m2>{_UINT})\s+are\s+(?P<second>\$\s*{_UINT}\s*\$\s+and\s+\$\s*{_UINT}\s*\$))"
    rf"(?=\s*[,.;]|\s*$)", re.I,
)
_COMPLETE_MOD_SQUARE = re.compile(
    rf"\bthere\s+are\s+two\s+solutions\s+mod\s+(?P<modulus>(?P<prime>{_UINT})(?:²|\^2))\s*:"
    rf"\s*(?P<values>{_UINT}\s+and\s+{_UINT}){_FINISH}", re.I,
)
_COMPLETE_SET = re.compile(
    rf"{_BOUND}(?:the\s+)?complete\s+(?:set\s+of\s+solutions|solution\s+set)\s+is\s*"
    rf"(?:\$\s*)?(?P<brace_escape>\\?)\{{(?P<values>{_INT}(?:\s*,\s*{_INT}){{0,31}})"
    rf"(?P=brace_escape)\}}(?:\s*\$)?{_FINISH}", re.I,
)
_ALL_PAIRS = re.compile(
    rf"\bremoving\s+\*{{0,2}}any\s+two\s+numbers\s+from\s+(?P<lo>{_UINT})\s+to\s+(?P<hi>{_UINT})"
    r"\*{0,2}\s*(?:\([^\n)]{0,70}\)\s*)?will\s+result\s+in\s+an\s+LCM\s+that\s+is\s+"
    r"\*{0,2}not\s+divisible\s+by\s+those\s+two\s+numbers\*{0,2},?\s+and\s+"
    r"\*{0,2}divisible\s+by\s+all\s+others\*{0,2}[.!]", re.I,
)
_ALL_PAIRS_THINK = re.compile(
    rf"\bthe\s+numbers\s+from\s+(?P<lo>{_UINT})\s+to\s+(?P<hi>{_UINT})\s+are\s+such\s+that\s+"
    r"removing\s+any\s+two\s+of\s+them\s+ensures\s+that\s+their\s+multiples\s+are\s+not\s+in\s+S,"
    r"\s+and\s+therefore,\s+the\s+LCM\(S\s*\\\s*\{m1,\s*m2\}\)\s+is\s+"
    r"not\s+divisible\s+by\s+m1\s+or\s+m2(?=[,.;])", re.I,
)
_PAIR_TRIAL = re.compile(
    rf"\b(?:take|for|if|with)\s+m_?1\s*=\s*(?P<first>{_UINT})\s+(?:and\s+)?"
    rf"m_?2\s*=\s*(?P<second>{_UINT})(?=[,.;!?]|\s*$)", re.I,
)
_RESIDUES = re.compile(
    rf"\bthe\s+greedy\s+algorithm\s+is\s+\*{{0,2}}optimal\*{{0,2}}\s+for\s+a\s+number\s+"
    rf"\$\s*N\s*\$\s+\*{{0,2}}(?P<relation>if\s+and\s+only\s+if)\*{{0,2}}\s*:"
    rf"\s*-\s+\*{{0,2}}Either\*{{0,2}}\s+\$\s*N\s*<\s*(?P<split>{_UINT})\s*\$"
    rf"[^\n]{{0,350}}\n\s*-\s+\*{{0,2}}Or\*{{0,2}}\s+\$\s*N\s*(?:\\geq?|≥)\s*(?P<lower>{_UINT})\s*\$"
    rf",?\s+and\s+the\s+\*{{0,2}}remainder\*{{0,2}}\s+\$\s*r\s*=\s*N\s*\\mod\s*(?P<modulus>{_UINT})\s*\$"
    rf"\s+is\s+in\s+the\s+set\s*:\s*\$\$\s*\\\{{(?P<residues>{_UINT}(?:\s*,\s*{_UINT}){{0,79}})\\\}}\s*\$\$",
    re.I,
)
_COUNT_SCOPE = re.compile(
    rf"\b(?:integers|values(?:\s+of)?)\s+\$\s*N\s*\$\s+(?:between|from)\s+"
    rf"(?P<lo>{_UINT})\s+(?:and|to)\s+(?P<hi>{_UINT})\s+inclusive\b", re.I,
)
_RESIDUES_PLAIN = re.compile(
    rf"\bfor\s+N\s+from\s+(?P<lower>{_UINT})\s+to\s+(?P<upper>{_UINT})\s*:"
    rf"\s*for\s+each\s+N,\s*if\s+N\s+mod\s+(?P<modulus>{_UINT})\s+is\s+in\s+"
    rf"\{{(?P<residues>{_UINT}(?:\s*,\s*{_UINT}){{0,79}})\}},\s*then\s+"
    r"(?:it's|it\s+is)\s+optimal\.\s+(?P<relation>Otherwise,\s+(?:it's|it\s+is)\s+not\.)",
    re.I,
)
_GREEDY_TRIAL = re.compile(
    rf"(?im)^[ \t]*N\s*=\s*(?P<n>{_UINT})\s*:\s*{_UINT}\s*(?:→|->)\s*"
    r"(?:not|optimal|yes|no)\.(?=\s|$)"
)
_HYPOTHETICAL = re.compile(r"\b(?:if|suppose|assuming|hypothetically|maybe|perhaps|whether|would|could)\b", re.I)
_BOX_GAP = re.compile(r"(?:[\s$,，;]|\\(?:quad|qquad|,|;))*")
_ANSWER_ALTERNATIVE = re.compile(r"\s*(?:[$]{1,2}\s*)?(?:or\b|either\b|maybe\b|perhaps\b|and\s+\\boxed)", re.I)
_FENCE = re.compile(r"(?m)^[ \t]*(?P<delimiter>```|~~~)[^\n]*(?:\n|$)")
_COMPARISON = re.compile(
    rf"\s*but\s+(?:that(?:'|’)s|it(?:'|’)s|that\s+is|it\s+is|(?P<left>{_UINT})\s+is)"
    rf"\s+smaller\s+than\s+(?P<right>{_UINT}){_FINISH}"
    rf"|\s*(?:but,?\s+)?(?P<explicit>{_UINT})\s*<\s*(?P<other>{_UINT}){_FINISH}",
    re.I,
)


def target_id_for(contract):
    return "goal_" + digest([contract.contract_id, contract.question_sha256, contract.goal])


def _number(text):
    surface = re.sub(r"\s+", "", text).replace("−", "-")
    frac = re.fullmatch(r"([+-]?)\\(?:dfrac|tfrac|frac)\{([+-]?\d+)\}\{([+-]?\d+)\}", surface)
    try:
        if frac:
            value = Fraction((-1 if frac[1] == "-" else 1) * int(frac[2]), int(frac[3]))
        elif "/" in surface:
            a, b = surface.split("/")
            value = Fraction(int(a), int(b))
        else:
            value = Fraction(surface)
    except (ValueError, ZeroDivisionError):
        return None
    if value.denominator == 1:
        return value.numerator
    return {"op": "rat", "num": value.numerator, "den": value.denominator}


def _regions(prefix):
    text = prefix.text
    stop = min((at for marker in ("<|im_end|>", "<|endoftext|>") if (at := text.find(marker)) >= 0), default=len(text))
    if prefix.initial_segment == "final":
        return [(0, text[:stop], "final")]
    open_at = text.find("<think>")
    start = 0 if open_at < 0 else open_at + len("<think>")
    close = text.find("</think>", start)
    if close < 0 or close > stop:
        return [(start, text[start:stop], "thinking")]
    after = close + len("</think>")
    return [(start, text[start:close], "thinking"), (after, text[after:stop], "final")]


def _fenced_ranges(text):
    ranges = []
    opening = None
    for marker in _FENCE.finditer(text):
        if opening is None:
            opening = marker
        elif marker["delimiter"] == opening["delimiter"]:
            ranges.append((opening.start(), marker.end()))
            opening = None
    if opening is not None:
        ranges.append((opening.start(), len(text)))
    return tuple(ranges)


def _overlaps(span, ranges):
    return any(span[0] < end and span[1] > start for start, end in ranges)


def _prelude(text, position, limit=260):
    return text[max(0, position - limit):position]


def _unasserted(text, position):
    local = _prelude(text, position, 180)
    clause = re.split(r"(?<=[.!?])\s+|\n", local)[-1]
    return bool(_HYPOTHETICAL.search(clause))


def _boxed_answers(text, goal, template):
    headings = list(_HEADING.finditer(text))
    boxes = list(_BOX.finditer(text))
    for index, box in enumerate(boxes):
        if (index and _BOX_GAP.fullmatch(text[boxes[index - 1].end():box.start()])
                or index + 1 < len(boxes) and _BOX_GAP.fullmatch(text[box.end():boxes[index + 1].start()])):
            continue
        previous = _prelude(text, box.start())
        after = text[box.end():box.end() + 90]
        before_heading = next((h for h in reversed(headings) if h.end() <= box.start()), None)
        wrapped_heading = before_heading and re.fullmatch(_MATH_GAP, text[before_heading.end():box.start()])
        committed_suffix = re.match(r"\s*is\s+the\s+(?:final\s+)?answer[.!]", after, re.I)
        maximum_cue = goal == "MAX" and re.search(
            r"\b(?:the\s+)?\*{0,2}largest\s+valid\s+fibbish\s+number\*{0,2}\s+is\s*:\s*" + _MATH_GAP + r"$",
            previous, re.I,
        )
        minimum_cue = goal == "MIN" and re.search(
            r"\b(?:the\s+)?\*{0,2}smallest\s+positive\*{0,2}\s+one\s+is\s*" + _MATH_GAP + r"$",
            previous, re.I,
        )
        count_cue = template == "greedy_coin_count_v1" and re.search(
            r"\bthe\s+number\s+of\s+values\s+of\s+\$\s*N\s*\$\s+between\s+\d+\s+and\s+\d+\s+"
            r"inclusive\s+for\s+which\s+the\s+greedy\s+algorithm\s+gives\s+the\s+"
            r"\*{0,2}minimal\s+number\s+of\s+coins\*{0,2}\s+is\s*:\s*" + _MATH_GAP + r"$", previous, re.I,
        )
        if ((wrapped_heading or committed_suffix or maximum_cue or minimum_cue or count_cue)
                and not _ANSWER_ALTERNATIVE.match(after) and not re.match(r"\s*(?:\$\s*)?[?+*/=]", after)):
            yield box


def _joint_parameters(text, before):
    found = list(_JOINT.finditer(text, 0, before))
    if not found:
        return {}, {}
    group = found[-1]
    names = {}
    fields = {}
    for item in _ASSIGN.finditer(text, *group.span("body")):
        name = re.sub(r"[_{}]", "", item["name"]).lower()
        if name in names or (value := _number(item["value"])) is None:
            return {}, {}
        names[name] = value
        fields[name] = item.span("value")
    if set(names) != {"a1", "b1", "d", "r"}:
        return {}, {}
    # Conflicting intervening rebindings remain uncertain.
    for item in _ASSIGN.finditer(text, group.end(), before):
        name = re.sub(r"[_{}]", "", item["name"]).lower()
        tail = text[item.end():item.end() + 3]
        if name in names and re.match(r"\s*[,.$\n]", tail):
            value = _number(item["value"])
            if value is not None and value != names[name]:
                return {}, {}
    return names, fields


def _prime_binding(text, before):
    primes = []
    for item in _PRIME.finditer(text, 0, before):
        if _unasserted(text, item.start()):
            continue
        group = "first" if item["first"] else "second"
        primes.append((int(item[group]), item.span(group)))
    if not primes or len({p for p, _ in primes}) != 1:
        return {}, {}
    value, span = primes[-1]
    return {"p": value}, {"p": span}


def _constructed(text):
    for match in _CONSTRUCT.finditer(text):
        name = "value" if match["value"] else "valid"
        value = int(match[name])
        if value > 0:
            yield match, match.span(name), value, "constructed_candidate"
    for match in _DIGIT_LIST.finditer(text):
        digits = re.findall(r"\d", match["digits"])
        yield match, match.span("digits"), int("".join(digits)), "constructed_digit_candidate"


def _cross_length_scope(text, end, incumbent):
    start = max(0, end - 1_800)
    previous = text[start:end]
    scope = _LENGTH_SEARCH.search(previous)
    if scope is None:
        return None
    for candidate, _, value, role in _constructed(previous):
        if role != "constructed_candidate" or candidate.start() < scope.start() or len(str(value)) <= len(str(incumbent)):
            continue
        paragraph_end = previous.find("\n\n", candidate.end())
        comparison = _COMPARISON.match(previous, candidate.end(), len(previous) if paragraph_end < 0 else paragraph_end)
        if comparison is None or int(comparison["right"] or comparison["other"]) != incumbent:
            continue
        explicit = comparison["left"] or comparison["explicit"]
        if explicit and int(explicit) != value:
            continue
        return {"cross_length_search": (start + scope.start(), start + scope.end()),
                "cross_length_comparison": (start + candidate.start(), start + comparison.end())}
    return None


def _role_emitter(prefix, contract, offset):
    target = target_id_for(contract)
    blocked = _fenced_ranges(prefix.text)
    def emit(kind, role, source, *, fields=None, value=None, assignments=None, claim=None, lineage=()):
        def shift(span):
            return offset + span[0], offset + span[1]
        if _overlaps(shift(source), blocked) or any(_overlaps(shift(span), blocked) for span in (fields or {}).values()):
            return None
        try:
            return observe(prefix, contract_id=contract.contract_id, target_id=target, goal_claim_type=kind,
                           role=role, source=shift(source), fields={k: shift(v) for k, v in (fields or {}).items()},
                           value=value, assignments=assignments, claim=claim, lineage=lineage)
        except ValueError:
            return None
    return emit


def _region_claims(prefix, contract, offset, text):
    emit = _role_emitter(prefix, contract, offset)
    goal = contract.goal
    template = contract.template_id
    found = []

    def add(kind, role, match, field, *, value=None, assignments=None, fields=None, claim=None):
        if value is not None and field is not None:
            fields = {"value": match.span(field), **(fields or {})}
        item = emit(kind, role, match.span(), value=value, assignments=assignments, fields=fields, claim=claim)
        if item is not None:
            found.append(item)

    if template == "fibbish_max_v1":
        for match, span, value, role in _constructed(text):
            item = emit("FEASIBLE_CANDIDATE", role, match.span(), value=value, fields={"value": span})
            if item is not None:
                found.append(item)
        for match in _EXTREMUM.finditer(text):
            if match["direction"].lower() != "maximum" or _unasserted(text, match.start()):
                continue
            value = int(match["value"])
            scope = _cross_length_scope(text, match.start(), value)
            if scope:
                add("MAXIMALITY_CLAIM", "provisional_cross_length_maximum", match, "value", value=value, fields=scope,
                    claim={"kind": "MAX", "value": value})
        for match in _GLOBAL_MAX.finditer(text):
            value = int(match["value"])
            add("MAXIMALITY_CLAIM", "asserted_global_maximum", match, "value", value=value, claim={"kind": "MAX", "value": value})

    if template == "least_prime_square_residue_v1":
        for match in _MINIMAL_M.finditer(text):
            if _unasserted(text, match.start()):
                continue
            group = next(name for name in ("value", "then", "smaller") if match[name] is not None)
            value = int(match[group])
            assignment, fields = _prime_binding(text, match.start())
            if assignment:
                add("MINIMALITY_CLAIM", "asserted_minimum", match, group, value=value, assignments=assignment,
                    fields=fields, claim={"kind": "MIN", "value": value, **assignment})
        for match in _COMPLETE_MOD.finditer(text):
            if _unasserted(text, match.start()):
                continue
            value_group = "first" if match["first"] else "second"
            mod_group = "m1" if match["m1"] else "m2"
            values = [int(value) for value in re.findall(r"\d+", match[value_group])]
            modulus = int(match[mod_group])
            if modulus > 1 and len(values) == len(set(values)) and all(0 <= value < modulus for value in values):
                add("COMPLETE_SOLUTIONS_CLAIM", "asserted_complete_residue_roots", match, None,
                    fields={"solutions": match.span(value_group), "modulus": match.span(mod_group)},
                    claim={"kind": "COMPLETE_SOLUTIONS", "values": values, "modulus": modulus})
        for match in _COMPLETE_MOD_SQUARE.finditer(text):
            if _unasserted(text, match.start()):
                continue
            values = [int(value) for value in re.findall(r"\d+", match["values"])]
            modulus = int(match["prime"]) ** 2
            if modulus > 1 and len(values) == len(set(values)) and all(0 <= value < modulus for value in values):
                add("COMPLETE_SOLUTIONS_CLAIM", "asserted_complete_residue_roots", match, None,
                    fields={"solutions": match.span("values"), "modulus": match.span("modulus")},
                    claim={"kind": "COMPLETE_SOLUTIONS", "values": values, "modulus": modulus})

    if goal in {"ALL_SOLUTIONS", "SOLVE_SET"}:
        for match in _COMPLETE_SET.finditer(text):
            values = [int(value.replace("−", "-")) for value in re.findall(_INT, match["values"])]
            if values and len(values) == len(set(values)):
                add("COMPLETE_SOLUTIONS_CLAIM", "asserted_complete_set", match, None,
                    fields={"solutions": match.span("values")}, claim={"kind": "COMPLETE_SOLUTIONS", "values": values})

    if template == "lcm_divisor_count_v1":
        for match in _PAIR_TRIAL.finditer(text):
            pair = [int(match[name]) for name in ("first", "second")]
            if 0 < pair[0] < pair[1]:
                add("FEASIBLE_CANDIDATE", "observed_pair_trial", match, None, value={"pair": pair},
                    fields={name: match.span(name) for name in ("first", "second")})
        for pattern in (_ALL_PAIRS, _ALL_PAIRS_THINK):
            for match in pattern.finditer(text):
                if _unasserted(text, match.start()):
                    continue
                lower, upper = int(match["lo"]), int(match["hi"])
                if 0 < lower < upper:
                    add("UNIVERSAL_CLAIM", "asserted_removed_pair_class", match, None,
                        fields={"lower": match.span("lo"), "upper": match.span("hi")},
                        claim={"kind": "ALL_REMOVED_PAIR_LCM_FAILS_BOTH", "lower": lower, "upper": upper})

    if template == "greedy_coin_count_v1":
        for match in _GREEDY_TRIAL.finditer(text):
            n = int(match["n"])
            if n > 0:
                add("FEASIBLE_CANDIDATE", "observed_greedy_point_trial", match, None, value={"n": n},
                    fields={"n": match.span("n")})
        for match in _RESIDUES_PLAIN.finditer(text):
            if _unasserted(text, match.start()):
                continue
            lower, upper, modulus = (int(match[name]) for name in ("lower", "upper", "modulus"))
            residues = [int(value) for value in re.findall(r"\d+", match["residues"])]
            if (0 < lower <= upper and modulus > 1 and len(residues) == len(set(residues))
                    and all(0 <= value < modulus for value in residues)):
                add("UNIVERSAL_CLAIM", "asserted_greedy_residue_class", match, None,
                    fields={name: match.span(name) for name in ("lower", "upper", "modulus", "residues", "relation")},
                    claim={"kind": "GREEDY_RESIDUE_CLASS", "lower": lower, "upper": upper,
                           "modulus": modulus, "residues": residues, "relation": "IFF"})
        for match in _RESIDUES.finditer(text):
            scopes = list(_COUNT_SCOPE.finditer(text, 0, match.start()))
            if not scopes or len({(scope["lo"], scope["hi"]) for scope in scopes}) != 1:
                continue
            lower, upper, modulus = int(match["lower"]), int(scopes[-1]["hi"]), int(match["modulus"])
            residues = [int(value) for value in re.findall(r"\d+", match["residues"])]
            if (lower != int(match["split"]) or not int(scopes[-1]["lo"]) <= lower <= upper
                    or not 1 < modulus or len(residues) != len(set(residues))
                    or not all(0 <= value < modulus for value in residues)):
                continue
            add("UNIVERSAL_CLAIM", "asserted_greedy_residue_class", match, None,
                fields={"lower": match.span("lower"), "upper": scopes[-1].span("hi"),
                        "modulus": match.span("modulus"), "residues": match.span("residues"),
                        "relation": match.span("relation")},
                claim={"kind": "GREEDY_RESIDUE_CLASS", "lower": lower, "upper": upper,
                       "modulus": modulus, "residues": residues, "relation": "IFF"})

    answers = list(_boxed_answers(text, goal, template))
    if goal in {"EXACT", "COUNT"}:
        answers.extend(match for match in _EXACT.finditer(text)
                       if not _ANSWER_ALTERNATIVE.match(text[match.end():match.end() + 90]))
    for match in answers:
        value = _number(match["value"])
        if value is None:
            continue
        assignment, fields = {}, {}
        if goal in {"EXACT", "COUNT"}:
            kind, role, claim = "EXACT_ANSWER", "explicit_answer", {}
            if template == "arithmetic_geometric_sequence_v1":
                assignment, fields = _joint_parameters(text, match.start())
        elif goal == "MAX" and type(value) is int and value > 0:
            kind, role, claim = "MAXIMALITY_CLAIM", "explicit_maximum_answer", {"kind": "MAX", "value": value}
        elif goal == "MIN" and type(value) is int and value > 0:
            assignment, fields = _prime_binding(text, match.start())
            if not assignment:
                continue
            kind, role, claim = "MINIMALITY_CLAIM", "explicit_minimum_answer", {"kind": "MIN", "value": value, **assignment}
        else:
            continue
        add(kind, role, match, "value", value=value, assignments=assignment, fields=fields, claim=claim)
    return found


def detect_claims(prefix, contract):
    """Return observations and lexical revisions. Verification is a separate step."""
    if prefix.question_sha256 != contract.question_sha256:
        raise ValueError("contract and source question differ")
    records = []
    for offset, text, _ in _regions(prefix):
        records.extend(_region_claims(prefix, contract, offset, text))
    records.sort(key=lambda item: (item.source_span.char_span, item.goal_claim_type))
    if contract.goal not in {"EXACT", "COUNT"}:
        return tuple(records)
    thinking = [item for item in records if item.goal_claim_type == "EXACT_ANSWER" and item.segment == "thinking"]
    final = [item for item in records if item.goal_claim_type == "EXACT_ANSWER" and item.segment == "final"]
    if (thinking and final and len({digest(item.value) for item in final}) == 1
            and final[-1].value != thinking[-1].value):
        prior, later = thinking[-1], final[-1]
        fields = {name: span.char_span for name, span in later.field_spans.items()}
        item = _role_emitter(prefix, contract, 0)(
            "FINAL_ANSWER_REVISION", "different_explicit_final_value", later.source_span.char_span,
            fields=fields, value=later.value, assignments=later.assignments, lineage=(prior.candidate_id,),
            claim={"prior_candidate_id": prior.candidate_id, "later_candidate_id": later.candidate_id},
        )
        if item is not None:
            records.append(item)
    return tuple(records)


@dataclass(frozen=True)
class ComparisonSupport:
    contract_id: str
    target_id: str
    observed_prefix_sha256: str
    left: int
    right: int
    relation: str
    source_span: SourceSpan
    paragraph_span: SourceSpan
    left_span: SourceSpan
    right_span: SourceSpan


def comparison_supports(prefix, contract):
    """Bind direct comparisons to the sole immediately named candidate."""
    if prefix.question_sha256 != contract.question_sha256:
        raise ValueError("contract and source question differ")
    if contract.template_id != "fibbish_max_v1":
        return ()
    found = []
    blocked = _fenced_ranges(prefix.text)
    for offset, text, _ in _regions(prefix):
        for match, value_span, left, role in _constructed(text):
            if role != "constructed_candidate":
                continue
            para_start = text.rfind("\n\n", 0, match.start()) + 2
            para_start = 0 if para_start == 1 else para_start
            para_end = text.find("\n\n", match.end())
            if para_end < 0:
                para_end = len(text)
            direct = _COMPARISON.match(text, match.end(), para_end)
            if direct is None or len(list(_CONSTRUCT.finditer(text, para_start, direct.start()))) != 1:
                continue
            explicit = direct["left"] or direct["explicit"]
            if explicit and int(explicit) != left:
                continue
            if _overlaps((offset + para_start, offset + para_end), blocked):
                continue
            other = "right" if direct["right"] else "other"
            def bind(span):
                return prefix.span(offset + span[0], offset + span[1])
            try:
                found.append(ComparisonSupport(contract.contract_id, target_id_for(contract), prefix.prefix_sha256,
                                               left, int(direct[other]), "<",
                                               bind((match.start(), direct.end())), bind((para_start, para_end)),
                                               bind(value_span), bind(direct.span(other))))
            except ValueError:
                continue
    return tuple(found)
