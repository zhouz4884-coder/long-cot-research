"""Freeze scope-bound asserted points from exact label-blind archived prefixes."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import re
import sys
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
D45 = HERE.parent / "phase5d45_feasible_witness_20261110"
sys.path.insert(0, str(D45))
from extract_d45_claims import (
    ADJACENT_GAP, ADJACENT_LIMIT, AUTHOR_SCORER_SHA, BLIND_COLUMNS, LITERAL, MODEL_ID, MODEL_REVISION,
    OPEN, PRESENTATION_START, RETRACTION, THINK_CLOSE, digest, exact_value, final_readout,
    finish_literal, load_author_scorer, termination, write_exclusive,
)


RULES_SHA = "ac82afe29ec5fbe6feee48b0d97be700e32560de305c70043e456b5a4e41af45"
D45_LITERAL_SOURCE_SHA = "714ef1569f81c792206dca0835e55aee74356f434e2a9914c9bbd20238225985"
GENERATION_CONTRACT = "185daff44fc19ac2102b42bf480de11a7651bae7eb6253fff8ea9d030ac58e61"
HEX = re.compile(r"[a-f0-9]{64}\Z")
BOUND = "EXPLICIT_SCOPED_POINT"
ASSERTED = "ASSERTED_ORIGINAL_CANDIDATE"
CLAUSE_BOUNDARY = re.compile(r"\r\n|[\r\n!?;。]|\.(?=[ \t]|$)")
PARAGRAPH_BOUNDARY = re.compile(r"\r?\n[ \t]*\r?\n")
FENCE = re.compile(r"(?m)^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)")
LEAD = re.compile(
    r"[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*)?"
    r"(?:(?:therefore|thus|hence|so|consequently|accordingly|actually),?[ \t]+|"
    r"(?:we|I) conclude that[ \t]+)?(?:the[ \t]+)?", re.I
)
DIRECTION = re.compile(
    r"(?P<word>maximum|max|greatest|largest|minimum|min|least|smallest|first(?=[ \t]+valid\b))\b"
    r"(?:[ \t]+possible)?[ \t]+", re.I
)
ASSERTION = re.compile(
    r"\b(?:is[ \t]+equal[ \t]+to|equals|is)\b[ \t]*:?|(?<![<>=!~:≤≥≠≈≡])=(?!=)", re.I
)
UNSAFE_SUBJECT = re.compile(
    r"[<>=!~≤≥≠≈≡]|\\(?:leq?|geq?|neq|ne|approx|equiv|sim)\b|"
    r"\b(?:where|such[ \t]+that|for[ \t]+which|if|assuming|suppose|trial|testing|find|search|"
    r"guess|whether|not|at[ \t]+least|at[ \t]+most|candidate|either|or)\b", re.I
)
HYPOTHESIS = re.compile(r"(?:if\b|suppos(?:e|ing)\b|assum(?:e|ing)\b|case[ \t]+[\w-]+[ \t]*:|"
                        r"try\b|for[ \t]+this[ \t]+case\b)", re.I)
PRESENTATION = re.compile(r"\\[\[\]()]|\${1,2}|\*\*")
GENERIC_SUBJECTS = {"answer", "final answer", "the answer", "value", "requested value", "result", "optimum", "number",
                    "integer", "positive integer", "positive number"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def receipt(text, start, end, offset):
    return {"char_span_in_response": [offset + start, offset + end],
            "source_excerpt_sha256": digest(text[start:end].encode())}


def unknown(status, **extra):
    return {"status": status, "value": None, "rational": None, "scope_status": "UNBOUND",
            "complete_explicit_candidate": False, **extra}


def scope_case(case):
    direction, patterns = case["direction"], case["subject_patterns"]
    require(direction in {"MAX", "MIN", "VALUE"} and type(patterns) is list and 0 < len(patterns) <= 12
            and all(type(pattern) is str and 0 < len(pattern) <= 400 for pattern in patterns), "Malformed reviewed subject")
    aliases = [re.compile(pattern, re.I) for pattern in patterns]
    require(not any(alias.fullmatch("") for alias in aliases), "A reviewed subject cannot be empty")
    return direction, aliases


def canonical_subject(raw):
    # The subject can contain paired presentation markup, but no dangling delimiters.
    stack = []
    for mark in PRESENTATION.finditer(raw):
        token = mark[0]
        if stack and token == stack[-1]:
            stack.pop()
        elif token in {r"\)", r"\]"}:
            return None
        else:
            stack.append({r"\(": r"\)", r"\[": r"\]"}.get(token, token))
    if stack:
        return None
    return " ".join(PRESENTATION.sub("", raw).split())


def reviewed_alias(subject, aliases):
    forms = [(subject, "paired_presentation_only")]
    if subject.casefold().startswith("value of "):
        forms.append((subject[len("value of "):], "one_value_of_prefix_removed"))
    for spelling, normalization in forms:
        if spelling.casefold() in GENERIC_SUBJECTS:
            continue
        for index, alias in enumerate(aliases):
            if alias.fullmatch(spelling):
                return index, normalization
    return None


def related_to_hypothesis(prefix, left, floor):
    prior = prefix[max(floor, left - 1000):left].rstrip()
    # Do not lift an unresolved hypothesis in the visibly adjacent paragraph.
    paragraphs = PARAGRAPH_BOUNDARY.split(prior)
    return any(HYPOTHESIS.match(clause.lstrip()) for clause in CLAUSE_BOUNDARY.split(paragraphs[-1]))


def fenced_spans(prefix):
    opening = None
    spans = []
    for marker in FENCE.finditer(prefix):
        token, suffix = marker.groups()
        if opening is None:
            opening = (marker.start(), token)
        elif token[0] == opening[1][0] and len(token) >= len(opening[1]) and not suffix.strip():
            spans.append((opening[0], marker.end()))
            opening = None
    if opening is not None:
        spans.append((opening[0], len(prefix)))
    return spans


def assertion_event(prefix, left, floor, offset, direction, aliases, box_at, known_close):
    subject_start = LEAD.match(prefix, left).end()
    sense = DIRECTION.match(prefix, subject_start)
    if sense:
        observed_direction = "MAX" if sense["word"].casefold() in {"maximum", "max", "greatest", "largest"} else "MIN"
        subject_start = sense.end()
    else:
        observed_direction = "VALUE"
    if observed_direction != direction:
        return None
    for operator in ASSERTION.finditer(prefix, subject_start, min(len(prefix), subject_start + 240)):
        raw_subject = prefix[subject_start:operator.start()]
        if "\n" in raw_subject or "\r" in raw_subject or UNSAFE_SUBJECT.search(raw_subject):
            return None
        subject = canonical_subject(raw_subject)
        if not subject:
            continue
        alias = reviewed_alias(subject, aliases)
        if alias is None:
            continue
        alias_index, normalization = alias
        assignment_tail = operator.end()
        while assignment_tail < len(prefix) and prefix[assignment_tail].isspace():
            assignment_tail += 1
        numeric_start = PRESENTATION_START.match(prefix, assignment_tail).end()
        box = box_at.get(numeric_start)
        if box:
            numeric_lo = prefix.index("{", numeric_start, box.span[1]) + 1
            numeric_hi = box.span[1] - 1
            end = finish_literal(prefix, box.span[1], True)
        else:
            match = LITERAL.match(prefix, numeric_start)
            numeric_lo, numeric_hi = match.span() if match else (numeric_start, numeric_start)
            end = finish_literal(prefix, numeric_hi, known_close) if match else None
        numeric_text = prefix[numeric_lo:numeric_hi]
        value = exact_value(numeric_text)
        observed_end = end if end is not None else (box.span[1] if box else max(numeric_hi, operator.end()))
        evidence = receipt(prefix, left, observed_end, offset)
        if related_to_hypothesis(prefix, left, floor):
            event = unknown("ADJACENT_HYPOTHESIS_OR_TRIAL", **evidence)
        elif end is None or value is None:
            event = unknown("INCOMPLETE_OR_NONSCALAR_TARGET_ASSERTION", **evidence)
        else:
            event = {"status": BOUND, "scope_status": "ORIGINAL_REQUESTED_SCALAR", "direction": direction,
                     "assertion_role": ASSERTED, "complete_explicit_candidate": True,
                     "value": value.numerator if value.denominator == 1 else str(value),
                     "rational": {"numerator": value.numerator, "denominator": value.denominator},
                     "assertion_span": [left, end], "assertion_sha256": digest(prefix[left:end].encode()),
                     "numeric_span": [numeric_lo, numeric_hi], "numeric_text": numeric_text,
                     "numeric_sha256": digest(numeric_text.encode()),
                     "assertion_operator_receipt": receipt(prefix, *operator.span(), offset),
                     "subject_receipt": {"alias_index": alias_index, "normalization": normalization,
                                         **receipt(prefix, subject_start, operator.start(), offset)},
                     "direction_receipt": receipt(prefix, *sense.span("word"), offset) if sense else None,
                     "extraction_method": "explicit_target_box" if box else "explicit_target_literal", **evidence}
        return numeric_start, (observed_end, event)
    return None


def observation(scorer, prefix, offset, case, window, known_close):
    floor = max(0, len(prefix) - window)
    direction, aliases = scope_case(case)
    boxes, malformed = scorer.scan_box_events(prefix)
    box_at = {box.span[0]: box for box in boxes if box.span[0] >= floor}
    events = {left: (box.span[1], unknown("LATER_UNSCOPED_BOX", **receipt(prefix, *box.span, offset)))
              for left, box in box_at.items()}
    events.update({row["span"][0]: (len(prefix), unknown("LATER_UNCLOSED_BOX", **receipt(prefix, *row["span"], offset)))
                   for row in malformed if row["span"][0] >= floor})
    fenced = fenced_spans(prefix)
    starts = ([0] if floor == 0 else []) + [match.end() for match in CLAUSE_BOUNDARY.finditer(prefix, max(0, floor - 1))
                                           if match.end() >= floor]
    for left in starts:
        if any(lo <= left < hi for lo, hi in fenced):
            continue
        event = assertion_event(prefix, left, floor, offset, direction, aliases, box_at, known_close)
        if event:
            key, detail = event
            events[key] = detail
    for match in RETRACTION.finditer(prefix, floor):
        if not any(lo <= match.start() < hi for lo, hi in fenced):
            events[match.start()] = (match.end(), unknown("EXPLICIT_RETRACTION", **receipt(prefix, *match.span(), offset)))

    chosen, previous_end = unknown("NO_COMPLETE_SCOPED_POINT"), None
    counts = Counter()
    for key, (end, candidate) in sorted(events.items(), key=lambda pair: (pair[1][0], pair[0])):
        if (candidate["status"] == "LATER_UNSCOPED_BOX" and chosen["status"] == BOUND
                and chosen["extraction_method"] != "adjacent_repeated_box" and previous_end is not None
                and 0 <= key - previous_end <= ADJACENT_LIMIT and ADJACENT_GAP.fullmatch(prefix[previous_end:key])
                and finish_literal(prefix, end, True) is not None
                and exact_value(box_at[key].interior_raw) == Fraction(**chosen["rational"])):
            candidate = {**chosen, **receipt(prefix, key, end, offset), "extraction_method": "adjacent_repeated_box",
                         "terminal_echo_receipt": receipt(prefix, key, end, offset),
                         "adjacency_gap_characters": key - previous_end,
                         "adjacency_gap_sha256": digest(prefix[previous_end:key].encode())}
        counts[candidate["status"]] += 1
        chosen, previous_end = candidate, end
    return {**chosen, "observed_characters": len(prefix), "observation_prefix_sha256": digest(prefix.encode()),
            "observation_char_span_in_response": [offset, offset + len(prefix)], "lookback_characters": window,
            "event_status_counts": dict(counts)}


def extract_row(scorer, sample, case, rules):
    require(set(sample) == set(BLIND_COLUMNS), "Only exact label-blind archive columns may be read")
    text, question = sample["response"], sample["problem"]
    require(type(text) is str and digest(text.encode()) == sample["response_sha256"], "Unverified response")
    require(type(question) is str and digest(question.encode()) == case["question_sha256"], "Unverified original question")
    draw = sample["draw_index"]
    require(sample["problem_id"] == case["case_id"] and type(draw) is int and draw in rules["source_draws"]
            and sample["sample_id"] == f"{case['case_id']}:draw-{draw:02d}"
            and sample["model_id"] == MODEL_ID and sample["model_revision"] == MODEL_REVISION
            and sample["contract_sha256"] == GENERATION_CONTRACT, "Unexpected archive identity")
    costs = [sample[key] for key in ("input_tokens", "output_tokens", "effective_max_new_tokens")]
    require(all(type(v) is int and v >= 0 for v in costs) and costs[0] + costs[2] == 32768 and costs[1] <= costs[2]
            and type(sample["cap_hit"]) is bool and (not sample["cap_hit"] or costs[1] == costs[2]), "Invalid source work ledger")
    finish = termination(sample)
    start = len(OPEN) if text.startswith(OPEN) else 0
    close = text.find(THINK_CLOSE)
    early_end = start + rules["early"]["characters"]
    first_end = close if close >= 0 else len(text)
    early = unknown("UNOBSERVABLE_OPEN_THINKING_PREFIX")
    if first_end < early_end and close >= 0:
        early = unknown("UNREACHED_EARLY_BOUNDARY")
    elif first_end < early_end and finish == "LENGTH_CAP":
        early = unknown("UNREACHED_EARLY_BOUNDARY_CAP")
    elif first_end >= early_end and (start or close >= 0) and OPEN not in text[start:early_end]:
        early = observation(scorer, text[start:early_end], start, case, rules["early"]["lookback_characters"], False)
    late = unknown("UNOBSERVABLE_THINKING_CLOSE")
    if close < 0:
        boundary = "UNTERMINATED_THINKING" if finish == "LENGTH_CAP" else "THINKING_BOUNDARY_UNKNOWN"
        final = unknown("NO_FINAL_CHANNEL", segment="final")
    elif text.count(THINK_CLOSE) != 1 or OPEN in text[start:]:
        boundary = "THINKING_BOUNDARY_AMBIGUOUS"
        final = unknown(boundary, segment="final")
    else:
        boundary = "CLOSED_THINKING"
        late = observation(scorer, text[start:close], start, case, rules["late"]["lookback_characters"], True)
        final_start = close + len(THINK_CLOSE)
        final = final_readout(scorer, text[final_start:], final_start)
    identity = {key: sample[key] for key in ("problem_id", "sample_id", "draw_index", "seed", "response_sha256",
                                            "input_tokens", "output_tokens", "effective_max_new_tokens")}
    return {**identity, "case_id": case["case_id"], "question_sha256": case["question_sha256"],
            "direction": case["direction"], "termination": finish, "boundary": boundary,
            "early": early, "late": late, "final": final,
            "native_final_eligible": finish == "NATIVE_STOP" and final["complete_explicit_candidate"]}


def extract(scorer, blind, cohort, cohort_sha, rules):
    start, cpu = perf_counter_ns(), thread_time_ns()
    draws = rules["source_draws"]
    require(set(blind) in ({"cohort_freeze_sha256", "rows"}, {"cohort_freeze_sha256", "draws", "rows"})
            and blind["cohort_freeze_sha256"] == cohort_sha and blind.get("draws", draws) == draws,
            "Blind projection does not bind the frozen cohort")
    require(cohort.get("observation_rules_sha256", RULES_SHA) == RULES_SHA
            and cohort.get("generation_contract_sha256", GENERATION_CONTRACT) == GENERATION_CONTRACT,
            "Cohort rules or generation identity differ")
    cases = {row["case_id"]: row for row in cohort["rows"]}
    require(bool(cases) and len(cases) == len(cohort["rows"]) == cohort.get("selected_question_count", len(cases))
            and cohort.get("planned_trace_count", len(cases) * len(draws)) == len(cases) * len(draws),
            "Cohort count differs from the freeze")
    identities = {}
    for case in cases.values():
        scope_case(case)
        require(HEX.fullmatch(case["question_sha256"]) and [item["draw_index"] for item in case["draws"]] == draws,
                "Malformed frozen question or draws")
        identities.update({(case["case_id"], item["draw_index"]): item for item in case["draws"]})
    rows, seen = [], set()
    for sample in blind["rows"]:
        require(set(sample) == set(BLIND_COLUMNS), "Unexpected trace or label column")
        key = (sample["problem_id"], sample["draw_index"])
        expected = identities.get(key)
        require(expected is not None and key not in seen and
                all(sample[field] == expected[field] for field in ("sample_id", "seed", "response_sha256")),
                "Repeated or nonfrozen sample identity")
        case = cases[key[0]]
        require(sample["eval_index"] == case.get("eval_index", sample["eval_index"]), "Evaluation index changed")
        rows.append(extract_row(scorer, sample, case, rules))
        seen.add(key)
    require(seen == set(identities), "Incomplete label-blind draw matrix")
    return {"status": "FROZEN_D46_SCOPE_BOUND_POINTS_WITHOUT_GOLD", "cohort_freeze_sha256": cohort_sha,
            "observation_rules_sha256": RULES_SHA, "author_parser_sha256": AUTHOR_SCORER_SHA,
            "literal_parser_source_sha256": D45_LITERAL_SOURCE_SHA,
            "scope": "Exact archive text coordinates. Relative assertion/numeric spans are within the recorded thinking prefix slice. Raw prefixes stay local.",
            "paid_full_source_tokens": {key: sum(row[key] for row in rows) for key in ("input_tokens", "output_tokens")},
            "early_counts": dict(Counter(row["early"]["status"] for row in rows)),
            "late_counts": dict(Counter(row["late"]["status"] for row in rows)),
            "cost": {"wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu}, "rows": rows}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for flag in ("blind-input", "cohort-freeze", "author-scorer", "output"):
        cli.add_argument("--" + flag, type=Path, required=True)
    cli.add_argument("--observation-rules", type=Path, default=HERE / "D46_OBSERVATION_RULES.json")
    args = cli.parse_args()
    require(not args.output.exists(), "Refuse to overwrite a frozen observation")
    rule_bytes = args.observation_rules.read_bytes()
    require(digest(rule_bytes) == RULES_SHA and digest((D45 / "extract_d45_claims.py").read_bytes()) == D45_LITERAL_SOURCE_SHA,
            "Frozen observation rules or reused literal parser differ")
    blind_bytes, cohort_bytes = args.blind_input.read_bytes(), args.cohort_freeze.read_bytes()
    report = extract(load_author_scorer(args.author_scorer), json.loads(blind_bytes), json.loads(cohort_bytes),
                     digest(cohort_bytes), json.loads(rule_bytes))
    report.update(blind_input_sha256=digest(blind_bytes), extractor_sha256=digest(Path(__file__).read_bytes()))
    write_exclusive(args.output, report)
    print(json.dumps({key: report[key] for key in ("status", "early_counts", "late_counts", "paid_full_source_tokens")}))


if __name__ == "__main__":
    main()
