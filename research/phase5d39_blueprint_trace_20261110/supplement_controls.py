"""Prepare and optionally verify bounded supplementary p82/p30 preservation controls."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from time import perf_counter

from p159_prepare_reviewed import FOUNDATIONAL, ROOT, THEOREM, archive_member, digest, need


FREEZE = ROOT / "supplement_freeze.json"
HEADER = {
    "p82": "import Architect\nimport Mathlib\n\nnamespace P82Bad\n\n",
    "p30": "import Architect\nimport Mathlib.Tactic.Ring\nimport Mathlib.Tactic.Linarith\n"
           "import Mathlib.Tactic.NormNum\n\nnamespace P30Bad\n\n",
}
TARGETS = {
    "p82": ("theorem p82_target (b : ℕ) (h₀ : Nat.lcm 120 b = 3720) (h₁ : Nat.gcd 120 b = 8) : b = 248",
            "∀ (b : ℕ), Nat.lcm 120 b = 3720 → Nat.gcd 120 b = 8 → b = 248"),
    "p30": ("theorem p30_target (n : ℕ) (h₀ : 5 * n % 17 = 8) : n % 17 = 5",
            "∀ (n : ℕ), 5 * n % 17 = 8 → n % 17 = 5"),
}
NAMES = {"p82": ("abandoned_residue", "product_slip_wrong", "p82_target"),
         "p30": ("residue_wrong", "p30_target")}
PROTECTED = {"p82": "product_slip_wrong", "p30": "residue_wrong"}
ANNOTATION = re.compile(r'@\[blueprint "([A-Za-z0-9:_-]+)"\s*(?:\(latexEnv := "lemma"\)\s*)?'
                        r'(?:\(proofUses := \[[A-Za-z0-9_, ]*\]\)\s*)?\]\s*')
START = re.compile(r'(?m)^@\[blueprint "')
FORBIDDEN = re.compile(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|elab|macro|attribute|"
                       r"set_option|open|import|opaque|native_decide|initialize|syntax|def|abbrev|notation|include)\b|#")
AXIOM_LINE = re.compile(r"'([\w.]+)' depends on axioms: \[([^]]*)\]")
AXIOM_EMPTY = re.compile(r"'([\w.]+)' does not depend on any axioms")
P82_LINK = "      _ = 29760 := product_slip_wrong"
P82_TRANSPORT = "      _ = 120 * 248 := product_slip_wrong\n      _ = 29760 := by norm_num"
P30_INVERSE = """ by
  calc
    n % 17 = ((5 * 7 % 17) * n) % 17 := by rw [residue_wrong, Nat.one_mul]
    _ = ((5 * 7) * n) % 17 := Nat.mod_mul_mod (5 * 7) n 17
    _ = (7 * (5 * n)) % 17 := by rw [Nat.mul_comm 5 7, Nat.mul_assoc]
    _ = (7 * ((5 * n) % 17)) % 17 := (Nat.mul_mod_mod 7 (5 * n) 17).symm
    _ = 5 := by rw [h₀] <;> decide"""


def namespace(case):
    return case.upper() + "Bad"


def end_marker(case):
    return f"end {namespace(case)}\n"


def print_axioms(case, names):
    return "".join(f"#print axioms {namespace(case)}.{name}\n" for name in names)


def extract(case, text, names):
    """Reject any top-level text outside exact imports, known theorem cells and namespace closure."""
    begin, end = HEADER[case], end_marker(case)
    need(text.startswith(begin) and text.endswith(end), "Unapproved import or namespace")
    body = text[:-len(end)]
    starts = list(START.finditer(body))
    need(len(starts) == len(names) and starts[0].start() == len(begin), "Unexpected top-level commands")
    result = {}
    for index, match in enumerate(starts):
        raw = body[match.start():starts[index + 1].start() if index + 1 < len(starts) else len(body)].rstrip()
        theorem, = THEOREM.finditer(raw)
        header, separator, proof = raw[theorem.start():].partition(" :=")
        annotation = raw[:theorem.start()]
        need(theorem[1] == names[index] and ANNOTATION.fullmatch(annotation) and separator and proof.startswith(" by"),
             "Unexpected annotation, declaration identity or proof region")
        need(not FORBIDDEN.search(raw) and all(not line.strip() or line.startswith(" ") for line in proof.splitlines()[1:]),
             "Unapproved proof command")
        result[theorem[1]] = {"source": raw, "annotation": annotation, "header": header, "proof": proof}
    target = case + "_target"
    need(target not in result or result[target]["header"] == TARGETS[case][0], "Complete immutable target differs")
    return result


def authors_axioms(log, case, pins, names, *, failed=False):
    need(log["pins"] == pins and not log["timed_out"], "Wrong author runtime or timeout")
    if failed:
        need(log["exit_code"] != 0 and any(row["severity"] == "error" for row in log["diagnostics"]),
             "Expected archived Lean failure did not occur")
    else:
        need(log["exit_code"] == 0 and not log["diagnostics"], "Archived complete proof did not close")
    expected = {f"{namespace(case)}.{name}" for name in names}
    result = {}
    for line in log["stdout"].splitlines():
        with_axioms, empty = AXIOM_LINE.fullmatch(line), AXIOM_EMPTY.fullmatch(line)
        found = with_axioms or empty
        if found is None or found[1] not in expected:
            need(failed, "Unexpected archived axiom output")
            continue
        axioms = {a.strip() for a in with_axioms[2].split(",") if a.strip()} if with_axioms else set()
        need(axioms <= FOUNDATIONAL and found[1] not in result, "Invalid archived axiom closure")
        result[found[1]] = sorted(axioms)
    need(set(result) == expected, "Incomplete named axiom closure")
    return result


def split_checked(case, raw, names):
    text = raw.decode()
    suffix = print_axioms(case, names)
    need(text.endswith(suffix), "Archive commands exceed known axiom suffix")
    text = text[:-len(suffix)]
    return text, extract(case, text, names)


def replace_once(text, old, new):
    need(text.count(old) == 1, "Deterministic splice is absent or ambiguous")
    return text.replace(old, new, 1)


def identity_suffix(case):
    ns = namespace(case)
    references = ", ".join(f"`{ns}.{name}" for name in NAMES[case])
    # Fixed auditor code. None of these executable directives is extracted from the archive.
    return (f"#check ({ns}.{case}_target : {TARGETS[case][1]})\n" + print_axioms(case, NAMES[case]) + "\nopen Lean in\n"
            "#eval show Lean.Elab.Command.CommandElabM Unit from do\n"
            f"  let names : Array Name := #[{references}]\n"
            "  let jsonConstants := fun (xs : Array Name) => Json.arr (xs.map (fun x => Json.str x.toString))\n"
            "  for n in names do\n"
            "    let some info := (← getEnv).find? n | throwError \"Missing reviewed declaration: {n}\"\n"
            "    let some proof := info.value? true | throwError \"Missing reviewed proof: {n}\"\n"
            "    let display ← Lean.Elab.Command.liftTermElabM (Lean.Meta.ppExpr info.type)\n"
            "    let packet := Json.mkObj [(\"name\", Json.str n.toString), (\"type\", Json.str display.pretty),\n"
            "      (\"type_constants\", jsonConstants info.type.getUsedConstants),\n"
            "      (\"proof_constants\", jsonConstants proof.getUsedConstants)]\n"
            "    IO.println (\"D39_SUPPLEMENT_IDENTITY \" ++ packet.compress)\n")


def collect(tar, members, case, pins, frozen, *, direct=False):
    prefix = frozen["author_direct_prefix" if direct else "accepted_prefix"]
    get = lambda name, sha: archive_member(tar, members, prefix + name, sha)
    if direct:
        raw = get("step01.assembled.lean", frozen["author_direct_check_sha256"])
        names = (case + "_target",)
        text, nodes = split_checked(case, raw, names)
        axioms = authors_axioms(json.loads(get("step01.assembled.elab.json", frozen["author_direct_log_sha256"])),
                                case, pins, names)
        need(nodes["p30_target"]["proof"] == " by omega", "Direct proof is not the reviewed author body")
        return nodes["p30_target"]["proof"], axioms
    episode = json.loads(get("episode.json", frozen["accepted_episode_sha256"]))
    need(episode["state_id"] == frozen["state_id"] and episode["model"] == "deepseek/deepseek-v4-flash"
         and episode["mode"] == "patch" and episode["protocol"] == "equal_source_v2" and episode["outcome"] == "solved"
         and episode["final_module_sha256"] == frozen["accepted_module_sha256"], "Accepted author identity differs")
    final = get("final.module.lean", frozen["accepted_module_sha256"])
    raw = get(frozen["accepted_check_member"], frozen["accepted_check_sha256"])
    text, nodes = split_checked(case, raw, NAMES[case])
    if case == "p82":
        need(text.encode() == final, "Accepted checker source differs from the final module")
    else:
        # p30's final.module.lean is the pre-assembly author artifact; never stage it.
        need(text.encode() != final, "Unexpected p30 author assembly provenance")
    axioms = authors_axioms(json.loads(get(frozen["accepted_check_log_member"], frozen["accepted_check_log_sha256"])),
                            case, pins, NAMES[case])
    return text, nodes, axioms


def get_before(tar, members, case, pins, frozen):
    prefix = frozen["failed_prefix"]
    get = lambda name, sha: archive_member(tar, members, prefix + name, sha)
    step = json.loads(get("step02.json", frozen["failed_step_sha256"]))
    meta = step["meta"]
    need(meta["state_id"] == frozen["state_id"] and meta["model"] == "qwen/qwen3.6-flash"
         and meta["mode"] == "patch" and meta["step"] == 2 and not step["tool_execution"]["solved"],
         "Wrong failed checkpoint source")
    msg = step["request"]["messages"][3]
    need(msg["role"] == "user" and msg["content"].startswith("Verifier feedback:"), "Prestate source is not visible feedback")
    text, = re.findall(r"```lean\n(.*?)```", msg["content"], flags=re.S)
    need(digest(text) == frozen["old_visible_module_sha256"], "Old proof context differs")
    nodes = extract(case, text, NAMES[case])
    raw = get("step02.check.lean", frozen["failed_check_source_sha256"])
    need(nodes[PROTECTED[case]]["source"].encode() in raw, "Old protected proof is absent from the author's failed check")
    axioms = authors_axioms(json.loads(get("step02.check.elab.json", frozen["failed_check_log_sha256"])),
                            case, pins, (PROTECTED[case],), failed=True)
    return nodes, axioms


def transform(case, accepted, new, old, direct):
    protected, target = PROTECTED[case], case + "_target"
    need(old[protected]["header"] != new[protected]["header"] and old[target]["header"] == new[target]["header"],
         "Expected protected type change under an identical full target")
    transplanted = replace_once(accepted, new[protected]["source"], old[protected]["source"])
    if case == "p82":
        need(old["abandoned_residue"]["source"] == new["abandoned_residue"]["source"], "Unrelated valid cell changed")
        return {"preserved_transport": replace_once(transplanted, P82_LINK, P82_TRANSPORT)}
    basis = new[target]["source"][:-len(new[target]["proof"])]
    return {"preserved_direct": replace_once(transplanted, new[target]["source"], basis + direct),
            "preserved_inverse": replace_once(transplanted, new[target]["source"], basis + P30_INVERSE)}


def write_once(path, data):
    if path.exists():
        need(path.read_bytes() == data, "Existing supplement artifact differs")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def prepare(deepseek, qwen, out, receipt_path):
    frozen_raw = FREEZE.read_bytes()
    frozen = json.loads(frozen_raw)
    inputs_raw = (ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes()
    need(digest(inputs_raw) == frozen["author_inputs_sha256"] and
         digest((ROOT / "D39_REPLAY_GATE.json").read_bytes()) == frozen["root_gate_sha256"] and
         digest((ROOT / "corpus_replay_nomination.json").read_bytes()) == frozen["corpus_nomination_sha256"],
         "Secondary comparison basis differs")
    inputs = json.loads(inputs_raw)
    rev = {row["name"]: row["rev"] for row in inputs["packages"]}
    pins = {"lean_toolchain": inputs["toolchain"], "mathlib_rev": rev["mathlib"], "leanarchitect_rev": rev["LeanArchitect"]}
    need(deepseek.stat().st_size <= 64 * 1024 * 1024 and qwen.stat().st_size <= 64 * 1024 * 1024
         and digest(deepseek.read_bytes()) == frozen["archive_sha256"]["deepseek"]
         and digest(qwen.read_bytes()) == frozen["archive_sha256"]["qwen"], "Wrong trajectory archives")
    variants, case_reports = {}, {}
    with tarfile.open(deepseek, "r:gz") as base, tarfile.open(qwen, "r:gz") as failure:
        def members(tar):
            all_members = [member for member in tar.getmembers() if member.isfile() and "/._" not in member.name]
            named = {member.name: member for member in all_members}
            need(len(named) == len(all_members), "Duplicate named trajectory member")
            return named
        b, f = members(base), members(failure)
        for case, data in frozen["cases"].items():
            text, accepted, archived = collect(base, b, case, pins, data)
            old, old_axioms = get_before(failure, f, case, pins, data)
            direct, direct_axioms = collect(base, b, case, pins, data, direct=True) if case == "p30" else (None, None)
            comparisons = {"author_check": text, **transform(case, text, accepted, old, direct)}
            protected = PROTECTED[case]
            for variant, module in comparisons.items():
                seen = extract(case, module, NAMES[case])
                preserves = variant != "author_check"
                need(seen[case + "_target"]["header"] == old[case + "_target"]["header"]
                     and (not preserves or seen[protected]["source"] == old[protected]["source"]),
                     "Reviewed candidate changed the target or protected cell")
                source = (module + identity_suffix(case)).encode()
                name = f"supplement_{case}_{variant}.lean"
                variants[name] = source
            case_reports[case] = {"target_id": data["target_id"], "target_header_sha256": digest(TARGETS[case][0]),
                                  "protected_declaration": f"{namespace(case)}.{protected}",
                                  "old_protected_cell_sha256": digest(old[protected]["source"]),
                                  "author_replacement_cell_sha256": digest(accepted[protected]["source"]),
                                  "archived_old_protected_axioms": old_axioms, "archived_complete_axioms": archived,
                                  "archived_direct_target_axioms": direct_axioms}
    out.mkdir(parents=True, exist_ok=True)
    for name, source in variants.items():
        write_once(out / name, source)
    receipt = {"status": "REVIEWED_SUPPLEMENT_SOURCE_ONLY", "secondary_freeze_sha256": digest(frozen_raw),
               "prepare_source_sha256": digest(Path(__file__).read_bytes()), "author_inputs_sha256": digest(inputs_raw),
               "author_runtime_pins": pins, "primary_selection_unchanged": frozen["primary_selection_unchanged"],
               "scope": "Exact archived inputs plus deterministic reviewed substitutions. Only trusted target/type/axiom/direct-constant probes added. No local Lean verification during prepare.",
               "cases": case_reports, "prepared_fixtures": {name: {"sha256": digest(data), "bytes": len(data)}
                                                            for name, data in variants.items()}}
    raw = json_bytes(receipt)
    write_once(receipt_path, raw)
    print(json.dumps({"status": receipt["status"], "fixtures": len(variants), "receipt_sha256": digest(raw)}))


def verified_output(stdout, case):
    expected = {f"{namespace(case)}.{name}" for name in NAMES[case]}
    axioms, nodes = {}, {}
    for line in stdout.splitlines():
        if line.startswith("{"):
            packet = json.loads(line)
            need(packet.get("severity") not in {"warning", "error"}, "Lean emitted a warning or error")
            lines = packet["data"].splitlines()
        else:
            lines = [line]
        for message in lines:
            if message.startswith("D39_SUPPLEMENT_IDENTITY "):
                node = json.loads(message.removeprefix("D39_SUPPLEMENT_IDENTITY "))
                name = node["name"]
                need(name in expected and name not in nodes and set(node) == {"name", "type", "type_constants", "proof_constants"},
                     "Unexpected named elaborated node")
                nodes[name] = node
                continue
            with_axioms, empty = AXIOM_LINE.fullmatch(message), AXIOM_EMPTY.fullmatch(message)
            found = with_axioms or empty
            if found:
                found_axioms = {a.strip() for a in with_axioms[2].split(",") if a.strip()} if with_axioms else set()
                need(found[1] in expected and found[1] not in axioms and found_axioms <= FOUNDATIONAL,
                     "Forbidden or duplicated axiom closure")
                axioms[found[1]] = sorted(found_axioms)
    need(set(axioms) == set(nodes) == expected, "Incomplete exact target or local dependency evidence")
    root = f"{namespace(case)}.{case}_target"
    seen, todo = set(), [root]
    while todo:
        node = nodes[todo.pop()]
        for dep in node["proof_constants"] + node["type_constants"]:
            if dep in nodes and dep not in seen:
                seen.add(dep)
                todo.append(dep)
    return {"target_type": nodes[root]["type"], "axiom_closures": axioms, "compiled_node_probes": nodes,
            "protected_declaration_actually_used": f"{namespace(case)}.{PROTECTED[case]}" in seen}


def execute(source_dir, receipt_path, lean, lake, project, output):
    # Importing and using these runtime checks is restricted to the explicit run subcommand.
    from author_runtime_setup import clean_env
    from measure_p159_replay_cost import FLAGS, check_environment

    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    input_raw = (ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes()
    need(receipt["status"] == "REVIEWED_SUPPLEMENT_SOURCE_ONLY"
         and receipt["secondary_freeze_sha256"] == digest(FREEZE.read_bytes())
         and receipt["prepare_source_sha256"] == digest(Path(__file__).read_bytes())
         and receipt["author_inputs_sha256"] == digest(input_raw), "Source preparation receipt is stale")
    version = check_environment(lean, lake, project, json.loads(input_raw))
    env = clean_env()
    env["PATH"] = str(lean.parent) + os.pathsep + env.get("PATH", "")
    results = {}
    for filename, expected in receipt["prepared_fixtures"].items():
        path = source_dir / filename
        raw = path.read_bytes()
        need(len(raw) == expected["bytes"] and digest(raw) == expected["sha256"], "Prepared supplement source differs")
        _, case, variant = filename.removesuffix(".lean").split("_", 2)
        start = perf_counter()
        try:
            finished = subprocess.run([str(lake), "env", str(lean), "--json", str(path)], cwd=project, env=env,
                                      creationflags=FLAGS, capture_output=True, timeout=120, encoding="utf-8", errors="replace")
            result = {"returncode": finished.returncode, "wall_seconds": perf_counter() - start}
            need(finished.returncode == 0 and not finished.stderr.strip(), "Lean did not verify the fixture cleanly")
            result.update(verified_output(finished.stdout, case))
            result["status"] = "VERIFIED"
        except (ValueError, subprocess.TimeoutExpired) as err:
            result = {"status": "UNVERIFIED", "reason": str(err), "wall_seconds": perf_counter() - start}
            if not isinstance(err, subprocess.TimeoutExpired):
                result["stdout"] = finished.stdout.replace(str(source_dir), "$FIXTURE_DIR")
                result["stderr"] = finished.stderr.replace(str(source_dir), "$FIXTURE_DIR")
        result.update(case=case, variant=variant, source_sha256=digest(raw), protected_source_preserved=variant != "author_check")
        results[filename] = result
    for result in results.values():
        author = results[f"supplement_{result['case']}_author_check.lean"]
        result["matches_author_elaborated_target_type"] = (result["status"] == author["status"] == "VERIFIED"
                                                          and result["target_type"] == author["target_type"])
    passed = all(row["status"] == "VERIFIED" and row["matches_author_elaborated_target_type"] for row in results.values())
    report = {"status": "PASS" if passed else "INCOMPLETE_OR_UNVERIFIED", "source_receipt_sha256": digest(receipt_raw),
              "runtime_version": version, "scope": "Secondary exact-author kernel checks. Source retention and observed proof/type dependence are separate fields.",
              "results": results}
    write_once(output, json_bytes(report))
    print(json.dumps({"status": report["status"], "proofs": len(results)}))
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="action", required=True)
    prep = cmds.add_parser("prepare")
    cache = Path(tempfile.gettempdir())
    prep.add_argument("--deepseek", type=Path, default=cache / "blueprint_trace_6acd6a2571ec_llm_calls_equal_source.tar.gz")
    prep.add_argument("--qwen", type=Path, default=cache / "blueprint_trace_8a7a7e6ed192_llm_calls_qwen_equal_source.tar.gz")
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--receipt", type=Path, default=ROOT / "supplement_source_receipt.json")
    live = cmds.add_parser("run")
    for flag in ("source-dir", "lean", "lake", "project", "output"):
        live.add_argument("--" + flag, required=True, type=Path)
    live.add_argument("--receipt", type=Path, default=ROOT / "supplement_source_receipt.json")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.deepseek.resolve(), args.qwen.resolve(), args.output_dir.resolve(), args.receipt.resolve())
    else:
        raise SystemExit(0 if execute(args.source_dir.resolve(), args.receipt.resolve(), args.lean.resolve(), args.lake.resolve(),
                                      args.project.resolve(), args.output.resolve()) else 1)
