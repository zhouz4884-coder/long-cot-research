"""Observe upstream generation without changing its behavior or source."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
import torch
from transformers.generation.utils import GenerationMixin

out = Path("results/original_raw.jsonl")
original = GenerationMixin.generate


def observed_generate(self, *args, **kwargs):
    inputs = kwargs.get("input_ids", args[0] if args else None)
    torch.cuda.synchronize()
    start = time.perf_counter()
    answer = original(self, *args, **kwargs)
    torch.cuda.synchronize()
    ms = 1000 * (time.perf_counter() - start)
    sequences = answer.sequences if hasattr(answer, "sequences") else answer
    n = inputs.shape[1]
    records = [{"call": observed_generate.calls, "input_ids": p, "generated_ids": r[n:],
                "prefix_hash": hashlib.sha256(json.dumps(p,separators=(",", ":")).encode()).hexdigest(),
                "batch_ms": ms, "batch_size": len(sequences), "max_new_tokens": kwargs.get("max_new_tokens"),
                "do_sample": kwargs.get("do_sample")} for p,r in zip(inputs.tolist(),sequences.tolist())]
    with out.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(json.dumps({"observed_generate":observed_generate.calls,"ms":round(ms,2),"tokens":int(sequences.shape[1]-n)}),flush=True)
    observed_generate.calls += 1
    return answer


observed_generate.calls = 0
GenerationMixin.generate = observed_generate
sys.argv = ["scripts/reason_budget_probe.py", *sys.argv[1:]]
runpy.run_path("vendor/llm-think-stop/scripts/reason_budget_probe.py", run_name="__main__")
