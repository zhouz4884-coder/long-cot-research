"""Freeze real D3.6 target-scope failures with positive same-value controls."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D35 = ROOT.parent / "phase5d35_witness_gated_revision_20261109"
D36 = ROOT.parent / "phase5d36_progressive_witness_20261109"
BASELINE = "6e36e197fd4f68da9ebba769f6fe2140fad22f70"
sys.path.append(str(D35))
from audit_dev_checkpoints import make_tokenizer


SPECS = (
    ("outside_problem", "early/s20261111/ProgressiveWitness.json", "thinking", 123456789, 24128, "OUTSIDE_TASK"),
    ("maximum_six_digit", "early/s20261111/EveryStepAudit.json", "thinking", 303369, 20974, "LOCAL_MAXIMUM"),
    ("same_number_global_first_draft", "early/s20261111/ProgressiveWitness.json", "final", 303369, 24927,
     "CURRENT_FINAL_MAXIMUM"),
    ("current_feasibility", "late/historical/ProgressiveWitness.json", "thinking", 10112358, 25206,
     "CURRENT_FEASIBLE_CANDIDATE"),
    ("current_final_answer", "late/s20261111/ProgressiveWitness.json", "final", 10112369, 36105,
     "CURRENT_FINAL_MAXIMUM"),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ids_digest(ids):
    return sha(json.dumps(ids, separators=(",", ":")).encode())


def from_baseline(path):
    raw = path.read_bytes()
    path_in_git = path.relative_to(REPO).as_posix()
    pinned = subprocess.check_output(["git", "show", f"{BASELINE}:{path_in_git}"], cwd=REPO)
    if raw != pinned:
        raise ValueError(f"Archive source bytes differ from publication: {path_in_git}")
    return raw


def observed_attempt(row, candidate):
    final = row["generated_ids"]
    versions = {"delivered_or_held": final}
    for index, draft in enumerate(row["rejected_drafts"]):
        ids = final[:draft["draft_start"]] + draft["discarded_sampled_ids"]
        if ids_digest(ids) != draft["generated_sha256"]:
            raise ValueError("Archived rejected draft does not reconstruct")
        versions[f"rejected_draft_{index}"] = ids
    count = candidate["observed_count"]
    for attempt, ids in versions.items():
        observed = ids[:count]
        if len(observed) == count and ids_digest(row["prompt_ids"] + observed) == candidate["observed_prefix_sha256"]:
            return attempt, observed
    raise ValueError("Archived candidate prefix could not be reconstructed")


def freeze():
    tokenizer = make_tokenizer()
    fixtures = []
    for name, relative, phase, value, token_start, expected in SPECS:
        path = D36 / "gpu_results" / relative
        raw = from_baseline(path)
        row = json.loads(raw)
        event, = (e for e in row["point_audit_events"] if e["phase"] == phase and e["candidate"]["value"] == value
                  and e["candidate"]["source_span"]["token_span"][0] == token_start)
        candidate = event["candidate"]
        attempt, ids = observed_attempt(row, candidate)
        text = tokenizer.decode(ids, skip_special_tokens=False)
        span = candidate["source_span"]
        start, stop = span["char_span"]
        if text[start:stop] != span["text"]:
            raise ValueError("Observed prefix text disagrees with the archived claim")
        before = max(start - 320, 0)
        after = min(stop + 220, len(text))
        fixtures.append({"id": name, "input": path.relative_to(REPO).as_posix(), "input_sha256": sha(raw),
                         "observed_attempt": attempt, "observed_prefix_sha256": candidate["observed_prefix_sha256"],
                         "observed_generated_count": len(ids), "phase": phase, "value": value,
                         "source_span": span, "context_char_span": [before, after], "context": text[before:after],
                         "v2_type": candidate["goal_claim_type"], "v2_action": event["decision"]["action"],
                         "v2_obligation": event["decision"]["obligation"] is not None, "expected_scope": expected,
                         "eligible_for_current_global_goal_check": expected.startswith("CURRENT_")})
    payload = {"source_commit": BASELINE,
               "scope": "Purposively selected real development regressions with matching positive controls, not a held-out coverage set. Labels establish claim scope only, not mathematical truth.",
               "fixtures": fixtures}
    target = ROOT / "scope_regressions.json"
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("Frozen source-scoped fixtures differ")
    else:
        target.write_bytes(encoded)
    return payload


if __name__ == "__main__":
    result = freeze()
    print(json.dumps([(r["id"], r["expected_scope"], r["observed_attempt"]) for r in result["fixtures"]], indent=2))
