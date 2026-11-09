"""Read back exact p159 fixture results and compare preserved declaration identities."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from p159_prepare_reviewed import APPROVED, FOUNDATIONAL, PROTECTED, ROOT, digest, need


NAMES = tuple("P159Bad." + row[0] for row in APPROVED.values())
INITIAL = tuple("P159Bad." + row[0] for row in PROTECTED.values())
IDENTITY_PREFIX = "P159_IDENTITY "
AXIOMS = re.compile(r"'([\w.]+)' depends on axioms: \[([^]]*)\]")
NO_AXIOMS = re.compile(r"'([\w.]+)' does not depend on any axioms")


def parse_output(text):
    messages = []
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith(IDENTITY_PREFIX):
            messages.append({"severity": "information", "data": line})
        elif line.startswith("{"):
            packet = json.loads(line)
            need(isinstance(packet, dict) and isinstance(packet.get("data"), str),
                 "Invalid Lean diagnostic data")
            messages.append(packet)
        else:
            raise ValueError("Unrecognized line in approved Lean stdout")
    return messages


def collect(messages, expected_axiom_names, *, identities):
    type_probes, axioms = {}, {}
    for msg in messages:
        need(msg.get("severity") not in {"error", "warning"}, "Approved Lean proof emitted a diagnostic")
        for line in msg["data"].splitlines():
            if line.startswith(IDENTITY_PREFIX):
                row = json.loads(line[len(IDENTITY_PREFIX):])
                name = row["name"]
                need(name in expected_axiom_names and name not in type_probes, "Unexpected identity declaration")
                need(set(row) == {"name", "type", "type_constants", "proof_constants"}
                     and isinstance(row["type"], str) and bool(row["type"].strip()),
                     "Missing elaborated type evidence")
                for key in ("type_constants", "proof_constants"):
                    need(isinstance(row[key], list) and all(isinstance(x, str) for x in row[key])
                         and len(set(row[key])) == len(row[key]), "Invalid direct constant set")
                    row[key] = sorted(row[key])
                need("sorryAx" not in row["proof_constants"], "Admitted proof found")
                type_probes[name] = row
            else:
                listed = AXIOMS.fullmatch(line)
                empty = NO_AXIOMS.fullmatch(line)
                if not (listed or empty):
                    continue
                name = (listed or empty)[1]
                found = {x.strip() for x in listed[2].split(",") if x.strip()} if listed else set()
                need(name in expected_axiom_names and name not in axioms and found <= FOUNDATIONAL,
                     "Missing or forbidden axiom closure")
                axioms[name] = sorted(found)
    need(set(axioms) == set(expected_axiom_names), "Incomplete axiom closure")
    need(set(type_probes) == (set(expected_axiom_names) if identities else set()),
         "Incomplete or unexpected identity output")
    return axioms, type_probes


def compare(source_receipt_path, observed_path, out):
    source_raw = source_receipt_path.read_bytes()
    observed_raw = observed_path.read_bytes()
    source, observed = json.loads(source_raw), json.loads(observed_raw)
    need(source["status"] == "ARCHIVE_BOUND_REVIEWED_SOURCE_ONLY"
         and observed["source_receipt_sha256"] == digest(source_raw)
         and observed["author_pins"] == source["expected_author_pins"]
         and observed["runtime_verified"] is True, "Runtime evidence is not bound to this fixture set")
    expected = source["prepared_fixtures"]
    cases = observed["cases"]
    need(set(cases) == set(expected), "Missing, duplicate or foreign fixture result")
    for path, run in cases.items():
        need(run["source_sha256"] == expected[path]["sha256"]
             and isinstance(run["returncode"], int) and not run["stderr"].strip(),
             "Fixture execution is not attributable to the reviewed source")
    names = ("p159_initial_identity.lean", "p159_accepted_identity.lean",
             "p159_author_exact_check.lean", "p159_false_helper_counterexample.lean")
    parsed = {}
    for path, declared in zip(names, (INITIAL, NAMES, NAMES, ("p159_false_helper_counterexample",)), strict=True):
        run = cases[path]
        need(run["returncode"] == 0, "A reviewed proof did not pass the author runtime")
        parsed[path] = collect(parse_output(run["stdout"]), declared, identities=path in names[:2])
    absence = cases["p159_import_absence.lean"]
    missing = [msg["data"] for msg in parse_output(absence["stdout"]) if msg["severity"] == "error"]
    need(absence["returncode"] != 0 and len(missing) == len(NAMES), "Source import absence was not proved")
    for declaration in NAMES:
        need(sum(declaration in line and re.search(r"unknown (?:constant|identifier)", line, re.I) is not None
                 for line in missing) == 1, "A target name is present before reviewed declarations")

    initial_axioms, initial_probes = parsed[names[0]]
    final_axioms, final_probes = parsed[names[1]]
    exact_axioms, _ = parsed[names[2]]
    original_axioms = {"P159Bad." + n: values for n, values in source["author_archived_axioms"].items()}
    need(final_axioms == exact_axioms == original_axioms, "Accepted source has a changed transitive axiom report")
    preserved = []
    for declaration in INITIAL:
        old, new = initial_probes[declaration], final_probes[declaration]
        flags = {"pretty_elaborated_type_equal": old["type"] == new["type"],
                 "type_direct_constants_equal": old["type_constants"] == new["type_constants"],
                 "proof_direct_constants_equal": old["proof_constants"] == new["proof_constants"],
                 "transitive_axioms_equal": initial_axioms[declaration] == final_axioms[declaration]}
        preserved.append({"declaration": declaration, **flags,
                          "type_sha256_initial": digest(old["type"]), "type_sha256_accepted": digest(new["type"]),
                          "type_direct_constant_count": len(old["type_constants"]),
                          "proof_direct_constant_count": len(old["proof_constants"]),
                          "axioms": final_axioms[declaration]})
    author_edges = {"P159Bad." + n: tuple(values)
                    for n, values in source["author_archived_blueprint_direct_dependencies"].items()}
    runtime_edges = {n: tuple(const for const in row["proof_constants"] if const in NAMES and const != n)
                     for n, row in final_probes.items()}
    need(runtime_edges == author_edges, "Elaborated proof-use edges disagree with author graph")
    exact_identity = all(all(row[key] for key in ("pretty_elaborated_type_equal", "type_direct_constants_equal",
                                                  "proof_direct_constants_equal", "transitive_axioms_equal"))
                         for row in preserved)
    report = {"status": "PASS" if exact_identity else "SOURCE_STABLE_BUT_IDENTITY_PROBE_DIFFERS",
              "scope": "Exact reviewed author-check and separate clean-process probes. Type formatting and direct constant-set equality do not imply proof-term or whole-environment identity.",
              "utc": datetime.now(timezone.utc).isoformat(), "source_receipt_sha256": digest(source_raw),
              "approved_runtime_observation_sha256": digest(observed_raw), "author_pins": observed["author_pins"],
              "source_target_absent_before_declarations": list(NAMES), "preserved_declarations": preserved,
              "complete_target": final_probes["P159Bad.p159_target"],
              "author_graph_edges_reproduced": runtime_edges, "author_check_axioms": exact_axioms,
              "false_original_helper_counterexample": {"status": "KERNEL_ACCEPTED", "a": 0, "d": 0,
                                                       "axioms": parsed[names[3]][0]["p159_false_helper_counterexample"]},
              "verified_original_proof_cells_released": 0, "model_generation": False}
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with out.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "protected": len(preserved), "sha256": digest(raw)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-receipt", type=Path, default=ROOT / "p159_reviewed_source_receipt.json")
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "p159_identity_receipt.json")
    args = parser.parse_args()
    compare(args.source_receipt, args.observed, args.output)
