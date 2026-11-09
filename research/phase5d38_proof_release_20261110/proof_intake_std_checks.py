"""Kernel-check pinned Std verification proofs without importing their target modules."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent
REVISION = "db93fe1608548721853390a10cd40580fe7d22ae"
MODULE_ROOT = "Std.Tactic.BVDecide.Bitblast.BVExpr.Circuit"
REPO = "https://github.com/leanprover/lean4"
EXPECTED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
STD_CASES = (
    ("GetLsbD", "Std.Tactic.BVDecide.BVPred.denote_blastGetLsbD", ("BVPred",)),
    ("Append", "Std.Tactic.BVDecide.BVExpr.bitblast.denote_blastAppend", ("BVExpr", "bitblast")),
    ("Eq", "Std.Tactic.BVDecide.BVPred.mkEq_denote_eq", ("BVPred",)),
)


def digest(raw):
    return sha256(raw).hexdigest()


def blob(checkout, revision, path):
    return subprocess.check_output(["git", "-C", str(checkout), "show", f"{revision}:{path}"])


def record_path(operation):
    target = f"{MODULE_ROOT}.Lemmas.Operations.{operation}"
    return "src/" + target.replace(".", "/") + ".lean"


def extract(checkout, operation, qualified, inner):
    path = record_path(operation)
    raw = blob(checkout, REVISION, path)
    text = raw.decode("utf-8")
    target = qualified.split(".")[-1]
    start, = re.finditer(rf"(?m)^theorem {re.escape(target)}\b", text)
    stop = re.search(r"(?m)^end \w", text[start.end():])
    if not stop:
        raise ValueError("Source theorem lacks the expected enclosing namespace ending")
    end = start.end() + stop.start()
    declaration = text[start.start():end].rstrip()
    delim = re.search(r":=\s*by(?=\n)", declaration)
    if delim is None:
        raise ValueError("Selected Std proof lacks a separate tactic body")
    source_header = declaration[:delim.start()].rstrip()
    source_proof = declaration[delim.start() + 2:].strip()
    if not source_proof.startswith("by\n") or re.search(r"\b(?:sorry|admit|axiom)\b", source_proof):
        raise ValueError("Selected Std source proof is missing or outside the trusted fixture grammar")
    if re.search(rf"\b{re.escape(target)}\b", source_proof):
        raise ValueError("Source proof references the theorem being tested")
    imports = re.findall(r"(?m)^public import ([\w.]+)\s*$", text)
    if imports != [f"{MODULE_ROOT}.Lemmas.Basic", f"{MODULE_ROOT}.Impl.Operations.{operation}"]:
        raise ValueError("Source dependency context changed")
    if any(f"namespace {part}\n" not in text for part in inner):
        raise ValueError("Source namespace context changed")
    # Lean forbids #print axioms within a module. Preserve the source imports
    # and namespace while using ordinary imports in this standalone fixture.
    parts = ["prelude", *(f"import {item}" for item in imports),
             "", "namespace Std.Tactic.BVDecide",
             "", "open Std.Sat", "open Std.Sat.AIG", "", *(f"namespace {part}" for part in inner),
             "", "variable [Hashable α] [DecidableEq α]", ""]
    preamble = "\n".join(parts) + "\n"
    endings = "\n" + "\n".join(f"end {part}" for part in (*reversed(inner), "Std.Tactic.BVDecide")) + "\n"
    fresh = f"d38_intake_{target}"
    renamed = re.sub(rf"^theorem {re.escape(target)}\b", f"theorem {fresh}", source_header, count=1)
    renamed_qualified = ".".join((*qualified.split(".")[:-1], fresh))
    return {
        "path": path, "raw_sha256": digest(raw), "declaration_sha256": digest(declaration.encode()),
        "header_sha256": digest(source_header.encode()), "proof_sha256": digest(source_proof.encode()),
        "source_char_span": [start.start(), start.start() + len(declaration)],
        "source_line_span_inclusive": [text.count("\n", 0, start.start()) + 1,
                                      text.count("\n", 0, start.start() + len(declaration)) + 1],
        "imports": imports, "source_declaration": qualified, "renamed_declaration": renamed_qualified,
        "target_module": f"{MODULE_ROOT}.Lemmas.Operations.{operation}",
        "preamble": preamble, "endings": endings, "renamed": renamed, "proof": source_proof,
    }


def invoke(lean, scratch, name, source):
    path = scratch / (name + ".lean")
    raw = source.encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
    began = time.monotonic()
    result = subprocess.run([str(lean), "--json", path.name], cwd=scratch, capture_output=True,
                            check=False, timeout=45, encoding="utf-8")
    diagnostics = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    for item in diagnostics:
        if item.get("fileName"):
            item["fileName"] = Path(item["fileName"]).name
    if result.stderr.strip():
        raise ValueError(f"Lean emitted unexpected stderr in {name}")
    return {"returncode": result.returncode, "fixture_sha256": digest(raw),
            "seconds": time.monotonic() - began, "diagnostics": diagnostics}


def axiom_set(result, name):
    if result["returncode"] != 0 or any(item.get("severity") in {"error", "warning"} for item in result["diagnostics"]):
        raise ValueError(f"{name} was not a clean accepted proof")
    messages = [item["data"] for item in result["diagnostics"] if item.get("severity") == "information"]
    if len(messages) != 1 or f"'{name}'" not in messages[0]:
        raise ValueError(f"{name} has no independently parsed kernel axiom report")
    message, = messages
    if "does not depend on any axioms" in message:
        return []
    match = re.search(r"depends on axioms: \[([^]]*)\]", message)
    if not match:
        raise ValueError(f"{name} has unexpected axiom output")
    axioms = sorted({item.strip() for item in match[1].split(",") if item.strip()})
    if not set(axioms) <= EXPECTED_AXIOMS:
        raise ValueError(f"{name} has a non-admitted axiom")
    return axioms


def check_case(lean, checkout, root, operation, qualified, inner):
    material = extract(checkout, operation, qualified, inner)
    scratch = root / operation
    scratch.mkdir()
    prefix, suffix = material["preamble"], material["endings"]
    target = material["renamed_declaration"]
    absence = invoke(lean, scratch, "TargetAbsent", prefix + f"#check {qualified}\n" + suffix)
    errors = [item["data"] for item in absence["diagnostics"] if item.get("severity") == "error"]
    if (absence["returncode"] == 0 or len(errors) != 1 or qualified not in errors[0]
            or not re.search(r"unknown (?:identifier|constant)", errors[0], re.I)):
        raise ValueError(f"Target absence was not established: {qualified}")
    with_target = invoke(lean, scratch, "ReferenceModule", f"import {material['target_module']}\n#print axioms {qualified}\n")
    original_axioms = axiom_set(with_target, qualified)
    actual = invoke(lean, scratch, "RenamedSourceProof", prefix + material["renamed"] +
                    " := " + material["proof"] + suffix + f"\n#print axioms {target}\n")
    renamed_axioms = axiom_set(actual, target)
    if original_axioms != renamed_axioms:
        raise ValueError("Transitive axiom sets differ between original and isolated renamed proof")
    skipped = invoke(lean, scratch, "SkipMutant", prefix + material["renamed"] + " := by\n  skip" + suffix)
    skip_errors = [x["data"] for x in skipped["diagnostics"] if x.get("severity") == "error"]
    if skipped["returncode"] == 0 or not any("unsolved goals" in x for x in skip_errors):
        raise ValueError("Controlled missing-step mutation did not fail on the unchanged statement")
    searched = invoke(lean, scratch, "LibrarySearch", prefix + material["renamed"] + " := by\n  exact?" + suffix)
    search_errors = [x["data"] for x in searched["diagnostics"] if x.get("severity") == "error"]
    if searched["returncode"] == 0 and not search_errors:
        exact_status = "CLOSED_BY_EXACT_QUERY"
    elif any("unknown tactic" in item for item in search_errors):
        exact_status = "TACTIC_UNAVAILABLE_IN_EXACT_IMPORT_CONTEXT"
    else:
        exact_status = "DID_NOT_CLOSE_IN_THIS_QUERY"
    details = {k: v for k, v in material.items() if k not in {"preamble", "endings", "renamed", "proof"}}
    return {"scope": "Natural source theorem and exact source proof bytes, plus separate controlled by-skip mutation.",
            **details, "axioms": renamed_axioms, "target_absence": absence, "source_module_control": with_target,
            "renamed_proof": actual, "controlled_skip_mutation": skipped,
            "same_imports_exact_query": {"status": exact_status, **searched}}


def run(checkout, lean, output):
    version = subprocess.check_output([str(lean), "--version"], encoding="utf-8").strip()
    if "version 4.27.0," not in version or REVISION not in version:
        raise ValueError("Expected exact Lean v4.27.0 official toolchain")
    with tempfile.TemporaryDirectory(prefix="longcot-d38-std-kernel-") as scratch:
        scratch = Path(scratch)
        with ThreadPoolExecutor(max_workers=3) as pool:
            cases = list(pool.map(lambda case: check_case(lean, checkout, scratch, *case), STD_CASES))
    receipt = {"status": "PASS_SOURCE_AND_CONTROL_CHECKS", "repository": REPO, "source_revision": REVISION,
               "lean_version": version, "lean_binary_sha256": digest(lean.read_bytes()),
               "same_imports_search_scope": "One exact? query per theorem. Failure does not exclude an equivalent imported lemma.",
               "natural_source_proofs_checked": len(cases), "controlled_skip_mutations_rejected": len(cases),
               "model_generation": False, "cases": cases}
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": receipt["status"], "sha256": digest(raw),
                      "cases": [(case["source_declaration"], case["axioms"], case["same_imports_exact_query"]["status"])
                                for case in cases]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--lean", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "proof_intake_std_kernel.json")
    args = parser.parse_args()
    run(args.checkout.resolve(), args.lean.resolve(), args.output.resolve())
