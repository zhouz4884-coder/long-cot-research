"""Operate and retrieve the explicitly staged D2.5/D3 GPU experiments."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import stat

ROOT = Path(__file__).resolve().parent
PYTHON = "/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013/.venv/bin/python"
MODES = ("identity", "precheck", "bank", "quality", "development")


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def ssh():
    path = Path.home() / ".codex" / "local-tools" / "contractkv_ssh_credential.py"
    spec = importlib.util.spec_from_file_location("authorized_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ssh_client()


def remote_read(ftp, path):
    with ftp.open(path, "rb") as stream:
        return stream.read()


def shell(client, command, timeout=40):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    data = stdout.read().decode()
    errors = stderr.read().decode()
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"Remote command failed ({status}): {errors[-3000:]}")
    return data


def put(ftp, remote, raw):
    try:
        old = remote_read(ftp, remote)
    except FileNotFoundError:
        with ftp.open(remote, "wxb") as stream:
            stream.write(raw)
    else:
        if old != raw:
            raise ValueError(f"Remote artifact exists with different bytes: {remote}")
    if remote_read(ftp, remote) != raw:
        raise ValueError("Remote readback differed")


def launch(client, ftp, remote, mode):
    if mode == "identity":
        raise ValueError("Identity was independently frozen and launched")
    evidence = read(ROOT / "IDENTITY_RETRIEVAL.json")
    if evidence["status"] != "COMPLETE":
        raise ValueError("Real-device identity must pass before another launch")
    gates = [read(path) for path in (ROOT / "identity_results").glob("worker_*/*/IDENTITY_GATE.json")]
    controlled = read(ROOT / "identity_results/worker_0/controlled_action/CONTROLLED_GATE.json")
    if len(gates) != 4 or any(gate["status"] != "PASS" for gate in gates) or controlled["status"] != "PASS":
        raise ValueError("The identity or action gate did not pass")
    if mode in ("bank", "quality") and not (ROOT / "precheck" / "SCORES.json").is_file():
        raise ValueError("Close and score calibration before using the formal bank")
    if mode in ("precheck", "bank", "quality"):
        scorer = read(ROOT / "COMPLETE_ANSWER_FREEZE.json")
        if scorer["status"] != "CPU_VERIFIED_SCORER_FROZEN" or scorer["source_sha256"] != sha((ROOT / "complete_answer.py").read_bytes()):
            raise ValueError("Freeze and verify the scorer before native experiment launch")
    refined = None
    if mode in ("bank", "quality"):
        refined = read(ROOT / "COMPLETE_ANSWER_V2_FREEZE.json")
        if refined["source_sha256"] != sha((ROOT / "complete_answer_v2.py").read_bytes()):
            raise ValueError("Formal scorer failed the post-calibration source check")
        method = read(ROOT / "D3_METHOD_FREEZE.json")
        if method["status"] != "FROZEN_BEFORE_FORMAL_GENERATION" or any(
            sha((ROOT / name).read_bytes()) != value for name, value in method["files"].items()
        ):
            raise ValueError("Formal method source or frozen evidence changed")
    phase = remote + "/" + mode
    for path in (f"{phase}/{mode}_launcher.json", f"{phase}/eval_only.jsonl"):
        try:
            ftp.stat(path)
        except FileNotFoundError:
            continue
        raise ValueError("Unexpected existing experiment status or evaluation file")
    occupied = shell(client, "nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader,nounits").strip()
    if occupied:
        raise RuntimeError("A GPU is occupied. Inspect the running process before launching another worker.")
    code = """import pathlib, subprocess, sys, json
root=pathlib.Path.cwd(); mode=sys.argv[1]
with (root/(mode+'_parent.log')).open('xb') as log:
 child=subprocess.Popen([sys.executable,'-u','-B',str(root/'launch_d3_workers.py'),'--root',str(root),'--mode',mode],cwd=root,start_new_session=True,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
print(json.dumps({'pid':child.pid,'root':str(root),'mode':mode}))
"""
    command = "cd " + shlex.quote(remote) + " && " + shlex.quote(PYTHON) + " - " + shlex.quote(mode)
    result = json.loads(shell(client, command + " <<'D25_LAUNCH'\n" + code + "\nD25_LAUNCH"))
    result.update(created_utc=utc(), protocol_sha256=sha((ROOT / "D3_PAIRING_PROTOCOL.json").read_bytes()))
    if refined is not None:
        result["complete_answer_v2_sha256"] = refined["source_sha256"]
        result["method_freeze_sha256"] = sha((ROOT / "D3_METHOD_FREEZE.json").read_bytes())
    path = ROOT / f"{mode.upper()}_LAUNCH.json"
    with path.open("xb") as stream:
        stream.write((json.dumps(result, indent=2) + "\n").encode())
    return result


def fetch(ftp, remote, mode):
    prefix = "" if mode == "identity" else mode + "/"
    stage = remote + "/" + prefix
    status_name = f"{mode}_launcher.json"
    status = json.loads(remote_read(ftp, stage + status_name))
    if status["status"] != "FINISHED" or any(worker["exit_code"] != 0 for worker in status["workers"]):
        raise ValueError("Retrieve the complete run only after both workers exited successfully")
    relative_result = "identity_results" if mode == "identity" else "native_results" if mode in ("precheck", "bank") else f"{mode}_results"
    files = []

    def save(relative):
        data = remote_read(ftp, stage + relative)
        destination = ROOT / (prefix + relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"Would replace completed evidence: {destination}")
        destination.write_bytes(data)
        files.append({"path": prefix + relative, "bytes": len(data), "sha256": sha(data)})

    def walk(relative):
        for entry in sorted(ftp.listdir_attr(stage + relative), key=lambda item: item.filename):
            child = relative + "/" + entry.filename
            if stat.S_ISLNK(entry.st_mode):
                raise ValueError("Unexpected symlink in experiment results")
            if stat.S_ISDIR(entry.st_mode):
                walk(child)
            elif entry.filename.endswith(".json"):
                save(child)

    walk(relative_result)
    for worker in status["workers"]:
        save(f"logs/{mode}_worker_{worker['worker']}.log")
    save(status_name)
    record = {"status": "COMPLETE", "mode": mode, "retrieved_utc": utc(), "launcher": status, "files": files}
    receipt = ROOT / f"{mode.upper()}_RETRIEVAL.json"
    receipt.write_bytes((json.dumps(record, indent=2) + "\n").encode())
    return {"status": "COMPLETE", "mode": mode, "files": len(files),
            "gpu_minutes": sum(worker["elapsed_seconds"] for worker in status["workers"]) / 60,
            "wall_seconds": status["elapsed_seconds"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("launch", "fetch"))
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args()
    remote = read(ROOT / "IDENTITY_LAUNCH.json")["root"]
    with ssh() as client, client.open_sftp() as ftp:
        output = launch(client, ftp, remote, args.mode) if args.action == "launch" else fetch(ftp, remote, args.mode)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
