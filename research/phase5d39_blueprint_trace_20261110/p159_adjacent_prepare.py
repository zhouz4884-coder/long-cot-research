"""Review the exact archived p149/p151 final checks without executing archive sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tarfile
import tempfile

from p159_prepare_reviewed import ANN, FOUNDATIONAL, PATCH, ROOT, THEOREM, archive_member, digest, need


ARCHIVE_SHA = "6acd6a2571ec420e61b05d2ed2d18da4422b6420a7b6d6feb98802030959500e"
CASES = {
    "p151": {
        "episode": "5129cbefed142f98af635dad063753a30edb8a6d6d4147a0d2bae62fe5ed6d32",
        "initial": "536161d3eb484f138ee0df36f289f0a0fdc115ba720ca54d668d293791383145",
        "steps": ["2741881646283a18879b61128c36949a0752dcf90c04f8a56ed73c29e478a1be",
                  "ef7cd5963304f58e67b5f36ae140e66f399a038d599a14303061c90a37d33806",
                  "0419a43cc4bae47ef2af8a1d327c01d1714b121d73e8a3733f808101f142de3a"],
        "final": "f016727b60bc222ce9a1a6c3ddcb90d912bf645d09b359b29c9acc83bf999590",
        "accepted_check": "b77266c94475397fceb94d96eb335cd814b009007f5d654bc232f963efb18bac",
        "accepted_check_log": "d0918d2065e63c1de3d4dd2170338250640cf66414fe875262b452f48c9f1aca",
        "reviewed_names": ("sum_subst", "sum_eval", "mod_window", "final_mod", "seven_mult", "p151_target"),
    },
    "p149": {
        "episode": "f4ecac07b8a4f8277919d7c64db363f1bd9e7f5dc55cbb943ff7b2ce1463b5d2",
        "initial": "28c23fdd35763d0b03f7f5f2764cc27b8af9cf61a8c1177253671521456047f2",
        "steps": ["0a10fe74a4d3a5a492a173a5a88391d3826fcbe1f2623609f4e1e305f8f97a99"],
        "final": "007b91579fbb44615298996c67a915a7689c36d9a42c3f61263a73587fb41f7b",
        "accepted_check": "8e3f4a13dbc68a0a22fa647d6e2e26595a925b9efae543eb5ac0da71698ef7f9",
        "accepted_check_log": "23d20494df9b42ca02a17b78f3a9ecb4aea0fafd1821e22d4384de87e6eef9db",
        "reviewed_names": ("sum_eval", "sub_bounds", "mult_range", "window", "key_multiple", "p149_target"),
    },
}


def declarations(raw, namespace):
    prefix = f"import Architect\nimport Mathlib\n\nnamespace {namespace}\n\n"
    suffix = f"end {namespace}\n"
    need(raw.startswith(prefix) and raw.endswith(suffix), "Unapproved import or namespace")
    body = raw[:-len(suffix)]
    starts = list(ANN.finditer(body))
    need(starts and starts[0].start() == len(prefix), "Unexpected source commands")
    found = []
    for i, point in enumerate(starts):
        piece = body[point.start():starts[i + 1].start() if i + 1 < len(starts) else len(body)].strip()
        theorem, = THEOREM.finditer(piece)
        decl = piece[theorem.start():]
        header, sep, proof = decl.partition(" :=")
        need(bool(sep) and bool(proof.strip()), "Theorem lacks a scoped proof body")
        found.append({"node_id": point[1], "name": theorem[1], "header": header,
                      "proof": proof, "source": piece})
    return found


def process(tar, members, stem, review, expected_pins):
    namespace = stem.upper() + "Bad"
    path = f"data/llm_calls/{stem}_compound_patchsrc_v0/typed/"
    read = lambda name, sha: archive_member(tar, members, path + name, sha)
    ep = json.loads(read("episode.json", review["episode"]))
    n = len(review["steps"])
    need(ep["state_id"] == stem + "_bad.state0" and ep["model"] == "deepseek/deepseek-v4-flash"
         and ep["mode"] == "patch" and ep["protocol"] == "equal_source_v2" and ep["outcome"] == "solved"
         and ep["solved_at_step"] == n and ep["final_module_sha256"] == review["final"], "Adjacent episode differs")
    first = json.loads(read("step01.json", review["steps"][0]))
    prompt, = (x["content"] for x in first["request"]["messages"]
               if x["role"] == "user" and x["content"].startswith("Failed blueprint state"))
    initial, = re.findall(r"```lean\n(.*?)```", prompt, re.S)
    need(digest(initial) == review["initial"], "Adjacent initial source differs")
    graph, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
    initial_decls = declarations(initial, namespace)
    node_graph = {row["node_id"]: row for row in graph["nodes"]}
    need(graph["target_node_id"] == "thm:" + stem + "bad-target" and set(node_graph) ==
         {row["node_id"] for row in initial_decls}, "Initial target graph differs")
    need(all(row["header"] == node_graph[row["node_id"]]["formal_statement"] for row in initial_decls),
         "Initial scope cannot bind theorem header")
    materialized = initial
    chain = []
    for i, sha in enumerate(review["steps"], 1):
        detail = json.loads(read(f"step{i:02d}.json", sha))
        execution = detail["tool_execution"]
        choice, = detail["response"]["choices"]
        message = choice["message"]
        patches = list(PATCH.finditer(message["content"]))
        need(execution["applied"] is True and execution["tool"] == "local_patch"
             and execution["solved"] == (i == n) and not message.get("tool_calls")
             and len(patches) == execution["blocks_applied"], "Unreviewed patch request")
        for found in patches:
            old, new = found.groups()
            need(materialized.count(old) == 1, "Search block absent or ambiguous")
            materialized = materialized.replace(old, new, 1)
        need(digest(materialized) == execution["module_sha256"] == ep["steps"][i - 1]["module_sha256"],
             "Exact adjacent patch differs")
        chain.append({"step": i, "step_sha256": sha, "module_sha256": digest(materialized), "blocks": len(patches)})
    final = read("final.module.lean", review["final"]).decode()
    need(final == materialized, "Exact final adjacent patch differs")
    final_decls = declarations(final, namespace)
    need(tuple(row["name"] for row in final_decls) == review["reviewed_names"] and
         [row["node_id"] for row in initial_decls] == [row["node_id"] for row in final_decls],
         "Unexpected accepted declarations")
    need(initial_decls[-1]["header"] == final_decls[-1]["header"], "Accepted target type text differs")
    for row in final_decls:
        need(not re.search(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|"
                           r"elab|macro|attribute|set_option|open|import|opaque|native_decide)\b|#", row["source"]),
             "Disallowed directive in reviewed exact adjacent proof")
    suffix = "".join(f"#print axioms {namespace}.{row['name']}\n" for row in final_decls)
    exact_check = read(f"step{n:02d}.check.lean", review["accepted_check"])
    need(exact_check == (final + suffix).encode(), "Accepted check is not a reviewed command-only suffix")
    log = json.loads(read(f"step{n:02d}.check.elab.json", review["accepted_check_log"]))
    need(log["pins"] == expected_pins and log["exit_code"] == 0 and not log["timed_out"]
         and not any(x["severity"] in {"error", "warning"} for x in log["diagnostics"]), "Author check did not close")
    author_axioms = {}
    for line in log["stdout"].splitlines():
        hit = re.fullmatch(rf"'{namespace}\.(\w+)' depends on axioms: \[([^]]*)\]", line)
        empty = re.fullmatch(rf"'{namespace}\.(\w+)' does not depend on any axioms", line)
        need(hit or empty, "Unexpected author axiom output")
        name = (hit or empty)[1]
        axioms = sorted({a.strip() for a in hit[2].split(",") if a.strip()}) if hit else []
        need(name in review["reviewed_names"] and name not in author_axioms
             and set(axioms) <= FOUNDATIONAL, "Unexpected axiom dependency")
        author_axioms[name] = axioms
    need(set(author_axioms) == set(review["reviewed_names"]), "Incomplete author axiom output")
    by_pair = list(zip(initial_decls, final_decls, strict=True))
    flagged_changes = []
    for before, after in by_pair:
        label = node_graph[before["node_id"]]["status"]
        if label == "proved_and_used" and before["source"] != after["source"]:
            flagged_changes.append({"node_id": before["node_id"], "archived_graph_label": label,
                                    "initial_contains_admission": re.search(r"\bsorry(?:_using)?\b", before["proof"]) is not None,
                                    "same_theorem_header": before["header"] == after["header"],
                                    "source_before_sha256": digest(before["source"]), "source_after_sha256": digest(after["source"])})
    return exact_check, {
        "state_id": ep["state_id"], "author_model": ep["model"], "archive_episode_member": path + "episode.json",
        "episode_sha256": review["episode"], "initial_module_sha256": review["initial"],
        "final_module_sha256": review["final"], "accepted_check_sha256": review["accepted_check"],
        "target_declaration": f"{namespace}.{final_decls[-1]['name']}",
        "target_header_sha256": digest(final_decls[-1]["header"]), "target_header_preserved": True,
        "proved_label_changes_at_initial_source": flagged_changes,
        "author_accepted_axioms": author_axioms, "patch_chain": chain,
        "executed_locally": False,
    }


def run(archive, out, receipt):
    evidence_raw = (ROOT / "D39_EVIDENCE_INPUTS.json").read_bytes()
    evidence = json.loads(evidence_raw)
    packages = {row["name"]: row["rev"] for row in evidence["packages"]}
    expected_pins = {"lean_toolchain": evidence["toolchain"], "mathlib_rev": packages["mathlib"],
                     "leanarchitect_rev": packages["LeanArchitect"]}
    need(archive.stat().st_size <= 64 * 1024 * 1024 and digest(archive.read_bytes()) == ARCHIVE_SHA
         and ARCHIVE_SHA in {item["sha256"] for item in evidence["trajectory_archive_hashes"]}, "Archive identity differs")
    with tarfile.open(archive, "r:gz") as tar:
        selected = [member for member in tar.getmembers() if member.isfile() and any(
            member.name.startswith(f"data/llm_calls/{case}_compound_patchsrc_v0/typed/") for case in CASES)]
        members = {row.name: row for row in selected}
        need(len(selected) == len(members), "Ambiguous member")
        outputs = {stem: process(tar, members, stem, review, expected_pins) for stem, review in CASES.items()}
    out.mkdir(parents=True, exist_ok=False)
    for stem, (source, _) in outputs.items():
        with (out / f"{stem}_author_exact_check.lean").open("xb") as stream:
            stream.write(source)
    result = {"status": "TWO_BOUND_REVIEWED_SOURCE_FIXTURES", "source_pins_sha256": digest(evidence_raw),
              "archive_sha256": ARCHIVE_SHA, "author_pins": expected_pins,
              "scope": "Line-reviewed fixed final declarations plus original axiom-print suffix only. Raw author gate and admitted initial modules are not staged.",
              "cases": [row for _, row in outputs.values()], "model_generation": False, "gpu_seconds": 0}
    raw = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    with receipt.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": result["status"], "cases": len(outputs), "receipt_sha256": digest(raw)}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--archive", type=Path, default=Path(tempfile.gettempdir()) /
                     "blueprint_trace_6acd6a2571ec_llm_calls_equal_source.tar.gz")
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--receipt", type=Path, default=ROOT / "p159_adjacent_source_receipt.json")
    args = cli.parse_args()
    run(args.archive.resolve(), args.output_dir.resolve(), args.receipt.resolve())
