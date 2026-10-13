"""Fresh, frozen-split baseline pilot, two independent GPU shards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reason_transition.core import Engine, stable_seed, grade, public, append_jsonl


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, default=2)
    args = p.parse_args()
    manifest = json.loads((ROOT / "provenance/data_freeze.json").read_text())
    assert manifest["new_generation_records_at_freeze"] == 0
    path = ROOT / "data/pilot.jsonl"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["splits"]["pilot"]["sha256"]
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    protocol = json.loads((ROOT / "provenance/pilot_protocol.json").read_text())
    out = ROOT / f"results/pilot_full_{args.shard}.jsonl"
    done = {json.loads(s)["problem_id"] for s in out.read_text().splitlines()} if out.exists() else set()
    e = Engine(args.model)
    # Runtime warmup is excluded from scientific measurements.
    for _ in range(2):
        warm = e.decode(e.prompt("What is 2 plus 2?"), 16, stable_seed("radar-warmup"))
        del warm
    for i, row in enumerate(rows):
        if i % args.shards != args.shard or row["problem_id"] in done:
            continue
        prompt = e.prompt(row["question"])
        seed = stable_seed(protocol["seed"], row["problem_id"], 0)
        e.torch.cuda.synchronize()
        start = time.perf_counter()
        trace = e.decode(prompt, protocol["max_think_tokens"], seed, capture=True)
        prefix = prompt + trace["ids"]
        answer = e.answer(prefix, seed, natural_closed=trace["stop_reason"] == "natural_end",
                          initial=(trace["cache"], trace["logits"]))
        e.torch.cuda.synchronize()
        wall_ms = 1000 * (time.perf_counter() - start)
        # Labels are used only after completing all model computation.
        scoring = grade(answer["text"], row["gold"])
        record = {"problem_id": row["problem_id"], "method": "bounded_full_boxed_v3",
                  "model_path": args.model, "seed": seed, "dtype": "float16", "attn": "sdpa",
                  "protocol_sha256": hashlib.sha256((ROOT / "provenance/pilot_protocol.json").read_bytes()).hexdigest(),
                  "correct": scoring["correct"], "grade": scoring, "wall_ms": wall_ms,
                  "think_tokens": trace["tokens"], "answer_tokens": answer["tokens"],
                  "total_tokens": trace["tokens"] + answer["tokens"],
                  "trace": public(trace), "answer": public(answer),
                  "length_censored": trace["length_censored"],
                  "quality_labels_available_during_decisions": False,
                  "visible_gpu": os.environ.get("CUDA_VISIBLE_DEVICES")}
        append_jsonl(out, record)
        print(json.dumps({"pilot_index": i, "problem_id": row["problem_id"], "correct": record["correct"],
                          "tokens": record["total_tokens"], "wall_s": wall_ms / 1000,
                          "censored": record["length_censored"]}), flush=True)
        del trace, answer
    count = len(out.read_text().splitlines())
    assert count == sum(i % args.shards == args.shard for i in range(len(rows)))
    (ROOT / f"results/pilot_shard_{args.shard}.complete.json").write_text(json.dumps({"n": count, "unix": time.time()}))
    print("PILOT_SHARD_COMPLETE", args.shard, count, flush=True)


if __name__ == "__main__":
    main()
