"""Reconstruct all D3.6 source-bound point events from committed raw bytes."""

from collections import Counter
import json
import re

from freeze_scope_regressions import BASELINE, D36, REPO, ROOT, from_baseline, ids_digest, make_tokenizer, sha


BOUNDARY = re.compile(r"[.!?](?=\s|$)|\n[ \t]*\n")


def attempt_versions(row):
    final = row["generated_ids"]
    if ids_digest(final) != row["generated_sha256"]:
        raise ValueError("Final token identity mismatch")
    versions = [("final_attempt", final)]
    for number, draft in enumerate(row["rejected_drafts"]):
        first = draft["draft_start"]
        ids = final[:first] + draft["discarded_sampled_ids"]
        if len(ids) != draft["draft_end"] or ids_digest(ids) != draft["generated_sha256"]:
            raise ValueError("Rejected token identity mismatch")
        versions.append((f"discarded_{number}", ids))
    return versions


def reconstruct(row, versions, n, digest):
    candidates = [(name, ids[:n]) for name, ids in versions if len(ids) >= n]
    matched = [(name, ids) for name, ids in candidates if ids_digest(row["prompt_ids"] + ids) == digest]
    if not matched:
        raise ValueError("Observed token prefix has no matching attempt")
    return matched[0]


def clause_offsets(text, source):
    start, stop = source
    boundaries = list(BOUNDARY.finditer(text, max(0, start - 800), min(len(text), stop + 800)))
    left = max((m.end() for m in boundaries if m.end() <= start), default=max(0, start - 800))
    right = min((m.end() for m in boundaries if m.start() >= stop), default=min(len(text), stop + 800))
    return left, right


def capture_source(text, ids, span):
    first, last = span["token_span"]
    start, stop = span["char_span"]
    if not (0 <= first < last <= len(ids) and 0 <= start < stop <= len(text)):
        raise ValueError("Source span falls outside the observation")
    if ids_digest(ids[first:last]) != span["token_sha256"] or text[start:stop] != span["text"]:
        raise ValueError("Source span bytes do not match the observation")
    left, right = clause_offsets(text, (start, stop))
    window_left, window_right = max(0, left - 160), min(len(text), right + 100)
    return {"source_span": span, "clause_char_span": [left, right], "clause": text[left:right],
            "context_char_span": [window_left, window_right], "context": text[window_left:window_right]}


def recorded_feedback(row, decision, observed, attempt, phase):
    obligation = decision["obligation"]
    if not obligation:
        return None
    if phase == "final":
        if not attempt.startswith("discarded_"):
            return None
        draft = row["rejected_drafts"][int(attempt.split("_")[-1])]
        observed = draft["draft_start"]
    channel = "terminal_feedback" if phase == "final" else "event_feedback"
    matches = [f for f in row["forced_feedback"] if f["start_generated"] == observed and f["phase"] == channel
               and f.get("text", "").strip() == obligation["message"].strip()]
    if len(matches) > 1:
        raise ValueError("An obligation unexpectedly maps to multiple edits")
    if not matches:
        return None
    feedback, = matches
    return {k: feedback[k] for k in ("phase", "status", "tokens", "start_generated", "end_generated")}


