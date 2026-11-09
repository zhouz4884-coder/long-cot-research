"""Freeze safe authored scope controls and bind original archive contrasts without running Lean."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
BASELINE = "94fc3cf7be07c59db3db9bab55c7492712d5c746"
ARCHIVES = {
    "qwen": ("blueprint_trace_8a7a7e6ed192_llm_calls_qwen_equal_source.tar.gz",
             "8a7a7e6ed192129a754f94ea85089978fc44f136fc11df01a1d676bf5b93ccb7"),
    "deepseek": ("blueprint_trace_6acd6a2571ec_llm_calls_equal_source.tar.gz",
                 "6acd6a2571ec420e61b05d2ed2d18da4422b6420a7b6d6feb98802030959500e"),
}
PAIR_HEADER = "(n : ℕ) (add_zero : ℕ) : (n + 0 = n) ∧ (add_zero = add_zero)"
SIMPLE_HEADER = "(n : ℕ) : n + 0 = n"
OPEN_MODULE = (
    "namespace AliasScope\n"
    "theorem scopedZero (n : ℕ) : n + 0 = n := _root_.Nat.add_zero n\n"
    "end AliasScope\n"
)
NEVER = "_root_.Nat.d41_scope_no_such_lemma"


def digest(x):
    return sha256(x.encode("utf-8") if isinstance(x, str) else x).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def inherited(name, sha=None):
    path = D40 / name
    raw = path.read_bytes()
    prior = subprocess.check_output(["git", "show", f"{BASELINE}:{path.relative_to(REPO).as_posix()}"],
                                    cwd=REPO, timeout=15)
    need(prior == raw and (sha is None or digest(raw) == sha), "Published D4.0 receipt differs")
    return raw


def case(case_id, context, header, body, classification, preflight, why, *, prefix="", tokens=(), pair=None,
         declaration="target"):
    return {"id": case_id, "original_import_scope": context, "header": f"theorem {declaration} {header}".strip(),
            "body": body, "trusted_prefix": prefix, "expected_kernel_class": classification,
            "authorized_preflight": preflight, "scope_reason": why, "candidate_spelling_examples": list(tokens),
            "paired_control": pair, "decl": declaration}


def authored():
    return [
        case("fq_visible", "p14", SIMPLE_HEADER, "  exact _root_.Nat.add_zero n", "PROVED",
             "VISIBLE_OR_FULL_CHECK", "Root-qualified, exact global reference; normalized declaration key is Nat.add_zero.",
             tokens=("_root_.Nat.add_zero", "n"), pair="fq_missing_mandatory"),
        case("fq_shadow_safe", "p14", PAIR_HEADER, "  constructor\n  · exact _root_.Nat.add_zero n\n  · rfl", "PROVED",
             "VISIBLE_OR_FULL_CHECK", "Local binder add_zero exists, but root-qualified Nat theorem is explicit.",
             tokens=("add_zero", "_root_.Nat.add_zero"), pair="bare_shadow_wrong"),
        case("bare_shadow_wrong", "p14", PAIR_HEADER, "  constructor\n  · exact add_zero n\n  · rfl", "FUNCTION_OR_TYPE_ERROR",
             "DEFER_TO_LEAN", "The bare spelling resolves to the local natural-number binder, not the global theorem.",
             tokens=("add_zero", "n"), pair="fq_shadow_safe"),
        case("local_hypothesis", "p14", "(n : ℕ) (h : n + 0 = n) : n + 0 = n", "  exact h", "PROVED",
             "DEFER_TO_LEAN", "h is a local hypothesis and is absent from an import-only global name query.", tokens=("h",)),
        case("let_alias", "p14", SIMPLE_HEADER,
             "  let localZero : n + 0 = n := _root_.Nat.add_zero n\n  exact localZero", "PROVED",
             "DEFER_TO_LEAN", "let-bound proof alias is introduced inside the candidate proof.", tokens=("localZero", "_root_.Nat.add_zero")),
        case("opened_alias", "p41", SIMPLE_HEADER, "  exact scopedZero n", "PROVED",
             "DEFER_TO_LEAN", "Trusted prefix opens a unique declared name, changing unqualified resolution.",
             prefix=OPEN_MODULE + "open AliasScope (scopedZero)\n", tokens=("scopedZero",), pair="closed_alias"),
        case("closed_alias", "p41", SIMPLE_HEADER, "  exact scopedZero n", "UNKNOWN_IDENTIFIER",
             "DEFER_TO_LEAN", "The qualified helper exists, but no open command brings its name into scope.",
             prefix=OPEN_MODULE, tokens=("scopedZero",), pair="opened_alias"),
        case("relative_qualified_alias", "p41", SIMPLE_HEADER, "  exact AliasScope.scopedZero n", "PROVED",
             "DEFER_TO_LEAN", "Namespace-relative spelling depends on the trusted declaration prefix.",
             prefix=OPEN_MODULE, tokens=("AliasScope.scopedZero",), pair="closed_alias"),
        case("local_notation_alias", "p41", SIMPLE_HEADER, "  exact d41zero n", "PROVED",
             "DEFER_TO_LEAN", "Trusted file-local notation expands to Nat.add_zero; spelling is not a declaration key.",
             prefix='local notation "d41zero" => _root_.Nat.add_zero\n', tokens=("d41zero",)),
        case("dot_notation", "p41", "(n : ℕ) : Nat.succ n = Nat.succ n", "  exact Eq.refl n.succ", "PROVED",
             "DEFER_TO_LEAN", "Lean dot syntax depends on local n's type, so a global lookup for n.succ is unsound.",
             tokens=("Eq.refl", "n.succ")),
        case("typeclass_present", "p41", "(α : Type) [Inhabited α] : Nonempty α",
             "  let witness : α := default\n  exact ⟨witness⟩", "PROVED", "DEFER_TO_LEAN",
             "Available projection default requires the implicit local typeclass binder.", tokens=("default", "witness", "Inhabited"),
             pair="typeclass_missing"),
        case("typeclass_missing", "p41", "(α : Type) : Nonempty α", "  exact ⟨(default : α)⟩", "INSTANCE_SYNTHESIS",
             "DEFER_TO_LEAN", "Same global projection exists, but the target has no Inhabited α instance.", tokens=("default",),
             pair="typeclass_present"),
        case("wrong_argument", "p14", "(n : ℤ) : n + 0 = n", "  exact _root_.Nat.add_zero n", "FUNCTION_OR_TYPE_ERROR",
             "VISIBLE_OR_FULL_CHECK", "The constant is visible, but expects a natural-number argument instead of this integer.", tokens=("_root_.Nat.add_zero", "n")),
        case("fq_missing_mandatory", "p14", SIMPLE_HEADER, f"  exact {NEVER} n", "UNKNOWN_IDENTIFIER",
             "HARD_SKIP_ONLY_IF_EXACT_ENV_ABSENT", "Explicit mandatory global reference and no fallback, after authoritative exact-key absence.",
             tokens=(NEVER,), pair="fq_visible"),
        case("fq_missing_fallback", "p14", SIMPLE_HEADER,
             f"  first | exact {NEVER} n | exact _root_.Nat.add_zero n", "PROVED", "DEFER_TO_LEAN",
             "The absent exact name appears in an optional branch; the fallback can still prove the unchanged goal.",
             tokens=(NEVER, "_root_.Nat.add_zero"), pair="fq_missing_mandatory"),
        case("notational_syntax_error", "p41", SIMPLE_HEADER, "  have h : n ≡ n [MOD 9] := by rfl\n  exact _root_.Nat.add_zero n",
             "SYNTAX_ERROR", "DEFER_TO_LEAN", "Original p41 narrow imports do not provide this scoped syntax. Parser error is not missing-term evidence.",
             tokens=("≡", "MOD", "_root_.Nat.add_zero")),
        case("open_goal", "p41", "(n : ℕ) : n = n ∧ n = n", "  constructor\n  · rfl", "UNSOLVED_GOALS",
             "DEFER_TO_LEAN", "The allowed first branch closes while a second proof obligation remains."),
        case("comment_not_term", "p14", SIMPLE_HEADER, f"  -- exact {NEVER} n\n  exact _root_.Nat.add_zero n", "PROVED",
             "DEFER_TO_LEAN", "An identifier-looking comment is never a mandatory proof reference.", tokens=(NEVER, "_root_.Nat.add_zero")),
        case("string_not_term", "p41", f': ("{NEVER}" : String) = "{NEVER}"',
             f'  exact Eq.refl ("{NEVER}" : String)', "PROVED", "DEFER_TO_LEAN",
             "The token-like literal is a string value, not executable name syntax.", tokens=(NEVER, "Eq.refl")),
    ]


def materialize(row, imports):
    prelude = "".join(f"import {n}\n" for n in imports) + "\nset_option warningAsError true\n\nnamespace D41ScopeCases\n\n"
    text = (prelude + row["trusted_prefix"] + row["header"] + " := by\n" + row["body"] + "\n\n"
            + "end D41ScopeCases\n" + f"#print axioms D41ScopeCases.{row['decl']}\n")
    return text


def archive_read(model, members):
    leaf, expected_sha = ARCHIVES[model]
    path = Path(tempfile.gettempdir()) / leaf
    need(path.stat().st_size <= 64 * 1024 * 1024 and digest(path.read_bytes()) == expected_sha,
         "Pinned archive bytes differ")
    data = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in members:
            node = tar.getmember(member)
            need(node.isfile() and node.size <= 1024 * 1024, "Archive member not bounded plain file")
            with tar.extractfile(node) as stream:
                data[member] = stream.read(1024 * 1024 + 1)
    return data


def historical(freeze, runtime_raw, source_raw):
    data, source = json.loads(runtime_raw), json.loads(source_raw)
    overlap = json.loads(inherited("support_accepted_overlap.json"))
    comparison_rows = next(value for value in overlap.values() if isinstance(value, list)
                           and any(isinstance(row, dict) and row.get("step_member") for row in value))
    deferred = {}
    for case_id, model, mode, index in (("p14", "qwen", "rewrite", 8), ("p41", "deepseek", "typed", 3)):
        row, = (r for r in comparison_rows if r.get("state_id") == case_id + "_bad.state0"
                and r.get("model", "").startswith(model) and r.get("interface") == mode and r.get("step") == index)
        prefix = row["step_member"].removesuffix(".json")
        names = [prefix + tail for tail in (".json", ".check.lean", ".check.elab.json")]
        found = archive_read(model, names)
        need([digest(found[name]) for name in names] ==
             [row["step_sha256"], row["check_source_sha256"], row["check_log_sha256"]],
             "Scoped archive contrast does not bind D4.0")
        step, checked, log = json.loads(found[names[0]]), found[names[1]].decode(), json.loads(found[names[2]])
        current = checked.split("#print axioms", 1)[0]
        original_imports = source["source_cases"][case_id]["exact_imports"]
        imports = re.findall(r"(?m)^import ([^\n]+)", current)
        exact_target = source["source_cases"][case_id]["exact_target_header"]
        errors = [d for d in log["diagnostics"] if d["severity"] == "error"]
        token = "sub_dvd_pow_sub_pow" if case_id == "p14" else "Nat.ModEq.pow"
        need(digest(current) == step["tool_execution"]["module_sha256"] and log["exit_code"] == 1 and errors
             and exact_target in current and token in current and "_root_." + token not in current,
             "Expected precise historical candidate context")
        deferred[case_id] = {
            "source_member": names[1], "source_sha256": digest(found[names[1]]), "check_log_sha256": digest(found[names[2]]),
            "target_header_preserved": True, "original_imports": original_imports, "actual_archive_imports": imports,
            "imports_match_frozen_target": imports == original_imports, "candidate_spelling": token,
            "mandatory_exact_root_name_established": False, "disposition": "DEFERRED_NOT_A_HISTORICAL_HARD_SKIP",
            "first_archived_error_line": errors[0].get("line"), "first_archived_error": errors[0]["message"],
            "reasons": (["Imports were narrowed in the rewrite.", "The applied identifier is bare."]
                        if case_id == "p14" else
                        ["The qualified spelling is relative.", "An earlier notation parse error prevented binding the use."]),
            "executed_in_d41": False,
        }
    p14 = data["cases"]["p14"]
    first = p14["trials"][p14["first_accepted_action_ordinal"] - 1]
    p40 = data["same_family_p40_separate_offline"]
    need(p14["first_accepted_action_ordinal"] == 21 and p14["accepted_actions"] == ["Induction:grind_pow"]
         and first["method"] == "Induction:grind_pow" and p40["exit_code"] == 0 and p40["matches_archived_axioms"]
         and not p40["reference_used_for_baseline_generation"], "Passing original-scope contrast differs")
    negatives = json.loads(inherited("cases_archive_failure_runtime.json", freeze["source_receipts_sha256"]["exact_negative_replays"]))
    return {
        "known_original_scope_negatives": {case_id: negatives["cases"][case_id] for case_id in ("p14", "p41")},
        "prior_signature_negatives": freeze["prior_scope_negatives"],
        "historical_candidates_deferred": deferred,
        "contrasting_passing_p14": {"target": p14["target"], "original_imports": p14["original_imports"],
                                   "target_header_sha256": p14["target_header_sha256"], "first_accept_ordinal": 21,
                                   "method": first["method"], "proof_body_sha256": first["proof_body_sha256"],
                                   "source_sha256": first["source_sha256"], "axioms": first["axioms"]},
        "same_family_p40_offline_positive": {"source_sha256": p40["source_sha256"], "exit_code": p40["exit_code"],
                                             "axioms": p40["axioms"], "used_as_candidate_input": False},
    }


def save(path, packet):
    raw = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def run(out, controls, evidence_path):
    freeze_raw = (ROOT / "D41_SCOPE_INPUT_FREEZE.json").read_bytes()
    freeze = json.loads(freeze_raw)
    need(freeze["baseline"] == BASELINE and freeze["status"] == "FROZEN_BEFORE_NEW_SCOPE_PROBES", "Wrong scope freeze")
    runtime_raw = inherited("baseline_runtime_approved.json", freeze["source_receipts_sha256"]["runtime"])
    source_raw = inherited("cases_source_receipt.json")
    source = json.loads(source_raw)
    imports = {k: tuple(source["source_cases"][k]["exact_imports"]) for k in ("p14", "p41")}
    need(all(list(imports[k]) == freeze["prior_scope_negatives"][k]["original_imports"] for k in imports),
         "Original imports disagree")
    old = historical(freeze, runtime_raw, source_raw)
    entries = []
    out.mkdir(parents=True, exist_ok=False)
    for row in authored():
        name = f"{row['id']}.lean"
        rendered = materialize(row, imports[row["original_import_scope"]])
        need(not re.search(r"(?m)^\s*(?:#(?:eval|reduce)|run_cmd|macro|elab|axiom|unsafe)\b|\bsorry(?:_using)?\b", rendered),
             "Unreviewed command in authored fixture")
        with (out / name).open("xb") as stream:
            stream.write(rendered.encode())
        entries.append({**row, "filename": name, "exact_imports": list(imports[row["original_import_scope"]]),
                        "fixture_sha256": digest(rendered), "fixture_bytes": len(rendered.encode()),
                        "complete_source": rendered})
    control_data = {"status": "FROZEN_AUTHORED_SCOPE_CONTROLS_BEFORE_EXECUTION", "source_scope_freeze_sha256": digest(freeze_raw),
                    "scope": "Trusted authored controls, independent of archived attempts. Positive and negative labels are preregistered expectations.",
                    "cases": entries, "executed_by_preparation": False, "model_generation": False}
    control_sha = save(controls, control_data)
    e = {"status": "PUBLISHED_ARCHIVE_CONTRASTS_BOUND", "source_scope_freeze_sha256": digest(freeze_raw),
         "controls_sha256": control_sha, "scope": "Historical evidence only. No archived source is executed or staged.",
         **old}
    print(json.dumps({"authored": len(entries), "controls_sha256": control_sha, "historical_sha256": save(evidence_path, e)}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--controls", type=Path, default=ROOT / "scope_cases_controls.json")
    cli.add_argument("--evidence", type=Path, default=ROOT / "scope_cases_evidence.json")
    a = cli.parse_args()
    run(a.output_dir.resolve(), a.controls, a.evidence)
