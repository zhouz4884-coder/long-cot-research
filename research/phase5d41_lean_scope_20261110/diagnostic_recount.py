"""Bind author compiler messages to the frozen D4.1 source population."""

from bisect import bisect_right
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
sys.path.extend([str(D39), str(D40)])
from corpus_recount import archive_for, bundles, digest, need, write_once
from support_recount import initial_source, lex


IMPORT = re.compile(r"^[ \t]*(?:(?:public|meta)\s+)?import\s+([\w.']+)")
NAMESPACE = re.compile(r"^namespace\s+([\w.']+)")
DECLARATION = re.compile(
    r"^(?:(?:private|protected|noncomputable|local)\s+)*(?:theorem|lemma|def|abbrev|instance)\s+([\w.']+)"
)
SCOPE_STOP = re.compile(r"^@\[|^#|^end\b|^section\b|^namespace\b|^open\b|^import\b")
NAME = re.compile(r"^unknown (constant|identifier|namespace)\s+(?:`([^`]+)`|'([^']+)'|([^\s]+))", re.I)
FIELD = re.compile(r"^invalid field `([^`]+)`", re.I)
BINDER = re.compile(r"[\(\{\[]\s*((?:[\w'₀-₉]+\s+)*[\w'₀-₉]+)\s*:")
LOCAL = re.compile(r"\b(?:have|let|suffices)\s+([\w'₀-₉]+)\s*(?::|:=)")
INTRO = re.compile(r"^\s*(?:[·|]\s*)?intros?\s+([\w'₀-₉]+(?:\s+[\w'₀-₉]+)*)\s*$")


def lexical_lines(source):
    # Preserve character offsets and newlines while excluding comments and strings.
    result = [char if char.isspace() else " " for char in source]
    for _, start, stop, string in lex(source):
        if not string:
            result[start:stop] = source[start:stop]
    return "".join(result).split("\n")


def imports(lines):
    return [match[1] for line in lines if (match := IMPORT.match(line))]


def filename(path):
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def has_token(line, token):
    return re.search(r"(?<![\w'.])" + re.escape(token) + r"(?![\w'.])", line) is not None


def source_scope(lines):
    events, owners = [], []
    names, namespaces = set(), set()
    for number, line in enumerate(lines, 1):
        if match := DECLARATION.match(line):
            name = match[1]
            names.add(name)
            events.append(number)
            owners.append({"name": name, "line": number})
        elif SCOPE_STOP.match(line):
            events.append(number)
            owners.append(None)
        if match := NAMESPACE.match(line):
            namespaces.add(match[1])
    return events, owners, names, namespaces


def local_name_evidence(name, line_number, lexical, owner, declarations, namespaces):
    if name in declarations:
        return "VISIBLE_MODULE_DECLARATION_NAME"
    if "." in name and any(name.startswith(namespace + ".") for namespace in namespaces):
        return "VISIBLE_PROJECT_NAMESPACE_PREFIX"
    if owner is None or "." in name:
        return None
    span = lexical[owner["line"] - 1:line_number]
    head = "\n".join(span).split(":=", 1)[0]
    if any(name in match[1].split() for match in BINDER.finditer(head)):
        return "LEXICAL_DECLARATION_BINDER"
    for line in span:
        if any(name == match[1] for match in LOCAL.finditer(line)):
            return "LEXICAL_HAVE_LET_OR_SUFFICES_LABEL"
        if (match := INTRO.fullmatch(line)) and name in match[1].split():
            return "LEXICAL_INTRO_LABEL"
    return None


