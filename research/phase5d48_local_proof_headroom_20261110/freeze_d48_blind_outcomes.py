"""Recheck the four typed observations at the assertion boundary and freeze outcomes."""
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from local_implication import (
    AssertionReceipt, ImplicationBinding, LocalImplicationVerifier, Predicate,
    REFUTE_THIS_LOCAL_ASSERTION_ONLY, ReviewedImplication, Variable,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BLIND = ROOT / "outputs/d48_matharena_blind_20261110/d48_reasoning_only.json"


def digest(value):
    return sha256(value.encode() if type(value) is str else value).hexdigest()


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), digest(raw)


def term(node):
    return tuple(term(x) for x in node) if type(node) is list else node


def predicate(node):
    return Predicate(node["op"], term(node["left"]), term(node["right"]))


def validate_span(text, span, quote_sha, prefix_sha):
    lo, hi = span
    if not 0 <= lo < hi <= len(text) or digest(text[lo:hi]) != quote_sha or digest(text[:hi]) != prefix_sha:
        raise ValueError("Original bounded assertion bytes differ")
    return text[:hi]


def replay(source, row, review_sha):
    text = source["reasoning_text"]
    uid = source["sample_uid"]
    year = source["year"]
    if year == 2025:
        typed = row.get("typed_counterexample")
        if not typed:
            return None
        observed = row["earliest_relevant_span"]
        old = typed["arithmetic_receipt"]["assertion"]
        specification = typed["typed_statement"]
        binding = ImplicationBinding(**old["binding"])
        span = tuple(observed["span_unicode_half_open"])
        quote_sha, prefix_sha = observed["excerpt_sha256"], observed["prefix_through_span_sha256"]
        witness = tuple((name, Fraction(value)) for name, value in typed["fixed_witness"])
        contract = ReviewedImplication(
            binding, tuple(Variable(**node) for node in specification["variables"]),
            tuple(predicate(node) for node in specification["domain"]),
            tuple(predicate(node) for node in specification["premises"]),
            predicate(specification["consequent"]), witness, digest(typed["mathematical_binding"]), review_sha,
        )
        if contract.statement_sha256 != typed["statement_sha256"]:
            raise ValueError("2025 reviewed mathematical statement differs")
        original_prefix_status = "FULL_REVIEW_WINDOW_IN_ORIGINAL_DIAGNOSTIC"
    else:
        observed = row["earliest_refutable_assertion"] or {}
        typed = observed.get("typed_check")
        if not typed:
            return None
        specification = typed["contract"]
        old = typed["receipt"]["assertion"]
        binding = ImplicationBinding(**specification["binding"])
        span = tuple(observed["span"])
        quote_sha, prefix_sha = observed["quote_sha256"], observed["event_prefix_sha256"]
        contract = ReviewedImplication(
            binding, tuple(Variable(**node) for node in specification["variables"]),
            tuple(predicate(node) for node in specification["domain_predicates"]),
            tuple(predicate(node) for node in specification["premises"]),
            predicate(specification["consequent"]), tuple(tuple(item) for item in specification["fixed_witness"]),
            specification["proof_sha256"], specification["review_sha256"],
        )
        if contract.sha256 != typed["contract_sha256"] or contract.statement_sha256 != typed["statement_sha256"]:
            raise ValueError("2026 reviewed mathematical statement differs")
        original_prefix_status = "ASSERTION_END_IN_ORIGINAL_DIAGNOSTIC"
    if old["sample_id"] != uid or old["response_sha256"] != source["archive_conversation_sha256"]:
        raise ValueError("Reviewed witness is attached to another observation")
    prefix = validate_span(text, span, quote_sha, prefix_sha)
    if len(prefix) > 12000 or binding.question_sha256 != source["archive_problem_sha256"]:
        raise ValueError("Assertion is outside the frozen prompt or reading window")
    assertion = AssertionReceipt(binding, contract.statement_sha256, uid, source["archive_conversation_sha256"],
                                 prefix_sha, span, quote_sha, review_sha)
    engine = LocalImplicationVerifier(contract, contract.sha256, approved_assertion_sha256=(assertion.sha256,),
                                     call_budget=1, work_budget=128, wall_budget_ns=500_000_000)
    receipt = engine.check(assertion, prefix)
    if receipt.status != REFUTE_THIS_LOCAL_ASSERTION_ONLY or not engine.authorizes_refutation(assertion, receipt):
        raise ValueError("Exact boundary replay did not preserve the reviewed mathematical counterexample")
    return {"case_id": row["case_id"], "sample_uid": uid, "original_diagnostic_prefix": original_prefix_status,
            "boundary_replay": receipt.as_dict()}


