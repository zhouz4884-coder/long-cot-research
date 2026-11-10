"""Extract only scope-bound optimum claims from frozen blind archive observations."""
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
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
sys.path.insert(0, str(D43))
from extract_candidates import AUTHOR_SCORER_SHA, THINK_CLOSE, final_readout, load_author_scorer, termination
from freeze_cohort import BLIND_COLUMNS, MODEL_ID, MODEL_REVISION, digest, write_exclusive


RULES_SHA = "638b746461fcec1af302230bc8e286bb209b97213decc39c5a9b9bcdcb566bc9"
OPEN = "<think>"
SHA = re.compile(r"[a-f0-9]{64}\Z")
LITERAL_INT = r"[+\-−]?[0-9]{1,24}"
FRAC_TEX = rf"[+\-−]?\\(?:dfrac|tfrac|frac)\s*\{{\s*{LITERAL_INT}\s*\}}\s*\{{\s*{LITERAL_INT}\s*\}}"
FRAC_PLAIN = rf"{LITERAL_INT}\s*/\s*{LITERAL_INT}"
DECIMAL = rf"{LITERAL_INT}\.[0-9]{{1,24}}"
LITERAL = re.compile(rf"(?:{FRAC_TEX}|{FRAC_PLAIN}|{DECIMAL}|{LITERAL_INT})")
TEX_PARTS = re.compile(rf"([+\-−]?)\\(?:dfrac|tfrac|frac)\s*\{{\s*({LITERAL_INT})\s*\}}\s*\{{\s*({LITERAL_INT})\s*\}}")
WRAP = re.compile(r"\\(?:text|mathrm|mathbf|mathit|mbox)\s*\{(.*)\}\Z", re.S)
PRESENTATION_START = re.compile(r"(?:[ \t]|\*\*|\${1,2}|\\[\[(])*")
PRESENTATION_END = re.compile(r"(?:[ \t]|\*\*|\${1,2}|\\[\]\)])*")
HEAD = re.compile(
    r"(?i)(?<![\w\\])(?P<direction>maximum|minimum|greatest|largest|least|smallest|max|min)\b"
    r"(?P<role>[^\r\n.!?;:=]{0,180}?)(?:\bis\b|\bequals\b|[:=])\s*"
)
TENTATIVE = re.compile(
    r"(?i)\b(?:if|whether|suppos(?:e|ing)|assum(?:e|ing)|hypothetically|maybe|perhaps|guess(?:ed|ing)?|"
    r"seems?|appears?|likely|might|could|would|trial|tentative|not)\b|"
    r"\b(?:this|that|our|the above|a fixed|a particular)\s+"
    r"(?:construction|configuration|assignment|example|family|method|scheme|choice|pattern)\b"
)
RETRACTION = re.compile(
    r"(?i)\b(?:(?:(?:my|our|the|this|that)\s+)?(?:previous|earlier|above|last)\s+"
    r"(?:answer|value|result|claim|maximum|minimum|conclusion)\s+(?:is|was)\s+"
    r"(?:wrong|incorrect|invalid|false|not\s+(?:correct|valid))|(?:I|we)\s+(?:retract|withdraw|discard)\s+"
    r"(?:(?:my|our|the|this|that)\s+)?(?:previous|earlier|above|last)?\s*"
    r"(?:answer|value|result|claim|maximum|minimum|conclusion)|"
    r"(?:this|that)\s+(?:answer|maximum|minimum|conclusion)\s+(?:is|was)\s+"
    r"(?:wrong|incorrect|invalid|false|not\s+(?:correct|valid)))\b"
)
CLAUSE_BREAK = re.compile(r"[\r\n!?;]|\.(?=\s|$)")
ADJACENT_MARKUP = r"(?:[\s.*#$!。]|\\[\[\]()])*"
ADJACENT_GAP = re.compile(
    rf"{ADJACENT_MARKUP}(?:final[ \t]+answer[ \t]*(?:\*\*)?[ \t]*:?{ADJACENT_MARKUP})?\Z", re.I
)
ADJACENT_LIMIT = 240


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def receipt(text, start, end, offset):
    return {"char_span_in_response": [offset + start, offset + end],
            "source_excerpt_sha256": digest(text[start:end].encode())}


