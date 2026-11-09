"""Bind exact archive target starts and keep the positive proof in a separate directory."""
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
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
BASELINE = "52078309c43f11dfa209c591ac3b2e1e8ab31dac"
FAMILY = "monolithic_needs_split"
SLOT = "  d40_slot"
DEEPSEEK = "deepseek/deepseek-v4-flash"
QWEN = "qwen/qwen3.6-flash"
IMPORT_TACTICS = ("Architect", "Mathlib.Tactic.Ring", "Mathlib.Tactic.Linarith", "Mathlib.Tactic.NormNum")
CASES = {
    "p14": ("induction_11div10tonmn1ton", "f4e29d5bca99b904fd5f49e55b522110073588b18f42b0f113281d0ae252c0fa",
            "theorem p14_target (n : ℕ) : 11 ∣ (10^n - (-1 : ℤ)^n)",
            (*IMPORT_TACTICS, "Mathlib.Tactic.LinearCombination")),
    "p41": ("induction_divisibility_9div10tonm1", "47a30179a6a3b64b91fe32c411e5dcab0f9114c814ff0615f3a41eca403ded5d",
            "theorem p41_target (n : ℕ) (h₀ : 0 < n) : 9 ∣ 10 ^ n - 1", IMPORT_TACTICS),
    "p138": ("mathd_numbertheory_427", "979ae92a9c33399bb64d34ade9553a8ad1acaece3a7baf37a2498674d06333ba",
             "theorem p138_target (a : ℕ) (h₀ : a = (∑ k ∈ (Nat.divisors 500), k)) : ∑ k ∈ Finset.filter (λ x => Nat.Prime x) (Nat.divisors a), k = 25",
             ("Architect", "Mathlib")),
    "p40": ("induction_12dvd4expnp1p20", "ece6a347bd82ba36c9800c7cf1085fa50278f4dc5a158f9056df01179fce7b99",
            "theorem p40_target (n : ℕ) : 12 ∣ 4^(n+1) + 20", IMPORT_TACTICS),
}
ARCHIVES = {
    DEEPSEEK: ("llm_calls_equal_source.tar.gz", "6acd6a2571ec420e61b05d2ed2d18da4422b6420a7b6d6feb98802030959500e"),
    QWEN: ("llm_calls_qwen_equal_source.tar.gz", "8a7a7e6ed192129a754f94ea85089978fc44f136fc11df01a1d676bf5b93ccb7"),
}
P40 = {
    "episode": "0fc8ba169ce35c623f6caf615a541d2ea814d80f8992042a5d6b47eeeebab4a2",
    "solved_step": "f29cf2bc6d6840d403f1bfdfd61d3fb119fc0c51c002aeabc4cfe8f9a43924fd",
    "final.module.lean": "6022e1900b3c781d0e55d740a35cac5711d84ad3f9f9b9f9d65ec47bc518c09e",
    "step05.check.lean": "d1d235455e42cd09ac77dae91c33cd41f269c8df5f65ac13d357240dec3a66fd",
    "step05.check.elab.json": "8f00b4bb9e601e6d26f59baf766c4c7d30c80f0e639171c440cf12a5a3104a70",
    "step05.gate.elab.json": "75490805cf8c866221cbe8c8e26f6cae212a4a131439590d2aa8f5b9bbec9ed8",
}
SAFE_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}


def digest(value):
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def published(path):
    rel = path.relative_to(REPO).as_posix()
    current = path.read_bytes()
    expected = subprocess.check_output(["git", "show", f"{BASELINE}:{rel}"], cwd=REPO, timeout=15)
    need(current == expected, "D3.9 published source differs")
    return current


def read_member(tar, path, sha):
    item = tar.getmember(path)
    need(item.isfile() and item.size <= 1024 * 1024, "Unsafe archive member size or type")
    with tar.extractfile(item) as stream:
        raw = stream.read(1024 * 1024 + 1)
    need(len(raw) == item.size and digest(raw) == sha, "Archive member hash differs")
    return raw


