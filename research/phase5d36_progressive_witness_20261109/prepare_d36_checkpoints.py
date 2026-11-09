"""Derive the two E15 stage packets from immutable, already paid D3 bytes."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
FREEZE = ROOT / "D36_EXPERIMENT_FREEZE.json"
BASELINE = "3067767577275cd5e2a28b8053acee6d407d6f1c"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ids_sha(ids):
    return sha(json.dumps(ids, separators=(",", ":")).encode())


def pinned(path):
    relative = path.relative_to(REPO).as_posix()
    raw = path.read_bytes()
    committed = subprocess.check_output(["git", "show", f"{BASELINE}:{relative}"], cwd=REPO)
    if raw != committed:
        raise ValueError(f"Published source differs from worktree: {relative}")
    return raw


def write_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Previously frozen bytes differ: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def prepare():
    protocol = json.loads(FREEZE.read_bytes())
    if protocol["baseline_commit"] != BASELINE:
        raise ValueError("Protocol pins an unexpected source commit")
    visible = pinned(D3 / "prepared_data/bank/visible.jsonl")
    bank = json.loads(pinned(D3 / "D3_DATA_FREEZE.json"))["banks"]["bank"]
    if sha(visible) != bank["visible_sha256"]:
        raise ValueError("Frozen visible source hash does not match its receipt")
    receipts = json.loads(pinned(D3 / "BANK_RETRIEVAL.json"))["files"]
    bank_hashes = {entry["path"]: entry["sha256"] for entry in receipts}
    case = "D3_E15"
    question, = (row["question"] for row in map(json.loads, visible.splitlines()) if row["case_id"] == case)
    path, = (D3 / "bank/native_results").glob(f"worker_*/{protocol['source_trajectory']}/result.json")
    source = path.relative_to(D3).as_posix()
    source_raw = pinned(path)
    row = json.loads(source_raw)
    if sha(source_raw) != bank_hashes[source] or row["case_id"] != case or not row["EOS"]:
        raise ValueError("Source trajectory fails immutable native receipt")
    prompt = row["prompt_ids"]
    evidence = {}
    for name, desired in protocol["checkpoints"].items():
        step, cut = desired["step"], desired["retained_generated_tokens"]
        event, = (x for x in row["events"] if x["step"] == step and x["thinking_open"])
        boundaries = sorted({x["end"] for x in row["steps"] if x["end"] <= cut and x["boundary"] == "paragraph"})
        if event["end"] != cut or cut != boundaries[-1]:
            raise ValueError("Checkpoint is not a stored complete live thinking boundary")
        rng = event["rng_state_base64"]
        generated = row["generated_ids"][:cut]
        packet = {"case_id": case, "seed": row["seed"], "source": source, "source_sha256": sha(source_raw),
                  "source_worker": int(path.parent.parent.name.split("_")[-1]), "checkpoint_step": step,
                  "question": question, "prompt_ids": prompt, "generated_ids": generated,
                  "observed_prefix_sha256": ids_sha(prompt + generated), "boundary_offsets": boundaries,
                  "rng_state_base64": rng, "checkpoint": name,
                  "scope": "Observed-only. Future tokens and scoring references are not included."}
        packet_path = ROOT / "prepared" / f"{name}_checkpoint.json"
        write_once(packet_path, packet)
        evidence[name] = {"step": step, "observed_tokens": cut, "packet_sha256": sha(packet_path.read_bytes()),
                          "prefix_sha256": packet["observed_prefix_sha256"],
                          "rng_sha256": sha(base64.b64decode(rng, validate=True))}
    reference = {"scope": "Local evaluation only. Never staged to the model runner.", "baseline": BASELINE,
                 "source": source, "source_sha256": sha(source_raw), "original_generated_sha256": row["generated_sha256"],
                 "original_generated_tokens": len(row["generated_ids"]), "checkpoints": evidence}
    write_once(ROOT / "D36_SOURCE_REFERENCE.json", reference)
    return evidence


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
