"""Two-pass format challenge with a separate historical D3.6 E15 diagnostic."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from terminal_scalar_fallback import terminal_scalar_fallback


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
D36 = ROOT.parent / "phase5d36_progressive_witness_20261109"
BASE = "6e36e19"
FREEZE = ROOT / "terminal_challenge_freeze.json"
INPUTS = ROOT / "terminal_challenge_inputs.json"
LABELS = ROOT / "terminal_challenge_labels.json"
OBSERVED = ROOT / "terminal_observations.json"
SCORED = ROOT / "terminal_format_audit.json"
sys.path.insert(0, str(D3))
import complete_answer
import complete_answer_v2


_E15_ALIASES = (
    "greatest fibbish number", "greatest valid fibbish number",
    "greatest positive integer that is fibbish",
)


def sha(raw):
    return sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def utc():
    return datetime.now(timezone.utc).isoformat()


def published(path):
    relative = path.relative_to(REPO).as_posix()
    original = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=REPO)
    raw = path.read_bytes()
    if raw != original:
        raise ValueError(f"Published bytes changed: {relative}")
    return raw


def write_once(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as out:
        out.write(raw)
    return sha(raw)


def observe_one(text, *, kind, aliases, eos, closed, delivered):
    if eos and closed and delivered and kind == "scalar" and isinstance(text, str):
        frozen = complete_answer_v2.extract_final_answer(text, "scalar")
    else:
        frozen = {"status": "not_delivered", "reason": "uncommitted_or_unsupported_scalar_scope"}
    f2_scalar = None
    if frozen.get("status") == "ok" and len(frozen.get("components", [])) == 1:
        value = complete_answer._rational(frozen["components"][0])
        if value is not None:
            f2_scalar = str(value)
    decision = terminal_scalar_fallback(text, frozen, target_kind=kind, target_aliases=tuple(aliases),
                                       eos=eos, think_closed=closed, delivered=delivered)
    if decision["status"] == "FALLBACK_ACCEPT":
        start, end = decision["box_span"]
        if not (0 <= start < end <= len(text) and text[start:end].startswith(r"\boxed")):
            raise ValueError("Fallback did not preserve the actual selected text span")
    return {"frozen_f2": frozen, "frozen_f2_exact_scalar": f2_scalar, "fallback": decision}


def historical_observations():
    planned = json.loads(published(D36 / "D36_EXPERIMENT_FREEZE.json"))
    expected = [(replica["id"], arm) for replica in planned["replicates"] for arm in planned["arms"]]
    for cut in planned["checkpoints"]:
        retrieved = json.loads(published(D36 / f"{cut.upper()}_RETRIEVAL.json"))
        if retrieved["status"] != "COMPLETE":
            raise ValueError("A historical shard is unclosed")
        by_path = {entry["path"]: entry for entry in retrieved["files"]}
        for replica, arm in expected:
            key = f"gpu_results/{cut}/{replica}/{arm}.json"
            raw = published(D36 / key)
            digest = sha(raw)
            if (digest != by_path[key]["sha256"] or len(raw) != by_path[key]["bytes"]):
                raise ValueError("Historical trace hash mismatch")
            row = json.loads(raw)
            if (row["status"] != "COMPLETE" or row["case_id"] != "D3_E15"
                    or row["replicate"] != replica or row["arm"] != arm):
                raise ValueError("Historical trace identity mismatch")
            delivered = row["final_delivery"] == "NATIVE_MODEL_DRAFT"
            yield {"checkpoint": cut, "replicate": replica, "arm": arm, "source_path": key,
                   "source_sha256": digest, "EOS": row["EOS"], "capacity": row["hit_context_cap"],
                   "delivery": row["final_delivery"],
                   **observe_one(row["delivered_final_response"], kind="scalar", aliases=_E15_ALIASES,
                                 eos=row["EOS"], closed=row["think_closed"], delivered=delivered)}


def observe():
    freeze = read(FREEZE)
    raw = INPUTS.read_bytes()
    if sha(raw) != freeze["input_sha256"]:
        raise ValueError("Frozen synthetic input bytes changed")
    source = [Path(__file__), ROOT / "terminal_scalar_fallback.py", D3 / "complete_answer.py",
              D3 / "complete_answer_v2.py"]
    for path in source[2:]:
        published(path)
    records = []
    for row in json.loads(raw)["rows"]:
        result = observe_one(row["final_text"], kind=row["target_kind"], aliases=row["target_aliases"],
                             eos=row["eos"], closed=row["think_closed"], delivered=row["delivered"])
        records.append({"id": row["id"], "category": row["category"], **result})
    if len(records) != freeze["inputs_count"] or len({r["id"] for r in records}) != len(records):
        raise ValueError("Challenge membership differs from freeze")
    data = {"status": "FROZEN_BEFORE_LABELS", "frozen_utc": utc(),
            "challenge_freeze_sha256": sha(FREEZE.read_bytes()), "label_file_opened": False,
            "scoring_reference_opened": False, "source_sha256": {
                p.relative_to(REPO).as_posix(): sha(p.read_bytes()) for p in source},
            "fresh_synthetic_observations": records, "historical_d36_e15_observations": list(historical_observations())}
    digest = write_once(OBSERVED, data)
    print(json.dumps({"status": data["status"], "observations_sha256": digest,
                      "synthetic": len(records), "historical": len(data["historical_d36_e15_observations"])}))


def accepted_and_value(row, hybrid):
    if hybrid and row["fallback"]["status"] == "FALLBACK_ACCEPT":
        return True, row["fallback"]["normalized_scalar"]
    return row["frozen_f2"].get("status") == "ok", row["frozen_f2_exact_scalar"]


def outcome(expected, accepted, value):
    if expected is None:
        return "FALSE_ACCEPT" if accepted else "TRUE_ABSTAIN"
    if not accepted:
        return "FALSE_ABSTAIN"
    return "TRUE_ACCEPT" if expected == value else "WRONG_VALUE_ACCEPT"


def score(expected_observation_sha):
    raw = OBSERVED.read_bytes()
    observed = json.loads(raw)
    if (sha(raw) != expected_observation_sha or observed["status"] != "FROZEN_BEFORE_LABELS"
            or observed["label_file_opened"] or observed["scoring_reference_opened"]
            or observed["challenge_freeze_sha256"] != sha(FREEZE.read_bytes())
            or any(sha((REPO / p).read_bytes()) != digest for p, digest in observed["source_sha256"].items())):
        raise ValueError("Frozen observation or its source no longer agrees")
    opened = utc()
    labels_raw = LABELS.read_bytes()
    freeze = read(FREEZE)
    if sha(labels_raw) != freeze["label_sha256"]:
        raise ValueError("Frozen labels changed")
    labels = {row["id"]: row for row in json.loads(labels_raw)["rows"]}
    scores = []
    for row in observed["fresh_synthetic_observations"]:
        label = labels[row["id"]]
        f2 = accepted_and_value(row, False)
        hybrid = accepted_and_value(row, True)
        scores.append({"id": row["id"], "category": row["category"], **label,
                       "frozen_f2": outcome(label["expected_scalar"], *f2),
                       "supplemented": outcome(label["expected_scalar"], *hybrid),
                       "supplemented_value": hybrid[1], "new_accept": hybrid[0] and not f2[0],
                       "fallback_reason": row["fallback"]["reason"]})
    if set(labels) != {r["id"] for r in scores}:
        raise ValueError("Synthetic label membership does not match observations")
    summary = {mode: dict(Counter(row[mode] for row in scores)) for mode in ("frozen_f2", "supplemented")}
    for counts in summary.values():
        for name in ("TRUE_ACCEPT", "TRUE_ABSTAIN", "FALSE_ACCEPT", "FALSE_ABSTAIN", "WRONG_VALUE_ACCEPT"):
            counts.setdefault(name, 0)
    audit = {cut: json.loads(published(D36 / f"{cut.upper()}_GPU_AUDIT.json")) for cut in ("early", "late")}
    by_key = {(cut, row["replicate"], row["arm"]): row for cut, result in audit.items() for row in result["model_arms"]}
    by_arm = defaultdict(Counter)
    additional = []
    for row in observed["historical_d36_e15_observations"]:
        cut, replica, arm = row["checkpoint"], row["replicate"], row["arm"]
        baseline = by_key[(cut, replica, arm)]
        frozen_correct = baseline["correct"]
        if row["frozen_f2"].get("status") == "ok" and row["frozen_f2"] != baseline["readout"]:
            raise ValueError("Frozen F2 readout changed for a historical parsed response")
        candidate = row["fallback"]["normalized_scalar"]
        extra_correct = row["fallback"]["status"] == "FALLBACK_ACCEPT" and (
            candidate == str(audit[cut]["historical_reference_after_close"]))
        if row["frozen_f2"].get("status") != "ok":
            additional.append({"checkpoint": cut, "replicate": replica, "arm": arm,
                               "source_sha256": row["source_sha256"], "EOS": row["EOS"],
                               "capacity": row["capacity"], "delivery": row["delivery"],
                               "frozen_reason": row["frozen_f2"].get("reason"), "fallback": row["fallback"],
                               "extra_correct": extra_correct})
        by_arm[arm].update({"n": 1, "frozen_f2_correct": int(frozen_correct),
                           "supplemented_correct": int(frozen_correct or extra_correct)})
    report = {"status": "COMPLETE_DEVELOPMENT_FORMAT_AUDIT", "first_label_read_utc": opened,
              "observations_sha256": expected_observation_sha, "additional_gpu_seconds": 0,
              "fresh_synthetic_confusion": summary, "fresh_synthetic_rows": scores,
              "historical_d36_e15": {"scope": "Retrospective after the observed E15 formatting cases, separate from the frozen D3.6 F2 endpoint.",
                                     "by_arm": dict(by_arm), "nonparsed_or_undelivered_rows": additional}}
    digest = write_once(SCORED, report)
    print(json.dumps({"status": report["status"], "audit_sha256": digest, "challenge": summary,
                      "historical_fallback_accepts": sum(x["fallback"]["status"] == "FALLBACK_ACCEPT" for x in additional),
                      "historical_extra_correct": sum(x["extra_correct"] for x in additional)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("observe")
    grade = sub.add_parser("score")
    grade.add_argument("--observation-sha", required=True)
    args = parser.parse_args()
    if args.operation == "observe":
        observe()
    else:
        score(args.observation_sha)
