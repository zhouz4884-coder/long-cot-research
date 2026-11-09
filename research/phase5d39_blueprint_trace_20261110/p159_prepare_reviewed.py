"""Bind the released p159 patch chain and emit only explicitly reviewed Lean fixtures."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D38 = ROOT.parent / "phase5d38_proof_release_20261110"
BASELINE = "df460b430f8ec792af69b896edc5aa9f958a90a8"
RUN = "data/llm_calls/p159_algebra_patchsrcq_v0/typed/"
STATE_ID = "p159_bad.state0"
TARGET_ID = "thm:p159bad-target"
MODEL = "qwen/qwen3.6-flash"
ARCHIVE_SHA = "8a7a7e6ed192129a754f94ea85089978fc44f136fc11df01a1d676bf5b93ccb7"
INITIAL_SHA = "cb4f8755ac3d00e3250f99ff194eb2b62a429e4883f55487526749158f6c7d07"
FINAL_SHA = "d03b8ff9aa54b325e791db2e95c843a68bde720c01f2a72a6d80b2a58c85d6b9"
TARGET_HEADER_SHA = "334efe5b663d8a8f8ab3fbb124c651074b12c19ef1813e29c051cf52724c7549"
HEADER = "import Architect\nimport Mathlib\n\nnamespace P159Bad\n\n"
ENDING = "end P159Bad\n"
PROTECTED = {
    "lem:p159bad-diff-four": ("diff_four", "df37fc5f3f7e017166511b3883dafcb7ced28f37354322ad411965d600987e3e"),
    "lem:p159bad-a-value": ("a_value", "e8f53357f75d293c65830ec16e0c547156bb7ef4e51ef05344899779f01251e0"),
    "lem:p159bad-diff-ten": ("diff_ten", "b64964e7b62c5d0c63a66816f19efb07b5efe93e4318d9454c8d0ac0d5a39b61"),
}
# These exact five blocks were read line by line. Their only proof commands
# are intro/ring/rw/have/linarith/calc/exact and invocations of the listed lemmas.
APPROVED = {
    **PROTECTED,
    "lem:p159bad-final-step": ("final_step", "2dc6ae42089a8ef27b9bb25911f80a27bf1241b9055d0736e4527284ff250ea0"),
    TARGET_ID: ("p159_target", "a59ff55980506eff5ab7daf5196360aa6e7aee3850da37e6e4967aa44f9b8b7a"),
}
EXPECTED_TYPES = {
    "diff_four": "∀ a b : ℝ, (a * 6 + b) - (a * 2 + b) = 4 * a",
    "a_value": "∀ (a b : ℝ) (f : ℝ → ℝ), (∀ x, f x = a * x + b) → f 6 - f 2 = 12 → a = 3",
    "diff_ten": "∀ a b : ℝ, (a * 12 + b) - (a * 2 + b) = 10 * a",
    "final_step": "∀ a d : ℝ, d = 10 * a → a = 3 → d = 30",
    "p159_target": "∀ (a b : ℝ) (f : ℝ → ℝ), (∀ x, f x = a * x + b) → f 6 - f 2 = 12 → f 12 - f 2 = 30",
}
FALSE_HELPER_TYPE = "∀ a d : ℝ, d = 10 * a → d = 30"
FOUNDATIONAL = frozenset({"propext", "Classical.choice", "Quot.sound"})
PATCH = re.compile(r"(?ms)^<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE(?:\n|$)")
ANN = re.compile(r'(?m)^@\[blueprint "([^"\n]+)"')
THEOREM = re.compile(r"(?m)^theorem ([A-Za-z_][A-Za-z0-9_]*) ")


def need(test, reason):
    if not test:
        raise ValueError(reason)


def digest(value):
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def from_baseline(path):
    rel = path.relative_to(REPO).as_posix()
    raw = path.read_bytes()
    original = subprocess.check_output(["git", "show", f"{BASELINE}:{rel}"], cwd=REPO, timeout=15)
    need(raw == original, "Earlier frozen evidence differs")
    return raw


def archive_member(tar, members, path, sha):
    need(path in members and members[path].size <= 1024 * 1024, "Expected bounded archive member missing")
    with tar.extractfile(members[path]) as stream:
        raw = stream.read(1024 * 1024 + 1)
    need(len(raw) == members[path].size and digest(raw) == sha, "Frozen archive member differs")
    return raw


def nodes(text):
    need(text.startswith(HEADER) and text.endswith(ENDING), "Module imports or enclosing namespace differ")
    end = len(text) - len(ENDING)
    starts = list(ANN.finditer(text[:end]))
    need([m[1] for m in starts] == list(APPROVED) and starts[0].start() == len(HEADER),
         "Unexpected declaration order or unreviewed top-level source")
    result = {}
    for i, match in enumerate(starts):
        stop = starts[i + 1].start() if i + 1 < len(starts) else end
        raw = text[match.start():stop]
        body = raw.rstrip()
        thms = list(THEOREM.finditer(body))
        need(len(thms) == 1 and thms[0][1] == APPROVED[match[1]][0], "Unexpected theorem declaration")
        declaration = body[thms[0].start():]
        header, delim, proof = declaration.partition(" := by\n")
        need(bool(delim) and bool(proof.strip()), "Expected bounded proof block")
        result[match[1]] = {"name": thms[0][1], "annotation_and_theorem": body, "header": header,
                            "proof": proof, "char_span": [match.start(), match.start() + len(body)],
                            "utf8_span": [len(text[:match.start()].encode()), len(text[:match.start() + len(body)].encode())]}
    return result


def check_suffix(names):
    return "".join(f"#print axioms P159Bad.{n}\n" for n in names)


def identity_suffix(names):
    """All executable audit commands below are authored here, never extracted."""
    checked = "".join(f"#check (P159Bad.{name} : {EXPECTED_TYPES[name]})\n" for name in names)
    names_lean = ", ".join(f"`P159Bad.{n}" for n in names)
    return ("\n" + checked + check_suffix(names) + "\nopen Lean in\n"
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
            "    IO.println (\"P159_IDENTITY \" ++ packet.compress)\n")


def approved_nodes(sections, allowed):
    for node_id, row in sections.items():
        if node_id not in allowed:
            continue
        name, sha = allowed[node_id]
        need(row["name"] == name and digest(row["annotation_and_theorem"]) == sha,
             "Source bytes are outside the line-reviewed declaration allowlist")
        need(not re.search(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|"
                           r"elab|macro|attribute|set_option|open|import|opaque)\b|#",
                           row["annotation_and_theorem"]), "Disallowed command in reviewed declaration")


def parse_archived_axioms(log, names):
    output = {}
    for line in log["stdout"].splitlines():
        found = re.fullmatch(r"'P159Bad\.(\w+)' depends on axioms: \[([^]]*)\]", line)
        need(found and found[1] in names and found[1] not in output, "Unexpected author axiom log")
        axioms = {part.strip() for part in found[2].split(",") if part.strip()}
        need(axioms <= FOUNDATIONAL, "Author check used an untrusted axiom")
        output[found[1]] = sorted(axioms)
    need(set(output) == set(names), "Incomplete author axiom log")
    return output


def parse_archived_dependencies(log, names):
    deps = {}
    for line in log["stdout"].splitlines():
        found = re.fullmatch(r"COLLECT_USED P159Bad\.(\w+) (\{.*\})", line)
        need(found and found[1] in names and found[1] not in deps, "Unexpected author dependency line")
        packet = json.loads(found[2])
        need(set(packet) == {"typeUsed", "proofUsed"} and set(packet["typeUsed"]) <= FOUNDATIONAL,
             "Author graph log has untrusted type evidence")
        need(set(packet["proofUsed"]) <= {"P159Bad." + n for n in names}, "Author graph has an unknown node")
        deps[found[1]] = sorted(packet["proofUsed"])
    need(set(deps) == set(names), "Incomplete author dependency log")
    return deps


def collect(archive_path):
    freeze_raw = from_baseline(D38 / "blueprint_trace_freeze.json")
    intake_raw = from_baseline(D38 / "blueprint_trace_intake.json")
    preserved_raw = from_baseline(D38 / "blueprint_trace_preservation.json")
    freeze, intake, preserved = map(json.loads, (freeze_raw, intake_raw, preserved_raw))
    evidence_raw = (ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes()
    evidence = json.loads(evidence_raw)
    need(evidence["baseline"] == BASELINE and evidence["d38_evidence_sha256"] ==
         {"freeze": digest(freeze_raw), "intake": digest(intake_raw), "p159": digest(preserved_raw)},
         "Current evidence intake does not bind the frozen upstream record")
    expected_pins = {key: intake["runtime_compatibility"]["author"][key] for key in
                     ("lean_toolchain", "mathlib_rev", "leanarchitect_rev")}
    package_revs = {row["name"]: row["rev"] for row in evidence["packages"]}
    need(expected_pins == {"lean_toolchain": evidence["toolchain"], "mathlib_rev": package_revs["mathlib"],
                           "leanarchitect_rev": package_revs["LeanArchitect"]}, "Author environment pins differ")
    episode, = (row for row in intake["episodes"] if
                (row["state_id"], row["model"], row["mode"]) == (STATE_ID, MODEL, "patch"))
    archive, = (row for row in freeze["trajectory_archives"] if row["path"] == episode["archive"])
    need(archive["sha256"] == ARCHIVE_SHA and archive_path.stat().st_size <= 64 * 1024 * 1024
         and digest(archive_path.read_bytes()) == ARCHIVE_SHA, "Archive identity differs")
    need(episode["episode_member"] == RUN + "episode.json" and episode["author_outcome"] == "solved"
         and episode["final_module_sha256"] == FINAL_SHA and len(episode["steps"]) == 4, "Episode not the reviewed case")
    protected_source = {row["node_id"]: row["boundary_trimmed_declaration_sha256"]
                        for row in preserved["verified_source_spans"]}
    need(protected_source == {node: sha for node, (_, sha) in PROTECTED.items()}, "Frozen protected set differs")
    with tarfile.open(archive_path, mode="r:gz") as tar:
        chosen = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(RUN)]
        members = {m.name: m for m in chosen}
        need(len(chosen) == len(members), "Ambiguous archive member")
        read = lambda path, sha: archive_member(tar, members, path, sha)
        episode_file = json.loads(read(episode["episode_member"], episode["episode_sha256"]))
        need(episode_file["outcome"] == "solved" and episode_file["solved_at_step"] == 4
             and episode_file["final_module_sha256"] == FINAL_SHA, "Author episode metadata differs")
        step1 = episode["steps"][0]
        first = json.loads(read(step1["step_member"], step1["step_sha256"]))
        prompt_index = step1["prerequisites_before_attempt"]["prompt_message_index"]
        prompt = first["request"]["messages"][prompt_index]["content"]
        need(digest(prompt) == step1["prerequisites_before_attempt"]["prompt_message_sha256"], "Initial prompt bytes differ")
        initial, = re.findall(r"```lean\n(.*?)```", prompt, re.S)
        need(digest(initial) == INITIAL_SHA, "Initial module bytes differ")
        graph, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
        by_id = {row["node_id"]: row for row in graph["nodes"]}
        need(graph["target_node_id"] == TARGET_ID and set(by_id) == set(APPROVED)
             and all(by_id[key]["status"] == "proved_and_used" for key in PROTECTED)
             and by_id["lem:p159bad-final-step"]["status"] == "false_confirmed", "Initial graph scope differs")
        old_nodes = nodes(initial)
        for node_id, row in old_nodes.items():
            need(row["header"] == by_id[node_id]["formal_statement"], "Initial graph theorem header differs")
        need(digest(old_nodes[TARGET_ID]["header"]) == TARGET_HEADER_SHA, "Frozen target type text differs")
        approved_nodes(old_nodes, PROTECTED)
        reconstructed = initial
        chain = []
        names = tuple(value[0] for value in APPROVED.values())
        for i, step in enumerate(episode["steps"], 1):
            detail = json.loads(read(step["step_member"], step["step_sha256"]))
            execution = detail["tool_execution"]
            need(detail["meta"]["step"] == i and detail["meta"]["state_id"] == STATE_ID
                 and detail["meta"]["model"] == MODEL and detail["meta"]["mode"] == "patch"
                 and execution["tool"] == "local_patch" and execution["applied"] is True
                 and execution["solved"] == (i == 4), "Patch action identity differs")
            choices = detail["response"]["choices"]
            choice, = choices
            message = choice["message"]
            need(not message.get("tool_calls"), "Unexpected external executable tool request")
            patches = list(PATCH.finditer(message["content"]))
            need(len(patches) == execution["blocks_applied"] == (2 if i < 3 else 1), "Unexpected patch block count")
            patch_records = []
            for found in patches:
                old, new = found.groups()
                need(reconstructed.count(old) == 1, "Patch source search is missing or ambiguous")
                start = reconstructed.index(old)
                patch_records.append({"search_sha256": digest(old), "replace_sha256": digest(new),
                                      "pre_replacement_utf8_span": [len(reconstructed[:start].encode()),
                                                                    len(reconstructed[:start + len(old)].encode())]})
                reconstructed = reconstructed.replace(old, new, 1)
            need(digest(reconstructed) == execution["module_sha256"], "Exact patch replay differs from author result")
            current = nodes(reconstructed)
            need(current[TARGET_ID]["header"] == old_nodes[TARGET_ID]["header"]
                 and all(current[k] == old_nodes[k] for k in PROTECTED), "Patch changed protected declarations or target")
            checked, = (row for row in step["lean_checks"] if row["archive_member"].endswith(".check.elab.json"))
            log = json.loads(read(checked["archive_member"], checked["sha256"]))
            check_source = read(checked["source_member"], checked["source_sha256"])
            need(check_source == (reconstructed + check_suffix(names)).encode()
                 and log["pins"] == expected_pins and log["exit_code"] == (0 if i == 4 else 1)
                 and log["timed_out"] is False, "Author compiler check identity differs")
            errors = [item["message"] for item in log["diagnostics"] if item["severity"] == "error"]
            need(errors == ([] if i == 4 else ["No goals to be solved"]), "Author compiler diagnostics differ")
            chain.append({"step": i, "archive_step_sha256": step["step_sha256"], "blocks": patch_records,
                          "post_module_sha256": digest(reconstructed), "author_check_sha256": checked["source_sha256"],
                          "author_check_exit_code": log["exit_code"], "errors": errors, "executed_locally": False})
        final = read(preserved["accepted_final_module_member"], FINAL_SHA).decode("utf-8")
        need(final == reconstructed and final.endswith(ENDING), "Final module differs from the exact four-patch reconstruction")
        final_nodes = nodes(final)
        approved_nodes(final_nodes, APPROVED)
        final_check = check_source
        final_axioms = parse_archived_axioms(log, names)
        gate, = (row for row in episode["steps"][-1]["lean_checks"] if row["archive_member"].endswith(".gate.elab.json"))
        gate_log = json.loads(read(gate["archive_member"], gate["sha256"]))
        need(gate_log["pins"] == expected_pins and gate_log["exit_code"] == 0 and not gate_log["diagnostics"],
             "Author graph-check metadata differs")
        original_gate_raw = read(gate["source_member"], gate["source_sha256"])
        need(original_gate_raw.startswith(final.encode()) and b"#eval" in original_gate_raw,
             "Unexpected author graph-check source context")
        author_dependencies = parse_archived_dependencies(gate_log, names)
    initial_names = tuple(value[0] for value in PROTECTED.values())
    initial_clean = HEADER + "\n\n".join(old_nodes[key]["annotation_and_theorem"] for key in PROTECTED) + "\n\n" + ENDING
    controls = {
        "p159_author_exact_check.lean": final_check,
        "p159_initial_identity.lean": (initial_clean + identity_suffix(initial_names)).encode(),
        "p159_accepted_identity.lean": (final + identity_suffix(names)).encode(),
        "p159_import_absence.lean": (HEADER.split("namespace", 1)[0] +
                                    "".join(f"#check P159Bad.{n}\n" for n in names)).encode(),
        "p159_false_helper_counterexample.lean": (
            "import Mathlib\n\n"
            f"theorem p159_false_helper_counterexample : ¬ ({FALSE_HELPER_TYPE}) := by\n"
            "  intro h\n  have h0 : (0 : ℝ) = 10 * 0 := by norm_num\n  have impossible := h 0 0 h0\n"
            "  norm_num at impossible\n\n#print axioms p159_false_helper_counterexample\n").encode(),
    }
    node_bindings = [{"node_id": key, "qualified_name": "P159Bad." + row["name"],
                      "initial_utf8_span": old_nodes[key]["utf8_span"], "accepted_utf8_span": row["utf8_span"],
                      "initial_node_sha256": digest(old_nodes[key]["annotation_and_theorem"]),
                      "accepted_node_sha256": digest(row["annotation_and_theorem"]),
                      "initial_header_sha256": digest(old_nodes[key]["header"]),
                      "accepted_header_sha256": digest(row["header"]),
                      "preserved_full_node": old_nodes[key]["annotation_and_theorem"] == row["annotation_and_theorem"]}
                     for key, row in final_nodes.items()]
    return controls, {"status": "ARCHIVE_BOUND_REVIEWED_SOURCE_ONLY", "scope": "Source preparation; no Lean execution or model data access outside the fixed archive members.",
                      "baseline": BASELINE, "author_inputs_sha256": digest(evidence_raw), "archive_sha256": ARCHIVE_SHA,
                      "archive_path": archive["path"], "episode_sha256": episode["episode_sha256"],
                      "expected_author_pins": expected_pins, "initial_module_sha256": INITIAL_SHA,
                      "accepted_module_sha256": FINAL_SHA, "target_header_sha256": TARGET_HEADER_SHA,
                      "protected_source_count": len(PROTECTED), "protected_source_changed_count": 0,
                      "author_exact_patch_chain": chain, "node_bindings": node_bindings,
                      "author_archived_axioms": final_axioms, "author_archived_blueprint_direct_dependencies": author_dependencies,
                      "retained_false_helper_claim": "not included in the initial proof fixture",
                      "raw_author_gate_executable": False, "raw_prior_drafts_executable": False,
                      "identity_probe_scope": "Auditor-authored fixed #check/#print axioms/#eval reading types and direct constant uses; no archived meta commands.",
                      "model_payload_generated": False, "new_gpu_seconds": 0}


def run(archive, out, receipt):
    controls, summary = collect(archive)
    out.mkdir(parents=True, exist_ok=False)
    for filename, raw in controls.items():
        with (out / filename).open("xb") as stream:
            stream.write(raw)
    summary["prepared_fixtures"] = {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in controls.items()}
    payload = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"status": summary["status"], "fixtures": len(controls), "receipt_sha256": digest(payload)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(tempfile.gettempdir()) /
                        "blueprint_trace_8a7a7e6ed192_llm_calls_qwen_equal_source.tar.gz")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt", type=Path, default=ROOT / "p159_reviewed_source_receipt.json")
    args = parser.parse_args()
    run(args.archive.resolve(), args.output_dir.resolve(), args.receipt.resolve())
