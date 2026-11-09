"""Conservative source scopes for the pinned E15 dialect, separate from math checks."""

from dataclasses import dataclass
import re


ELIGIBLE_POINT_ROLES = frozenset({
    "CHECKPOINT_OPERAND", "CURRENT_CONSTRUCTED_CANDIDATE", "CURRENT_FEASIBLE_CANDIDATE",
    "CURRENT_MAXIMUM", "CURRENT_FINAL_MAXIMUM",
})
GLOBAL_CLAIMS = frozenset({"CURRENT_MAXIMUM", "CURRENT_FINAL_MAXIMUM"})
FEASIBILITY_CLAIMS = GLOBAL_CLAIMS | {"CURRENT_FEASIBLE_CANDIDATE"}

MAXIMUM = re.compile(r"\b(?:maximum|greatest|largest)\b", re.I)
MAX_BEFORE = re.compile(r"\b(?:maximum|greatest|largest)(?:\s+(?:valid|positive|fibbish|number|candidate|value)){0,5}\s+(?:is|=)\s*$", re.I)
MAX_AFTER = re.compile(r"\s+(?:is|was)\s+(?:the\s+)?(?:(?:current|global)\s+)?(?:maximum|greatest|largest)\b", re.I)
GLOBAL = re.compile(
    r"\b(?:maximum|greatest|largest)\s+(?:(?:valid|positive)\s+)?(?:fibbish|valid number)\b"
    r"|\b(?:after checking all possible paths|of all positive (?:fibbish )?integers|overall)\b", re.I,
)
OUTSIDE = re.compile(
    r"\b(?:similar|another|previous|earlier|different|unrelated)\s+(?:problems?|puzzles?|tasks?)\b", re.I,
)
QUOTATION = re.compile(r'"[^"]+"|“[^”]+”|‘[^’]+’|(?<!\w)\'[^\'\n]+\'(?!\w)')
REPORT = re.compile(
    r"\b(?:other model|earlier draft|previous attempt|draft|contestant|transcript|sample|example|source)"
    r"(?:\s+[^.!?\n]{1,70})?\s+(?:said|claimed|wrote|proposed|reported)\b", re.I,
)
LOCAL = re.compile(
    r"\b(?:maximum|greatest|largest)\s+(?:(?:valid|fibbish)\s+)?[a-z0-9]+-digit\b"
    r"|\b(?:for|in|along|within)\s+(?:this|that|the current)\s+(?:path|sequence|branch|case)\b"
    r"|\b(?:starting|beginning)\s+with\b|\bwith\s+(?:the\s+)?prefix\b|\b(?:so|thus)\s+far\b"
    r"|\bby\s+this\s+method\b|\b(?:above|below|under)\s+\d+\b"
    r"|\b(?:among|of)\s+(?:the\s+)?(?:(?:\w+-digit)\s+(?:ones|numbers)|(?:candidates|cases)\s+considered)\b"
    r"|\b(?:has|with)\s+(?:exactly\s+)?\w+\s+digits\b|\b(?:restricted|limited)\s+to\b"
    r"|\b(?:numbers?\s+)?of\s+length\s+\w+\b", re.I,
)
ASSUMED = re.compile(r"\b(?:if|suppose|assuming|assume|hypothetically|let['’]s say|how about)\b", re.I)
INHERITED_ASSUMPTION = re.compile(
    r"\b(?:assume|suppose|assuming)\b[^.!?\n]{0,90}\b(?:constraint|condition|rule)\b[^.!?\n]{0,50}"
    r"\b(?:relaxed|weakened|different|changed|removed)\b", re.I,
)
FINAL_BOUND_ONLY = re.compile(r"\b(?:best feasible|feasible bound|so far|tentative|provisional|scratch draft|unsubmitted)\b", re.I)


@dataclass(frozen=True)
class ClaimScope:
    role: str

    @property
    def admits_point_check(self):
        return self.role in ELIGIBLE_POINT_ROLES

    @property
    def may_refute_global_maximum(self):
        return self.role in GLOBAL_CLAIMS

    @property
    def may_refute_feasibility_claim(self):
        return self.role in FEASIBILITY_CLAIMS


def observed_integer(text, value, *, at=None):
    if type(value) is not int or value <= 0:
        return None
    pattern = re.compile(rf"(?<![\w,./+−-]){value}(?![\w,/+−-]|\.\d)")
    return pattern.search(text) if at is None else pattern.match(text, at)


