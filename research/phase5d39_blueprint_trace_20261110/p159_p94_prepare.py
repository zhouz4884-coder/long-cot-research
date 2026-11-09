"""Prepare the reviewed p94 accepted source and a fixed additive bridge control."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tarfile
import tempfile

from p159_adjacent_prepare import ARCHIVE_SHA, declarations
from p159_prepare_reviewed import ARCHIVE_SHA as QWEN_SHA, FOUNDATIONAL, PATCH, ROOT, archive_member, digest, need
from p159_p165_prepare import FORBIDDEN


DEEPSEEK = "data/llm_calls/p94_missing_hypothesis_patchsrc_v0/typed/"
QWEN = "data/llm_calls/p94_missing_hypothesis_patchsrcq_v0/typed/"
INITIAL = "86bdb907b9d67e141c28eb34fc4ee938ff1e309785fad465a4c4b9eaa0f71834"
PROMPT = "e5a37ac664e78f0b4af1795a42263ef23b14d94374b17494b4d0abe2ea12857e"
FINAL = "e4da78f80dc79ef6f2562240191a843c91106c2e7ba9b4df9f63838b8805a64a"
HEADER = "89481f8ec547ab24ef6b13983f05d3bdff528995180817117faf5f06abe502ec"
OLD_PROTECTED = "3abf24fa4c7e8d2f746c06d5a75a80ff0afb4cd916b046618d55a49f7f5b4766"
DEEP_HASHES = {
    "episode.json": "79283a0f4d0afba55099aa41e7d3e1888246ed0a06cbc168ae8ef9d0ca3f8a01",
    "step01.json": "f4aa74138df0b6377ff38ff43ad0079f2dff2a1cba3afd06cc07a5d70794a695",
    "step02.json": "a02b415035e712fd9033d3ca357644b20d13d4c971b110cded848bc84f2ad9ab",
    "step03.json": "be5a7f0b1da2b01ed746684a7e1e4e2bee0921de27f039331d53ddc0c828d50e",
    "step04.json": "aba8d8a9948b466ee007a788d69e0ebe5ace5e4931e398cf377c62091e79b7f2",
    "step04.check.lean": "e9ce4bb5c8105fe95fd16a35f9b74157f4d9ae86bd1eb087ba7e6ae10e309b16",
    "step04.check.elab.json": "d138621d1bc977e627bbe8809c22f367df2f5ad5fa4faf569da13daaed500b53",
    "final.module.lean": FINAL,
}
QWEN_HASHES = {
    "episode.json": "a37a55033d3d986b80fb05aa96c6887445cc041c437ef14429c07ac9d5c07afb",
    "step01.json": "294baf8b76b8fa186303f490100ecf633d1537730f8f62fe0edd19d44090e851",
    "step02.json": "33fbb020d69efcdeebb9849156c4829b5c31f573255eb2510ea039895e9955a4",
    "step01.check.lean": "00dc7e75a000ba8312728474d14765900de38488ba4e88b516bd25ff3b9237e8",
    "step01.check.elab.json": "16ba112e1f109d4c7e79cf3b22d2bfa3bfb5352f106a4e547ca0167780637f5b",
}
QWEN_PRESTATE = "ba5ca534db248fde7742baa723f1af356cd099e99b87e4f9a8dd53ee169988b1"
QWEN_FEEDBACK = "34d34d9975e4b5fa488a02ff2aad7bd153bef24ec1fe1528de1966221beab300"
IMPORTS = "import Architect\nimport Mathlib\n\nnamespace P94Bad\n\n"
TARGET_TYPE = "∀ a m c : ℕ, a + m + c = 12 → a*m*c + a*m + m*c + a*c ≤ 112"
OLD_TYPE = "∀ a m c : ℕ, a + m + c = 12 → (a + 1) * (m + 1) * (c + 1) ≤ 125"
TARGET_CHECK = f"#check (P94Bad.p94_target : {TARGET_TYPE})\n"
BRIDGE = '''@[blueprint "lem:p94bad-preserved-bridge"
  (latexEnv := "lemma")
  (proofUses := [product_bound_wrong])]
theorem product_bound_expanded (a m c : ℕ) (h : a + m + c = 12) :
    a*m*c + a*m + m*c + a*c ≤ 112 := by
  have old := product_bound_wrong a m c h
  have expanded : (a + 1) * (m + 1) * (c + 1) =
      (a*m*c + a*m + m*c + a*c) + (a + m + c) + 1 := by ring
  rw [expanded, h] at old
  omega'''


def fetch(archive, sha, base, expected):
    need(archive.stat().st_size <= 64 * 1024 * 1024 and digest(archive.read_bytes()) == sha, "Archive differs")
    with tarfile.open(archive, "r:gz") as tar:
        picked = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(base)]
        members = {m.name: m for m in picked}
        need(len(members) == len(picked), "Duplicate archive members")
        return {name: archive_member(tar, members, base + name, digest_value)
                for name, digest_value in expected.items()}


def parse_fence(message):
    source, = re.findall(r"```lean\n(.*?)```", message, re.S)
    return source


def print_axioms(names):
    return "".join(f"#print axioms P94Bad.{n}\n" for n in names)


def closure(log, name):
    matches = re.findall(rf"'P94Bad\.{re.escape(name)}' depends on axioms: \[([^]]*)\]", log["stdout"])
    need(len(matches) == 1, "Expected one author axiom closure")
    return sorted({value.strip() for value in matches[0].split(",") if value.strip()})


def first_source(detail):
    prompt = detail["request"]["messages"][1]["content"]
    need(digest(prompt) == PROMPT, "Initial source prompts differ")
    initial = parse_fence(prompt)
    need(digest(initial) == INITIAL, "Initial source bytes differ")
    graph, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
    need(graph["target_node_id"] == "thm:p94bad-target", "Initial target differs")
    return initial


def patch(text, detail, expected_hash):
    execution = detail["tool_execution"]
    choice, = detail["response"]["choices"]
    blocks = list(PATCH.finditer(choice["message"]["content"]))
    need(execution["tool"] == "local_patch" and execution["applied"] and not choice["message"].get("tool_calls")
         and len(blocks) == execution["blocks_applied"], "Unexpected patch action")
    for block in blocks:
        search, replace = block.groups()
        need(text.count(search) == 1, "Unresolved patch search")
        text = text.replace(search, replace, 1)
    need(digest(text) == execution["module_sha256"] == expected_hash, "Exact patch does not bind recorded module")
    return text


def run(deep, qwen, out, receipt):
    evidence = json.loads((ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes())
    revisions = {x["name"]: x["rev"] for x in evidence["packages"]}
    pins = {"lean_toolchain": evidence["toolchain"], "mathlib_rev": revisions["mathlib"],
            "leanarchitect_rev": revisions["LeanArchitect"]}
    ds = fetch(deep, ARCHIVE_SHA, DEEPSEEK, DEEP_HASHES)
    qw = fetch(qwen, QWEN_SHA, QWEN, QWEN_HASHES)
    ds_ep, qw_ep = json.loads(ds["episode.json"]), json.loads(qw["episode.json"])
    need(ds_ep["state_id"] == qw_ep["state_id"] == "p94_bad.state0"
         and ds_ep["model"] == "deepseek/deepseek-v4-flash" and qw_ep["model"] == "qwen/qwen3.6-flash"
         and ds_ep["mode"] == qw_ep["mode"] == "patch" and ds_ep["outcome"] == "solved"
         and ds_ep["solved_at_step"] == 4 and ds_ep["final_module_sha256"] == FINAL
         and qw_ep["outcome"] == "budget_exhausted", "Unexpected source episode status")
    qfirst = json.loads(qw["step01.json"])
    common_initial = first_source(json.loads(ds["step01.json"]))
    need(common_initial == first_source(qfirst), "The two episodes did not begin at the same module")
    current = common_initial
    for i in range(1, 5):
        current = patch(current, json.loads(ds[f"step{i:02d}.json"]), ds_ep["steps"][i - 1]["module_sha256"])
    ds_final = ds["final.module.lean"].decode()
    need(ds_final == current, "DeepSeek accepted module differs from exact patch reconstruction")
    source_names = ("product_bound_wrong", "p94_target")
    accepted_check = ds["step04.check.lean"].decode()
    need(accepted_check == ds_final + print_axioms(source_names), "Unapproved accepted check suffix")
    ds_log = json.loads(ds["step04.check.elab.json"])
    ds_axioms = {name: closure(ds_log, name) for name in source_names}
    need(ds_log["pins"] == pins and ds_log["exit_code"] == 0 and not ds_log["timed_out"]
         and not ds_log["diagnostics"] and all(set(x) <= FOUNDATIONAL for x in ds_axioms.values()),
         "DeepSeek author acceptance does not close")
    q_prev = patch(common_initial, qfirst, QWEN_PRESTATE)
    q_second = json.loads(qw["step02.json"])
    feedback = q_second["request"]["messages"][3]["content"]
    need(digest(feedback) == QWEN_FEEDBACK and parse_fence(feedback) == q_prev,
         "Prior proved helper scope differs from the exact Qwen feedback")
    graph, _ = json.JSONDecoder().raw_decode(feedback[feedback.index("{"):])
    scope = {x["node_id"]: x for x in graph["graph"]["nodes"]}
    need(graph["applied"] and graph["target_preserved"] and not graph["solved"]
         and scope["lem:p94bad-product-bound"]["status"] == "proved"
         and scope["thm:p94bad-target"]["status"] == "type_invalid", "Prior graph roles differ")
    before = {r["name"]: r for r in declarations(q_prev, "P94Bad")}
    approved = {r["name"]: r for r in declarations(ds_final, "P94Bad")}
    old = before["product_bound_wrong"]
    need(old["header"] == scope[old["node_id"]]["formal_statement"] and digest(old["source"]) == OLD_PROTECTED
         and not FORBIDDEN.search(old["source"]) and all(not FORBIDDEN.search(r["source"]) for r in approved.values()),
         "Unreviewed proof directive or protected source mismatch")
    q_log = json.loads(qw["step01.check.elab.json"])
    q_axioms = closure(q_log, "product_bound_wrong")
    error, = q_log["diagnostics"]
    need(qw["step01.check.lean"].decode() == q_prev + print_axioms(source_names)
         and q_log["pins"] == pins and q_log["exit_code"] == 1 and not q_log["timed_out"]
         and error["severity"] == "error" and error["message"].startswith("unsolved goals")
         and " - 13" in error["message"] and set(q_axioms) <= FOUNDATIONAL
         and "sorryAx" in closure(q_log, "p94_target"), "Qwen prior helper/target check differs")
    target = approved["p94_target"]
    need(digest(target["header"]) == HEADER and before["p94_target"]["header"] == target["header"]
         and target["source"].count("product_bound_wrong") == 2, "Target statement or dependency span differs")
    transplanted = ds_final.replace(approved["product_bound_wrong"]["source"], old["source"] + "\n\n" + BRIDGE, 1)
    transplanted = transplanted.replace(target["source"], target["source"].replace("product_bound_wrong", "product_bound_expanded"), 1)
    after = {r["name"]: r for r in declarations(transplanted, "P94Bad")}
    need(tuple(after) == ("product_bound_wrong", "product_bound_expanded", "p94_target")
         and after["product_bound_wrong"]["source"] == old["source"]
         and after["p94_target"]["header"] == target["header"], "Bridge changed protected source or target")
    old_only = (IMPORTS + old["source"] + "\n\nend P94Bad\n" +
                f"#check (P94Bad.product_bound_wrong : {OLD_TYPE})\n" + print_axioms(("product_bound_wrong",)))
    fixtures = {
        "p94_author_exact_check.lean": accepted_check,
        "p94_author_bound_check.lean": accepted_check + TARGET_CHECK,
        "p94_qwen_helper_only.lean": old_only,
        "p94_preserving_bridge.lean": transplanted + TARGET_CHECK + print_axioms(tuple(after)),
    }
    out.mkdir(parents=True, exist_ok=False)
    for name, raw in fixtures.items():
        with (out / name).open("xb") as stream:
            stream.write(raw.encode())
    report = {"status": "ARCHIVE_BOUND_REVIEWED_CROSS_EPISODE_BRIDGE_SOURCE_ONLY",
              "state_id": "p94_bad.state0", "scope": "Qwen complete helper from a prior applied-but-failing target step, and independently accepted DeepSeek target from same initial state. The bridge is a new controlled cross-episode construction.",
              "deepseek_archive_sha256": ARCHIVE_SHA, "qwen_archive_sha256": QWEN_SHA,
              "deepseek_members": DEEP_HASHES, "qwen_members": QWEN_HASHES, "author_pins": pins,
              "shared_initial_module_sha256": INITIAL, "unchanged_target_header_sha256": HEADER,
              "accepted_deepseek_module_sha256": FINAL, "qwen_pre_failure_module_sha256": QWEN_PRESTATE,
              "preserved_qwen_helper_declaration_sha256": OLD_PROTECTED,
              "qwen_helper_author_axioms": q_axioms, "qwen_target_archived_error": error["message"],
              "deepseek_target_author_axioms": ds_axioms["p94_target"],
              "prepared_fixtures": {name: {"sha256": digest(text), "bytes": len(text.encode())} for name, text in fixtures.items()},
              "local_kernel_acceptance_claim": False, "raw_qwen_target_and_raw_author_gates_executable": False,
              "model_generation": False}
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"status": report["status"], "fixtures": len(fixtures), "receipt_sha256": digest(payload)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    scratch = Path(tempfile.gettempdir())
    parser.add_argument("--deepseek-archive", type=Path, default=scratch / "blueprint_trace_6acd6a2571ec_llm_calls_equal_source.tar.gz")
    parser.add_argument("--qwen-archive", type=Path, default=scratch / "blueprint_trace_8a7a7e6ed192_llm_calls_qwen_equal_source.tar.gz")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=ROOT / "p159_p94_source_receipt.json")
    args = parser.parse_args()
    run(args.deepseek_archive.resolve(), args.qwen_archive.resolve(), args.output_dir.resolve(), args.receipt.resolve())
