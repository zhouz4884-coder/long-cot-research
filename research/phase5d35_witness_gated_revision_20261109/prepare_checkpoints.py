"""Stage only the source tokens and RNG already observable at each development gate."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
CASES = {"e12": ("D3_E12", 20261110, 152), "e15": ("D3_E15", 20261110, 464)}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def id_sha(ids):
    return sha(json.dumps(ids, separators=(",", ":")).encode())


def write_once(path, value):
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Frozen bytes differ: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main():
    raw_visible = (D3 / "prepared_data/bank/visible.jsonl").read_bytes()
    manifest = json.loads((D3 / "D3_DATA_FREEZE.json").read_bytes())
    if sha(raw_visible) != manifest["banks"]["bank"]["visible_sha256"]:
        raise ValueError("Frozen source question bank differs")
    questions = {row["case_id"]: row["question"] for row in map(json.loads, raw_visible.splitlines())}
    receipts = {row["path"]: row["sha256"] for row in json.loads((D3 / "BANK_RETRIEVAL.json").read_bytes())["files"]}
    expected = {}
    for key, (case, seed, step) in CASES.items():
        path, = (D3 / "bank/native_results").glob(f"worker_*/{case}_{seed}/result.json")
        raw = path.read_bytes()
        relative = path.relative_to(D3).as_posix()
        if sha(raw) != receipts[relative]:
            raise ValueError("Frozen raw source trajectory differs")
        row = json.loads(raw)
        event, = [event for event in row["events"] if event["step"] == step and event["thinking_open"]]
        t = event["end"]
        before = row["generated_ids"][:t]
        prompt = row["prompt_ids"]
        boundaries = sorted({x["end"] for x in row["steps"] if x["end"] <= t and x["boundary"] == "paragraph"})
        if t not in boundaries or not event.get("rng_state_base64"):
            raise ValueError("Requested checkpoint lacks live native state provenance")
        payload = {"case_id": case, "seed": seed, "source": relative, "source_sha256": sha(raw),
                   "source_worker": int(path.parent.parent.name.split("_")[-1]), "checkpoint_step": step,
                   "question": questions[case], "prompt_ids": prompt, "generated_ids": before,
                   "observed_prefix_sha256": id_sha(prompt + before), "boundary_offsets": boundaries,
                   "rng_state_base64": event["rng_state_base64"],
                   "scope": "Observed-only development checkpoint. No original future tokens, solution or Gold staged."}
        write_once(ROOT / "prepared" / f"{key}_checkpoint.json", payload)
        expected[key] = {"source": relative, "source_sha256": sha(raw), "full_ids_sha256": row["generated_sha256"],
                         "original_generated_tokens": len(row["generated_ids"]), "checkpoint_generated_count": t}
    write_once(ROOT / "DEVELOPMENT_SOURCE_COMPARISON.json", {"scope": "Local post-generation comparison only", "cases": expected})
    print(json.dumps({key: {"observed": item["checkpoint_generated_count"], "original_total": item["original_generated_tokens"]}
                      for key, item in expected.items()}, indent=2))


if __name__ == "__main__":
    main()
