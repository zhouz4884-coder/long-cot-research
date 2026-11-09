"""Reconstruct three exact, source-reviewed archive failures and frozen local edits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
D41 = ROOT.parent / "phase5d41_lean_scope_20261110"
sys.path.insert(0, str(D40))
from cases_source_review import ARCHIVES, DEEPSEEK, QWEN, default_archive, digest, need, read_member


BASE = "ad202e572534c8e7376d9fba7f8191fb7b3012d6"
SLOT = "  d42_slot"
DEFAULT_SCRATCH = Path(tempfile.gettempdir()) / "longcot-d42-causal-cases-20261110"
REVIEWED = {
    "p104": (
        "f896b57a1a81241db56778a0d5b548bf2fe0901157c1c57c063de7b42a8d95fa",
        "775e7b620c16318386278803e4e4a7257f9cb69cd72d765e05169fe97c7ad13e",
        "  have h : ((a : ZMod p) ^ p = (a : ZMod p)) := ZMod.pow_card p a",
        "  have h : ((a : ZMod p) ^ p = (a : ZMod p)) := by\n"
        "    letI : Fact (Nat.Prime p) := ⟨h₁⟩\n"
        "    exact ZMod.pow_card (a : ZMod p)",
    ),
    "p113": (
        "eb6c84a33a1e02bd0375bb6e11ef80297ce581cda2a23c99b00670e944a55768",
        "24623c77d2831d5a02f854589da8df7d4135c29d1d92002d82aef04ea61a7850",
        "    | zero => exfalso; exact hk lt_rfl",
        "    | zero => exfalso; exact Nat.lt_irrefl 0 hk",
    ),
    "p41": (
        "b8ed70782b522a30cc0b8b14ada46c14124b39286a632ef9cdea7ad58839610c",
        "47a30179a6a3b64b91fe32c411e5dcab0f9114c814ff0615f3a41eca403ded5d",
        "        _ ≤ 10 ^ m := Nat.pow_le_pow_right (by norm_num : 0 < 10) hm",
        "        _ ≤ 10 ^ m := Nat.pow_le_pow_right (by norm_num : 0 < 10) (Nat.zero_le m)",
    ),
}
UNAPPROVED = re.compile(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|native_decide|run_cmd|run_tac|run_elab|"
                        r"macro|elab|opaque|set_option|attribute)\b|#|```")


def frozen_git(path):
    rel = path.relative_to(REPO).as_posix()
    pinned = subprocess.check_output(["git", "show", f"{BASE}:{rel}"], cwd=REPO, timeout=20)
    need(path.read_bytes() == pinned, f"Baseline byte mismatch: {rel}")
    return pinned


def target_scope(tar, episode, case):
    start = episode["steps"][0]
    initial_step = json.loads(read_member(tar, start["archive_member"], start["sha256"]))
    record = initial_step["request"]["messages"][start["prestate_prompt_index"]]
    prompt = record["content"]
    need(record["role"] == "user" and prompt.startswith("Failed blueprint state")
         and digest(prompt) == start["prestate_prompt_sha256"], "Initial prompt differs")
    graph, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
    node, = graph["nodes"]
    ns = case.upper() + "Bad"
    label = f"thm:{case}bad-target"
    header = node["formal_statement"]
    need(graph["target_node_id"] == node["node_id"] == label and not graph["edges"]
         and node["status"] == "proof_too_hard" and header.startswith(f"theorem {case}_target "),
         "Initial target graph differs")
    source, = re.findall(r"```lean\n(.*?)```", prompt, re.S)
    imports = re.findall(r"(?m)^import ([\w.]+)$", source)
    prefix = "".join(f"import {module}\n" for module in imports) + f'\nnamespace {ns}\n\n@[blueprint "{label}"]\n'
    proof_prefix = prefix + header + " := by\n"
    suffix = f"\n\nend {ns}\n"
    need(source == proof_prefix + "  sorry" + suffix and digest(source) == REVIEWED[case][1],
         "Initial one-target source differs")
    return imports, header, proof_prefix, suffix, f"{ns}.{case}_target", {
        "source_sha256": digest(source), "initial_step_sha256": start["sha256"],
        "initial_prompt_sha256": digest(prompt), "episode_sha256": episode["episode_sha256"],
    }


def diagnostics(log, frozen, pins, target, expected_count):
    need(log["pins"] == pins and log["exit_code"] == 1 and not log["timed_out"], "Author log scope differs")
    errors = [d for d in log["diagnostics"] if d["severity"] == "error"]
    need(len(errors) == expected_count == len(frozen["ordered_error_categories"])
         and errors[0]["line"] == frozen["first_reported_error_line"], "Author errors differ")
    axiom_text, = re.findall(rf"(?m)^'{re.escape(target)}' depends on axioms: \[([^]]*)\]$", log["stdout"])
    axioms = sorted(axiom_text.split(", "))
    need("sorryAx" in axioms, "Expected a rejected proof with incomplete axiom closure")
    coordinates = [{"line": d["line"], "column": d["col"], "category": category,
                    "message_sha256": digest(d["message"])}
                   for d, category in zip(errors, frozen["ordered_error_categories"], strict=True)]
    return coordinates, axioms, errors


def source_variants(original, scope, case, line):
    _, _, prefix, suffix, target, _ = scope
    _, _, old_text, new_text = REVIEWED[case]
    old, new = old_text.encode(), new_text.encode()
    lines = original.split(b"\n")
    offset = sum(len(value) + 1 for value in lines[:line - 1])
    need(lines[line - 1] == old and original.count(old) == 1, "First repair span differs")
    line_delta = new.count(b"\n") - old.count(b"\n")
    byte_delta = len(new) - len(old)
    need(byte_delta >= line_delta >= 0, "Cannot construct a matched whitespace placebo")
    placebo = old + b" " * (byte_delta - line_delta) + b"\n" * line_delta
    audit = f"#print axioms {target}\n"
    variants = {}
    for key, replacement in {"original": old, "noop": old, "placebo": placebo, "edited": new}.items():
        raw = original[:offset] + replacement + original[offset + len(old):]
        source = raw.decode()
        need(source.startswith(prefix) and source.endswith(suffix + audit)
             and not UNAPPROVED.search(source.removesuffix(audit))
             and len(re.findall(r"(?m)^theorem ", source)) == 1, "Source is outside reviewed one-target grammar")
        variants[key] = raw
    need(len(variants["placebo"]) == len(variants["edited"])
         and variants["placebo"].count(b"\n") == variants["edited"].count(b"\n"), "Placebo size differs")
    return variants, {"original_line": line, "old_text": old_text, "new_text": new_text,
                      "old_span_utf8": [offset, offset + len(old)], "new_span_utf8": [offset, offset + len(new)],
                      "byte_delta": byte_delta, "line_delta": line_delta,
                      "mapped_unchanged_lines": "Before the original repair line: same. After it: add line_delta."}


def collect(tar, selection, frozen, episode, pins):
    case = selection["state_id"].split("_", 1)[0]
    member = selection["source_member"]
    reviewed_sha = REVIEWED[case][0]
    need(frozen["source_sha256"] == selection["source_sha256"] == reviewed_sha
         and frozen["import_list_comparison"] == "SAME_IMPORT_LIST"
         and frozen["state_id"] == selection["state_id"] == episode["state_id"]
         and not episode["author_rescan_pass"] and episode["loop_time_outcome"] == "budget_exhausted",
         "Unexpected frozen cohort scope")
    raw = read_member(tar, member, reviewed_sha)
    check_member = member.removesuffix(".lean") + ".elab.json"
    attempt_member = member.removesuffix(".check.lean") + ".json"
    step, = [s for s in episode["steps"] if s["archive_member"] == attempt_member]
    check, = [d for d in step["author_elaborations"] if d["member"] == check_member]
    need(step["sha256"] == frozen["attempt_sha256"] and step["outcome"] == "ARCHIVED_LEAN_ERROR"
         and check["sha256"] == frozen["compiler_log_sha256"] and check["exit_code"] == 1
         and not check["timed_out"], "Original source and diagnostic do not bind the attempt")
    attempt = json.loads(read_member(tar, attempt_member, step["sha256"]))
    log = json.loads(read_member(tar, check_member, check["sha256"]))
    scope = target_scope(tar, episode, case)
    imports, header, prefix, suffix, target, initial = scope
    main = raw.removesuffix(f"#print axioms {target}\n".encode())
    need(attempt["tool_execution"]["module_sha256"] == digest(main), "Archive attempt module bytes differ")
    errors, axioms, detail = diagnostics(log, frozen, pins, target, check["error_count"])
    variants, splice = source_variants(raw, scope, case, selection["reported_line"])
    files = {f"{case}_{kind}.lean": value for kind, value in variants.items()}
    offline_diagnostics = f"{case}_author_diagnostics.offline.json"
    files[offline_diagnostics] = encode_json(detail)
    slot_file = f"{case}_target_slot.lean"
    files[slot_file] = (prefix + SLOT + suffix + f"#print axioms {target}\n").encode()
    row = {"state_id": episode["state_id"], "target_id": frozen["target_id"], "target": target,
           "model_in_archive": frozen["model"], "mode_in_archive": frozen["mode"],
           "initial_scope": initial, "exact_imports": imports, "immutable_target_header": header,
           "immutable_target_header_sha256": digest(header), "helpers": [],
           "archive_source_member": member, "archive_candidate_sha256": reviewed_sha,
           "archive_module_sha256": digest(main), "archive_attempt_sha256": step["sha256"],
           "archive_diagnostics_sha256": check["sha256"], "author_errors": errors, "author_target_axioms": axioms,
           "original_error_lines": [d["line"] for d in errors],
           "original_error_classes": [d["category"] for d in errors], "localized_edit": splice,
           "offline_diagnostics": {"filename": offline_diagnostics, "sha256": digest(files[offline_diagnostics])},
           "target_slot": {"filename": slot_file, "source_sha256": digest(files[slot_file]),
                           "immutable_prefix_sha256": digest(prefix), "marker": SLOT},
           "variants": {kind: {"filename": f"{case}_{kind}.lean", "source_sha256": digest(value),
                               "bytes": len(value)} for kind, value in variants.items()}}
    return case, row, files


def encode_json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def prepare(paths, scratch, receipt):
    inventory_raw = frozen_git(D39 / "corpus_inventory.json")
    ledger_raw = frozen_git(D41 / "diagnostic_ledger.jsonl")
    primary_raw = (ROOT / "D42_ERROR_ORDER_FREEZE.json").read_bytes()
    selection_raw = (ROOT / "cascade_selection_freeze.json").read_bytes()
    inventory, primary, selection = map(json.loads, (inventory_raw, primary_raw, selection_raw))
    need(primary["baseline"] == BASE and selection["d42_input_freeze_sha256"] == digest(primary_raw)
         and selection["d41_ledger_sha256"] == digest(ledger_raw), "Source selection is not on the pinned inputs")
    pins = inventory["author_lean_runtime_pins"]
    rows, files = {}, {}
    for model, path in paths.items():
        need(path.stat().st_size <= 64 * 1024 * 1024 and digest(path.read_bytes()) == ARCHIVES[model][1],
             "Archive bytes differ")
        with tarfile.open(path, "r:gz") as tar:
            for selected in selection["fixed_cases"]:
                frozen, = [r for r in primary["anchored_multi_error_candidates"]
                           if r["source_member"] == selected["source_member"]]
                if frozen["model"] != model:
                    continue
                episode, = [ep for ep in inventory["episodes"] if ep["state_id"] == frozen["state_id"]
                            and ep["model"] == model and ep["mode"] == frozen["mode"]]
                case, row, artifacts = collect(tar, selected, frozen, episode, pins)
                rows[case] = row
                files.update(artifacts)
    need(set(rows) == set(REVIEWED), "Exact reviewed target set differs")
    report = {"status": "THREE_EXACT_ARCHIVED_NEGATIVES_AND_EDIT_CONTROLS_SOURCE_REVIEWED",
              "baseline": BASE, "inventory_sha256": digest(inventory_raw), "ledger_sha256": digest(ledger_raw),
              "d42_input_freeze_sha256": digest(primary_raw), "source_selection_sha256": digest(selection_raw),
              "author_pins": pins, "archive_sha256": {model: ARCHIVES[model][1] for model in paths},
              "cases": {case: rows[case] for case in REVIEWED},
              "variants": {"original": "Exact archive bytes", "noop": "Byte-identical independent repeat",
                           "placebo": "Same positive byte and line delta as edit using trailing spaces and blank lines",
                           "edited": "One reviewed contiguous first-site proof-line replacement"},
              "prior_control": selection["separate_prior_control"], "known_proofs_read_or_emitted": False,
              "local_execution_performed_by_prepare": False}
    need(not scratch.exists() and not receipt.exists(), "Refuse to overwrite frozen output")
    scratch.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        with (scratch / name).open("xb") as stream:
            stream.write(data)
    raw = encode_json(report)
    with receipt.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "sha256": digest(raw), "cases": list(REVIEWED)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deepseek", type=Path, default=default_archive(DEEPSEEK))
    parser.add_argument("--qwen", type=Path, default=default_archive(QWEN))
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--receipt", type=Path, default=ROOT / "causal_cases_source_receipt.json")
    args = parser.parse_args()
    prepare({DEEPSEEK: args.deepseek, QWEN: args.qwen}, args.scratch.resolve(), args.receipt.resolve())