def classify_scope(clause, phase, value, *, terminal_committed=True, value_offset=None, context=None, context_offset=None):
    """Use the complete observed clause. A numeric hit alone grants no authority."""
    if type(value) is not int or value <= 0 or phase not in {"checkpoint_operand", "thinking", "final"}:
        return ClaimScope("UNKNOWN")
    text = clause.replace("**", "  ").replace("<|im_end|>", " " * len("<|im_end|>"))
    point = observed_integer(text, value, at=value_offset)
    if not point:
        return ClaimScope("UNKNOWN")
    if phase == "checkpoint_operand":
        return ClaimScope("CHECKPOINT_OPERAND")
    if phase == "final" and not terminal_committed:
        return ClaimScope("UNCOMMITTED")
    context = text if context is None else context
    position = point.start() if context_offset is None else context_offset
    if not 0 <= position < len(context) or context[position:position + len(str(value))] != str(value):
        return ClaimScope("UNKNOWN")
    previous = context[:position]
    line = previous.rsplit("\n", 1)[-1]
    if OUTSIDE.search(text):
        return ClaimScope("OUTSIDE_TASK")
    if (line.lstrip().startswith(">") or REPORT.search(text)
            or any(match.start() < position < match.end() for match in QUOTATION.finditer(context))):
        return ClaimScope("QUOTED")
    before = text[:point.start()].rsplit(";", 1)[-1]
    after = text[point.end():].split(";", 1)[0]
    segment = before + str(value) + after
    if (re.search(r"\b(?:false|incorrect)\s+that\b", before, re.I)
            or re.search(r"\b(?:do not|don't|never|cannot)\s+(?:claim|assert|adopt|endorse|conclude)\b", before, re.I)
            or re.match(r"\s+(?:is|was)\s+(?:not|never)\b", after, re.I)):
        return ClaimScope("NEGATED")
    if text.rstrip().endswith("?"):
        return ClaimScope("QUESTION")
    any_maximum = bool(MAXIMUM.search(segment))
    is_maximum = bool(MAX_BEFORE.search(before) or MAX_AFTER.match(after))
    if any_maximum and LOCAL.search(segment):
        return ClaimScope("LOCAL_MAXIMUM")
    if after.lstrip().startswith(("...", "…")):
        return ClaimScope("INCOMPLETE")
    if re.match(r"\s+(?:or|versus|vs\.)\s+(?:(?:perhaps|maybe)\s+)?\d+\b", after, re.I):
        return ClaimScope("ALTERNATIVES")
    if (ASSUMED.search(before) or INHERITED_ASSUMPTION.search(previous)
            or re.search(r"\b(?:if|provided|assuming|just a trial)\b", after, re.I)
            or (is_maximum and re.match(r"\s*(?:Alternatively|For example)\b", segment, re.I))):
        return ClaimScope("HYPOTHESIS")
    if phase == "final":
        if FINAL_BOUND_ONLY.search(previous[-130:]):
            return ClaimScope("LOCAL_MAXIMUM")
        boxes = re.findall(r"\\boxed\{\s*(\d+)\s*\}", text)
        return ClaimScope("CURRENT_FINAL_MAXIMUM" if boxes == [str(value)] else "UNKNOWN")
    if is_maximum:
        return ClaimScope("CURRENT_MAXIMUM" if GLOBAL.search(segment) else "UNKNOWN_MAXIMUM_SCOPE")
    if value < 10 and re.search(r"\b(?:digit|starting with)\b", text, re.I):
        return ClaimScope("NON_OBJECT_COMPONENT")
    if (re.match(r"\s+(?:is\s+(?:a\s+)?valid\b|satisfies\s+the\s+(?:original\s+)?(?:digit|fibbish)\b)", after, re.I)
            or re.search(r"\b(?:valid|fibbish)\s+number\s+(?:is|=)\s*$", before, re.I)):
        return ClaimScope("CURRENT_FEASIBLE_CANDIDATE")
    if re.search(r"\b(?:number|candidate)\s*(?:is|=)\s*$", before, re.I):
        return ClaimScope("CURRENT_CONSTRUCTED_CANDIDATE")
    return ClaimScope("UNKNOWN")


def bind_event_scope(event, *, trusted_target_id):
    """Bind the scoped clause to an already reconstructed observed candidate."""
    if event["target_id"] != trusted_target_id:
        return ClaimScope("UNKNOWN")
    span = event["source_span"]
    start, stop = event["clause_char_span"]
    left, right = span["char_span"]
    point = observed_integer(span["text"], event["value"])
    if (not start <= left < right <= stop or event["clause"][left - start:right - start] != span["text"]
            or not point):
        return ClaimScope("UNKNOWN")
    context = event.get("context", event["clause"])
    context_start, context_stop = event.get("context_char_span", event["clause_char_span"])
    if (not context_start <= start < stop <= context_stop
            or context[start - context_start:stop - context_start] != event["clause"]):
        return ClaimScope("UNKNOWN")
    return classify_scope(event["clause"], event["phase"], event["value"],
                          terminal_committed=event.get("terminal_committed", True),
                          value_offset=left - start + point.start(), context=context,
                          context_offset=left - context_start + point.start())


def permits_existing_action(scope, action):
    """Only the semantic gate. An independently checked math certificate is still required."""
    if action == "UPDATE_BOUND":
        return scope.admits_point_check
    if action == "REPAIR_INFEASIBLE":
        return scope.may_refute_feasibility_claim
    if action == "BLOCK_REGRESSION":
        return scope.may_refute_global_maximum
    return False
