"""Start the frozen native calibration on an idle card while rank88 runs."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from launch_d3_workers import GPUS, MODEL, write


def main():
    root = Path(__file__).resolve().parent
    phase = root / "precheck"
    log_dir = phase / "logs"
    log_dir.mkdir(exist_ok=True)
    status_path = phase / "precheck_launcher.json"
    dev_path = root / "development/development_launcher.json"
    if status_path.exists() or any(log_dir.glob("precheck_worker_*.log")):
        raise ValueError("Calibration already started")
    development = json.loads(dev_path.read_bytes())
    if len(development["workers"]) != 1 or development["workers"][0]["gpu"] != GPUS[0]:
        raise ValueError("Expected the dedicated historical development worker on GPU 0")
    started = time.monotonic()
    running, ended = {}, {}

    def spawn(worker):
        gpu = GPUS[worker]
        current = subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid",
                                           "--format=csv,noheader,nounits"], text=True)
        if any(row.split(",")[0].strip() == gpu for row in current.splitlines()):
            raise RuntimeError(f"GPU {worker} is occupied at calibration admission")
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="4", MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="1")
        entry = root / "legacy/native_d2_worker.py"
        command = [sys.executable, "-u", "-B", str(entry), "--root", str(phase), "--model", MODEL,
                   "--gpu", gpu, "--worker", str(worker)]
        with (log_dir / f"precheck_worker_{worker}.log").open("xb") as log:
            process = subprocess.Popen(command, cwd=phase, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        running[worker] = process, time.monotonic()

    spawn(1)
    while True:
        development = json.loads(dev_path.read_bytes())
        if 0 not in running and development["status"] == "FINISHED":
            spawn(0)
        rows = []
        for worker, (process, launched) in sorted(running.items()):
            code = process.poll()
            if code is not None:
                ended.setdefault(worker, time.monotonic())
            rows.append({"worker": worker, "gpu": GPUS[worker], "pid": process.pid, "exit_code": code,
                         "elapsed_seconds": ended.get(worker, time.monotonic()) - launched})
        finished = len(ended) == 2
        write(status_path, {"status": "FINISHED" if finished else "RUNNING", "mode": "precheck",
                            "launcher_pid": os.getpid(), "workers": rows, "elapsed_seconds": time.monotonic() - started,
                            "overlap_policy": "Worker 1 starts independently. Worker 0 starts when the dedicated development job releases its card.",
                            "worker_0_pending": 0 not in running})
        if finished:
            if any(row["exit_code"] != 0 for row in rows):
                raise SystemExit(1)
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
