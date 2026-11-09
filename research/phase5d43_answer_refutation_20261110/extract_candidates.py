"""Freeze candidate observations using only the locally projected blind view."""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import sys
from time import perf_counter_ns, thread_time_ns

from freeze_cohort import BLIND_COLUMNS, digest, write_exclusive


AUTHOR_SCORER_SHA = "c6b10ee5a5667a21df095f9ef87a04c2499cf8dbe56cff11f3bf9836d8262256"
TERMINAL_PUNCTUATION = re.compile(r"(?:\s|[.$!。]|\\[\]\)])*\Z")
DECLARATION = re.compile(
    r"(?im)\b(?:(?:the\s+)?(?:final\s+)?answer(?:\s+is|\s*[:=])|"
    r"(?:the\s+)?(?:requested|final)\s+(?:value|result)(?:\s+is|\s*[:=]))\s*"
    r"(?:\*\*\s*|\\[\[(]\s*|\${1,2}\s*)?(?P<value>\+?\d{1,32})"
    r"(?=\s*(?:\*\*\s*)?(?:[$.!。]|\\[\]\)]|\s)*\Z)"
)
DECLARATION_BEFORE_BOX = re.compile(
    r"(?i)(?:\banswer|\b(?:requested|final)\s+(?:value|result))"
    r"(?:\s+is|\s*[:=])?\s*[*$\s]*(?:\\[\[(]\s*)?\Z"
)
THINK_CLOSE = "</think>"
TERMINAL_WINDOW = 3000
STOP_TOKENS = {"im_end": 151645, "endoftext": 151643}


def load_author_scorer(path: Path):
    if digest(path.read_bytes()) != AUTHOR_SCORER_SHA:
        raise ValueError("Unexpected upstream parser source")
    spec = importlib.util.spec_from_file_location("d43_pinned_aime_scorer", path)
    if spec is None or spec.loader is None:
        raise ValueError("The pinned parser is not a Python source file")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def termination(sample: dict) -> str:
    reason = sample["finish_reason"]
    if reason == "length" and sample["cap_hit"] and sample["stop_condition"] == "length_cap":
        return "LENGTH_CAP"
    token = STOP_TOKENS.get(sample["stop_condition"])
    if reason == "stop" and not sample["cap_hit"] and token is not None and sample["stop_token_id"] == token:
        return "NATIVE_STOP"
    return "TERMINATION_UNKNOWN"


def span_record(segment: str, start: int, end: int, offset: int) -> dict:
    return {"char_span_in_response": [offset + start, offset + end],
            "source_excerpt_sha256": digest(segment[start:end].encode())}


def unknown(reason: str, segment: str, **evidence) -> dict:
    return {"status": reason, "segment": segment, "value": None,
            "scope_status": "UNBOUND", "complete_explicit_candidate": False, **evidence}


def complete(name: str, value: int, scope: str, method: str, **evidence) -> dict:
    return {"status": "EXPLICIT_INTEGER", "segment": name, "value": value,
            "scope_status": scope, "complete_explicit_candidate": True,
            "extraction_method": method, **evidence}


def last_box(scorer, text: str):
    events, malformed = scorer.scan_box_events(text)
    nonempty = [event for event in events if event.valid]
    return (nonempty[-1] if nonempty else None), malformed


def whole_author_readout(scorer, text: str) -> int | None:
    box, _ = last_box(scorer, scorer.clean_generated_text(text))
    return scorer.parse_aime_integer(box.interior_raw) if box else None


def final_readout(scorer, segment: str, offset: int) -> dict:
    box, malformed = last_box(scorer, segment)
    if box is None:
        return unknown("MALFORMED_BOX" if malformed else "NO_COMPLETE_BOX", "final")
    evidence = span_record(segment, *box.span, offset)
    if any(item["span"][0] > box.span[0] for item in malformed):
        return unknown("LATER_UNCLOSED_BOX", "final", **evidence)
    value = scorer.parse_aime_integer(box.interior_raw)
    if value is None:
        return unknown("BOX_FAILS_INTEGER_FORMAT", "final", **evidence)
    return complete("final", value, "DELIVERY_CLAIM", "last_complete_box_in_final", **evidence)


