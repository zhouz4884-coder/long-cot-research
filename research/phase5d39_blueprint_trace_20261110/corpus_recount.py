"""Recount the complete pinned BlueprintTrace corpus without executing Lean or model code."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import tarfile


ROOT = Path(__file__).resolve().parent
D38 = ROOT.parent / "phase5d38_proof_release_20261110"
sys.path.append(str(D38))
from blueprint_trace_intake import archive_for, current_graph, digest, need, read_url, support_nodes


MODE = {"typed": "tool", "patch": "patch", "rewrite": "rewrite"}
MEMBER = re.compile(r"episode\.json|final\.module\.lean|step\d+\.(?:json|[^/]+\.lean|[^/]+\.elab\.json)")
ANNOTATION = re.compile(r'(?m)^@\[blueprint\s+"([^"]+)"')
LEAN_BLOCK = re.compile(r"```lean\n(.*?)```", re.S)
SCAN = {
    "deepseek/deepseek-v4-flash": ("graph_consistency_v0.json", "equal_source_v2",
                                  "f662267996655c8bda52bc54a709f4d58523871d85cbd6805ccc8df653d95313"),
    "qwen/qwen3.6-flash": ("graph_consistency_qwen_v2_v0.json", "qwen_equal_source",
                           "e34a2ff5fad17fb36abf661184d03253bb507717d6656840612d8cbe7ea7b863"),
}


def read_scan(github, model):
    leaf, pool, expected = SCAN[model]
    url = github + "data/stats/" + leaf
    raw = read_url(url, 4 * 1024 * 1024)
    need(digest(raw) == expected, "Author endpoint scan bytes differ")
    data = json.loads(raw)
    relevant = [row for row in data["rows"] if row["pool"] == pool]
    rows = {row["tree"]: row for row in relevant}
    need(len(rows) == len(relevant) and all(row["verdicts"]["tier1_pass_closure"] for row in relevant),
         "Author endpoint scans do not have unique tier-1 accepted trees")
    return rows, {row["tree"]: row["failure"] for row in data["enumeration_findings"]}, {"url": url, "sha256": expected}


def bundles(path):
    """Stream relevant files once, leaving the author tar members unmodified."""
    grouped = defaultdict(dict)
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            folder, _, leaf = member.name.rpartition("/")
            if (not member.isfile() or not folder.startswith("data/llm_calls/") or not folder.endswith("/typed")
                    or "/._" in member.name or MEMBER.fullmatch(leaf) is None):
                continue
            need(member.size <= 12 * 1024 * 1024 and leaf not in grouped[folder], "Unsafe or ambiguous episode member")
            with archive.extractfile(member) as stream:
                grouped[folder][leaf] = stream.read()
    return grouped


def prestate(messages):
    try:
        target, graph, index = current_graph(messages)
        support = support_nodes(target, graph)
        labels = [node["node_id"] for node in support["proved_prerequisites"]]
        return support["status"], labels, index, digest(messages[index]["content"].encode())
    except (KeyError, TypeError, ValueError):
        return "ARCHIVED_CONTEXT_UNRESOLVED", [], None, None


def normalize_step(files, folder, episode, record, pins):
    n = record["step"]
    stem = f"step{n:02d}"
    raw = files[stem + ".json"]
    step = json.loads(raw)
    meta, action = step["meta"], step["tool_execution"]
    need((meta["run_id"], meta["state_id"], meta["step"], meta["model"], meta["protocol"]) == (
        episode["run_id"], episode["state_id"], n, episode["model"], episode["protocol"]), "Episode step belongs to another run")
    need(all(action.get(k) == record.get(k) for k in ("applied", "solved", "tool", "module_sha256")),
         "Published episode summary does not match its provider step")
    messages = step["request"]["messages"]
    pre, labels, index, before_sha = prestate(messages)
    choices = step.get("response", {}).get("choices", [])
    authored = any(choice.get("message", {}).get("content") or choice.get("message", {}).get("tool_calls") for choice in choices)
    elaborations = []
    for name in sorted(name for name in files if name.startswith(stem + ".") and name.endswith(".elab.json")):
        raw_check = files[name]
        check = json.loads(raw_check)
        need(check["pins"] == pins, "Archived Lean run uses a different author toolchain")
        error_count = sum(diag.get("severity") == "error" for diag in check["diagnostics"])
        elaborations.append({"member": f"{folder}/{name}", "sha256": digest(raw_check),
                             "exit_code": check["exit_code"], "timed_out": check["timed_out"], "error_count": error_count})
    if not authored:
        status = "NO_OBSERVED_MODEL_ACTION"
    elif action.get("solved") is True:
        status = "AUTHOR_LOOP_ACCEPTED_TARGET"
    elif any(row["exit_code"] not in (None, 0) and not row["timed_out"] and row["error_count"] for row in elaborations):
        status = "ARCHIVED_LEAN_ERROR"
    elif any(row["timed_out"] for row in elaborations):
        status = "ARCHIVED_TIMEOUT"
    elif action.get("applied") is False:
        status = "HARNESS_REJECTED"
    else:
        status = "APPLIED_BUT_UNSOLVED"
    edit = action.get("edit") or {}
    known_edit = {key: edit[key] for key in ("mode", "blocks_applied", "nodes_added", "nodes_deleted", "statements_changed",
                                             "proofs_changed", "edges_added", "edges_deleted") if key in edit}
    return {"step": n, "archive_member": f"{folder}/{stem}.json", "sha256": digest(raw), "outcome": status,
            "action": action.get("tool"), "applied": action.get("applied"), "recorded_edit": known_edit,
            "prestate_status": pre, "proved_target_prerequisites": labels, "prestate_prompt_index": index,
            "prestate_prompt_sha256": before_sha, "author_elaborations": elaborations}, messages


def declaration_sources(text):
    starts = list(ANNOTATION.finditer(text))
    labels = [match[1] for match in starts]
    if len(labels) != len(set(labels)):
        return {}
    return {m[1]: text[m.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
            for i, m in enumerate(starts)}


def preservation(initial, accepted, labels):
    if not labels:
        return {"status": "NO_IDENTIFIED_INITIAL_PROVED_PREREQUISITE", "rows": []}
    if initial is None or accepted is None:
        return {"status": "UNRESOLVED_SOURCE", "rows": []}
    old, new = declaration_sources(initial), declaration_sources(accepted)
    rows = []
    for label in labels:
        start = old.get(label)
        end = new.get(label)
        if start is None or not new:
            status = "UNRESOLVED_DECLARATION_SOURCE"
        elif end is None:
            status = "EXACT_LABEL_ABSENT"
        elif start == end:
            status = "EXACT_SOURCE_RETAINED"
        else:
            status = "SOURCE_SPAN_CHANGED"
        rows.append({"label": label, "status": status, "initial_span_sha256": digest(start.encode()) if start else None,
                     "endpoint_span_sha256": digest(end.encode()) if end else None})
    result = "ALL_IDENTIFIED_SOURCE_RETAINED" if all(row["status"] == "EXACT_SOURCE_RETAINED" for row in rows) else (
        "UNRESOLVED_SOURCE" if any(row["status"] == "UNRESOLVED_DECLARATION_SOURCE" for row in rows) else "SOURCE_CHANGED_OR_LABEL_ABSENT")
    return {"status": result, "rows": rows}


def actual_endpoint_support(scan, initial_target, prior_labels):
    if scan is None or initial_target is None:
        return {"status": "NO_AUTHOR_RESCAN", "used_prior_labels": []}
    nodes = {row["node"]: row for row in scan["nodes"]}
    roots = [row["node"] for row in nodes.values() if row["label"] == initial_target]
    if len(roots) != 1:
        return {"status": "TARGET_BINDING_UNRESOLVED", "used_prior_labels": []}
    root, = roots
    seen, pending = {root}, [root]
    while pending:
        node = nodes[pending.pop()]
        for source in node["actual_proof"] + node["actual_type"]:
            if source in nodes and source not in seen:
                pending.append(source)
                seen.add(source)
    used = sorted({nodes[key]["label"] for key in seen - {root}} & set(prior_labels))
    return {"status": "AUTHOR_COMPILED_PROOF_AND_TYPE_CLOSURE", "used_prior_labels": used}


def endpoint(files, folder, ep, initial_messages, labels, scan):
    result = {"strict_source_kind": None, "strict_source_sha256": None,
              "strict_preservation": {"status": "TARGET_NOT_ACCEPTED", "rows": []},
              "release_necessity": "UNKNOWN"}
    if ep["outcome"] != "solved":
        return result
    start = None
    first_target = None
    for message in initial_messages:
        text = message.get("content")
        if message.get("role") != "user" or not isinstance(text, str) or not text.startswith("Failed blueprint state"):
            continue
        blocks = LEAN_BLOCK.findall(text)
        start = blocks[0] if len(blocks) == 1 else None
        first_target = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]["target_node_id"]
        break
    strict = None
    accepted, = (step for step in ep["steps"] if step.get("solved") is True)
    if ep.get("final_module_sha256") is not None:
        final = files.get("final.module.lean")
        if final is not None and digest(final) == ep["final_module_sha256"]:
            strict, kind = final, "STANDALONE_FINAL_MATCHES_AUTHOR_SHA256"
        else:
            kind = "STANDALONE_FINAL_MISSING_OR_MISMATCHED"
    else:
        step_prefix = f"step{accepted['step']:02d}."
        matching = [raw for name, raw in files.items() if name.startswith(step_prefix) and name.endswith(".lean")
                    and digest(raw) == accepted.get("module_sha256")]
        if matching:
            strict, kind = matching[0], "STEP_SOURCE_MATCHES_AUTHOR_MODULE_SHA256"
        else:
            kind = "NO_VERBATIM_ACCEPTED_STEP_HASH_MATCH"
    comparison = preservation(start, strict.decode() if strict is not None else None, labels)
    result.update(strict_source_kind=kind, strict_source_sha256=digest(strict) if strict else None,
                  strict_preservation=comparison)
    if scan is not None:
        # Supplemental source comparison bound by the author's terminal-rescan record and the archive SHA.
        # This does not promote a step-only file to the stricter accepted-step digest identity above.
        source = scan["source"]
        leaf = source.rsplit("/", 1)[-1]
        rescanned = files.get(leaf) if source.rsplit("/", 1)[0] == folder else None
        result["author_rescan"] = {"archive_member": source, "archive_member_sha256": digest(rescanned) if rescanned else None,
                                   "preservation": preservation(start, rescanned.decode() if rescanned else None, labels),
                                   "actual_endpoint_support": actual_endpoint_support(scan, first_target, labels)}
        if (result["author_rescan"]["preservation"]["status"] == "ALL_IDENTIFIED_SOURCE_RETAINED"
                and result["author_rescan"]["actual_endpoint_support"]["status"] == "AUTHOR_COMPILED_PROOF_AND_TYPE_CLOSURE"
                and set(labels) == set(result["author_rescan"]["actual_endpoint_support"]["used_prior_labels"])):
            result["release_necessity"] = "OBSERVED_ALL_PRIOR_DECLARATIONS_RETAINED_AND_USED"
        elif result["author_rescan"]["preservation"]["status"] == "ALL_IDENTIFIED_SOURCE_RETAINED":
            result["release_necessity"] = "OBSERVED_PRIOR_DECLARATION_SOURCE_RETAINED_USE_MAY_DIFFER"
    return result


def inspect_archive(path, archive, states, freeze, github, pins):
    scans, findings, scan_pin = read_scan(github, archive["model"])
    grouped = bundles(path)
    rows, identities = [], set()
    for folder, files in grouped.items():
        raw = files["episode.json"]
        ep = json.loads(raw)
        mode = ep.get("mode", "typed")
        state, model, run = ep["state_id"], ep["model"], ep["run_id"]
        need(state in states and model == archive["model"] and mode in MODE and ep["protocol"] == "equal_source_v2"
             and folder.split("/")[-2] == run and (state, mode) not in identities, "Episode population identity mismatch")
        identities.add((state, mode))
        scan = scans.pop(run, None)
        need(scan is None or (ep["outcome"] == "solved" and scan["arm"] == MODE[mode]), "Author endpoint scan joins another mode")
        report_steps = []
        initial_messages = None
        for record in ep["steps"]:
            report, messages = normalize_step(files, folder, ep, record, pins)
            report_steps.append(report)
            if initial_messages is None:
                initial_messages = messages
        need(len(report_steps) == ep["llm_calls"] and [row["step"] for row in report_steps] == list(range(1, len(report_steps) + 1)),
             "Archive does not enumerate every paid step")
        labels = report_steps[0]["proved_target_prerequisites"] if report_steps else []
        outcome = endpoint(files, folder, ep, initial_messages or [], labels, scan)
        row = states[state]
        rows.append({"state_id": state, "target_id": row["seed_source"]["item_id"], "model": model, "mode": mode,
                     "prior_d38_sample": state in freeze["population"]["previous_d38_states"], "controlled_failure_family": row["error_family"],
                     "run_id": run, "episode_member": folder + "/episode.json", "episode_sha256": digest(raw),
                     "loop_time_outcome": ep["outcome"], "author_rescan_pass": scan is not None,
                     "rescan_unavailable_reason": findings.get(run) if ep["outcome"] == "solved" and scan is None else None,
                     "author_verifier_calls": ep["verifier_calls"], "endpoint": outcome, "steps": report_steps})
    expected = {(state, mode) for state in states for mode in MODE}
    need(identities == expected and not scans, "Missing episode or unmatched author terminal rescan")
    return rows, scan_pin


def summarize(rows, states, freeze, inventory_sha):
    pairs = []
    all_steps = [(ep, step) for ep in rows for step in ep["steps"]]
    error_with_proof = [(ep, step) for ep, step in all_steps if step["outcome"] == "ARCHIVED_LEAN_ERROR" and step["proved_target_prerequisites"]]
    matrix = defaultdict(list)
    for ep in rows:
        matrix[ep["model"], ep["mode"]].append(ep)
    for (model, mode), episodes in sorted(matrix.items()):
        rescanned = [ep for ep in episodes if ep["author_rescan_pass"]]
        pairs.append({"model": model, "mode": mode, "state_denominator": len(episodes),
                      "loop_time_solved": sum(ep["loop_time_outcome"] == "solved" for ep in episodes),
                      "author_rescan_accepted": len(rescanned),
                      "author_rescan_accepted_target_clusters": len({ep["target_id"] for ep in rescanned}),
                      "strict_preservation": dict(Counter(ep["endpoint"]["strict_preservation"]["status"] for ep in rescanned)),
                      "rescanned_source_preservation": dict(Counter(ep["endpoint"]["author_rescan"]["preservation"]["status"] for ep in rescanned)),
                      "rescanned_release_evidence": dict(Counter(ep["endpoint"]["release_necessity"] for ep in rescanned))})
    closed = [ep for ep in rows if ep["author_rescan_pass"]]
    targets = {ep["target_id"] for ep in rows}
    actual_retained = [ep for ep in closed if ep["endpoint"]["release_necessity"] == "OBSERVED_ALL_PRIOR_DECLARATIONS_RETAINED_AND_USED"]
    unchanged = [ep for ep in closed if ep["endpoint"]["release_necessity"].startswith("OBSERVED_")]
    return {"status": "COMPLETE_PUBLISHED_CORPUS_RECOUNT", "inventory_sha256": inventory_sha,
            "state_count": len(states), "original_target_cluster_count": len(targets), "episodes": len(rows), "attempts": len(all_steps),
            "episode_outcomes": dict(Counter(ep["loop_time_outcome"] for ep in rows)),
            "attempt_outcomes": dict(Counter(step["outcome"] for _, step in all_steps)),
            "prestate_resolution": dict(Counter(step["prestate_status"] for _, step in all_steps)),
            "errors_with_proved_ancestor": {"attempts": len(error_with_proof), "states": len({ep["state_id"] for ep, _ in error_with_proof}),
                                             "targets": len({ep["target_id"] for ep, _ in error_with_proof}),
                                             "targets_outside_previous_d38_sample": len({ep["target_id"] for ep, _ in error_with_proof if not ep["prior_d38_sample"]})},
            "author_rescan_accepted_episodes": len(closed), "author_rescan_accepted_any_mode_targets": len({ep["target_id"] for ep in closed}),
            "closed_endpoint_actions": dict(Counter(step["action"] for ep in closed for step in ep["steps"] if step["outcome"] == "AUTHOR_LOOP_ACCEPTED_TARGET")),
            "loop_solved_without_author_rescan": [{k: ep[k] for k in ("run_id", "state_id", "model", "mode", "rescan_unavailable_reason")}
                                                  for ep in rows if ep["loop_time_outcome"] == "solved" and not ep["author_rescan_pass"]],
            "observed_no_replacement_source": {"episodes": len(unchanged), "targets": len({ep["target_id"] for ep in unchanged})},
            "observed_no_replacement_and_actual_use": {"episodes": len(actual_retained), "targets": len({ep["target_id"] for ep in actual_retained})},
            "positive_minimum_release_certificates": 0,
            "scope": freeze["analysis_scope"], "matrix": pairs}


def write_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        need(path.read_bytes() == raw, "Recount differs from its frozen output")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return digest(raw)


def run():
    need(digest((D38 / "blueprint_trace_intake.py").read_bytes()) == "d491af579ca214c65e606c9c124555aba670424cd625ca06b24ac8718c866841",
         "Inherited archive parser differs from D3.8")
    freeze_raw = (ROOT / "corpus_freeze.json").read_bytes()
    freeze = json.loads(freeze_raw)
    source = freeze["source"]
    base = f"https://huggingface.co/datasets/{source['dataset']}/resolve/{source['revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{source['artifact_commit']}/"
    raw = read_url(base + source["state_source_path"], 16 * 1024 * 1024)
    need(digest(raw) == source["state_source_sha256"], "State population SHA changed")
    state_rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    states = {state["state_id"]: state for state in state_rows}
    targets = Counter(row["seed_source"]["item_id"] for row in state_rows)
    need(len(states) == len(state_rows) == freeze["population"]["expected_states"]
         and len(targets) == freeze["population"]["expected_independent_target_ids"], "State or target denominator differs")
    manifest = read_url(base + "SHA256SUMS", 128 * 1024)
    need(digest(manifest) == source["archive_manifest_sha256"], "Archive checksum manifest differs")
    pins = json.loads((D38 / "blueprint_trace_intake.json").read_bytes())["runtime_compatibility"]["author"]
    rows, rescan_pins = [], []
    for archive in source["archives"]:
        path = archive_for(archive, base, github)
        observed, pin = inspect_archive(path, archive, states, freeze, github, pins)
        rows.extend(observed)
        rescan_pins.append({"model": archive["model"], **pin})
    need(len(rows) == freeze["population"]["expected_episodes"], "Author archives have incomplete episode coverage")
    rows.sort(key=lambda ep: (ep["state_id"], ep["model"], ep["mode"]))
    inventory = {"status": "COMPLETE_PUBLISHED_CORPUS_RECOUNT", "freeze_sha256": digest(freeze_raw),
                 "author_lean_runtime_pins": pins, "author_rescan_sources": rescan_pins,
                 "supplemental_rescan_scope": "Post-freeze cross-reference of the complete author terminal-rescan tables to archived members and actual proof/type edges. Separate from the frozen exact accepted-source identity metric.",
                 "episodes": rows}
    inventory_sha = write_once(ROOT / "corpus_inventory.json", inventory)
    summary = summarize(rows, states, freeze, inventory_sha)
    write_once(ROOT / "corpus_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
