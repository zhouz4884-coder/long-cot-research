"""Fresh D2 natural coverage trajectories using the D1 native execution schedule."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from native_engine import NativeEngine, digest_ids
from native_worker import load, write
from observations import Observer

SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0, "batch": 1}
MODEL_HASH = "37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"


def prompt_for(tokenizer, question):
    messages = [{"role": "user", "content": question +
                 "\nPlease reason step by step, and put your final answer within \\boxed{}."}]
    prompt = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=True)
    closed = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
    if prompt == closed or not isinstance(prompt, list) or any(type(x) is not int for x in prompt):
        raise ValueError("Native thinking template failed")
    assistant = tokenizer.decode(prompt, skip_special_tokens=False).rsplit("<|im_start|>", 1)[-1]
    if not assistant.startswith("assistant\n") or "</think>" in assistant or "<|im_end|>" in assistant:
        raise ValueError("Malformed native assistant prompt")
    return prompt


def run_case(engine, prompt, seed, folder):
    started = time.monotonic()
    rng = engine.rng(seed=seed)
    engine.stage = "native_prefill"
    cache, logits = engine.prefill(prompt)
    engine.stage = "native_decode"
    generated, observer = [], Observer()
    thinking = engine.open_ids[0] in prompt
    if thinking:
        observer.open(0)
    last_closed = None
    stop = "CONTEXT_CAP"
    while len(prompt) + len(generated) < engine.capacity:
        token = engine.sample(logits, rng)
        generated.append(token)
        if token == engine.open_ids[0]:
            thinking = True
            observer.open(len(generated))
        elif token == engine.close_ids[0]:
            observer.complete(engine, prompt, generated, len(generated)-1, rng,
                              open_thinking=False, boundary="think_close")
            observer.step_start = None
            thinking = False
            last_closed = len(generated)
        if token in engine.eos:
            stop = "EOS"
            break
        if len(prompt) + len(generated) >= engine.capacity:
            break
        cache, logits = engine.forward([token], cache)
        if thinking and engine.tokenizer.decode(generated[-8:], skip_special_tokens=False).endswith("\n\n"):
            observer.complete(engine, prompt, generated, len(generated), rng,
                              open_thinking=True, boundary="paragraph")
        if len(generated) % 256 == 0:
            write(folder / "progress.json", {"status": "GENERATING", "tokens": generated,
                                             "elapsed_seconds": time.monotonic() - started,
                                             "events_observed": len(observer.events)})
    engine.sync()
    final_ids = generated[last_closed:] if last_closed is not None else []
    return {"status": "COMPLETE", "seed": seed, "prompt_ids": prompt, "prompt_sha256": digest_ids(prompt),
            "generated_ids": generated, "generated_sha256": digest_ids(generated),
            "text": engine.tokenizer.decode(generated, skip_special_tokens=False),
            "final_response": engine.tokenizer.decode(final_ids, skip_special_tokens=True),
            "think_closed": last_closed is not None and not thinking, "stop_reason": stop,
            "EOS": stop == "EOS", "hit_context_cap": stop == "CONTEXT_CAP",
            "new_tokens": len(generated), "context_capacity": engine.capacity,
            "elapsed_seconds": time.monotonic() - started, "steps": observer.steps,
            "events": observer.events, "checkpoints": observer.checkpoints,
            "ledger": engine.ledger, "sampling": SAMPLING}


def load_runtime(root, model_path, gpu):
    if os.environ.get("CUDA_VISIBLE_DEVICES") != gpu:
        raise RuntimeError("GPU identity mismatch")
    busy = subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                                    "--format=csv,noheader,nounits"], text=True)
    if any(line.split(",")[0].strip() == gpu for line in busy.splitlines()):
        raise RuntimeError("GPU already occupied")
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if transformers.__version__ != "4.55.2" or torch.__version__.split("+")[0] != "2.8.0":
        raise RuntimeError("D1 runtime mismatch")
    torch.set_num_threads(4)
    device = torch.device("cuda:0")
    assets = load(root / "p0_base_frozen.py", "d2_assets").model_file_manifest(model_path)
    if assets["manifest_sha256"] != MODEL_HASH:
        raise RuntimeError("D1 model asset mismatch")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.float16, attn_implementation="sdpa", low_cpu_mem_usage=True).eval().to(device)
    if next(model.parameters()).dtype != torch.float16 or model.config._attn_implementation != "sdpa":
        raise RuntimeError("D1 execution mode mismatch")
    metadata = {"gpu": gpu, "model_files": assets, "torch": torch.__version__, "transformers": transformers.__version__,
                "dtype": "FP16", "backend": "sdpa", "context_capacity": model.config.max_position_embeddings,
                "sampling": SAMPLING, "scientific_new_token_cap": None}
    return model, tokenizer, device, metadata


def verify_inputs(root, filename):
    for row in json.loads((root / filename).read_text(encoding="utf-8"))["files"]:
        if hashlib.sha256((root / row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Frozen input mismatch: {row['path']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--worker", type=int, required=True, choices=(0, 1))
    args = parser.parse_args()
    root = args.root
    verify_inputs(root, "coverage_freeze.json")
    out = root / "native_results" / f"worker_{args.worker}"
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    model, tokenizer, device, meta = load_runtime(root, args.model, args.gpu)
    import torch

    write(out / "manifest.json", {**meta, "worker": args.worker,
                                 "hash_and_load_seconds": time.monotonic() - started})
    cases = [json.loads(line) for line in (root / "d2_visible.jsonl").read_text(encoding="utf-8").splitlines()]
    protocol = json.loads((root / "COVERAGE_PROTOCOL.json").read_text(encoding="utf-8"))
    seeds = protocol["seeds"]
    tasks = [(case, seed, (question_index + seed_index) % 2)
             for question_index, case in enumerate(cases) for seed_index, seed in enumerate(seeds)]
    summaries = []
    for case, seed, assigned_worker in tasks:
        if assigned_worker != args.worker:
            continue
        folder = out / f"{case['case_id']}_{seed}"
        folder.mkdir(exist_ok=True)
        if (folder / "result.json").exists():
            row = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        else:
            engine = NativeEngine(model, tokenizer, device)
            prompt = prompt_for(tokenizer, case["question"])
            write(folder / "started.json", {"case_id": case["case_id"], "seed": seed,
                                           "prompt_sha256": digest_ids(prompt), "status": "IN_PROGRESS"})
            torch.cuda.reset_peak_memory_stats(device)
            with torch.inference_mode():
                row = run_case(engine, prompt, seed, folder)
            row.update(case_id=case["case_id"], peak_allocated_bytes=torch.cuda.max_memory_allocated(device),
                       question_hash=case["problem_hash"])
            write(folder / "result.json", row)
        summaries.append({key: row[key] for key in ("case_id", "seed", "EOS", "new_tokens", "elapsed_seconds")})
        write(out / "progress.json", {"status": "RUNNING", "completed": len(summaries), "cases": summaries,
                                      "elapsed_seconds": time.monotonic()-started})
    write(out / "summary.json", {"status": "COMPLETE", "completed": len(summaries), "cases": summaries,
                                 "elapsed_seconds": time.monotonic()-started})


if __name__ == "__main__":
    main()