def audit_arm(row, packet, plan, tokenizer, key):
    versions = attempt_versions(row)
    raw_events = []
    support = plan["observed_comparison"]
    for decision in row["initial_point_receipts"]:
        receipt = decision["receipt"]
        side = "left" if receipt["objective"] == support["left"] else "right"
        if receipt["objective"] != support[side]:
            raise ValueError("Initial point is not one of the observed comparison operands")
        source = support[f"{side}_span"]
        if tuple(source["token_span"]) != tuple(receipt["source_token_span"]):
            raise ValueError("Initial point does not bind the comparison source")
        raw_events.append(("checkpoint_operand", "FEASIBLE_CANDIDATE", receipt["objective"], source, decision))
    for event in row["point_audit_events"]:
        candidate, decision = event["candidate"], event["decision"]
        receipt = decision["receipt"]
        if any(candidate[k] != receipt[k] for k in ("candidate_id", "observed_prefix_sha256", "observed_count", "target_id")):
            raise ValueError("Live source and point receipt identities differ")
        raw_events.append((event["phase"], candidate["goal_claim_type"], candidate["value"], candidate["source_span"], decision))
    raw_prefixes = {}
    output = []
    for index, (phase, kind, value, source, decision) in enumerate(raw_events):
        receipt = decision["receipt"]
        n, digest = receipt["observed_count"], receipt["observed_prefix_sha256"]
        if (n, digest) not in raw_prefixes:
            attempt, ids = reconstruct(row, versions, n, digest)
            raw_prefixes[n, digest] = (attempt, ids, tokenizer.decode(ids, skip_special_tokens=False))
        attempt, ids, text = raw_prefixes[n, digest]
        if phase == "final":
            stop = (row["rejected_drafts"][int(attempt.split("_")[-1])]["stop_reason"]
                    if attempt.startswith("discarded_") else row["stop_reason"])
            expected_size = next(len(full) for name, full in versions if name == attempt)
            if stop != "EOS" or n != expected_size or "</think>" not in text or not decision["terminal"]:
                raise ValueError("Terminal claim is not from a closed EOS draft")
        evidence = capture_source(text, ids, source)
        output.append({"id": f"{key}:{index}", "trajectory": key, "phase": phase, "kind": kind,
                       "value": value, "attempt": attempt, "observed_generated_count": n, "observed_prefix_sha256": digest,
                       "candidate_id": receipt["candidate_id"], "target_id": receipt["target_id"], **evidence,
                       "v2_status": receipt["status"], "v2_action": decision["action"], "v2_terminal_veto": decision["veto"],
                       "v2_feedback": recorded_feedback(row, decision, n, attempt, phase)})
    return output


def write_once(path, report):
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Published-source reconstruction changed: {path.name}")
    else:
        path.write_bytes(raw)


def run():
    tokenizer = make_tokenizer()
    freeze = json.loads(from_baseline(D36 / "D36_EXPERIMENT_FREEZE.json"))
    arms, events = [], []
    for checkpoint in freeze["checkpoints"]:
        folder = D36 / "gpu_results" / checkpoint
        packet = json.loads(from_baseline(D36 / "prepared" / f"{checkpoint}_checkpoint.json"))
        initial_ids = packet["generated_ids"]
        plan = json.loads(from_baseline(folder / "SOURCE_BOUND_PLAN.json"))
        receipt = json.loads(from_baseline(D36 / f"{checkpoint.upper()}_RETRIEVAL.json"))
        manifest = {member["path"]: member for member in receipt["files"]}
        for rep in freeze["replicates"]:
            for arm in freeze["arms"]:
                path = folder / rep["id"] / f"{arm}.json"
                raw = from_baseline(path)
                rel = path.relative_to(D36).as_posix()
                if sha(raw) != manifest[rel]["sha256"] or len(raw) != manifest[rel]["bytes"]:
                    raise ValueError("Raw arm differs from its published retrieval receipt")
                row = json.loads(raw)
                if (row["status"] != "COMPLETE" or row["prompt_ids"] != packet["prompt_ids"]
                        or row["generated_ids"][:len(initial_ids)] != initial_ids):
                    raise ValueError("Raw arm is open or its initial observation differs")
                key = "/".join((checkpoint, rep["id"], arm))
                found = audit_arm(row, packet, plan, tokenizer, key)
                arms.append({"trajectory": key, "source_path": path.relative_to(REPO).as_posix(),
                             "source_sha256": sha(raw), "event_count": len(found), "stop_reason": row["stop_reason"],
                             "final_delivery": row["final_delivery"]})
                events.extend(found)
    counts = Counter(e["phase"] for e in events)
    if len(arms) != 48 or counts != {"checkpoint_operand": 36, "thinking": 403, "final": 12}:
        raise ValueError(f"Unexpected published frame count: {len(arms)}, {counts}")
    report = {"source_commit": BASELINE, "score_reference_read": False, "model_generation": False,
              "arm_count": len(arms), "event_count": len(events), "counts_by_phase": dict(counts), "arms": arms,
              "events": events}
    write_once(ROOT / "scope_event_inventory.json", report)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: result[k] for k in ("arm_count", "event_count", "counts_by_phase")}, indent=2))