def exact_value(raw):
    if raw is None:
        return None
    text = raw.strip().replace("−", "-")
    for _ in range(6):
        wrapper = WRAP.fullmatch(text)
        if wrapper:
            text = wrapper[1].strip()
        elif text.startswith("$") and text.endswith("$") and len(text) > 2:
            text = text[1:-1].strip()
        elif (text[:2], text[-2:]) in {(r"\(", r"\)"), (r"\[", r"\]")}:
            text = text[2:-2].strip()
        else:
            break
    if not LITERAL.fullmatch(text):
        return None
    try:
        tex = TEX_PARTS.fullmatch(text)
        if tex:
            return Fraction((-1 if tex[1] == "-" else 1) * int(tex[2]), int(tex[3]))
        if "/" in text:
            numerator, denominator = text.split("/")
            return Fraction(int(numerator), int(denominator))
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def finish_literal(prefix, end, known_close):
    end = PRESENTATION_END.match(prefix, end).end()
    if end == len(prefix):
        return end if known_close else None
    if prefix[end] in "\r\n;。":
        return end
    if prefix[end] == "." and (known_close and end + 1 == len(prefix) or
                                end + 1 < len(prefix) and prefix[end + 1].isspace()):
        return end
    return None


def scope_case(case):
    direction = case["direction"].upper()
    direction = {"MAXIMIZE": "MAX", "MINIMIZE": "MIN"}.get(direction, direction)
    require(direction in {"MAX", "MIN"}, "Expected frozen MAX or MIN direction")
    patterns = case["role_patterns"]
    require(type(patterns) is list and 0 < len(patterns) <= 8 and
            all(type(x) is str and 0 < len(x) <= 400 for x in patterns), "Missing reviewed role patterns")
    compiled = [re.compile(pattern, re.I) for pattern in patterns]
    require(all(not pattern.search("") for pattern in compiled), "A role pattern cannot match an empty span")
    return direction, compiled


def unknown(status, **evidence):
    return {"status": status, "value": None, "rational": None, "scope_status": "UNBOUND",
            "complete_explicit_candidate": False, **evidence}


def inherit_adjacent_box(prefix, offset, events, box_at):
    ordered = []
    for key, (end, event) in sorted(events.items(), key=lambda pair: (pair[1][0], pair[0])):
        if ordered and event["status"] == "LATER_UNSCOPED_BOX" and key in box_at:
            previous_end, previous = ordered[-1]
            gap = prefix[previous_end:key]
            candidate = exact_value(box_at[key].interior_raw)
            if (previous["status"] == "EXPLICIT_SCOPED_OPTIMUM"
                    and previous["extraction_method"] != "adjacent_repeated_box"
                    and 0 <= key - previous_end <= ADJACENT_LIMIT and ADJACENT_GAP.fullmatch(gap)
                    and finish_literal(prefix, end, True) is not None
                    and candidate == Fraction(**previous["rational"])):
                previous_receipt = {field: previous[field] for field in ("char_span_in_response", "source_excerpt_sha256")}
                event = {**previous, **receipt(prefix, key, end, offset), "extraction_method": "adjacent_repeated_box",
                         "preceding_scoped_claim": previous_receipt, "adjacency_gap_characters": len(gap),
                         "adjacency_gap_sha256": digest(gap.encode())}
        ordered.append((end, event))
    return ordered


def declaration_events(prefix, floor, offset, scorer, case, known_close):
    direction, patterns = scope_case(case)
    boxes, malformed = scorer.scan_box_events(prefix)
    box_at = {event.span[0]: event for event in boxes if event.span[0] >= floor}
    events = {box.span[0]: (box.span[1], unknown("LATER_UNSCOPED_BOX", **receipt(prefix, *box.span, offset)))
              for box in box_at.values()}
    events.update({row["span"][0]: (len(prefix), unknown("LATER_UNCLOSED_BOX", **receipt(prefix, *row["span"], offset)))
                   for row in malformed if row["span"][0] >= floor})
    for match in HEAD.finditer(prefix, floor):
        observed_direction = "MAX" if match["direction"].casefold() in {"maximum", "max", "greatest", "largest"} else "MIN"
        subject = match["role"]
        roles = [pattern.search(subject) for pattern in patterns]
        start = PRESENTATION_START.match(prefix, match.end()).end()
        box = box_at.get(start)
        if box is not None:
            end, value = box.span[1], exact_value(box.interior_raw)
            # The box itself closes the literal, but a visible continuation can put it inside a larger expression.
            if finish_literal(prefix, end, True) is None:
                continue
        else:
            literal = LITERAL.match(prefix, start)
            if literal is None:
                continue
            value = exact_value(literal[0])
            end = finish_literal(prefix, literal.end(), known_close)
            if end is None:
                continue
        # For unscoped prose we leave the preceding scoped claim intact. A later box is an explicit barrier.
        if any(role is None for role in roles):
            continue
        bounds = list(CLAUSE_BREAK.finditer(prefix, max(floor, match.start() - 180), match.start()))
        left = bounds[-1].end() if bounds else max(floor, match.start() - 180)
        evidence = receipt(prefix, match.start(), end, offset)
        if TENTATIVE.search(prefix[left:match.start()] + subject):
            status = unknown("TENTATIVE_OR_CONSTRUCTION_CLAIM", **evidence)
        elif observed_direction != direction:
            status = unknown("WRONG_OPTIMUM_DIRECTION", **evidence)
        elif value is None:
            status = unknown("SCOPED_CLAIM_NOT_EXACT_RATIONAL", **evidence)
        else:
            role_start = match.start("role")
            status = {"status": "EXPLICIT_SCOPED_OPTIMUM", "scope_status": "ORIGINAL_REQUESTED_OPTIMUM",
                      "direction": direction, "value": value.numerator if value.denominator == 1 else str(value),
                      "rational": {"numerator": value.numerator, "denominator": value.denominator},
                      "complete_explicit_candidate": True, "extraction_method": "scoped_box" if box else "scoped_literal",
                      "direction_receipt": receipt(prefix, *match.span("direction"), offset),
                      "role_receipts": [{"pattern_index": i, **receipt(prefix, role_start + hit.start(),
                                                                       role_start + hit.end(), offset)}
                                        for i, hit in enumerate(roles)], **evidence}
        events[start] = (end, status)
    for match in RETRACTION.finditer(prefix, floor):
        events[match.start()] = (match.end(), unknown("EXPLICIT_RETRACTION", **receipt(prefix, *match.span(), offset)))
    return inherit_adjacent_box(prefix, offset, events, box_at)


