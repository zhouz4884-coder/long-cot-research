"""Read direct Lean constants and transitive local dependency paths for preserving proofs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from p159_identity_audit import collect, parse_output
from p159_prepare_reviewed import ROOT, digest, need
from p159_run_reviewed import PROJECT, RUNTIME, SUITES, invoke, verify_runtime


CASES = {
    "p165": ("p165_preserved_transplant.lean", "P165Bad",
             ("a_cubed", "a_value", "b_cubed", "b_value", "p165_target"),
             ("a_value", "b_cubed", "b_value")),
    "p94": ("p94_preserving_bridge.lean", "P94Bad",
            ("product_bound_wrong", "product_bound_expanded", "p94_target"), ("product_bound_wrong",)),
}


def fixed_suffix(names):
    names_lean = ", ".join(f"`{n}" for n in names)
    return ("\nopen Lean in\n"
            "#eval show Lean.Elab.Command.CommandElabM Unit from do\n"
            f"  let names : Array Name := #[{names_lean}]\n"
            "  let constantsToJson := fun (xs : Array Name) => Json.arr (xs.map (fun x => Json.str x.toString))\n"
            "  for n in names do\n"
            "    let some info := (← getEnv).find? n | throwError \"Missing reviewed declaration: {n}\"\n"
            "    let some proof := info.value? true | throwError \"Missing reviewed proof body: {n}\"\n"
            "    let display ← Lean.Elab.Command.liftTermElabM (Lean.Meta.ppExpr info.type)\n"
            "    let packet := Json.mkObj [(\"name\", Json.str n.toString),\n"
            "      (\"type\", Json.str display.pretty),\n"
            "      (\"type_constants\", constantsToJson info.type.getUsedConstants),\n"
            "      (\"proof_constants\", constantsToJson proof.getUsedConstants)]\n"
            "    IO.println (\"P159_IDENTITY \" ++ packet.compress)\n").encode()


def paths_from(graph, start):
    paths = {start: [start]}
    todo = [start]
    while todo:
        head = todo.pop(0)
        for child in graph[head]:
            if child not in paths:
                paths[child] = paths[head] + [child]
                todo.append(child)
    return paths


def save(path, packet):
    raw = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as f:
        f.write(raw)
    return digest(raw)


def run(runtime, project, smoke_path, freeze_path, output, scratches):
    smoke = smoke_path.read_bytes()
    pins = verify_runtime(runtime, project, smoke)
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"LEAN_PATH", "LEAN_SYSROOT", "LEAN_SRC_PATH", "HF_TOKEN",
                                "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"}}
    env.update({"PATH": str(runtime / "bin") + os.pathsep + env["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    receipts = {}
    with tempfile.TemporaryDirectory(prefix="d39-closure-probe-") as temp:
        temporary = Path(temp)
        prepared = {}
        for suite, (file, namespace, simple_names, preserve) in CASES.items():
            source_name, receipt_sha, default_scratch = SUITES[suite]
            source_raw = (ROOT / source_name).read_bytes()
            source = json.loads(source_raw)
            need(digest(source_raw) == receipt_sha and source["author_pins"] == pins, "Preserving source receipt differs")
            scratch = scratches[suite] or Path(tempfile.gettempdir()) / default_scratch
            base = (scratch / file).read_bytes()
            expected = source["prepared_fixtures"][file]
            need(len(base) == expected["bytes"] and digest(base) == expected["sha256"], "Preserving fixture differs")
            all_names = tuple(f"{namespace}.{n}" for n in simple_names)
            suffix = fixed_suffix(all_names)
            path = temporary / (suite + "_trusted_closure_probe.lean")
            with path.open("xb") as stream:
                stream.write(base + suffix)
            prepared[suite] = (path, all_names, tuple(f"{namespace}.{n}" for n in preserve),
                               {"base_source_receipt_sha256": receipt_sha, "base_fixture_sha256": digest(base),
                                "trusted_suffix_sha256": digest(suffix), "full_probe_sha256": digest(base + suffix)})
        freeze_sha = save(freeze_path, {"status": "FROZEN_BEFORE_CLOSURE_PROBES", "author_pins": pins,
                                       "runtime_smoke_sha256": digest(smoke),
                                       "scope": "Two reviewed preserving fixtures plus an auditor-authored read-only suffix.",
                                       "cases": {suite: row[3] for suite, row in prepared.items()}})
        for suite, (path, names, old, binding) in prepared.items():
            need(digest(path.read_bytes()) == binding["full_probe_sha256"], "Frozen probe changed")
            result = invoke(runtime, project, env, path, binding["full_probe_sha256"])
            need(result["returncode"] == 0 and not result["stderr"].strip(), "Read-only closure probe did not close")
            axioms, rows = collect(parse_output(result["stdout"]), names, identities=True)
            target = names[-1]
            direct_types = {n: sorted(set(row["type_constants"]) & set(names)) for n, row in rows.items()}
            direct_proofs = {n: sorted(set(row["proof_constants"]) & set(names)) for n, row in rows.items()}
            transitive = paths_from({name: sorted(set(direct_types[name]) | set(direct_proofs[name]))
                                     for name in names}, target)
            receipts[suite] = {**binding, "returncode": result["returncode"],
                               "target": target, "elaborated_target_type": rows[target]["type"],
                               "target_transitive_axioms": axioms[target],
                               "direct_constant_probe": rows,
                               "direct_local_type_constants": direct_types,
                               "direct_local_proof_constants": direct_proofs,
                               "target_paths_to_preserved_declared_nodes": {n: transitive.get(n) for n in old},
                               "all_preserved_nodes_actually_in_target_local_closure": all(n in transitive for n in old)}
    report = {"status": "MATCHED_RUNTIME_READ_ONLY_CLOSURE_PROBES_COMPLETED", "freeze_sha256": freeze_sha,
              "author_pins": pins, "scope": "All direct constants from actual Lean type and proof expressions. Transitive dependency paths over the local declarations, plus global transitive axiom closure. No timing or model score.",
              "cases": receipts, "model_generation": False, "gpu_seconds": 0}
    print({"status": report["status"], "sha256": save(output, report),
           "paths": {key: r["target_paths_to_preserved_declared_nodes"] for key, r in receipts.items()}}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--runtime-smoke", type=Path, default=ROOT / "author_runtime_smoke.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "p159_closure_probe_freeze.json")
    parser.add_argument("--output", type=Path, default=ROOT / "p159_closure_probe_receipt.json")
    parser.add_argument("--p165-scratch", type=Path)
    parser.add_argument("--p94-scratch", type=Path)
    a = parser.parse_args()
    run(a.runtime.resolve(), a.project.resolve(), a.runtime_smoke.resolve(), a.freeze.resolve(), a.output.resolve(),
        {"p165": a.p165_scratch, "p94": a.p94_scratch})