def thinking_readout(scorer, segment: str, offset: int) -> dict:
    if not segment.strip():
        return unknown("MISSING_SEGMENT", "thinking")
    floor = max(0, len(segment) - TERMINAL_WINDOW)
    box, malformed = last_box(scorer, segment)
    if any(item["span"][0] >= floor for item in malformed):
        return unknown("TERMINAL_UNCLOSED_BOX", "thinking")
    for match in DECLARATION.finditer(segment, floor):
        value = scorer.parse_aime_integer(match["value"])
        if value is not None:
            evidence = span_record(segment, *match.span(), offset)
            return complete("thinking", value, "GENERIC_TARGET_CLAIM", "terminal_declaration", **evidence)
    if box is None or box.span[0] < floor or not TERMINAL_PUNCTUATION.fullmatch(segment[box.span[1]:]):
        return unknown("NO_EXPLICIT_TERMINAL_OBJECT", "thinking")
    evidence = span_record(segment, *box.span, offset)
    value = scorer.parse_aime_integer(box.interior_raw)
    if value is None:
        return unknown("BOX_FAILS_INTEGER_FORMAT", "thinking", **evidence)
    anchored = DECLARATION_BEFORE_BOX.search(segment[max(floor, box.span[0] - 120):box.span[0]])
    scope = "GENERIC_TARGET_CLAIM" if anchored else "TERMINAL_BOX_UNANCHORED"
    return complete("thinking", value, scope, "terminal_thinking_box", **evidence)


def extract_row(scorer, sample: dict) -> dict:
    if set(sample) != set(BLIND_COLUMNS):
        raise ValueError("The extractor only accepts the declared label-blind projection")
    identity = {key: sample[key] for key in (
        "problem_id", "sample_id", "draw_index", "seed", "response_sha256",
        "input_tokens", "output_tokens", "effective_max_new_tokens",
    )}
    text = sample["response"]
    if not isinstance(text, str) or digest(text.encode()) != sample["response_sha256"]:
        raise ValueError("Unverified response")
    finish = termination(sample)
    start = len("<think>") if text.startswith("<think>") else 0
    end = text.find(THINK_CLOSE)
    if end < 0:
        boundary = "UNTERMINATED_THINKING" if finish == "LENGTH_CAP" else "THINKING_BOUNDARY_UNKNOWN"
        thinking = thinking_readout(scorer, text[start:], start) if finish == "LENGTH_CAP" else unknown(boundary, "thinking")
        final = unknown("NO_FINAL_CHANNEL", "final")
    elif text.count(THINK_CLOSE) != 1 or "<think>" in text[start:]:
        boundary = "THINKING_BOUNDARY_AMBIGUOUS"
        thinking, final = (unknown(boundary, side) for side in ("thinking", "final"))
    else:
        boundary = "CLOSED_THINKING"
        next_start = end + len(THINK_CLOSE)
        thinking = thinking_readout(scorer, text[start:end], start)
        final = final_readout(scorer, text[next_start:], next_start)
    return {
        **identity, "termination": finish, "boundary": boundary,
        "thinking": thinking, "final": final,
        "author_whole_response_candidate": whole_author_readout(scorer, text),
    }


def extract(scorer, data: dict) -> dict:
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    rows = [extract_row(scorer, sample) for sample in data["rows"]]
    if len(rows) != 128 or len({r["sample_id"] for r in rows}) != 128:
        raise ValueError("The fixed pilot has 128 distinct traces")
    return {
        "status": "FROZEN_MACHINE_READOUT_WITHOUT_GOLD",
        "cohort_freeze_sha256": data["cohort_freeze_sha256"],
        "author_parser_sha256": AUTHOR_SCORER_SHA,
        "cost": {"wall_ns": perf_counter_ns() - started_wall,
                 "cpu_ns": thread_time_ns() - started_cpu},
        "termination_counts": dict(Counter(r["termination"] for r in rows)),
        "thinking_readout_counts": dict(Counter(r["thinking"]["status"] for r in rows)),
        "final_readout_counts": dict(Counter(r["final"]["status"] for r in rows)),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blind-input", type=Path, required=True)
    parser.add_argument("--author-scorer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.blind_input.read_bytes()
    result = extract(load_author_scorer(args.author_scorer), json.loads(raw))
    result["blind_input_sha256"] = digest(raw)
    result["extractor_sha256"] = digest(Path(__file__).read_bytes())
    write_exclusive(args.output, result)
    print({k: v for k, v in result.items() if k.endswith("_counts")})


if __name__ == "__main__":
    main()