def main():
    channels, channel_sha = read(HERE / "D48_MATHARENA_CHANNEL_RECEIPT.json")
    blind, blind_sha = read(BLIND)
    if blind_sha != channels["reasoning_local_sha256"]:
        raise ValueError("Blind source changed")
    source = {row["sample_uid"]: row for row in blind["rows"]}
    readout, readout_sha = read(HERE / "D48_FINAL_READOUT_RECEIPT.json")
    if channel_sha != readout["channels_receipt_sha256"] or {r["sample_uid"] for r in readout["rows"]} != set(source):
        raise ValueError("Final-only readout differs from archived identities")
    reviews = {}
    reviewed = set()
    typed = []
    for year in (2025, 2026):
        scope, scope_sha = read(HERE / f"D48_BLIND_SCOPE_{year}.json")
        if scope_sha != readout["reviewer_freeze_sha256"][str(year)]:
            raise ValueError("Reviewer changed after final readout")
        reviews[year] = scope_sha
        for row in scope["rows"]:
            uid = row["sample_uid"]
            if uid in reviewed or source[uid]["case_id"] != row["case_id"] or source[uid]["year"] != year:
                raise ValueError("Changed review identity")
            reviewed.add(uid)
            text = source[uid]["reasoning_text"]
            lo, hi = row["reviewed_span_unicode_half_open"] if year == 2025 else row["reviewed_span"]
            if lo != 0 or hi > min(12000, len(text)) or digest(text[:hi]) != row["reviewed_prefix_sha256"]:
                raise ValueError("Reviewed prefix differs from the frozen source")
            if year == 2025:
                for field in ("earliest_relevant_span", "correction_within_reviewed_slice"):
                    anchor = row.get(field)
                    if anchor:
                        validate_span(text[:hi], anchor["span_unicode_half_open"], anchor["excerpt_sha256"],
                                      anchor["prefix_through_span_sha256"])
            result = replay(source[uid], row, scope_sha)
            if result:
                typed.append(result)
    if reviewed != set(source) or len(source) != 9 or len(typed) != 4:
        raise ValueError("Unexpected full study coverage")
    ordinary = {}
    for name in ("D48_ORDINARY_2025_FREEZE.json", "D48_ORDINARY_C10_PRE_GOLD.json", "D48_ORDINARY_HMMT_2026_CONTROLS.json"):
        _, ordinary[name] = read(HERE / name)
    artifact = {
        "status": "D48_BLIND_LOCAL_CHECKS_AND_FINAL_READOUT_FROZEN_BEFORE_GOLD",
        "method_sha256": channels["method_sha256"], "cohort_sha256": channels["cohort_sha256"],
        "archive_channels_sha256": channel_sha, "blind_input_sha256": blind_sha,
        "sample_uids": sorted(source), "reviewer_freeze_sha256": reviews,
        "final_readout_receipt_sha256": readout_sha, "final_readout_sha256": readout["final_readout_sha256"],
        "ordinary_control_sha256": ordinary,
        "typed_diagnostic_replay_counts": dict(Counter(x["boundary_replay"]["status"] for x in typed)),
        "typed_diagnostic_replays": typed,
        "scope": "Counterexamples at the archived assertion end. They are not online or terminal interventions. "
                 "2025 original review receipts used the entire bounded slice; the separate replays here remove later text.",
    }
    path = HERE / "D48_BLIND_OUTCOME_FREEZE.json"
    raw = (json.dumps(artifact, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    print(digest(raw))


if __name__ == "__main__":
    main()
