"""Launch the frozen two-card worker matrix for one study phase."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


GPUS = ("GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a", "GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28")
MODEL = "/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B"


def write(path, record):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("identity", "development", "precheck", "bank", "quality"), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.mode == "identity":
        entry, phase = root / "paired_d2_worker.py", root
    elif args.mode == "development":
        entry, phase = root / "development_worker.py", root / "development"
    elif args.mode == "quality":
        entry, phase = root / "d3_quality_worker.py", root / "quality"
    else:
        entry, phase = root / "legacy" / "native_d2_worker.py", root / args.mode
    log_dir = phase / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status = phase / f"{args.mode}_launcher.json"
    if status.exists() or any(log_dir.glob(f"{args.mode}_worker_*.log")):
        raise RuntimeError("Existing launch found; inspect worker state before retry")
    started = time.monotonic()
    processes = []
    for worker, gpu in enumerate(GPUS[:1] if args.mode == "development" else GPUS):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="4", MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="1")
        command = [sys.executable, "-u", "-B", str(entry), "--root", str(phase), "--model", MODEL,
                   "--gpu", gpu, "--worker", str(worker)]
        with (log_dir / f"{args.mode}_worker_{worker}.log").open("xb") as stream:
            process = subprocess.Popen(command, cwd=phase, env=env, stdout=stream, stderr=stream,
                                       stdin=subprocess.DEVNULL)
        processes.append((worker, gpu, process, time.monotonic()))
    ended = {}
    while True:
        rows = []
        for worker, gpu, process, began in processes:
            code = process.poll()
            if code is not None:
                ended.setdefault(worker, time.monotonic())
            rows.append({"worker": worker, "gpu": gpu, "pid": process.pid, "exit_code": code,
                         "elapsed_seconds": ended.get(worker, time.monotonic()) - began})
        finished = len(ended) == len(processes)
        write(status, {"status": "FINISHED" if finished else "RUNNING", "mode": args.mode,
                       "launcher_pid": os.getpid(), "workers": rows, "elapsed_seconds": time.monotonic() - started})
        if finished:
            if any(row["exit_code"] != 0 for row in rows):
                raise SystemExit(1)
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
