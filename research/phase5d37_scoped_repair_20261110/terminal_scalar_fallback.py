"""Conservative, supplemental terminal scalar extraction after a frozen F2 abstention."""
from __future__ import annotations

from fractions import Fraction
import re
import unicodedata


VERSION = "d37_terminal_scalar_fallback_v1"
_MAX_TEXT = 150_000
_REASONS = frozenset({
    "alternative_final_objects", "boxed_objects_do_not_consume_final_payload",
    "no_terminal_answer_delivery", "unresolved_earlier_final_delivery",
    "unsupported_scalar_or_tail",
})
_HEADER = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*|__)?"
    r"(?P<name>final[ \t]+(?:answer|result|conclusion)|conclusion)"
    r"(?:\*\*|__)?(?:[ \t]*:[ \t]*|[ \t]*\r?\n|[ \t]*\Z)"
)
_SIGNED = r"[+\-−]?"
_INTEGER = rf"{_SIGNED}(?:[0-9]{{1,24}}|[0-9]{{1,3}}(?:,[0-9]{{3}}){{1,7}})"
_PLAIN = rf"(?:{_INTEGER}(?:/[0-9]{{1,24}}|\.[0-9]{{1,18}})?|{_SIGNED}\.[0-9]{{1,18}})"
_TEX = rf"\\(?:dfrac|tfrac|frac)\s*\{{\s*({_INTEGER})\s*\}}\s*\{{\s*([0-9]{{1,24}})\s*\}}"
_TEX_VALUE = re.compile(_TEX)
_PLAIN_VALUE = re.compile(_PLAIN)
_BOX = re.compile(rf"(?<!\\)\\boxed\s*\{{\s*(?P<surface>{_TEX}|{_PLAIN})\s*\}}")
_BOX_MENTION = re.compile(r"(?<!\\)\\(?:boxed|fbox)\b")
_INLINE_ANSWER = re.compile(r"(?im)\b(?:the[ \t]+)?(?:final[ \t]+)?answer[ \t]+(?:is|equals)\b(?P<payload>[^\r\n]*)")
_INLINE_ROLE = re.compile(
    r"(?im)(?:^|(?<=[.!?])[ \t]+)[ \t]*(?P<subject>[^.!?\r\n=:]{1,130}?)"
    r"\s*(?:\bis\b|\bequals\b|=)\s*(?P<payload>[^\r\n]*)"
)
_UNSAFE_CONTAINER = re.compile(r"(?m)^\s*>|```|~~~|</?(?:think|pre|code|blockquote)\b|<!--", re.I)
_UNSAFE_SCOPE = re.compile(
    r"\b(?:if|unless|suppose|assuming|hypothetical|maybe|perhaps|might|"
    r"would|either|or|tentative|estimate|approximate|approximately|"
    r"subgoal|subtotal|intermediate|example|quoted|so[ \t]+far)\b|[?≈≃≅]",
    re.I,
)
_SUBJECT_PREFIX = re.compile(r"(?P<subject>[^\r\n=:]{1,130}?)\s*(?:\bis\b|\bequals\b|=)\s*:?\s*\Z", re.I)
_SUBJECT_SUFFIX = re.compile(r"is[ \t]+(?P<subject>[^\r\n=:]{1,130}?)\s*\.?\s*\Z", re.I)
_INTRO = re.compile(r"(?:after[ \t]+[^.?!\r\n]{1,180},[ \t]+)?we conclude that[ \t]*:\s*\Z", re.I)
_WRAPPERS = (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$"))
_GENERIC = frozenset({"answer", "final answer", "requested scalar", "requested value", "final result"})


def exact_literal(surface: str) -> str | None:
    """Canonicalize only complete exact literals, never an answer fragment."""
    value = surface.strip().replace("−", "-")
    latex = _TEX_VALUE.fullmatch(value)
    try:
        if latex:
            numerator, denominator = latex.groups()
            return str(Fraction(int(numerator.replace(",", "")), int(denominator)))
        if _PLAIN_VALUE.fullmatch(value):
            return str(Fraction(value.replace(",", "")))
    except (ValueError, ZeroDivisionError):
        return None
    return None


def _subject(text):
    text = unicodedata.normalize("NFC", text).strip().casefold()
    text = text.replace("**", "").replace("__", "").replace("$", "")
    text = " ".join(text.split())
    return text.removeprefix("the ")


def _reply(status, reason, *, scalar=None, box_span=None):
    return {"version": VERSION, "status": status, "reason": reason,
            "normalized_scalar": scalar, "box_span": box_span}


def _separate_wrappers(before, after):
    for opener, closer in _WRAPPERS:
        if before.endswith(opener) and after.startswith(closer):
            return before[:-len(opener)].strip(), after[len(closer):].strip()
        if before.startswith(opener) and after.endswith(closer):
            return before[len(opener):].strip(), after[:-len(closer)].strip()
    return before, after


def _section(text, offset, label, allowed_subjects):
    payload = re.sub(r"(?m)\n\s*---+\s*\Z", "", text).rstrip()
    matches = list(_BOX.finditer(payload))
    if len(matches) != 1 or len(list(_BOX_MENTION.finditer(payload))) != 1:
        return None, "section_requires_one_exact_box"
    box, = matches
    scalar = exact_literal(box["surface"])
    if scalar is None:
        return None, "invalid_exact_scalar"
    before, after = _separate_wrappers(payload[:box.start()].strip(), payload[box.end():].strip())
    if _UNSAFE_SCOPE.search(before + " " + after) or any(mark in before + after for mark in ('"', '“', '”', '`')):
        return None, "qualified_or_quoted_delivery"
    prefix = _SUBJECT_PREFIX.fullmatch(before)
    suffix = _SUBJECT_SUFFIX.fullmatch(after)
    role_prefix = prefix is not None and _subject(prefix["subject"]) in allowed_subjects
    role_suffix = suffix is not None and _subject(suffix["subject"]) in allowed_subjects
    if label != "conclusion" and not before and after in ("", "."):
        pass
    elif role_prefix and after in ("", "."):
        pass
    elif role_suffix and (not before or _INTRO.fullmatch(before)):
        pass
    else:
        return None, "terminal_subject_or_scope_unbound"
    return (scalar, [offset + box.start(), offset + box.end()]), None


def _prior_commits(before, task_aliases):
    matches = list(_INLINE_ANSWER.finditer(before))
    matches.extend(m for m in _INLINE_ROLE.finditer(before) if _subject(m["subject"]) in task_aliases)
    values = []
    for match in matches:
        payload = match["payload"].strip().removeprefix(":").strip().removesuffix(".").strip()
        for opening, closing in _WRAPPERS:
            if payload.startswith(opening) and payload.endswith(closing):
                payload = payload[len(opening):-len(closing)].strip()
                break
        box = _BOX.fullmatch(payload)
        scalar = exact_literal(box["surface"] if box else payload)
        if scalar is None:
            return None
        values.append(scalar)
    return values


def terminal_scalar_fallback(
    final_text: str | None,
    frozen_f2: dict,
    *,
    target_kind: str,
    target_aliases: tuple[str, ...] = (),
    eos: bool,
    think_closed: bool,
    delivered: bool,
):
    """Return a supplemental readout decision. Existing F2 success stays untouched."""
    if eos is not True or think_closed is not True or delivered is not True:
        return _reply("ABSTAIN", "no_committed_natural_eos_delivery")
    if target_kind != "scalar":
        return _reply("ABSTAIN", "unknown_or_nonscalar_objective")
    if frozen_f2.get("status") == "ok":
        return _reply("KEEP_FROZEN_F2", "frozen_success_precedes_fallback")
    if frozen_f2.get("reason") not in _REASONS:
        return _reply("ABSTAIN", "frozen_reason_outside_fallback_scope")
    if (not isinstance(final_text, str) or not final_text.strip() or len(final_text) > _MAX_TEXT
            or _UNSAFE_CONTAINER.search(final_text)):
        return _reply("ABSTAIN", "missing_or_unsafe_text")
    headings = list(_HEADER.finditer(final_text))
    if not headings:
        return _reply("ABSTAIN", "no_explicit_terminal_section")
    if len(headings) > 12:
        return _reply("ABSTAIN", "too_many_final_sections")
    task_aliases = {_subject(alias) for alias in target_aliases if isinstance(alias, str) and alias.strip()}
    aliases = _GENERIC | task_aliases
    before = final_text[:headings[0].start()]
    if _BOX_MENTION.search(before):
        return _reply("ABSTAIN", "unscoped_prior_box")
    earlier = _prior_commits(before, task_aliases - _GENERIC)
    if earlier is None:
        return _reply("ABSTAIN", "unresolved_prior_explicit_answer")
    values = earlier
    selected = None
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(final_text)
        label = " ".join(heading["name"].lower().split())
        section, reason = _section(final_text[heading.end():end], heading.end(), label, aliases)
        if section is None:
            return _reply("ABSTAIN", reason)
        scalar, selected = section
        values.append(scalar)
    if len(set(values)) != 1:
        return _reply("ABSTAIN", "conflicting_explicit_answers")
    return _reply("FALLBACK_ACCEPT", "single_consistent_explicit_scalar", scalar=values[-1], box_span=selected)