def non_name_category(headline):
    line = headline.lower()
    if line.startswith("unknown tactic"):
        return "UNKNOWN_TACTIC_SYNTAX_OR_IMPORT"
    if FIELD.match(headline):
        return "INVALID_FIELD_PROJECTION"
    if line.startswith(("maximum recursion", "maximum heartbeats", "deterministic timeout", "interrupted")):
        return "RESOURCE_OR_INTERRUPT"
    if line.startswith(("unexpected token", "unexpected identifier", "expected token", "invalid syntax",
                        "unterminated", "numerals are", "unknown parser", "elaboration function")):
        return "SYNTAX_NOTATION_OR_PARSER"
    if line.startswith(("failed to synthesize", "typeclass instance", "cannot synthesize")):
        return "INSTANCE_SYNTHESIS"
    if "implicit argument" in line or line.startswith(("failed to infer", "don't know how to synthesize")):
        return "IMPLICIT_OR_TYPE_INFERENCE"
    if line.startswith(("type mismatch", "application type", "function expected", "type expected",
                        "invalid 'calc'", "'calc' expression", "invalid argument")):
        return "TYPE_APPLICATION_OR_CALC"
    if line.startswith(("unsolved goals", "missing cases", "no goals", "case tag")):
        return "GOALS_OR_CASES"
    if line.startswith(("omega could", "linarith failed", "nlinarith failed", "tactic `", "`simp` made",
                        "invalid rewrite", "simp made", "rewrite failed")):
        return "TACTIC_PROOF_STEP_FAILURE"
    if line.startswith(("unknown module", "unknown package", "object file")):
        return "IMPORT_OR_MODULE_FAILURE"
    return "OTHER_ERROR"


def diagnostic_row(diag, lexical, raw_lines, scope, paired_leaf, whitelist):
    number = diag.get("line")
    line_bound = filename(diag.get("file")) == paired_leaf and type(number) is int and 1 <= number <= len(lexical)
    raw = raw_lines[number - 1] if line_bound else None
    events, owners, declarations, namespaces = scope
    index = bisect_right(events, number) - 1 if line_bound else -1
    owner = owners[index] if index >= 0 else None
    message = diag["message"]
    headline = message.partition("\n")[0]
    severity = diag["severity"]
    result = {
        "severity": severity, "line": number, "raw_column": diag.get("col"), "source_line_bound": line_bound,
        "lexical_owner": owner, "source_line_sha256": digest(raw.encode()) if raw is not None else None,
        "headline": headline[:240], "message_sha256": digest(message.encode()),
    }
    if diag.get("code"):
        result["author_code"] = diag["code"]
    if severity != "error":
        result["category"] = "SORRY_WARNING" if diag.get("is_sorry_warning") else "OTHER_NONERROR"
        return result
    missing = NAME.match(headline)
    if missing is None:
        result["category"] = non_name_category(headline)
        return result
    kind = missing[1].lower()
    name = next(value for value in missing.groups()[1:] if value is not None)
    token_bound = line_bound and has_token(lexical[number - 1], name)
    result.update({"name": name, "unknown_kind": kind, "name_token_bound": token_bound})
    if not token_bound:
        category = "MISSING_NAME_NO_EXACT_LINE_TOKEN"
    elif kind == "namespace":
        category = "UNKNOWN_NAMESPACE_NAME"
    elif evidence := local_name_evidence(name, number, lexical, owner, declarations, namespaces):
        result["local_lexical_evidence"] = evidence
        category = "PROJECT_OR_LOCAL_SHAPED_NAME"
    elif "." in name and name.partition(".")[0] in whitelist:
        category = "QUALIFIED_LIBRARY_SHAPED_NAME"
    elif "." in name:
        category = "OTHER_QUALIFIED_NAME_ORIGIN_UNKNOWN"
    else:
        category = "UNQUALIFIED_NAME_ORIGIN_UNKNOWN"
    result["category"] = category
    return result


def pinned(path, expected):
    raw = path.read_bytes()
    need(digest(raw) == expected, f"Pinned input changed: {path.name}")
    return json.loads(raw)


