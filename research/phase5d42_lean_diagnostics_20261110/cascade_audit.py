"""Recount archival diagnostic order and bind the three preselected source cases."""

from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
D41 = ROOT.parent / "phase5d41_lean_scope_20261110"
sys.path.extend([str(D39), str(D40)])
from corpus_recount import archive_for, bundles, digest, need, write_once
from support_recount import lex


FIRST_TYPES = {"TYPE_APPLICATION_OR_CALC", "TACTIC_PROOF_STEP_FAILURE"}
ADMISSIONS = {"sorry", "sorry_using", "admit"}


def ledger_checks(ledger, groups):
    for line in ledger.splitlines():
        episode = json.loads(line)
        group = groups[episode["state_id"]]
        for attempt in episode["attempts"]:
            for check in attempt["invocations"]:
                if check["stage"] == "check":
                    errors = [row for row in check["diagnostics"] if row["severity"] == "error"]
                    yield group, episode, attempt, check, errors


def update_counts(counts, errors, same_imports):
    counts["checks"] += 1
    if not errors:
        return
    counts["checks_with_error"] += 1
    if len(errors) == 1:
        return
    need(all(row["source_line_bound"] for row in errors), "Source position unavailable")
    lines = [row["line"] for row in errors]
    counts["multi_error_checks"] += 1
    counts["first_report_line_not_earliest"] += lines[0] > min(lines)
    counts["report_lines_not_nondecreasing"] += lines != sorted(lines)
    counts["multi_error_same_line_only"] += len(set(lines)) == 1
    if not same_imports:
        return
    counts["same_import_multi_error_checks"] += 1
    counts["same_import_multi_error_first_type_or_tactic"] += errors[0]["category"] in FIRST_TYPES


def verify_anchor(frozen, episode, attempt, check, errors):
    expected = {
        **{key: episode[key] for key in ("state_id", "target_id", "model", "mode")},
        "attempt_sha256": attempt["sha256"], "source_member": check["source_member"],
        "source_sha256": check["source_sha256"], "compiler_log_sha256": check["sha256"],
        "import_list_comparison": check["import_list_comparison"],
        "first_reported_error_category": errors[0]["category"],
        "first_reported_error_line": errors[0]["line"],
        "ordered_error_categories": [row["category"] for row in errors],
    }
    need(frozen == expected, f"Changed ledger anchor for {check['source_member']}")


def archive_member(files, member, expected):
    folder, leaf = member.rsplit("/", 1)
    raw = files[folder][leaf]
    need(digest(raw) == expected, f"Archive member bytes changed: {member}")
    return raw


def verify_raw(episode, attempt, check, errors, files):
    archive_member(files, episode["episode_member"], episode["episode_sha256"])
    archive_member(files, attempt["archive_member"], attempt["sha256"])
    source = archive_member(files, check["source_member"], check["source_sha256"])
    log = json.loads(archive_member(files, check["member"], check["sha256"]))
    raw_errors = [row for row in log["diagnostics"] if row["severity"] == "error"]
    need(len(raw_errors) == len(errors), "Changed author error count")
    lines = source.split(b"\n")
    for archive_error, ledger_error in zip(raw_errors, errors):
        line = archive_error["line"]
        need(1 <= line <= len(lines), "Author source coordinate outside file")
        observed = (line, archive_error["col"], digest(archive_error["message"].encode()), digest(lines[line - 1]))
        recorded = (ledger_error["line"], ledger_error["raw_column"], ledger_error["message_sha256"],
                    ledger_error["source_line_sha256"])
        need(observed == recorded, "Changed author diagnostic order or source-line binding")
    return source.decode()


def selected_row(pick, frozen, episode, attempt, check, errors, source):
    need(pick["state_id"] == episode["state_id"] and pick["source_sha256"] == check["source_sha256"],
         "Selected source differs from freeze")
    source_line = source.split("\n")[pick["reported_line"] - 1]
    need(pick["reported_line"] == errors[0]["line"] and pick["original_expression"] in source_line,
         "Selected expression not on original first diagnostic line")
    need(not any(token in ADMISSIONS for token, _, _, is_string in lex(source) if not is_string),
         "Selected source contains a lexical admission")
    return {
        **frozen, "attempt_member": attempt["archive_member"], "check_member": check["member"],
        "checked_imports": check["checked_imports"], "original_visible_imports": episode["original_visible_imports"],
        "first_reported_source_line": source_line, "lexical_admission_detected": False,
        "contrast": pick["contrast"], "review_hypothesis": pick["review_hypothesis"],
        "ordered_errors": errors,
    }