def case_templates(case):
    _, _, header, imports = CASES[case]
    ns = case.upper() + "Bad"
    node = f"thm:{case}bad-target"
    imports_prefix = "".join(f"import {m}\n" for m in imports)
    prelude = imports_prefix + f'\nnamespace {ns}\n\n@[blueprint "{node}"]\n' + header + " := by\n"
    suffix = f"\n\nend {ns}\n"
    return prelude + "  sorry" + suffix, prelude + SLOT + suffix, imports_prefix + f"\n#check {ns}.{case}_target\n"


def check_initial(episode, member, episode_raw, pins):
    case = episode["state_id"].split("_", 1)[0]
    expected_target, initial_sha, header, _ = CASES[case]
    expected_initial, _, _ = case_templates(case)
    start = episode["steps"][0]
    ep = json.loads(episode_raw)
    need(ep["state_id"] == episode["state_id"] and ep["model"] == episode["model"]
         and ep.get("mode", "typed") == episode["mode"] and ep["protocol"] == "equal_source_v2"
         and ep["outcome"] == episode["loop_time_outcome"], "Archive episode identity differs")
    step = json.loads(member(start["archive_member"], start["sha256"]))
    index = start["prestate_prompt_index"]
    prompt_record = step["request"]["messages"][index]
    prompt = prompt_record["content"]
    need(prompt_record["role"] == "user" and prompt.startswith("Failed blueprint state")
         and digest(prompt) == start["prestate_prompt_sha256"], "Expected pinned initial source prompt")
    start_graph, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
    target_id = f"thm:{case}bad-target"
    node, = start_graph["nodes"]
    need(start_graph["target_node_id"] == node["node_id"] == target_id
         and node["formal_statement"] == header and node["status"] == "proof_too_hard"
         and not start_graph["edges"], "Initial target or graph differs")
    text, = re.findall(r"```lean\n(.*?)```", prompt, re.S)
    need(digest(text) == initial_sha and text == expected_initial,
         "Exact initial source is outside one-theorem admitted fixture grammar")
    error = None
    # Keep one actual compiler error provenance marker per episode, without reading any proof proposal.
    first_error = next((s for s in episode["steps"] if s["outcome"] == "ARCHIVED_LEAN_ERROR"), None)
    if first_error:
        checked = next(x for x in first_error["author_elaborations"] if x["exit_code"] not in (None, 0)
                       and not x["timed_out"] and x["error_count"] > 0)
        recorded = json.loads(member(checked["member"], checked["sha256"]))
        errors = [x for x in recorded["diagnostics"] if x["severity"] == "error"]
        need(recorded["pins"] == pins and recorded["exit_code"] == checked["exit_code"]
             and not recorded["timed_out"] and len(errors) == checked["error_count"],
             "Author Lean-error marker does not bind archive")
        error = {"step": first_error["step"], "diagnostic_sha256": checked["sha256"],
                 "exit_code": checked["exit_code"], "error_count": len(errors)}
    return {"state": case + "_bad.state0", "target": expected_target, "episode_sha256": episode["episode_sha256"],
            "model": episode["model"], "mode": episode["mode"], "initial_step_sha256": start["sha256"],
            "initial_prompt_sha256": digest(prompt), "initial_source_sha256": initial_sha,
            "loop_outcome": ep["outcome"], "author_rescan_pass": episode["author_rescan_pass"],
            "first_archived_lean_error": error}