def invocation(check, files, pins, original_imports, known_names, whitelist):
    member = check["member"]
    leaf = filename(member)
    raw_log = files[leaf]
    need(digest(raw_log) == check["sha256"], f"Changed compiler log: {member}")
    log = json.loads(raw_log)
    need(log["pins"] == pins, f"Changed Lean toolchain: {member}")
    need(all(log[key] == check[key] for key in ("exit_code", "timed_out")), f"Changed run status: {member}")
    need(sum(row["severity"] == "error" for row in log["diagnostics"]) == check["error_count"], f"Changed error count: {member}")
    stage = leaf.partition(".")[2].removesuffix(".elab.json")
    need(stage in {"check", "gate", "assembled", "assembled.gate"}, f"Unknown invocation stage: {member}")
    source_leaf = leaf.removesuffix(".elab.json") + ".lean"
    raw_source = files.get(source_leaf)
    command_match = bool(log["command"]) and filename(log["command"][-1]) == source_leaf
    source = raw_source.decode() if raw_source is not None and command_match else None
    lexical = lexical_lines(source) if source is not None else []
    raw_lines = source.split("\n") if source is not None else []
    current_imports = imports(lexical) if source is not None else None
    import_scope = ("UNKNOWN" if original_imports is None or current_imports is None else
                    "SAME_IMPORT_LIST" if original_imports == current_imports else "CHANGED_IMPORT_LIST")
    scope = source_scope(lexical)
    diagnostics = [
        diagnostic_row(row, lexical, raw_lines, scope, source_leaf, whitelist) for row in log["diagnostics"]
    ]
    for row in diagnostics:
        if row.get("name_token_bound") and row["name"] in known_names.get("names_rejected_in_original_imports", []):
            row["prior_original_import_probe"] = {
                "sha256": known_names["availability_probe_sha256"],
                "probe_imports_match_checked": current_imports == known_names["original_imports"],
            }
    return {
        "stage": stage, **check, "source_member": member.removesuffix(".elab.json") + ".lean" if raw_source is not None else None,
        "source_sha256": digest(raw_source) if raw_source is not None else None, "author_command_source_match": command_match,
        "checked_imports": current_imports, "import_list_comparison": import_scope, "diagnostics": diagnostics,
    }


def episode(row, files, pins, known_names, whitelist):
    need(digest(files["episode.json"]) == row["episode_sha256"], "Pinned episode bytes changed")
    original_source = None
    attempts = []
    for step in row["steps"]:
        raw = files[filename(step["archive_member"])]
        need(digest(raw) == step["sha256"], f"Changed provider attempt: {step['archive_member']}")
        if len(attempts) == 0:
            original_source = initial_source(json.loads(raw)["request"]["messages"])
            original_imports = imports(lexical_lines(original_source)) if original_source is not None else None
        attempts.append({
            "step": step["step"], "archive_member": step["archive_member"], "sha256": step["sha256"],
            "author_attempt_outcome": step["outcome"],
            "invocations": [invocation(check, files, pins, original_imports, known_names, whitelist)
                            for check in step["author_elaborations"]],
        })
    need(bool(attempts), "Frozen cohort episode has no observed provider attempt")
    return {
        **{key: row[key] for key in ("state_id", "target_id", "model", "mode", "episode_member",
                                    "episode_sha256", "author_verifier_calls")},
        "original_visible_source_sha256": digest(original_source.encode()) if original_source is not None else None,
        "original_visible_imports": original_imports, "attempts": attempts,
    }


def summary(rows):
    def records(stage=None):
        return ((ep, attempt, check) for ep in rows for attempt in ep["attempts"] for check in attempt["invocations"]
                if stage is None or check["stage"] == stage)

    targets = {ep["target_id"] for ep in rows}
    counters, affected, names = {}, {}, defaultdict(lambda: defaultdict(set))
    prior = []
    totals = Counter()
    scopes = Counter()
    for ep, attempt, check in records():
        stage = check["stage"]
        totals[stage] += 1
        scopes[check["import_list_comparison"]] += 1
        for row in check["diagnostics"]:
            for scope in (stage, "all"):
                counters.setdefault(scope, Counter())[row["category"]] += 1
                affected.setdefault(scope, defaultdict(set))[row["category"]].add(ep["target_id"])
            if row["severity"] != "error":
                continue
            category = row["category"]
            if row.get("name_token_bound"):
                names[category][row["name"]].add(ep["target_id"])
            if "prior_original_import_probe" in row:
                prior.append({
                    "state_id": ep["state_id"], "model": ep["model"], "mode": ep["mode"], "step": attempt["step"],
                    "stage": stage, "name": row["name"], "line": row["line"], "check_member": check["member"],
                    "check_sha256": check["sha256"], "source_sha256": check["source_sha256"],
                    "checked_imports": check["checked_imports"], **row["prior_original_import_probe"],
                })
    return {
        "states": len({ep["state_id"] for ep in rows}), "independent_targets": len(targets),
        "episodes": len(rows), "attempts": sum(len(ep["attempts"]) for ep in rows),
        "author_primary_verifier_calls": sum(ep["author_verifier_calls"] for ep in rows),
        "episodes_with_original_visible_source": sum(ep["original_visible_imports"] is not None for ep in rows),
        "invocations_by_stage": dict(sorted(totals.items())),
        "invocations_without_bound_source": sum(not check["source_sha256"] or not check["author_command_source_match"]
                                                for _, _, check in records()),
        "invocations_by_import_list_comparison": dict(sorted(scopes.items())),
        "messages_without_bound_source_line": sum(not row["source_line_bound"] for _, _, check in records()
                                                  for row in check["diagnostics"]),
        "messages_by_stage_and_category": {stage: dict(sorted(counts.items())) for stage, counts in sorted(counters.items())},
        "affected_targets_by_stage_and_category": {
            stage: {name: len(ids) for name, ids in sorted(categories.items())}
            for stage, categories in sorted(affected.items())
        },
        "source_bound_names_by_category_and_target": {
            category: {name: sorted(ids) for name, ids in sorted(entries.items())}
            for category, entries in sorted(names.items())
        },
        "earlier_original_import_probe_links": prior,
    }


