"""Ordinary approved target-slot CPU comparison under the matched author runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter

from cascade_runtime_actions import actions
from cascade_runtime_probe import (CACHE, LEAN_ROOT, PREFIX, PROJECT, ROOT, ResidentLean, clean_env, cold_frame, digest,
                                   resident_frame, verified_environment)


SOURCE_RECEIPT = ROOT / "causal_cases_source_receipt.json"
SOURCE_SHA256 = "35b92fe363277eccfff22ab75825f65857bad0dcda766fee1e1a9664b348db28"
FREEZE = ROOT / "cascade_runtime_ordinary_freeze.json"
CASES = ("p104", "p113", "p41")
OPTIONS = "set_option warningAsError true\nset_option maxHeartbeats 200000\n"


def load_case(case, item, folder):
    record = item["target_slot"]
    if record["filename"] != f"{case}_target_slot.lean" or record["marker"] != "  d42_slot" or item["helpers"]:
        raise ValueError("Unexpected theorem slot or source helper authorization")
    data = (folder / record["filename"]).read_bytes()
    if digest(data) != record["source_sha256"]:
        raise ValueError("Approved theorem slot differs from review")
    source = data.decode()
    before, mark, after = source.partition(record["marker"])
    if not mark or source.count(mark) != 1 or digest(before) != record["immutable_prefix_sha256"]:
        raise ValueError("Immutable theorem prefix changed")
    header = item["immutable_target_header"]
    if digest(header) != item["immutable_target_header_sha256"] or before.count(header) != 1:
        raise ValueError("Immutable target header differs from the reviewed theorem")
    imports = "".join(f"import {name}\n" for name in item["exact_imports"])
    if not before.startswith(imports + "\n") or re.search(r"(?m)^set_option (?:maxHeartbeats|warningAsError)\b", before):
        raise ValueError("Unexpected source prelude or conflicting checker options")
    if f"#print axioms {item['target']}\n" not in after:
        raise ValueError("Review source lacks the exact named closure target")
    return {"prefix": imports + "\n" + OPTIONS + before[len(imports):], "suffix": after,
            "case": case, "target": item["target"], "imports": item["exact_imports"],
            "original_slot_sha256": record["source_sha256"], "target_header_sha256": digest(header)}


def render(case, body):
    return case["prefix"] + "\n".join("  " + line for line in body.splitlines()) + case["suffix"]


def run(slots):
    trusted = json.loads((ROOT / "cascade_runtime_trusted.json").read_bytes())
    if trusted["status"] != "PASS_TRUSTED_CASCADE":
        raise ValueError("Trusted anchored runtime controls must pass first")
    raw_receipt = SOURCE_RECEIPT.read_bytes()
    if digest(raw_receipt) != SOURCE_SHA256:
        raise ValueError("The approved source review receipt changed")
    receipt = json.loads(raw_receipt)
    if receipt["known_proofs_read_or_emitted"] or receipt["local_execution_performed_by_prepare"]:
        raise ValueError("The reviewed slots must exclude archived proof material")
    frozen = json.loads(FREEZE.read_bytes())
    for case in CASES:
        expected = [{"id": name, "proof_body_sha256": digest(body)} for name, body in actions(case)]
        if expected != frozen["actions_by_case"][case]:
            raise ValueError("Ordinary action differs from the frozen pre-run body")
    loaded = {case: load_case(case, receipt["cases"][case], slots) for case in CASES}
    start = perf_counter()
    environment = verified_environment()
    preparation = perf_counter() - start
    if environment != trusted["environment"]:
        raise ValueError("Exact runtime differs from trusted diagnostics controls")
    bindir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bindir / "lake.exe"), "env", str(bindir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    results, contexts = {}, []
    with tempfile.TemporaryDirectory(prefix="d42-approved-ordinary-", dir=CACHE) as temp:
        directory = Path(temp)
        for group in (("p104", "p113"), ("p41",)):
            imports = loaded[group[0]]["imports"]
            if any(loaded[case]["imports"] != imports for case in group):
                raise ValueError("Resident context group mixes different imports")
            server = ResidentLean(command, PROJECT, 120, env=env)
            try:
                path = directory / f"Resident_{group[0]}.lean"
                prelude = "".join(f"import {name}\n" for name in imports) + "\n#check True.intro\n"
                warmup = resident_frame(server, path, prelude, [])
                for case in group:
                    current = loaded[case]
                    rows = []
                    for label, body in actions(case):
                        source = render(current, body)
                        result = resident_frame(server, path, source, [current["target"]])
                        rows.append({"action": label, "proof_body_sha256": digest(body), **result})
                    results[case] = {"target": current["target"], "target_header_sha256": current["target_header_sha256"],
                                     "original_slot_sha256": current["original_slot_sha256"],
                                     "exact_imports": imports, "resident": rows,
                                     "accepted": [r["action"] for r in rows if r["status"] == "KERNEL_ACCEPTED"]}
                    print(json.dumps({"checkpoint": case, "attempts": len(rows), "accepted": results[case]["accepted"]}), flush=True)
            finally:
                t = perf_counter()
                server.close()
                shutdown = perf_counter() - t
            contexts.append({"cases": list(group), "startup_seconds": server.startup_seconds,
                             "warmup": warmup, "shutdown_seconds": shutdown})
        for case, row in results.items():
            plain, = (body for label, body in actions(case) if label == "plain_whole_slot")
            source = render(loaded[case], plain)
            cold = cold_frame(command, directory / f"Cold_{case}_plain.lean", source, [row["target"]], env)
            warm, = (result for result in row["resident"] if result["action"] == "plain_whole_slot")
            if cold["source_sha256"] != warm["source_sha256"]:
                raise ValueError("Cold plain proof differs from its resident candidate")
            row["cold_plain"] = cold
            row["cold_resident_plain_status_and_axioms_agree"] = (cold["status"], cold["axioms"]) == (warm["status"], warm["axioms"])
    return {"status": "COMPLETE_APPROVED_ORDINARY_CPU_BASELINE", "scope": "Reviewed theorem slots only. No archived attempt body or model code executed.",
            "source_receipt_sha256": digest(raw_receipt), "action_freeze_sha256": digest(FREEZE.read_bytes()),
            "environment": environment, "preparation_seconds": preparation, "resident_contexts": contexts,
            "cases": results, "resident_attempts": sum(len(row["resident"]) for row in results.values()),
            "cold_plain_attempts": len(results), "accepted_cases": sum(bool(row["accepted"]) for row in results.values()),
            "model_tokens": 0, "gpu_seconds": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slots", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.slots)
    with args.output.open("xb") as handle:
        handle.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": report["status"], "accepted": {case: r["accepted"] for case, r in report["cases"].items()}}))