def control_reference(member, episode, pins):
    need(episode["state_id"] == "p40_bad.state0" and episode["model"] == DEEPSEEK
         and episode["mode"] == "typed" and episode["episode_sha256"] == P40["episode"]
         and episode["author_rescan_pass"], "Expected fixed p40 archived positive")
    base = episode["episode_member"].rsplit("/", 1)[0] + "/"
    raw = member(base + "final.module.lean", P40["final.module.lean"])
    final = raw.decode()
    names = ("base_case", "step", "p40_target")
    imports = "".join(f"import {m}\n" for m in CASES["p40"][3])
    need(final.startswith(imports + "\nnamespace P40Bad\n\n") and final.endswith("end P40Bad\n")
         and tuple(re.findall(r"(?m)^theorem (\w+)", final)) == names
         and CASES["p40"][2] + " := by\n" in final
         and not re.search(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|"
                           r"elab|macro|attribute|set_option|opaque|native_decide)\b|#", final),
         "Accepted reference source differs from the exact reviewed ordinary proof")
    accepted = json.loads(member(base + "step05.json", P40["solved_step"]))
    need(accepted["tool_execution"]["solved"] and accepted["tool_execution"]["module_sha256"] == digest(raw)
         and episode["endpoint"]["author_rescan"]["archive_member_sha256"] == digest(raw),
         "Positive archive step does not bind final module")
    exact_check = member(base + "step05.check.lean", P40["step05.check.lean"])
    suffix = "".join(f"#print axioms P40Bad.{n}\n" for n in names).encode()
    need(exact_check == raw + suffix, "Unexpected raw execution directives in positive check")
    log = json.loads(member(base + "step05.check.elab.json", P40["step05.check.elab.json"]))
    gate = json.loads(member(base + "step05.gate.elab.json", P40["step05.gate.elab.json"]))
    need(all(x["pins"] == pins and x["exit_code"] == 0 and not x["timed_out"] and not x["diagnostics"]
             for x in (log, gate)), "Positive author logs did not close")
    axioms = {}
    for line in log["stdout"].splitlines():
        hit = re.fullmatch(r"'P40Bad\.(\w+)' depends on axioms: \[([^]]*)\]", line)
        need(hit and hit[1] in names and hit[1] not in axioms, "Unbound author axiom output")
        axioms[hit[1]] = sorted(set(hit[2].split(", ")) if hit[2] else set())
        need(set(axioms[hit[1]]) <= SAFE_AXIOMS, "Positive control uses unexpected axioms")
    need(set(axioms) == set(names), "Incomplete axiom output")
    return exact_check, {"state_id": "p40_bad.state0", "target_id": CASES["p40"][0], "mode": "typed",
                         "model": DEEPSEEK, "archive_episode_sha256": P40["episode"], "accepted_step": 5,
                         "archive_final_module_sha256": digest(raw), "exact_reviewed_check_sha256": digest(exact_check),
                         "archived_transitive_axioms": axioms, "reference_in_authoring_slots": False,
                         "local_replay_performed": False}


