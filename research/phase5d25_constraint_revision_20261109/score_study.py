"""Freeze local memberships and stage evaluation answers only after generation closes."""

import argparse
import hashlib
import json
from pathlib import Path
import shlex

from remote_study import ROOT, PYTHON, put, read, remote_read, shell, ssh, utc


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jsonlines(path):
    return list(map(json.loads, path.read_bytes().splitlines()))


def require_receipt(mode):
    manifest = read(ROOT / f"{mode.upper()}_RETRIEVAL.json")
    if manifest["status"] != "COMPLETE" or any(w["exit_code"] != 0 for w in manifest["launcher"]["workers"]):
        raise ValueError(f"Raw {mode} run is incomplete")
    by_path = {item["path"]: item for item in manifest["files"]}
    for path, item in by_path.items():
        raw = (ROOT / path).read_bytes()
        if len(raw) != item["bytes"] or sha(raw) != item["sha256"]:
            raise ValueError(f"Retrieved raw evidence changed: {path}")
    return by_path


def add_record(records, path, case_id, seed, arm, retrieved, bank):
    rel = path.relative_to(ROOT).as_posix()
    if rel not in retrieved:
        raise ValueError("A planned scoring row lacks a retrieval receipt")
    records.append({"path": rel, "sha256": retrieved[rel]["sha256"], "case_id": case_id,
                    "seed": seed, "arm": arm, "evaluation_partition": bank})


def freeze(mode):
    retrieved = require_receipt(mode)
    records = []
    if mode == "development":
        case = ROOT / "development/development_results/worker_0/rank88"
        # The tuple is the independently verified unique solution from integer polynomial reduction.
        solution = read(ROOT / "DEVELOPMENT_GOLD_AUDIT.json")
        if solution["status"] != "UNIQUE_EXACT_SOLUTION" or solution["solution"] != [6, 31, -1]:
            raise ValueError("Historical tuple did not have the prerequired exact audit")
        answer = (json.dumps({"case_id": "Phase5B_rank88", "gold": "(6,31,-1)", "answer_kind": "tuple"}) + "\n").encode()
        expected_eval = sha(answer)
        for arm in ("GenericRewind", "ScopedRebaseNoCarry", "ScopedRebaseCarry"):
            add_record(records, case / (arm + ".json"), "Phase5B_rank88", 20261109, arm, retrieved, "historical_development")
    else:
        data = read(ROOT / "D3_DATA_FREEZE.json")["banks"][mode]
        cases = jsonlines(ROOT / "prepared_data" / mode / "visible.jsonl")
        for index, case in enumerate(cases):
            for seed_index, seed in enumerate(data["seeds"]):
                worker = (index + seed_index) % 2
                path = ROOT / mode / "native_results" / f"worker_{worker}" / f"{case['case_id']}_{seed}" / "result.json"
                add_record(records, path, case["case_id"], seed, "NativeContinue", retrieved, "native_bank")
        if mode == "bank":
            selection = read(ROOT / "quality/D3_PAIR_SELECTION.json")
            if selection["status"] != "FROZEN":
                raise ValueError("No formal-bank quality decision was frozen")
            if selection["quality_gate"] == "READY":
                paired = require_receipt("quality")
                for event in selection["selected"]:
                    case_id, seed = event["case_id"], event["seed"]
                    folder = ROOT / "quality/quality_results" / f"worker_{event['worker']}" / f"{case_id}_{seed}"
                    for arm in ("NativeContinue", "InContextCheck", "UnscopedIndependent", "ScopedIndependent"):
                        add_record(records, folder / (arm + ".json"), case_id, seed, arm, paired, "conditional_pair")
            elif selection["quality_gate"] != "NO_ELIGIBLE_TARGET" or selection["selected"]:
                raise ValueError("Unknown formal quality disposition")
        answer = ROOT / "prepared_data" / mode / "eval_only.jsonl"
        expected_eval = data["eval_only_sha256"]
    return records, answer, expected_eval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("precheck", "bank", "development"))
    args = ap.parse_args()
    mode = args.mode
    out = ROOT / mode
    if (out / "SCORES.json").exists():
        raise ValueError("The score has already been frozen")
    records, reference, expected_eval = freeze(mode)
    runner = (ROOT / "score_bank.py").read_bytes()
    base = (ROOT / "complete_answer.py").read_bytes()
    cpu_freeze = read(ROOT / "COMPLETE_ANSWER_FREEZE.json")
    if cpu_freeze["status"] != "CPU_VERIFIED_SCORER_FROZEN" or cpu_freeze["source_sha256"] != sha(base):
        raise ValueError("Scorer does not match the independent CPU gate")
    module = "complete_answer_v2" if mode == "bank" else "complete_answer"
    extractor = (ROOT / (module + ".py")).read_bytes()
    if mode == "bank":
        refined = read(ROOT / "COMPLETE_ANSWER_V2_FREEZE.json")
        if refined["source_sha256"] != sha(extractor):
            raise ValueError("D3 scorer differs from its post-calibration CPU freeze")
    manifest = {"status": "FROZEN_AFTER_GENERATION", "created_utc": utc(), "bank": mode,
                "records": records, "eval_sha256": expected_eval, "grader_runner_sha256": sha(runner),
                "complete_answer_sha256": sha(extractor), "extractor_module": module, "base_extractor_sha256": sha(base)}
    raw_manifest = (json.dumps(manifest, indent=2) + "\n").encode()
    with (out / "GRADE_FREEZE.json").open("xb") as stream:
        stream.write(raw_manifest)
    answers = reference.read_bytes() if isinstance(reference, Path) else reference
    if sha(answers) != expected_eval:
        raise ValueError("Local frozen reference differs")
    remote = read(ROOT / "IDENTITY_LAUNCH.json")["root"]
    target = remote + f"/scoring_{mode}"
    with ssh() as client, client.open_sftp() as ftp:
        try:
            ftp.stat(target)
        except FileNotFoundError:
            ftp.mkdir(target)
        put(ftp, target + "/score_bank.py", runner)
        put(ftp, target + "/complete_answer.py", base)
        if module != "complete_answer":
            put(ftp, target + "/" + module + ".py", extractor)
        put(ftp, target + "/GRADE_FREEZE.json", raw_manifest)
        put(ftp, target + "/eval_only.jsonl", answers)
        command = "CUDA_VISIBLE_DEVICES='' " + shlex.quote(PYTHON) + " -X utf8 -B " + shlex.quote(target + "/score_bank.py")
        command += " --root " + shlex.quote(remote) + " --scoring " + shlex.quote(target)
        print(shell(client, command, timeout=600), flush=True)
        score = remote_read(ftp, target + "/SCORES.json")
    if json.loads(score)["freeze_sha256"] != sha(raw_manifest):
        raise ValueError("Score result did not consume the declared freeze")
    with (out / "SCORES.json").open("xb") as stream:
        stream.write(score)
    (out / "SCORE_RECEIPT.json").write_bytes((json.dumps({"status": "COMPLETE", "sha256": sha(score),
              "freeze_sha256": sha(raw_manifest), "retrieved_utc": utc()}, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
