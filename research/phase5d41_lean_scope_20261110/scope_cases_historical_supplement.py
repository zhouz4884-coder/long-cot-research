"""Prepare reviewed exact archive failures and distinct trusted name queries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from scope_cases_prepare import ARCHIVES, BASELINE, REPO, ROOT, digest, need, save


D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
SITES = {
    "p104": (1, "ZMod.nat_cast_eq_zero_iff", "2abf6a927079d029e87fc5aafbbe8fdbaf33429c6049c4bd09b106fbbd07f3a0",
             "775e7b620c16318386278803e4e4a7257f9cb69cd72d765e05169fe97c7ad13e",
             "DIRECT_MANDATORY_EXACT_TERM"),
    "p115": (5, "Nat.fib_succ_succ", "9fb3b58e797308c81b0153827421023d8f2e84e6993c2eb49479f061a1d5a5a2",
             "fdb685a642bd0aa0af70d9c6a9d6548f1c822c6acab8a1e59c12c5fcbdb42e46",
             "DEFER_NON_STRAIGHT_LINE_MATCH_ARM"),
    "p139": (1, "Nat.mersenne_prime_iff", "7e9303c33a0c1c5eb52bd9f0cc61834e7bda8a572b71f8fca592a9fa8069562d",
             "525b9f5348380d1b2a153928cef198f05ec4ad959c894737dc08698e23bd753c",
             "DIRECT_MANDATORY_EXACT_TERM"),
}
FORBIDDEN = re.compile(r"\b(?:sorry|sorry_using|admit|axiom|unsafe|run_cmd|run_tac|run_elab|elab|macro|"
                       r"attribute|set_option|opaque|native_decide|open|local|scoped)\b|#|```")


def inherited(path):
    raw = path.read_bytes()
    prior = subprocess.check_output(["git", "show", f"{BASELINE}:{path.relative_to(REPO).as_posix()}"],
                                    cwd=REPO, timeout=15)
    need(prior == raw, "Earlier published source differs")
    return raw


def read_member(tar, name, expected=None):
    member = tar.getmember(name)
    need(member.isfile() and member.size <= 1024 * 1024, "Unsafe archive member")
    with tar.extractfile(member) as stream:
        raw = stream.read(1024 * 1024 + 1)
    need(len(raw) == member.size and (expected is None or digest(raw) == expected), "Archive member bytes differ")
    return raw


def materialize(tar, ep, case):
    index, name, wanted, initial_sha, safety = SITES[case]
    initial_row = ep["steps"][0]
    initial_step = json.loads(read_member(tar, initial_row["archive_member"], initial_row["sha256"]))
    message = initial_step["request"]["messages"][initial_row["prestate_prompt_index"]]["content"]
    need(digest(message) == initial_row["prestate_prompt_sha256"], "Initial source prompt differs")
    initial, = re.findall(r"```lean\n(.*?)```", message, re.S)
    need(digest(initial) == initial_sha, "Initial source bytes differ")
    header, = re.findall(rf"(?m)^theorem {case}_target[^\n]+(?= := by\n)", initial)
    namespace = case.upper() + "Bad"
    imports = "import Architect\nimport Mathlib\n"
    expected_prefix = imports + f'\nnamespace {namespace}\n\n@[blueprint "thm:{case}bad-target"]\n'
    need(initial == expected_prefix + header + f" := by\n  sorry\n\nend {namespace}\n",
         "Unexpected starting target module")
    step = ep["steps"][index - 1]
    need(step["step"] == index and step["outcome"] == "ARCHIVED_LEAN_ERROR", "Expected actual archive failure")
    log_row, = step["author_elaborations"]
    log = json.loads(read_member(tar, log_row["member"], log_row["sha256"]))
    source_name = step["archive_member"].removesuffix(".json") + ".check.lean"
    check = read_member(tar, source_name, wanted)
    checked = check.decode()
    suffix = f"#print axioms {namespace}.{case}_target\n"
    need(checked.endswith(suffix), "Unexpected author audit command")
    candidate = checked[:-len(suffix)]
    need(candidate.startswith(expected_prefix + header + " := by\n")
         and candidate.endswith(f"end {namespace}\n") and not FORBIDDEN.search(candidate[len(expected_prefix):])
         and len(re.findall(r"(?m)^theorem ", candidate)) == 1
         and name in candidate and "_root_." + name not in candidate,
         "Not the exact reviewed ordinary source and immutable statement")
    step_json = json.loads(read_member(tar, step["archive_member"], step["sha256"]))
    need(step_json["tool_execution"]["module_sha256"] == digest(candidate) and
         step_json["tool_execution"]["applied"] and not step_json["tool_execution"]["solved"],
         "Author module digest or step state differs")
    error, = (row for row in log["diagnostics"] if row["severity"] == "error")
    need(log["exit_code"] == 1 and not log["timed_out"] and error["message"] == f"Unknown constant `{name}`",
         "Author compiler class differs")
    occurrence, = [line for line in candidate.splitlines() if name in line]
    if safety == "DIRECT_MANDATORY_EXACT_TERM":
        need(occurrence.startswith("  exact ") and candidate.split(occurrence, 1)[1].strip() == f"end {namespace}"
             and not re.search(r"(?m)\b(?:first|match|try|repeat|fallback)\b", candidate),
             "Mandatory final proof site differs")
    else:
        need("match m with" in candidate and occurrence.lstrip().startswith("simpa using "),
             "Expected guarded non-straight-line author context")
    query = (imports + f"\nnamespace {namespace}\n\n#check {name}\n#check _root_.{name}\n"
             f"\nend {namespace}\n")
    return check, query.encode(), {
        "state_id": ep["state_id"], "target_id": ep["target_id"], "qualified_target": f"{namespace}.{case}_target",
        "archive_episode_sha256": ep["episode_sha256"], "archive_step_sha256": step["sha256"],
        "archive_check_member": source_name, "archive_check_sha256": wanted,
        "archive_log_sha256": log_row["sha256"], "author_module_sha256": digest(candidate),
        "exact_target_header_sha256": digest(header), "exact_imports": ["Architect", "Mathlib"],
        "relative_qualified_spelling": name, "source_scope_review": safety,
        "author_error_line": error["line"], "author_error": error["message"], "author_pins": log["pins"],
        "exact_source_approved_for_ordinary_cpu_replay": safety == "DIRECT_MANDATORY_EXACT_TERM",
        "hard_skip_authority_before_runtime_query": False,
    }


def run(out, receipt):
    d41 = ROOT / "D41_SCOPE_INPUT_FREEZE.json"
    frozen = json.loads(d41.read_bytes())
    ledger = inherited(D39 / "corpus_inventory.json")
    inventory = json.loads(ledger)
    leaf, archive_sha = ARCHIVES["deepseek"]
    archive = Path(tempfile.gettempdir()) / leaf
    need(frozen["baseline"] == BASELINE and digest(archive.read_bytes()) == archive_sha, "Input pins differ")
    out.mkdir(parents=True, exist_ok=False)
    cases = {}
    with tarfile.open(archive, "r:gz") as tar:
        for case in SITES:
            state = case + "_bad.state0"
            need(state in frozen["unresolved_state_ids"], "Supplement is outside frozen unresolved cohort")
            episode, = (row for row in inventory["episodes"] if
                        (row["state_id"], row["model"], row["mode"]) == (state, "deepseek/deepseek-v4-flash", "patch"))
            exact, query, row = materialize(tar, episode, case)
            fixtures = {f"{case}_same_scope_queries.lean": query}
            if row["exact_source_approved_for_ordinary_cpu_replay"]:
                fixtures[f"{case}_archived_exact_negative.lean"] = exact
            for name, raw in fixtures.items():
                with (out / name).open("xb") as stream:
                    stream.write(raw)
            row["prepared_fixtures"] = {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in fixtures.items()}
            cases[case] = row
    report = {"status": "FROZEN_REVIEWED_HISTORICAL_SUPPLEMENTS_BEFORE_EXECUTION",
              "source_scope_freeze_sha256": digest(d41.read_bytes()), "published_inventory_sha256": digest(ledger),
              "archive_sha256": archive_sha, "scope": "Source safety and immutable target review only; no historical hard skip inferred from archive bytes.",
              "cases": cases, "model_generation": False}
    print(json.dumps({"status": report["status"], "sha256": save(receipt, report)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=ROOT / "scope_cases_historical_supplement.json")
    args = parser.parse_args()
    run(args.output_dir.resolve(), args.receipt)