def observation(scorer, text, offset, case, window, known_close):
    floor = max(0, len(text) - window)
    events = declaration_events(text, floor, offset, scorer, case, known_close)
    chosen = events[-1][1] if events else unknown("NO_COMPLETE_SCOPED_OPTIMUM")
    return {**chosen, "observed_characters": len(text), "observation_prefix_sha256": digest(text.encode()),
            "observation_char_span_in_response": [offset, offset + len(text)], "lookback_characters": window,
            "event_status_counts": dict(Counter(event["status"] for _, event in events))}


def extract_row(scorer, sample, case, rules):
    require(set(sample) == set(BLIND_COLUMNS), "Only the declared D43 blind columns may be read")
    text, question = sample["response"], sample["problem"]
    require(type(text) is str and digest(text.encode()) == sample["response_sha256"], "Unverified blind response")
    require(type(question) is str and digest(question.encode()) == case["question_sha256"], "Question differs from freeze")
    require(sample["problem_id"] == case["case_id"] and sample["draw_index"] in rules["draws"], "Trace outside cohort")
    require(type(sample["draw_index"]) is int and type(sample["seed"]) is int
            and sample["sample_id"] == f"{case['case_id']}:draw-{sample['draw_index']:02d}"
            and sample["model_id"] == MODEL_ID and sample["model_revision"] == MODEL_REVISION
            and isinstance(sample["contract_sha256"], str) and SHA.fullmatch(sample["contract_sha256"]),
            "Unverified archived model or sample identity")
    costs = [sample[name] for name in ("input_tokens", "output_tokens", "effective_max_new_tokens")]
    require(all(type(value) is int and value >= 0 for value in costs) and costs[1] <= costs[2]
            and (not sample["cap_hit"] or costs[1] == costs[2]), "Invalid source token ledger")
    finish = termination(sample)
    start = len(OPEN) if text.startswith(OPEN) else 0
    close = text.find(THINK_CLOSE)
    first_end = close if close >= 0 else len(text)
    early_rule, late_rule = rules["early_observation"], rules["late_observation"]
    early_end = start + early_rule["prefix_length"]
    early = unknown("UNOBSERVABLE_OPEN_THINKING_PREFIX")
    if first_end < early_end and close >= 0:
        early = unknown(early_rule["if_close_precedes_boundary"])
    elif first_end < early_end and finish == "LENGTH_CAP":
        early = unknown(early_rule["if_cap_precedes_boundary"])
    elif first_end >= early_end and OPEN not in text[start:early_end]:
        early = observation(scorer, text[start:early_end], start, case, early_rule["lookback_characters"], False)
    late = unknown(late_rule["if_unclosed_or_ambiguous"])
    if close < 0:
        boundary = "UNTERMINATED_THINKING" if finish == "LENGTH_CAP" else "THINKING_BOUNDARY_UNKNOWN"
        final = unknown("NO_FINAL_CHANNEL", segment="final")
    elif text.count(THINK_CLOSE) != 1 or OPEN in text[start:]:
        boundary = "THINKING_BOUNDARY_AMBIGUOUS"
        final = unknown(boundary, segment="final")
    else:
        boundary = "CLOSED_THINKING"
        late = observation(scorer, text[start:close], start, case, late_rule["lookback_characters"], True)
        final_start = close + len(THINK_CLOSE)
        final = final_readout(scorer, text[final_start:], final_start)
    identity = {name: sample[name] for name in ("problem_id", "sample_id", "draw_index", "seed", "response_sha256",
                                               "input_tokens", "output_tokens", "effective_max_new_tokens")}
    return {**identity, "case_id": case["case_id"], "question_sha256": case["question_sha256"],
            "direction": scope_case(case)[0], "termination": finish, "boundary": boundary, "early": early, "late": late,
            "final": final, "native_final_eligible": finish == "NATIVE_STOP" and final["complete_explicit_candidate"]}


