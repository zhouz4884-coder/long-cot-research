"""Freeze the actual observed history and run the CPU admissibility check."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT.parent / "p05_design_review_20261105" / "runtime4552"
if RUNTIME.is_dir():
    sys.path.insert(0, str(RUNTIME))

from development_worker import digest_ids, prepare_plan
from paired_d2_worker import prompt_for


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_once(path, value):
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("Development fixture was already frozen")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return sha(payload)


def covering_span(tokenizer, ids, quote):
    text = tokenizer.decode(ids, skip_special_tokens=False)
    if text.count(quote) != 1:
        raise ValueError("Local checked premise cannot be uniquely anchored")
    start = text.index(quote)
    end = start + len(quote)

    def first_at_or_past(char_index):
        lo, hi = 0, len(ids)
        while lo < hi:
            mid = (lo + hi) // 2
            if len(tokenizer.decode(ids[:mid], skip_special_tokens=False)) >= char_index:
                hi = mid
            else:
                lo = mid + 1
        return lo

    lo, hi = first_at_or_past(start), first_at_or_past(end)
    if len(tokenizer.decode(ids[:lo], skip_special_tokens=False)) > start:
        lo -= 1
    if quote not in tokenizer.decode(ids[lo:hi], skip_special_tokens=False):
        raise ValueError("Token covering span does not preserve the mathematical premise")
    return [lo, hi]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer", type=Path, required=True)
    args = ap.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True, trust_remote_code=False)
    review = (ROOT / "DEV_FALSE_EVENT_REVIEW.json").read_bytes()
    row = next(row for row in json.loads(review)["phase5b_development_only"] if row["rank"] == 88)
    filename, line = row["source_line"].split(":")
    source = ROOT.parents[1] / "results/online" / filename
    raw = source.read_bytes().splitlines(keepends=True)[int(line) - 1]
    if sha(raw) != row["source_raw_line_sha256"]:
        raise ValueError("Historical source line changed")
    full = json.loads(raw)["trace"]["ids"]
    if digest_ids(full) != row["source_trace_ids_sha256"]:
        raise ValueError("Historical native token array changed")
    observed = row["observed"]
    selected = observed["233"]
    ids = full[:selected["observed_paragraph_token_span"][1]]
    if digest_ids(ids) != selected["original_generated_prefix_ids_sha256"]:
        raise ValueError("Historical cutoff changed")
    packet = {"status": "SOURCE_REVIEW_FROZEN", "case_id": "Phase5B_rank88", "question": row["question"],
              "candidate": [6, 31, -1], "generated_ids": ids, "generated_prefix_sha256": digest_ids(ids),
              "historical_raw_line_sha256": sha(raw), "independent_review_sha256": sha(review),
              "invalid_step_span": observed["170"]["observed_paragraph_token_span"],
              "conflict_step_span": selected["observed_paragraph_token_span"],
              "scope": "Historical generated prefix with newly seeded execution. Verified local coefficient and candidate feasibility. No historical KV/RNG identity."}
    for name, index in (("invalid", "170"), ("candidate", "150"), ("conflict", "233")):
        start, end = observed[index]["quote_covering_original_token_span"]
        if ids[start:end] != observed[index]["quote_covering_original_token_ids"]:
            raise ValueError("Independent source quote no longer matches sampled IDs")
        packet[name + "_span"] = [start, end]
    # The model writes a=3 in paragraph 210, not in the faulty paragraph 170.
    packet["derived_a_span"] = covering_span(tokenizer, ids, "Coefficient of x^8: a - 3 = 0 => a = 3.")
    for name in ("invalid", "candidate", "conflict", "derived_a"):
        start, end = packet[name + "_span"]
        packet[name + "_span_sha256"] = sha(tokenizer.decode(ids[start:end], skip_special_tokens=False).encode())
    prompt = prompt_for(tokenizer, packet["question"])
    opener = tokenizer.encode("<think>", add_special_tokens=False)
    if opener[0] not in prompt + ids:
        prompt += opener
    math, _, observation, plans, latest = prepare_plan(packet, tokenizer, prompt)
    bound = write_once(ROOT / "development/DEV_RANK88_PACKET.json", packet)
    check = {"status": "PASS", "packet_sha256": bound, "raw_source": row["source_line"],
             "input_prefix_sha256": observation.prefix_sha256, "boundaries": observation.complete_boundaries,
             "generic_cut": latest, "rebase_cut": plans["ScopedRebaseCarry"].cut_token,
             "carried_claims": plans["ScopedRebaseCarry"].carried_claims, "actual_a_source_tokens": packet["derived_a_span"],
             "certified_coefficient_difference": math["difference_from_claim_at_derived_a"],
             "candidate_feasibility": math["verified_feasibility"]["status"]}
    write_once(ROOT / "DEVELOPMENT_CPU_GATE.json", check)
    print(json.dumps(check, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
