"""Launch the frozen event experiment after the full native coverage bank."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from launch_coverage import GPUS, MODEL
from native_worker import write


def main():
    root = Path(__file__).resolve().parent
    coverage = json.loads((root / "coverage_launcher.json").read_text(encoding="utf-8"))
    if coverage["status"] != "FINISHED" or any(worker["exit_code"] != 0 for worker in coverage["workers"]):
        raise ValueError("Native coverage must finish successfully before paired generation")
    status_path = root / "pairing_launcher.json"
    if status_path.exists():
        raise ValueError("Inspect existing pairing processes before any recovery")
    selection = json.loads((root / "PAIR_SELECTION.json").read_text(encoding="utf-8"))
    if selection["status"] != "FROZEN":
        raise ValueError("Event selection is not frozen")
    started = time.time()
    children = []
    for worker, gpu in enumerate(GPUS):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="4", MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4")
        command = [sys.executable, "-u", "-B", str(root / "paired_d2_worker.py"),
                   "--root", str(root), "--model", MODEL, "--gpu", gpu, "--worker", str(worker)]
        path = root / "logs" / f"pairing_{worker}.log"
        with path.open("xb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL, cwd=root, env=env)
        children.append((worker, gpu, process, time.time()))
    ended = {}
    while len(ended) != len(children):
        rows = []
        for worker, gpu, process, began in children:
            code = process.poll()
            if code is not None:
                ended.setdefault(worker, time.time())
            rows.append({"worker": worker, "gpu": gpu, "pid": process.pid, "exit_code": code,
                         "elapsed_seconds": ended.get(worker, time.time()) - began})
        write(status_path, {"status": "FINISHED" if len(ended) == len(children) else "RUNNING",
                            "launcher_pid": os.getpid(), "workers": rows,
                            "elapsed_seconds": time.time()-started})
        if len(ended) != len(children):
            time.sleep(3)


if __name__ == "__main__":
    main()