def run():
    freeze_raw = (ROOT / "D42_ERROR_ORDER_FREEZE.json").read_bytes()
    freeze = json.loads(freeze_raw)
    selection_raw = (ROOT / "cascade_selection_freeze.json").read_bytes()
    selection = json.loads(selection_raw)
    need(digest(freeze_raw) == selection["d42_input_freeze_sha256"], "Changed D42 input freeze")
    ledger = (D41 / "diagnostic_ledger.jsonl").read_bytes()
    need(digest(ledger) == freeze["ledger_sha256"] == selection["d41_ledger_sha256"], "Changed D41 ledger")
    d41 = json.loads((D41 / "D41_SCOPE_INPUT_FREEZE.json").read_bytes())
    groups = {state: group for group in ("unresolved", "solved_controls") for state in
              d41["unresolved_state_ids" if group == "unresolved" else "same_family_solved_state_ids"]}
    need(Counter(groups.values()) == freeze["cohort_counts"], "Changed cohort denominator")

    frozen_rows = freeze["anchored_multi_error_candidates"]
    frozen = {row["source_member"]: row for row in frozen_rows}
    picks = {row["source_member"]: row for row in selection["fixed_cases"]}
    need(len(frozen) == len(frozen_rows) and len(picks) == len(selection["fixed_cases"]) == 3,
         "Duplicated member in frozen input")
    need(len({row["state_id"] for row in picks.values()}) == len(picks), "Duplicated primary target")
    counts = {group: Counter() for group in freeze["cohort_counts"]}
    totals = Counter()
    matched = {}
    for group, episode, attempt, check, errors in ledger_checks(ledger, groups):
        same = check["import_list_comparison"] == "SAME_IMPORT_LIST"
        update_counts(counts[group], errors, same)
        totals.update(row["category"] for row in errors)
        if group != "unresolved" or not same or len(errors) < 2 or errors[0]["category"] not in FIRST_TYPES:
            continue
        member = check["source_member"]
        need(member not in matched and member in frozen, f"Unexpected cohort candidate {member}")
        verify_anchor(frozen[member], episode, attempt, check, errors)
        matched[member] = episode, attempt, check, errors
    need(set(matched) == set(frozen), "Incomplete reproduction of frozen candidates")
    need({key: totals[key] for key in FIRST_TYPES} == freeze["diagnostic_message_counts"], "Changed message denominators")

    pinned = json.loads((D39 / "corpus_freeze.json").read_bytes())["source"]
    base = f"https://huggingface.co/datasets/{pinned['dataset']}/resolve/{pinned['revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{pinned['artifact_commit']}/"
    raw_verified = set()
    selected = {}
    for archive in pinned["archives"]:
        files = bundles(archive_for(archive, base, github))
        for member, (episode, attempt, check, errors) in matched.items():
            if episode["model"] != archive["model"]:
                continue
            source = verify_raw(episode, attempt, check, errors, files)
            raw_verified.add(member)
            if member in picks:
                selected[member] = selected_row(picks[member], frozen[member], episode, attempt, check, errors, source)
    need(raw_verified == set(frozen) and set(selected) == set(picks), "Incomplete raw archive source verification")

    result = {
        "status": "REPRODUCED_ARCHIVED_DIAGNOSTIC_ORDER_ONLY",
        "input_freeze_sha256": digest(freeze_raw), "selection_freeze_sha256": digest(selection_raw),
        "ledger_sha256": digest(ledger), "raw_verified_frozen_candidates": len(raw_verified),
        "independent_frozen_target_count": len({row["target_id"] for row in frozen.values()}),
        "frozen_invocations_by_state": dict(sorted(Counter(row["state_id"] for row in frozen.values()).items())),
        "cohort_check_counts": {group: dict(sorted(counter.items())) for group, counter in counts.items()},
        "selected_primary_cases": [selected[member] for member in picks],
        "prior_control": selection["separate_prior_control"],
        "interpretation": "Author array order and lexical source line differ. Neither determines causal error dependency. "
                          "The three nominated archived modules were not executed or modified by this audit.",
    }
    output_sha = write_once(ROOT / "cascade_audit.json", result)
    print(f"cascade_audit_sha256={output_sha}")


if __name__ == "__main__":
    run()