def extract(scorer, blind, cohort, cohort_sha, rules):
    started, cpu = perf_counter_ns(), thread_time_ns()
    require(set(blind) in ({"cohort_freeze_sha256", "rows"}, {"cohort_freeze_sha256", "rows", "draws"})
            and blind["cohort_freeze_sha256"] == cohort_sha
            and blind.get("draws", rules["draws"]) == rules["draws"], "Blind intake differs from frozen draw scope")
    cases = {row["case_id"]: row for row in cohort["rows"]}
    require(bool(cases) and len(cases) == len(cohort["rows"]) == cohort["selected_question_count"]
            and cohort["observation_rules_sha256"] == RULES_SHA
            and cohort["planned_draw_count"] == len(rules["draws"])
            and cohort["planned_trace_count"] == len(cases) * len(rules["draws"]),
            "Missing or duplicate cohort identity")
    archive = {}
    for case in cases.values():
        require(SHA.fullmatch(case["question_sha256"]), "Malformed question freeze")
        scope_case(case)
        require([row["draw_index"] for row in case["draws"]] == rules["draws"], "Frozen trace identity list differs")
        archive.update({(case["case_id"], row["draw_index"]): row for row in case["draws"]})
    rows = []
    for sample in blind["rows"]:
        require(sample.get("problem_id") in cases, "Unexpected blind problem")
        case = cases[sample["problem_id"]]
        expected = archive.get((case["case_id"], sample["draw_index"]))
        require(expected is not None and sample["eval_index"] == case["eval_index"]
                and sample["contract_sha256"] == cohort["generation_contract_sha256"]
                and all(sample[key] == expected[key] for key in ("sample_id", "seed", "response_sha256")),
                "Blind trace identity differs from the identity-only cohort freeze")
        rows.append(extract_row(scorer, sample, cases[sample["problem_id"]], rules))
    require(len(rows) == len(cases) * len(rules["draws"]) == len({r["sample_id"] for r in rows})
            and {(r["case_id"], r["draw_index"]) for r in rows} == {(case, draw) for case in cases for draw in rules["draws"]},
            "Missing or repeated archive observations")
    return {"status": "FROZEN_D45_SCOPED_OBSERVATIONS_WITHOUT_GOLD", "cohort_freeze_sha256": cohort_sha,
            "author_parser_sha256": AUTHOR_SCORER_SHA, "observation_rules_sha256": RULES_SHA,
            "scope": "Text-coordinate observations and complete paid source tokens. No online state or answer labels.",
            "paid_full_source_tokens": {key: sum(row[key] for row in rows) for key in ("input_tokens", "output_tokens")},
            "early_counts": dict(Counter(row["early"]["status"] for row in rows)),
            "late_counts": dict(Counter(row["late"]["status"] for row in rows)),
            "cost": {"wall_ns": perf_counter_ns() - started, "cpu_ns": thread_time_ns() - cpu}, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("blind-input", "cohort-freeze", "author-scorer", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--observation-rules", type=Path, default=HERE / "D45_OBSERVATION_RULES.json")
    args = parser.parse_args()
    require(not args.output.exists(), "Refuse to overwrite a frozen observation")
    rule_bytes = args.observation_rules.read_bytes()
    require(digest(rule_bytes) == RULES_SHA, "Observation rule bytes differ from the frozen version")
    blind_bytes, cohort_bytes = args.blind_input.read_bytes(), args.cohort_freeze.read_bytes()
    report = extract(load_author_scorer(args.author_scorer), json.loads(blind_bytes), json.loads(cohort_bytes),
                     digest(cohort_bytes), json.loads(rule_bytes))
    report["blind_input_sha256"] = digest(blind_bytes)
    report["extractor_sha256"] = digest(Path(__file__).read_bytes())
    write_exclusive(args.output, report)
    print(json.dumps({key: report[key] for key in ("status", "early_counts", "late_counts", "paid_full_source_tokens")}))


if __name__ == "__main__":
    main()
