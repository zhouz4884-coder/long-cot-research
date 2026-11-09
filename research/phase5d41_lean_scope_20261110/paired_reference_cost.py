"""End-to-end controls for existing exact Lean environment lookup plus full verification."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
BASE = "94fc3cf7be07c59db3db9bab55c7492712d5c746"
sys.path.append(str(D39))
from author_runtime_setup import PROJECT, clean_env
from lean_resident_probe import ResidentLean
from measure_p159_replay_cost import check_environment


CASES = {
    "p14": {"library": "sub_dvd_pow_sub_pow", "accepted": "ordinary_inline_induction", "passing_receipt": "expert_split_control_results.json"},
    "p41": {"library": "Nat.sub_one_dvd_pow_sub_one", "accepted": "ordinary_inline_induction_use_positive_binder",
            "passing_receipt": "expert_split_recheck_results.json"},
}


def digest(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def pinned(name):
    path = D40 / name
    raw = path.read_bytes()
    relative = path.relative_to(REPO).as_posix()
    if raw != subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=REPO):
        raise ValueError("A D4.0 input is different from its published commit")
    return json.loads(raw)


def closure_names(source):
    names = re.findall(r"(?m)^#print axioms ([A-Za-z_][A-Za-z_0-9.]*)\s*$", source)
    if not names or len(names) != len(set(names)):
        raise ValueError("Trusted proof source has no unambiguous named closure")
    return names


def build_queue(archive):
    reviewed = pinned("cases_archive_failure_receipt.json")
    original = pinned("expert_split_control_results.json")
    author_scope = pinned("cases_source_receipt.json")
    queue = {}
    for case, spec in CASES.items():
        old = (archive / f"{case}_archived_exact_failure.lean").read_bytes()
        if digest(old) != reviewed["cases"][case]["source_sha256"] or reviewed["cases"][case]["source_shape_rejections"]:
            raise ValueError("Historical fixture is outside the D4.0 safe source review")
        missing, = (r for r in original["per_case"][case]["attempts"] if r["method"] == "direct_library_specialization")
        accepted, = (r for r in pinned(spec["passing_receipt"])["per_case"][case]["attempts"] if r["method"] == spec["accepted"])
        for row in (missing, accepted):
            if digest(row["source"]) != row["source_sha256"]:
                raise ValueError("A D4.0 authored proof differs from its actual checked source")
        name = spec["library"]
        line = f"  exact {name} "
        if missing["source"].count(line) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.]*", name):
            raise ValueError("Direct trusted library reference is not uniquely bound")
        explicit = missing["source"].replace(line, f"  exact _root_.{name} ", 1)
        inputs = [("exact_historical_negative", old.decode(), None, "ARCHIVED_REVIEWED_SOURCE_DEFER"),
                  ("explicit_root_missing_control", explicit, name, "CPU_AUTHORED_MANDATORY_ROOT_REFERENCE"),
                  ("ordinary_full_proof_control", accepted["source"], None, "CPU_AUTHORED_ORDINARY_PROOF_DEFER")]
        imports = author_scope["source_cases"][case]["exact_imports"]
        for _, text, _, _ in inputs:
            observed = re.findall(r"(?m)^import (\S+)\s*$", text)
            if observed != imports:
                raise ValueError("A proof input changes the original imports")
        queue[case] = {"imports": imports,
                       "sequence": ["direct", "query_then_full", "query_then_full", "direct"] if case == "p14"
                       else ["query_then_full", "direct", "direct", "query_then_full"],
                       "inputs": [{"id": item, "source": text, "source_sha256": digest(text), "mandatory_root_name": key,
                                   "scope": scope, "targets": closure_names(text)} for item, text, key, scope in inputs]}
    return {"status": "FROZEN_IDENTICAL_RESIDENT_PROOF_QUEUES", "baseline": BASE,
            "scope": "Fixed authored controls and safe exact historical negatives from D4.0. The historical failures remain deferred. An explicit root qualification is a constructed calibration input, not a reported historical skip. Both methods receive the identical proof queue.",
            "replay_cost_protocol_sha256": digest((ROOT / "D41_REPLAY_AND_COST_PROTOCOL.json").read_bytes()), "cases": queue}


def exact_query(imports, name):
    return ("".join(f"import {item}\n" for item in imports) + "\nopen Lean in\n"
            "#eval show CoreM Unit from do\n  let env ← getEnv\n"
            f'  logInfo m!"D41_EXACT|{name}|{{(env.find? `{name}).isSome}}"\n')


def frozen_metadata(queue):
    # The reviewer-approved historical proof sources stay in scratch. Their hashes and
    # D4.0 receipts are enough to reconstruct and authenticate these inputs.
    return {**queue, "cases": {case: {**item, "inputs": [{k: v for k, v in row.items() if k != "source"}
                                                      for row in item["inputs"]]}
                               for case, item in queue["cases"].items()}}


def available(result, name):
    good = [m["message"].strip() for m in result["messages"] if m["message"].strip().startswith(f"D41_EXACT|{name}|")]
    if result["status"] != "KERNEL_ACCEPTED" or len(good) != 1:
        raise ValueError("Existing Lean query did not yield an exact declaration verdict")
    flag = good[0].rsplit("|", 1)[1]
    if flag not in {"true", "false"}:
        raise ValueError("Lean did not return a Boolean availability verdict")
    return flag == "true"


def pass_queue(server, file, data, policy):
    began = time.perf_counter()
    rows, queries = [], []
    existing = {}
    if policy == "query_then_full":
        for name in sorted({r["mandatory_root_name"] for r in data["inputs"] if r["mandatory_root_name"]}):
            source = exact_query(data["imports"], name)
            response = server.check(file, source, [])
            existing[name] = available(response, name)
            queries.append({"root_name": name, "available": existing[name], **response})
    for item in data["inputs"]:
        key = item["mandatory_root_name"]
        if key in existing and not existing[key]:
            rows.append({"id": item["id"], "source_sha256": item["source_sha256"],
                         "status": "SKIPPED_MANDATORY_UNAVAILABLE", "full_check_seconds": 0.0})
        else:
            result = server.check(file, item["source"], item["targets"])
            if result["source_sha256"] != item["source_sha256"]:
                raise ValueError("The proof submitted to Lean differs from the frozen candidate")
            rows.append({"id": item["id"], "full_check_seconds": result["elapsed_seconds"], **result})
    return {"policy": policy, "queries": queries, "rows": rows, "elapsed_seconds": time.perf_counter() - began}


def cases_report(queue, command, env, *, run_retrieval):
    report = {}
    with tempfile.TemporaryDirectory(prefix="d41_paired_", dir=PROJECT) as directory:
        for case, data in queue["cases"].items():
            server = ResidentLean(command, PROJECT, timeout=100, env=env)
            file = Path(directory) / f"{case}_paired.lean"
            try:
                prefix = "".join(f"import {name}\n" for name in data["imports"]) + "\n#check Nat.add_zero\n"
                prelude = server.check(file, prefix, [])
                if prelude["status"] != "KERNEL_ACCEPTED":
                    raise ValueError("The matched Lean imports did not initialize")
                sequences = [pass_queue(server, file, data, policy) for policy in data["sequence"]]
                retrieval = None
                if run_retrieval:
                    fixture, = (row for row in data["inputs"] if row["id"] == "explicit_root_missing_control")
                    prefix = "  exact _root_." + fixture["mandatory_root_name"] + " "
                    proof_line, = (line for line in fixture["source"].splitlines() if line.startswith(prefix))
                    text = fixture["source"].replace(proof_line + "\n", "  exact?\n", 1)
                    retrieval = server.check(file, text, fixture["targets"])
            finally:
                began = time.perf_counter()
                server.close()
                shutdown = time.perf_counter() - began
            direct = [r for s in sequences if s["policy"] == "direct" for r in s["rows"]]
            checked = {r["id"] for r in direct if r["status"] == "KERNEL_ACCEPTED"}
            filtered = [r for s in sequences if s["policy"] == "query_then_full" for r in s["rows"]]
            accepted = {r["id"] for r in filtered if r["status"] == "KERNEL_ACCEPTED"}
            false_rejected = [r["id"] for r in filtered if r["status"].startswith("SKIPPED") and r["id"] in checked]
            report[case] = {"startup_seconds": server.startup_seconds, "prelude": prelude, "shutdown_seconds": shutdown,
                            "ordered_runs": sequences, "existing_exact_retrieval": retrieval,
                            "direct_accepted": sorted(checked), "filtered_accepted": sorted(accepted),
                            "same_acceptance_set": checked == accepted, "false_rejections": false_rejected}
            print(case, {"same_acceptance_set": checked == accepted,
                         "run_seconds": [(s["policy"], s["elapsed_seconds"]) for s in sequences]}, flush=True)
    return report


def run(queue, lean, lake, out, *, zero_delay, queue_seconds):
    began = time.perf_counter()
    source = json.loads((D39 / "D39_EVIDENCE_INPUTS.json").read_bytes())
    version = check_environment(lean, lake, PROJECT.resolve(), source)
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env["PATH"]
    prepare_seconds = time.perf_counter() - began
    flags = ["-Dserver.reportDelayMs=0"] if zero_delay else []
    result = cases_report(queue, [str(lake), "env", str(lean), *flags], env, run_retrieval=not zero_delay)
    report = {"status": "COMPLETE_PAIRED_CPU_CALIBRATION", "scope": "End-to-end warm resident controls with alternate policy order. Preparation, shared prelude, initialization, queries, full checks and shutdown are measured. No historical hard skips or model proof-search gain asserted.",
              "queue_sha256": digest(json.dumps(frozen_metadata(queue), ensure_ascii=False, indent=2) + "\n"),
              "lean": version, "queue_material_preparation_seconds": queue_seconds,
              "environment_preparation_seconds": prepare_seconds, "server_flags": flags,
              "delay_sensitivity_freeze_sha256": digest((ROOT / "D41_RESIDENT_DELAY_SENSITIVITY.json").read_bytes()),
              "retrieval_control_freeze_sha256": digest((ROOT / "D41_RETRIEVAL_CONTROL_FREEZE.json").read_bytes()),
              "per_case": result,
              "new_model_tokens": 0, "gpu_seconds": 0}
    with out.open("xb") as f:
        f.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive-dir", type=Path, required=True)
    cli.add_argument("--freeze", type=Path, required=True)
    cli.add_argument("--lean", type=Path)
    cli.add_argument("--lake", type=Path)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--report-delay-zero", action="store_true")
    args = cli.parse_args()
    began = time.perf_counter()
    queue = build_queue(args.archive_dir)
    raw = (json.dumps(frozen_metadata(queue), ensure_ascii=False, indent=2) + "\n").encode()
    if args.freeze.exists():
        if args.freeze.read_bytes() != raw:
            raise ValueError("Paired proof queue differs from its freeze")
    else:
        args.freeze.write_bytes(raw)
    if args.output:
        run(queue, args.lean.resolve(), args.lake.resolve(), args.output, zero_delay=args.report_delay_zero,
            queue_seconds=time.perf_counter() - began)
    else:
        print(digest(raw))