def run():
    freeze_raw = (ROOT / "diagnostic_freeze.json").read_bytes()
    freeze = json.loads(freeze_raw)
    cohort = pinned(ROOT / "D41_SCOPE_INPUT_FREEZE.json", freeze["source"]["d41_cohort_sha256"])
    inventory = pinned(D39 / "corpus_inventory.json", freeze["source"]["d39_inventory_sha256"])
    source = json.loads((D39 / "corpus_freeze.json").read_bytes())["source"]
    need([item["sha256"] for item in source["archives"]] == freeze["source"]["d39_archive_shas"], "Archive pins changed")
    base = f"https://huggingface.co/datasets/{source['dataset']}/resolve/{source['revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{source['artifact_commit']}/"
    cohorts = {
        "unresolved": set(cohort["unresolved_state_ids"]),
        "same_family_solved": set(cohort["same_family_solved_state_ids"]),
    }
    need(not cohorts["unresolved"] & cohorts["same_family_solved"], "Frozen cohort overlaps")
    selected = cohorts["unresolved"] | cohorts["same_family_solved"]
    rows = []
    for archive in source["archives"]:
        grouped = bundles(archive_for(archive, base, github))
        for row in inventory["episodes"]:
            state = row["state_id"]
            if state not in selected or row["model"] != archive["model"]:
                continue
            folder = row["episode_member"].rsplit("/", 1)[0]
            known_names = cohort["prior_scope_negatives"].get(state.split("_", 1)[0], {})
            rows.append(episode(row, grouped[folder], inventory["author_lean_runtime_pins"],
                                known_names, set(freeze["qualified_prefixes"])))
    rows.sort(key=lambda row: (row["state_id"], row["model"], row["mode"]))
    expected = {(state, archive["model"], mode) for state in selected for archive in source["archives"]
                for mode in ("typed", "patch", "rewrite")}
    actual = {(row["state_id"], row["model"], row["mode"]) for row in rows}
    need(actual == expected and len(rows) == len(expected), "Frozen episode denominator changed")
    encoded = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
                      for row in rows).encode()
    ledger = ROOT / "diagnostic_ledger.jsonl"
    if ledger.exists():
        need(ledger.read_bytes() == encoded, "Recount differs from frozen ledger")
    else:
        with ledger.open("xb") as stream:
            stream.write(encoded)
    report = {
        "status": "ARCHIVED_DIAGNOSTIC_INVENTORY_ONLY", "diagnostic_freeze_sha256": digest(freeze_raw),
        "ledger_sha256": digest(encoded), "lean_runtime_pins": inventory["author_lean_runtime_pins"],
        "combined": summary(rows),
        "cohorts": {name: summary([row for row in rows if row["state_id"] in states]) for name, states in cohorts.items()},
    }
    report_sha = write_once(ROOT / "diagnostic_summary.json", report)
    print(f"diagnostic_ledger_sha256={report['ledger_sha256']} diagnostic_summary_sha256={report_sha}")


if __name__ == "__main__":
    run()
