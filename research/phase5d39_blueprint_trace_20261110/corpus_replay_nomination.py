"""Bind author-proved prereqs to visible non-stub declarations before nominating replay cases."""

from collections import Counter, defaultdict
import json
import re

from corpus_recount import (ROOT, LEAN_BLOCK, archive_for, bundles, declaration_sources, digest, need, write_once)


DECL = re.compile(r"(?m)^\s*(?:private\s+)?(?:theorem|lemma)\s+([^\s:({]+)")
STUB = re.compile(r"\b(?:sorry(?:_using)?|admit)\b")
COMMENT = re.compile(r"--[^\n]*|/\-.*?\-/", re.S)
TOKEN = re.compile(r"[^\W\d]\w*|[0-9]+|\S")


def suffix(label):
    return label.rsplit(":", 1)[-1]


def normalize(text):
    return tuple(TOKEN.findall(COMMENT.sub("", text)))


def definitions(text):
    result = {}
    for label, span in declaration_sources(text).items():
        found = DECL.search(span)
        if found is None:
            continue
        key = suffix(label)
        if key in result:
            result[key] = None
            continue
        statement, sep, body = span[found.start():].strip().partition(":=")
        if sep:
            result[key] = {"label": label, "name": found[1], "statement": statement.strip(), "proof": body.strip(),
                           "stub": bool(STUB.search(body)), "boundary_trimmed_span_sha256": digest(span.encode())}
    return result


def current_module(messages, graph_index):
    for index in range(len(messages) - 1, graph_index - 1, -1):
        message = messages[index]
        text = message.get("content")
        if (message["role"] == "user" and isinstance(text, str)
                and text.startswith(("Failed blueprint state", "Verifier feedback", "Current module source:"))):
            sources = LEAN_BLOCK.findall(text)
            if len(sources) == 1:
                return index, sources[0]
    return None, None


def proof_change(old, new):
    if new is None or new["stub"] or old["name"] != new["name"]:
        return "UNKNOWN_DECLARATION_BINDING"
    if normalize(old["statement"]) != normalize(new["statement"]):
        return "TYPE_SOURCE_CHANGED"
    if normalize(old["proof"]) != normalize(new["proof"]):
        return "PROOF_SOURCE_CHANGED"
    return "THEOREM_AND_PROOF_SOURCE_RETAINED"


def model_refs(row, step):
    return {"model": row["model"], "run_id": row["run_id"], "step": step["step"],
            "step_member": step["archive_member"], "step_sha256": step["sha256"]}


def observed_sources(inventory, freeze):
    all_episodes = inventory["episodes"]
    earlier, endpoints, reasons, rejected_stubs = defaultdict(list), defaultdict(list), Counter(), defaultdict(Counter)
    provenance = freeze["source"]
    base = f"https://huggingface.co/datasets/{provenance['dataset']}/resolve/{provenance['revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{provenance['artifact_commit']}/"
    for archive in provenance["archives"]:
        source = bundles(archive_for(archive, base, github))
        for episode in (row for row in all_episodes if row["model"] == archive["model"]):
            state = episode["state_id"]
            folder = episode["episode_member"].rsplit("/", 1)[0]
            files = source[folder]
            terminal = episode["endpoint"].get("author_rescan", {})
            if episode["author_rescan_pass"] and terminal.get("archive_member_sha256"):
                raw = files[terminal["archive_member"].rsplit("/", 1)[-1]]
                need(digest(raw) == terminal["archive_member_sha256"], "Author-rescanned module member differs")
                endpoints[state].append({"model": episode["model"], "run_id": episode["run_id"], "mode": episode["mode"],
                                         "archive_sha256": archive["sha256"], "member": terminal["archive_member"],
                                         "source_sha256": digest(raw),
                                         "standalone_or_step_author_module_hash_matched": (
                                             terminal["archive_member_sha256"] == episode["endpoint"]["strict_source_sha256"]),
                                         "definitions": definitions(raw.decode())})
            for step in episode["steps"]:
                labels = step["proved_target_prerequisites"]
                if step["outcome"] != "ARCHIVED_LEAN_ERROR" or not labels:
                    continue
                raw = files[step["archive_member"].rsplit("/", 1)[-1]]
                need(digest(raw) == step["sha256"], "Failure step source changed")
                messages = json.loads(raw)["request"]["messages"]
                index, before = current_module(messages, step["prestate_prompt_index"])
                if before is None:
                    reasons["CURRENT_MODULE_SOURCE_UNAVAILABLE"] += 1
                    for label in labels:
                        rejected_stubs[state][suffix(label), "UNAVAILABLE"] += 1
                    continue
                parsed = definitions(before)
                proven = {}
                for label in labels:
                    key = suffix(label)
                    declaration = parsed.get(key)
                    if declaration is None:
                        rejected_stubs[state][key, "DECLARATION_UNRESOLVED"] += 1
                    elif declaration["stub"]:
                        rejected_stubs[state][key, "VISIBLE_STUB"] += 1
                    else:
                        proven[key] = declaration
                if not proven:
                    reasons["ONLY_STUB_OR_UNRESOLVED_DECLARATIONS"] += 1
                    continue
                first_check = next((check for check in step["author_elaborations"] if check["exit_code"] not in (None, 0)
                                    and not check["timed_out"] and check["error_count"]), None)
                need(first_check is not None, "Missing linked Lean error for nomination")
                raw_check = files[first_check["member"].rsplit("/", 1)[-1]]
                need(digest(raw_check) == first_check["sha256"], "Lean diagnostic member changed")
                notes = [{"line": row.get("line"), "message": row.get("message")}
                         for row in json.loads(raw_check)["diagnostics"] if row.get("severity") == "error"]
                earlier[state].append({**model_refs(episode, step), "archive_sha256": archive["sha256"],
                                       "prestate_message_index": index, "prestate_source_sha256": digest(before.encode()),
                                       "author_check_member": first_check["member"], "author_check_sha256": first_check["sha256"],
                                       "archived_errors": notes[:2], "definitions": proven})
    return earlier, endpoints, reasons, rejected_stubs


