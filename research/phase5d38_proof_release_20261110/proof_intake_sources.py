"""Intake pinned public proof sources without bundling reference proof bodies."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from proof_intake_std_checks import STD_CASES, REVISION as STD_REVISION, blob, extract, record_path


ROOT = Path(__file__).resolve().parent
PINS = {
    "openai_original": (0, "https://github.com/openai/miniF2F", "4e433ff5cadff23f9911a2bb5bbab2d351ce5554"),
    "yang_port": (1, "https://github.com/yangky11/miniF2F-lean4", "5746b7d6c47855ce1294bed87329618ff7f1bc31"),
    "putnam": (2, "https://github.com/trishullab/PutnamBench", "a635813f5edf297d928f9bd5ef8324a26bdde09c"),
    "verisoft": (3, "https://github.com/utopia-group/VeriSoftBench", "8f5e8b36ab5fbdec6fd8d8f4ee0580d29647097a"),
    "deepmind": (4, "https://github.com/google-deepmind/miniF2F", "f0a20e14c1eeccd859d51bb4c2b3ee487889c303"),
    "std": (5, "https://github.com/leanprover/lean4", STD_REVISION),
    "leroy": (7, "https://github.com/leanprover/LeroyCompilerVerificationCourse", "a2730e7f9228b9d7ecf4510f1f8652f2cae7ba01"),
}
DEEP_TEST = "MiniF2F/Test.lean"
ORIGINAL_TEST = "lean/src/test.lean"
DEEP_CASES = (
    ("mathd_numbertheory_66", "A closed natural-number remainder identity.", "SOURCE_PROOF_PRESENT"),
    ("mathd_algebra_302", "Squaring a scaled complex unit.", "SOURCE_PROOF_PRESENT"),
    ("mathd_algebra_141", "Recover a sum of squares from a product and a perimeter constraint.", "NO_SOURCE_PROOF"),
    ("numbertheory_4x3m7y3neq2003", "Rule out an integral difference of weighted cubes.", "NO_SOURCE_PROOF"),
    ("induction_12dvd4expnp1p20", "Divisibility of a geometric expression at every natural index.", "NO_SOURCE_PROOF"),
)
PUTNAM_CASES = (
    ("putnam_1978_a1", "Pigeonhole pairing in a finite arithmetic progression."),
    ("putnam_1994_a1", "Divergence from positive binary-tree inequalities."),
)
VERISOFT_CASES = {
    363: "Simulation contract for compilation of arithmetic expressions.",
    364: "Big-step termination implies small-step reduction to SKIP.",
}
STD_DESCRIPTIONS = {
    "GetLsbD": "Bit-blasted indexed read agrees with circuit semantics, including an out-of-range index.",
    "Append": "Concatenation bitblaster reads the correct source circuit on each side of the split.",
    "Eq": "An equality circuit denotes bit-vector equality.",
}


def sha(raw):
    return sha256(raw).hexdigest()


def checkout(prefix, key):
    return prefix.with_name(f"{prefix.name}-{PINS[key][0]}")


def fetch(prefix, key, path):
    return blob(checkout(prefix, key), PINS[key][2], path)


def url(key, path):
    _, project, rev = PINS[key]
    return f"{project}/blob/{rev}/{path}"


def normalized(text):
    return " ".join(text.split())


def declaration(raw, name, corpus):
    source = raw.decode("utf-8")
    starts = list(re.finditer(rf"(?m)^theorem {re.escape(name)}\b", source))
    if len(starts) != 1:
        raise ValueError(f"{name} is missing or ambiguous")
    start = starts[0].start()
    if corpus in {"deepmind", "openai_original"}:
        end = source.index("\n\n", start)
    elif corpus == "putnam":
        end = len(source)
    elif corpus == "leroy":
        next_command = re.search(r"(?m)^(?:/-|--|theorem |lemma |def |end |@\[)", source[starts[0].end():])
        if next_command is None:
            raise ValueError("Expected bounded following source command")
        end = starts[0].end() + next_command.start()
    else:
        raise ValueError("Unsupported source slicing")
    exact = source[start:end].rstrip()
    header, delim, proof = exact.partition(":=")
    if not delim or not header.startswith("theorem ") or not proof.strip():
        raise ValueError(f"Malformed source declaration: {name}")
    header, proof = header.rstrip(), proof.strip()
    if re.search(r"(?m)^\s*(?:import|axiom|run_cmd|set_option|def|theorem)\s", header.split("\n", 1)[-1]
                 if "\n" in header else ""):
        raise ValueError("Unexpected command in the selected header")
    proof_status = "NO_SOURCE_PROOF" if re.fullmatch(r"(?:by\s+)?sorry", proof) else "SOURCE_PROOF_PRESENT"
    if proof_status == "SOURCE_PROOF_PRESENT" and re.search(r"\b(?:sorry|admit|axiom)\b", proof):
        raise ValueError("Selected purported proof contains an admission token")
    return {"source_raw_sha256": sha(raw), "declaration_sha256": sha(exact.encode()),
            "statement_sha256": sha(header.encode()), "proof_body_sha256": sha(proof.encode()),
            "proof_availability": proof_status, "source_char_span": [start, start + len(exact)],
            "source_line_span_inclusive": [source.count("\n", 0, start) + 1,
                                          source.count("\n", 0, start + len(exact)) + 1]}, header, proof


def run(prefix, std_receipt, output):
    sources = {}
    config_paths = {
        "openai_original": "leanpkg.toml", "yang_port": "lean-toolchain", "putnam": "lean4/lean-toolchain",
        "verisoft": "repos.json", "deepmind": "lean-toolchain", "std": None, "leroy": "lean-toolchain",
    }
    for key, (_, repo, revision) in PINS.items():
        path = config_paths[key]
        raw = fetch(prefix, key, path) if path is not None else None
        sources[key] = {"repository": repo, "revision": revision, "config_path": path,
                        "config_sha256": None if raw is None else sha(raw),
                        "toolchain_declared": raw.decode().strip() if path and path.endswith("lean-toolchain") else None}
    sources["openai_original"]["toolchain_declared"] = re.search(
        r'lean_version = "([^"]+)"', fetch(prefix, "openai_original", "leanpkg.toml").decode())[1]
    sources["std"]["toolchain_declared"] = "leanprover/lean4:v4.27.0"
    for key, path in (("yang_port", "lake-manifest.json"), ("putnam", "lean4/lake-manifest.json"),
                      ("deepmind", "lake-manifest.json"), ("leroy", "lake-manifest.json")):
        raw = fetch(prefix, key, path)
        dependencies = json.loads(raw)["packages"]
        sources[key]["lake_manifest_sha256"] = sha(raw)
        sources[key]["selected_dependencies"] = {row["name"]: row["rev"] for row in dependencies
                                                 if row["name"] in {"mathlib", "formal_conjectures", "batteries"}}
    config = json.loads(fetch(prefix, "verisoft", "repos.json"))["repos"]
    same_release = [key for key, row in config.items() if row["lean_toolchain"] == "leanprover/lean4:v4.27.0"]
    bench_raw = fetch(prefix, "verisoft", "data/verisoftbench.jsonl")
    bench = {row["id"]: row for row in map(json.loads, bench_raw.splitlines())}
    if len(config) != 23 or len(bench) != 500 or same_release:
        raise ValueError("Pinned VeriSoftBench release membership or environment differs")
    selected_project = config["LeroyCompilerVerificationCourse"]
    if (selected_project["commit"] != PINS["leroy"][2]
            or selected_project["lean_toolchain"] != sources["leroy"]["toolchain_declared"]):
        raise ValueError("VeriSoftBench upstream project identity differs")
    sources["verisoft"].update({"projects": len(config), "tasks": len(bench), "same_v4270_projects": same_release,
                               "dataset_sha256": sha(bench_raw)})
    sources["leroy"]["declared_source_license"] = selected_project["license"]

    rows = []
    dtest = fetch(prefix, "deepmind", DEEP_TEST)
    original_test = fetch(prefix, "openai_original", ORIGINAL_TEST)
    p_imports = fetch(prefix, "deepmind", "MiniF2F/ProblemImports.lean")
    sources["deepmind"]["problem_imports_sha256"] = sha(p_imports)
    sources["deepmind"]["test_theorem_lines"] = len(re.findall(rb"(?m)^theorem ", dtest))
    sources["deepmind"]["test_sorry_tokens_raw"] = len(re.findall(rb"\bsorry\b", dtest))
    for name, topic, expected in DEEP_CASES:
        metadata, _, _ = declaration(dtest, name, "deepmind")
        if metadata["proof_availability"] != expected:
            raise ValueError("MiniF2F selected proof status differs")
        original, _, _ = declaration(original_test, name, "openai_original")
        if original["proof_availability"] != "SOURCE_PROOF_PRESENT":
            raise ValueError("Selected original MiniF2F Lean 3 reference changed")
        rows.append({"source": "deepmind", "path": DEEP_TEST, "link": url("deepmind", DEEP_TEST),
                     "declaration": name, "topic": topic, "class": "NATURAL_PUBLISHED_STATEMENT",
                     "direct_imports": ["MiniF2F.ProblemImports"],
                     "scope_commands": ["open scoped Nat", "open scoped Real", "set_option autoImplicit false",
                                        "set_option relaxedAutoImplicit false"],
                     "forbidden_imports": ["MiniF2F.Test", "MiniF2F.Valid"],
                     "related_original_lean3_reference": {
                         "source": "openai_original", "path": ORIGINAL_TEST, "link": url("openai_original", ORIGINAL_TEST),
                         "scope": "Same declaration name in Lean 3. Source proof present; no port or theorem equivalence claim.",
                         **original},
                     "kernel_status_in_this_intake": "OFFICIAL_LAKE_ENVIRONMENT_REQUIRED", **metadata})
    for name, topic in PUTNAM_CASES:
        path = f"lean4/src/{name}.lean"
        raw = fetch(prefix, "putnam", path)
        metadata, header, _ = declaration(raw, name, "putnam")
        if metadata["proof_availability"] != "NO_SOURCE_PROOF" or "_solution" in header or b"_solution" in raw:
            raise ValueError("Expected a pure proof-only Putnam statement without an answer-key declaration")
        rows.append({"source": "putnam", "path": path, "link": url("putnam", path), "declaration": name,
                     "topic": topic, "class": "NATURAL_PUBLISHED_STATEMENT", "direct_imports": ["Mathlib"],
                     "scope_commands": re.findall(r"(?m)^open [^\n]+", raw.decode()),
                     "forbidden_imports": [name],
                     "kernel_status_in_this_intake": "SEPARATE_V4331_ENVIRONMENT_UNTESTED", **metadata})
    for case_id, topic in VERISOFT_CASES.items():
        task = bench[case_id]
        name, path = task["thm_name"], task["rel_path"]
        raw = fetch(prefix, "leroy", path)
        metadata, header, proof = declaration(raw, name, "leroy")
        if (task["lean_root"] != "LeroyCompilerVerificationCourse"
                or metadata["proof_availability"] != "SOURCE_PROOF_PRESENT"
                or normalized(task["thm_stmt"]) != normalized(header)
                or normalized(task["ground_truth_proof"]) != normalized(":= " + proof)):
            raise ValueError("Benchmark statement/proof disagrees with the pinned original project")
        rows.append({"source": "leroy", "path": path, "link": url("leroy", path), "declaration": name,
                     "topic": topic, "class": "NATURAL_PUBLISHED_PROJECT_THEOREM", "verisoftbench_id": case_id,
                     "benchmark_row_statement_sha256": sha(task["thm_stmt"].encode()),
                     "benchmark_row_proof_sha256": sha(task["ground_truth_proof"].encode()),
                     "benchmark_matches_upstream_modulo_whitespace": True,
                     "required_same_file_local_defs": [entry["name"] for entry in task["used_local_defs"]],
                     "required_same_file_local_lemmas": [entry["name"] for entry in task["used_local_lemmas"]],
                     "direct_imports": [value.removeprefix("import ") for value in task["imports"]],
                     "forbidden_imports": [path.removesuffix(".lean").replace("/", ".")],
                     "kernel_status_in_this_intake": "SEPARATE_V4230_RC2_ENVIRONMENT_UNTESTED", **metadata})
    proof_receipt_raw = std_receipt.read_bytes()
    proofs = json.loads(proof_receipt_raw)
    if proofs["status"] != "PASS_SOURCE_AND_CONTROL_CHECKS" or proofs["source_revision"] != STD_REVISION:
        raise ValueError("The kernel receipt does not match the pinned Lean Std source")
    checks = {row["source_declaration"]: row for row in proofs["cases"]}
    controlled = []
    for operation, qualified, inner in STD_CASES:
        record = extract(checkout(prefix, "std"), operation, qualified, inner)
        receipt = checks[qualified]
        keys = ("raw_sha256", "declaration_sha256", "header_sha256", "proof_sha256")
        if any(receipt[key] != record[key] for key in keys):
            raise ValueError("The kernel-checked Std proof source bytes differ from intake")
        rows.append({"source": "std", "path": record_path(operation), "link": url("std", record_path(operation)),
                     "declaration": qualified, "topic": STD_DESCRIPTIONS[operation],
                     "class": "NATURAL_PUBLISHED_PROJECT_THEOREM",
                     "proof_availability": "SOURCE_PROOF_PRESENT",
                     "kernel_status_in_this_intake": "RENAMED_WITH_MINIMAL_IMPORTS_KERNEL_ACCEPTED",
                     "source_line_span_inclusive": record["source_line_span_inclusive"],
                     "source_char_span": record["source_char_span"],
                     "source_raw_sha256": record["raw_sha256"], "declaration_sha256": record["declaration_sha256"],
                     "statement_sha256": record["header_sha256"], "proof_body_sha256": record["proof_sha256"],
                     "direct_imports": record["imports"], "forbidden_imports": [record["target_module"]],
                     "target_absence_confirmed": True, "reference_renamed_axioms": receipt["axioms"]})
        controlled.append({"natural_source": qualified, "class": "CONTROLLED_PROOF_BODY_OMISSION",
                           "unchanged_source_statement_sha256": record["header_sha256"],
                           "mutation": "Replace proof with by skip in the isolated renamed fixture.",
                           "observed_kernel_rejection": True,
                           "fixture_sha256": receipt["controlled_skip_mutation"]["fixture_sha256"]})
    if len(rows) != 12:
        raise ValueError("Unexpected public source intake membership")
    receipt = {"status": "COMPLETE_PUBLIC_SOURCE_INTAKE", "scope": "Public statements and proof provenance; not a model-ready or natural failure benchmark.",
               "sources": sources, "natural_public_statements": rows, "controlled_mutations_separate": controlled,
               "natural_public_statements_count": len(rows), "clean_source_proof_bodies_present": sum(
                   r["proof_availability"] == "SOURCE_PROOF_PRESENT" for r in rows),
               "related_original_lean3_proofs_for_selected_deepmind_names": len(DEEP_CASES),
               "checked_std_source_proofs": len(controlled), "std_kernel_receipt_sha256": sha(proof_receipt_raw),
               "proof_bodies_embedded": False, "model_payload_generated": False, "gpu_used": False}
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({key: receipt[key] for key in ("status", "natural_public_statements_count",
                                                    "clean_source_proof_bodies_present", "checked_std_source_proofs")}
                     | {"intake_sha256": sha(raw)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout-prefix", type=Path, required=True)
    parser.add_argument("--std-receipt", type=Path, default=ROOT / "proof_intake_std_kernel.json")
    parser.add_argument("--output", type=Path, default=ROOT / "proof_intake_manifest.json")
    args = parser.parse_args()
    run(args.checkout_prefix.resolve(), args.std_receipt.resolve(), args.output.resolve())
