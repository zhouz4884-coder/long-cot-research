"""Prepare the trusted p165 rescan and body-preserving counterfactual."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tarfile
import tempfile

from p159_adjacent_prepare import ARCHIVE_SHA, declarations
from p159_prepare_reviewed import FOUNDATIONAL, ROOT, archive_member, digest, need


RUN = "data/llm_calls/p165_algebra_rwsrc_v0/typed/"
HASHES = {
    "episode.json": "7543475938179b494371b2baf348f883e3184d2930a1c8480518d3a8f2de9304",
    "step01.json": "1f282d5417ea125880b319fd4abf0ebe5d1b456c06690d5554e5e6b0b9ba4dca",
    "step03.json": "cd36320c175a9e485a2522bfe46a69683080a1f20e957b20df1914d5d376ca2a",
    "step03.check.lean": "a200bc6ea6fb0d771b0ae4ae5a059b12ac2b5278c584a37bfcec7cf3ab3927d9",
    "step03.check.elab.json": "ec72c7f9cade9e78e8b7baac0dea99ef39e11a7eaeda5fb9857dc142501b3f76",
    "step03.gate.elab.json": "d0b3880be6c57ebc3f287b9e2a289ab0f4bbcb0d8e5c03b4b96922483249a19d",
}
INITIAL = "122f4f48afcaeb644bb0ba1e8e6ff708304e43290be6804cb304e9704ee560c6"
MODULE = "7838fd17d815f04393c77596acd271d758cbc0975adb6f49743e30af13268ae7"
PROMPT = "8c1fcb676aeaff64d636c3f03f8497a31614807f005ee629a83a2bc7cbf2fcb3"
TARGET = "7bc5bc984c27b6a7243d080722bcab692a76aa2a3797e443c63a075de29b5792"
NAMES = ("a_cubed", "a_value", "b_cubed", "b_value", "p165_target")
OLD_PROOFS = {
    "a_value": "0f0e36ee9cbb53952a71bcb74f2edeaa1c35bc6aee4ff89ee82eca0f66d3e360",
    "b_cubed": "0dee38d98d8288c98baa505acafe7189e8f4046e41da5a936589a5eaaee5fc14",
    "b_value": "6a019919d1adf9a9311d9cd788dad2b0ecb071e528ad77f3ad503347d00952ab",
}
FORBIDDEN = re.compile(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|elab|macro|"
                       r"attribute|set_option|open|import|opaque|native_decide)\b|#")
TYPE_CHECK = ("#check (P165Bad.p165_target : ∀ a b : ℝ, "
              "a^2 * b^3 = 32 / 27 → a / b^3 = 27 / 4 → a + b = 8 / 3)\n")


def check_suffix(names):
    return "".join(f"#print axioms P165Bad.{n}\n" for n in names)


def body(row):
    needle = " by\n"
    need(row["proof"].startswith(needle), "Expected reviewed tactic proof body")
    return row["proof"][len(needle):]


def author_axioms(log):
    result = {}
    for line in log["stdout"].splitlines():
        match = re.fullmatch(r"'P165Bad\.(\w+)' depends on axioms: \[([^]]*)\]", line)
        need(match and match[1] in NAMES and match[1] not in result, "Unexpected author axiom line")
        axioms = sorted({entry.strip() for entry in match[2].split(",") if entry.strip()})
        need(set(axioms) <= FOUNDATIONAL, "Unexpected author axiom")
        result[match[1]] = axioms
    need(set(result) == set(NAMES), "Incomplete author closure")
    return result


def run(archive, out, receipt):
    evidence = json.loads((ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes())
    revisions = {r["name"]: r["rev"] for r in evidence["packages"]}
    pins = {"lean_toolchain": evidence["toolchain"], "mathlib_rev": revisions["mathlib"],
            "leanarchitect_rev": revisions["LeanArchitect"]}
    need(archive.stat().st_size <= 64 * 1024 * 1024 and digest(archive.read_bytes()) == ARCHIVE_SHA,
         "Archive differs")
    with tarfile.open(archive, "r:gz") as tar:
        picked = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(RUN)]
        members = {m.name: m for m in picked}
        need(len(members) == len(picked), "Duplicate archive members")
        data = {name: archive_member(tar, members, RUN + name, sha) for name, sha in HASHES.items()}
    episode, initial, solved = (json.loads(data[key]) for key in ("episode.json", "step01.json", "step03.json"))
    need(episode["state_id"] == "p165_bad.state0" and episode["model"] == "deepseek/deepseek-v4-flash"
         and episode["mode"] == "rewrite" and episode["protocol"] == "equal_source_v2"
         and episode["outcome"] == "solved" and episode["solved_at_step"] == 3
         and episode["final_module_sha256"] is None and episode["steps"][2]["module_sha256"] == MODULE,
         "Wrong p165 episode scope")
    text = initial["request"]["messages"][1]["content"]
    need(digest(text) == PROMPT, "Initial prompt bytes changed")
    starting, = re.findall(r"```lean\n(.*?)```", text, re.S)
    need(digest(starting) == INITIAL, "Initial Lean module differs")
    graph, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    need(graph["target_node_id"] == "thm:p165bad-target", "Initial target differs")
    initial_nodes = {r["name"]: r for r in declarations(starting, "P165Bad")}
    initial_graph = {r["node_id"]: r for r in graph["nodes"]}
    need(all(initial_graph[r["node_id"]]["formal_statement"] == r["header"] for r in initial_nodes.values()),
         "Initial graph theorem header mismatch")
    archived_check = data["step03.check.lean"].decode("utf-8")
    suffix = check_suffix(NAMES)
    need(archived_check.endswith(suffix), "Unapproved author check suffix")
    accepted = archived_check[:-len(suffix)]
    rewrite, = re.findall(r"```lean\n(.*?)```", solved["response"]["choices"][0]["message"]["content"], re.S)
    need(digest(accepted) == MODULE and rewrite == accepted
         and solved["tool_execution"]["module_sha256"] == MODULE
         and solved["tool_execution"]["applied"] and solved["tool_execution"]["solved"],
         "Check source, response and per-step module differ")
    checked, gate = (json.loads(data[name]) for name in ("step03.check.elab.json", "step03.gate.elab.json"))
    for log in (checked, gate):
        need(log["pins"] == pins and log["exit_code"] == 0 and not log["timed_out"] and not log["diagnostics"],
             "Author rescan or dependency gate did not close")
    accepted_nodes = {r["name"]: r for r in declarations(accepted, "P165Bad")}
    need(tuple(accepted_nodes) == NAMES and all(not FORBIDDEN.search(r["source"]) for r in accepted_nodes.values())
         and digest(accepted_nodes["p165_target"]["header"]) == TARGET
         and accepted_nodes["p165_target"]["header"] == initial_nodes["p165_target"]["header"],
         "Accepted source differs from the fixed reviewed statement and proof scope")
    transplanted = accepted
    preserved = []
    for name, expected in OLD_PROOFS.items():
        earlier, later = initial_nodes[name], accepted_nodes[name]
        old, new = body(earlier), body(later)
        need(earlier["header"] == later["header"] and digest(old) == expected and old != new
             and not FORBIDDEN.search(earlier["source"])
             and initial_graph[earlier["node_id"]]["status"] == "proved_and_used",
             "Not a reviewed changed body under an unchanged declaration")
        replacement = later["source"][:-len(new)] + old
        need(transplanted.count(later["source"]) == 1, "Preserving body splice is ambiguous")
        transplanted = transplanted.replace(later["source"], replacement, 1)
        preserved.append({"declaration": f"P165Bad.{name}", "initial_blueprint_id": earlier["node_id"],
                          "accepted_blueprint_id": later["node_id"], "unchanged_header_sha256": digest(earlier["header"]),
                          "restored_original_proof_body_sha256": digest(old), "author_new_proof_body_sha256": digest(new)})
    new_nodes = {r["name"]: r for r in declarations(transplanted, "P165Bad")}
    need(all(row["header"] == accepted_nodes[name]["header"] for name, row in new_nodes.items())
         and {name for name, row in new_nodes.items() if row["source"] != accepted_nodes[name]["source"]} == set(OLD_PROOFS),
         "Counterfactual changed a declaration outside the three reviewed proof bodies")
    initial_clean = ("import Architect\nimport Mathlib\n\nnamespace P165Bad\n\n" +
                     "\n\n".join(initial_nodes[n]["source"] for n in OLD_PROOFS) + "\n\nend P165Bad\n")
    fixtures = {"p165_author_rescan_exact_check.lean": archived_check,
                "p165_author_bound_check.lean": archived_check + TYPE_CHECK,
                "p165_preserved_transplant.lean": transplanted + suffix + TYPE_CHECK,
                "p165_initial_three.lean": initial_clean + check_suffix(OLD_PROOFS)}
    out.mkdir(parents=True, exist_ok=False)
    for filename, source in fixtures.items():
        with (out / filename).open("xb") as stream:
            stream.write(source.encode())
    report = {"status": "ARCHIVE_BOUND_REVIEWED_COUNTERFACTUAL_SOURCE_ONLY", "author_pins": pins,
              "archive_sha256": ARCHIVE_SHA, "members": HASHES, "initial_module_sha256": INITIAL,
              "author_episode_final_module_sha256": None, "author_step_module_sha256": MODULE,
              "author_rescan_check_sha256": HASHES["step03.check.lean"], "target_header_sha256": TARGET,
              "scope": "Separate author rescan source and paired old-body transplant. Proof success and preservation need exact local kernel validation.",
              "author_archived_check_axioms": author_axioms(checked), "preserved_source_body_splices": preserved,
              "prepared_fixtures": {filename: {"sha256": digest(source), "bytes": len(source.encode())}
                                    for filename, source in fixtures.items()},
              "raw_author_gate_executable": False, "executed_locally": False, "model_generation": False}
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"status": report["status"], "fixtures": len(fixtures), "receipt_sha256": digest(payload)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(tempfile.gettempdir()) /
                         "blueprint_trace_6acd6a2571ec_llm_calls_equal_source.tar.gz")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=ROOT / "p159_p165_source_receipt.json")
    args = parser.parse_args()
    run(args.archive.resolve(), args.output_dir.resolve(), args.receipt.resolve())