def compare_state(earlier, endpoints):
    preserved, changed = [], []
    for before in earlier:
        for after in endpoints:
            outcomes = [(key, proof_change(prior, after["definitions"].get(key))) for key, prior in before["definitions"].items()]
            if all(outcome == "THEOREM_AND_PROOF_SOURCE_RETAINED" for _, outcome in outcomes):
                preserved.append({"failure_run": before["run_id"], "failure_step": before["step"], "accepted_run": after["run_id"],
                                  "prior_labels_retained": sorted(before["definitions"])})
            edits = [{"binding_key": key, "kind": outcome, "before": before["definitions"][key], "after": after["definitions"][key]}
                     for key, outcome in outcomes if outcome.endswith("_SOURCE_CHANGED")]
            if edits:
                changed.append({"failure": {k: v for k, v in before.items() if k != "definitions"},
                                "success": {k: v for k, v in after.items() if k != "definitions"}, "changed": edits})
    return preserved, changed


def run():
    inventory_raw = (ROOT / "corpus_inventory.json").read_bytes()
    freeze = json.loads((ROOT / "corpus_freeze.json").read_bytes())
    inventory = json.loads(inventory_raw)
    gate_sha = digest((ROOT / "D39_REPLAY_GATE.json").read_bytes())
    failures, accepted, reasons, rejected = observed_sources(inventory, freeze)
    state_ids = {row["state_id"]: row["target_id"] for row in inventory["episodes"]}
    author_scope_states = {row["state_id"] for row in inventory["episodes"] for step in row["steps"]
                           if step["outcome"] == "ARCHIVED_LEAN_ERROR" and step["proved_target_prerequisites"]}
    nominations, preservation, unknown = [], [], []
    for state in sorted(author_scope_states, key=lambda key: (state_ids[key], key)):
        identity = {"target_id": state_ids[state], "state_id": state, "visible_nonstub_failed_attempts": len(failures[state]),
                    "author_rescan_endpoints": len(accepted[state])}
        retained, changes = compare_state(failures[state], accepted[state])
        if retained:
            preservation.append({**identity, "preserved_pair_count": len(retained), "example": retained[0]})
        elif changes:
            nominations.append({**identity, "changed_pair_count": len(changes), "example": changes[0],
                                "need_to_release": "UNKNOWN_BEFORE_LOCAL_EQUAL_SCOPE_TEST"})
        else:
            why = ("NO_VISIBLE_NONSTUB_FAILURE_PREREQUISITE" if not failures[state] else
                   "NO_ACCEPTED_ENDPOINT_SOURCE" if not accepted[state] else "NO_COMPARABLE_NONSTUB_TYPE_OR_PROOF_CHANGE")
            unknown.append({**identity, "reason": why})
    return {"status": "ARCHIVE_NOMINATIONS_ONLY", "gate_sha256": gate_sha, "corpus_inventory_sha256": digest(inventory_raw),
            "scope": "Post-corpus source/proof screen, not Lean execution. Compare same original state. A prefixed label is matched only by unique suffix plus exact Lean declaration name. Ignore whitespace and simple comments when comparing declaration tokens. Keep true type or proof source changes separate from annotation changes and stub filling. Any observed preserved-prerequisite success excludes that state from nomination. No edit is assigned necessity.",
            "author_scope_failure_states": len(author_scope_states),
            "visible_nonstub_failure_attempts": sum(len(rows) for rows in failures.values()),
            "missing_failure_source_attempts": dict(reasons), "preserved_success_counterexamples": preservation,
            "unresolved_states": unknown, "nominations_in_lexical_target_order": nominations,
            "static_review_first_two": [{"target_id": row["target_id"], "state_id": row["state_id"]} for row in nominations[:2]],
            "p149_p151_changed_binding_source_controls": {
                state: {status: count for (key, status), count in rejected[state].items() if key == label}
                for state, label in (("p149_bad.state0", "p149bad-window"), ("p151_bad.state0", "p151bad-final-mod"))},
            "positive_minimum_release_certificates": 0}


if __name__ == "__main__":
    result = run()
    write_once(ROOT / "corpus_replay_nomination.json", result)
    print(json.dumps({"preserved_counterexamples": len(result["preserved_success_counterexamples"]),
                      "unresolved_states": len(result["unresolved_states"]),
                      "nominations": result["static_review_first_two"],
                      "all_nominations": [row["target_id"] for row in result["nominations_in_lexical_target_order"]]}, indent=2))
