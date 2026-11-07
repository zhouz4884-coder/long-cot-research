"""Run the fixed D2 NativeContinue coverage matrix on the two owned devices."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from native_worker import write

GPUS = ["GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a", "GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28"]
MODEL = "/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B"


def main():
    root = Path(__file__).resolve().parent
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    status_path = root / "coverage_launcher.json"
    if status_path.exists():
        raise RuntimeError("Inspect the existing launch before any recovery")
    started = time.time()
    children = []
    for worker, gpu in enumerate(GPUS):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="4", MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4")
        path = logs / f"coverage_{worker}.log"
        command = [sys.executable, "-u", "-B", str(root / "native_d2_worker.py"), "--root", str(root),
                   "--model", MODEL, "--gpu", gpu, "--worker", str(worker)]
        with path.open("xb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL, cwd=root, env=env)
        children.append((worker, gpu, process, time.time()))
    ended = {}
    while len(ended) < len(children):
        rows = []
        for worker, gpu, process, began in children:
            code = process.poll()
            if code is not None:
                ended.setdefault(worker, time.time())
            rows.append({"worker": worker, "gpu": gpu, "pid": process.pid, "exit_code": code,
                         "elapsed_seconds": ended.get(worker, time.time()) - began})
        write(status_path, {"status": "FINISHED" if len(ended) == len(children) else "RUNNING",
                            "launcher_pid": os.getpid(), "workers": rows,
                            "elapsed_seconds": time.time() - started})
        if len(ended) < len(children):
            time.sleep(3)


if __name__ == "__main__":
    main()
