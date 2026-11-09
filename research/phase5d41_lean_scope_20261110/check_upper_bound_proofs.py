"""Named-library full checks under a separately frozen additional-import upper bound."""

import argparse
import json
import os
from pathlib import Path
import tempfile

from paired_reference_cost import D39, PROJECT, ROOT, build_queue, check_environment, clean_env, digest, frozen_metadata
from lean_resident_probe import cold_check


def run(args):
    queue = build_queue(args.archive_dir)
    queue_bytes = (json.dumps(frozen_metadata(queue), ensure_ascii=False, indent=2) + "\n").encode()
    if (ROOT / "D41_PAIRED_QUEUE_FREEZE.json").read_bytes() != queue_bytes:
        raise ValueError("Upper-bound inputs differ from the frozen original scopes")
    frozen_raw = (ROOT / "D41_UPPER_FULL_PROOF_FREEZE.json").read_bytes()
    upper = json.loads(frozen_raw)
    permission = json.loads((ROOT / "D41_REPLAY_AND_COST_PROTOCOL.json").read_bytes())
    imports = upper["extra_imports"]
    if imports != permission["additional_import_upper_bound_only"]:
        raise ValueError("Upper-bound imports do not match the predeclared permission")
    lean, lake = args.lean.resolve(), args.lake.resolve()
    version = check_environment(lean, lake, PROJECT.resolve(), json.loads((D39 / "D39_EVIDENCE_INPUTS.json").read_bytes()))
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env["PATH"]
    command = [str(lake), "env", str(lean)]
    rows = []
    with tempfile.TemporaryDirectory(prefix="d41_upper_", dir=PROJECT) as directory:
        for case, record in queue["cases"].items():
            old, = (r for r in record["inputs"] if r["id"] == "explicit_root_missing_control")
            source = old["source"].replace("\n\n", "\n" + "".join(f"import {name}\n" for name in imports) + "\n", 1)
            variants = [("only_frozen_additional_imports", source)]
            if case == "p41":
                step = "  exact _root_.Nat.sub_one_dvd_pow_sub_one 10 n"
                if source.count(step) != 1:
                    raise ValueError("p41 authored proof body differs")
                fixed = ("  cases n with\n  | zero => exact False.elim (Nat.lt_irrefl 0 h₀)\n"
                         "  | succ n => exact _root_.Nat.sub_one_dvd_pow_sub_one 10 (n + 1)")
                variants.append(("additional_imports_and_explicit_binder_use", source.replace(step, fixed)))
            for mode, text in variants:
                result = cold_check(command, PROJECT, Path(directory) / f"{case}_{len(rows)}.lean", text, old["targets"],
                                    timeout=100, env=env)
                rows.append({"case": case, "mode": mode, "original_source_sha256": old["source_sha256"], **result})
                print(case, mode, result["status"], flush=True)
    report = {"status": "COMPLETE_SEPARATE_BROADER_IMPORT_UPPER_BOUND", "scope": "Ordinary CPU checks with additional imports. No matched original-scope proof costs or acceptance are changed.",
              "freeze_sha256": digest(frozen_raw), "version": version, "new_model_tokens": 0, "gpu_seconds": 0, "rows": rows}
    with args.output.open("xb") as f:
        f.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("lean", "lake", "archive-dir", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    run(parser.parse_args())