def run(paths, out, offline, receipt):
    freeze_raw = (ROOT / "D40_SOURCE_SELECTION_FREEZE.json").read_bytes()
    freeze = json.loads(freeze_raw)
    inv_raw = published(D39 / "corpus_inventory.json")
    inv = json.loads(inv_raw)
    need(freeze["baseline"] == BASELINE and freeze["source_sha256"] == digest(inv_raw)
         and freeze["status"] == "FROZEN_BEFORE_NEW_ATTEMPTS", "Source selection freeze does not match the published ledger")
    need(out != offline and not out.is_relative_to(offline) and not offline.is_relative_to(out),
         "Offline source must stay disjoint from authoring slots")
    frozen = {row["state_id"]: row for key in ("unresolved", "same_family_author_rescan_solved") for row in freeze[key]}
    readback, episode_sets = [], {}
    chosen = [row for row in inv["episodes"] if row["state_id"].split("_", 1)[0] in CASES]
    for case, (target, *_rest) in CASES.items():
        sid = case + "_bad.state0"
        eps = [x for x in chosen if x["state_id"] == sid]
        expected = frozen[sid]
        need(len(eps) == 6 and all(x["target_id"] == target and x["controlled_failure_family"] == FAMILY for x in eps)
             and len({(x["model"], x["mode"]) for x in eps}) == 6
             and {x["episode_sha256"] for x in eps} == set(expected["archive_episode_sha256"])
             and sum(len(x["steps"]) for x in eps) == expected["archived_steps"]
             and sum(x["author_verifier_calls"] for x in eps) == expected["author_reported_verifier_calls"],
             "Frozen per-start denominator or original target differs")
        successes = sum(x["author_rescan_pass"] for x in eps)
        need((successes > 0) == (case == "p40"), "Wrong archive outcome stratum")
        episode_sets[case] = {"episodes": len(eps), "archived_step_records": expected["archived_steps"],
                              "archived_steps_by_outcome": dict(Counter(s["outcome"] for ep in eps for s in ep["steps"])),
                              "loop_outcomes": dict(Counter(x["loop_time_outcome"] for x in eps)),
                              "author_rescan_passes": successes, "author_verifier_calls": expected["author_reported_verifier_calls"]}
    positive_bytes = positive = None
    for model, path in paths.items():
        _, sha = ARCHIVES[model]
        need(path.stat().st_size <= 64 * 1024 * 1024 and digest(path.read_bytes()) == sha, "Frozen archive bytes differ")
        with tarfile.open(path, "r:gz") as tar:
            members = [m.name for m in tar.getmembers() if m.isfile()]
            need(len(set(members)) == len(members), "Duplicate archive paths")
            subset = sorted((row for row in chosen if row["model"] == model),
                            key=lambda row: tar.getmember(row["episode_member"]).offset)
            fetch = lambda name, digest_value: read_member(tar, name, digest_value)
            for episode in subset:
                raw_episode = fetch(episode["episode_member"], episode["episode_sha256"])
                readback.append(check_initial(episode, fetch, raw_episode, inv["author_lean_runtime_pins"]))
                if model == DEEPSEEK and episode["state_id"] == "p40_bad.state0" and episode["mode"] == "typed":
                    positive_bytes, positive = control_reference(fetch, episode, inv["author_lean_runtime_pins"])
    need(len(readback) == 24 and positive_bytes is not None, "Selected archive cases did not close")
    out.mkdir(parents=True, exist_ok=False)
    offline.mkdir(parents=True, exist_ok=False)
    staged = {}
    for case, (target, initial_sha, header, imports) in CASES.items():
        _, slot, absence = case_templates(case)
        row = {"target_id": target, "state_id": case + "_bad.state0",
               "role": "same_family_positive_control" if case == "p40" else "unresolved_archive_development",
               "exact_target_header": header, "target_header_sha256": digest(header),
               "exact_imports": list(imports), "archive_initial_source_sha256": initial_sha,
               "local_slot": {}, "archive_counts": episode_sets[case]}
        for suffix, text in (("author_target_slot", slot), ("absence", absence)):
            name = case + "_" + suffix + ".lean"
            with (out / name).open("xb") as stream:
                stream.write(text.encode())
            row["local_slot"][suffix] = {"name": name, "sha256": digest(text), "bytes": len(text.encode())}
        staged[case] = row
    with (offline / "p40_author_exact_offline_check.lean").open("xb") as stream:
        stream.write(positive_bytes)
    report = {"status": "ARCHIVE_BOUND_TARGET_SLOTS_ONLY", "scope": "No Lean execution or model attempt. Positive exact proof is staged only offline in a disjoint directory.",
              "freeze_sha256": digest(freeze_raw), "published_inventory_sha256": digest(inv_raw), "baseline": BASELINE,
              "author_runtime_pins": inv["author_lean_runtime_pins"], "slot_placeholder": SLOT.strip(),
              "source_cases": staged, "initial_source_archive_readback": readback,
              "offline_positive_reference": {**positive, "filename": "p40_author_exact_offline_check.lean"},
              "raw_failed_proofs_staged": False, "author_gate_sources_staged": False,
              "local_model_ready_or_proved_claim": False}
    raw = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": report["status"], "cases": len(staged), "sha256": digest(raw)}))


def default_archive(model):
    leaf, sha = ARCHIVES[model]
    return Path(tempfile.gettempdir()) / f"blueprint_trace_{sha[:12]}_{leaf}"


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--deepseek-archive", type=Path, default=default_archive(DEEPSEEK))
    cli.add_argument("--qwen-archive", type=Path, default=default_archive(QWEN))
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--offline-reference-dir", type=Path, required=True)
    cli.add_argument("--receipt", type=Path, default=ROOT / "cases_source_receipt.json")
    a = cli.parse_args()
    run({DEEPSEEK: a.deepseek_archive.resolve(), QWEN: a.qwen_archive.resolve()},
        a.output_dir.resolve(), a.offline_reference_dir.resolve(), a.receipt.resolve())
