"""Recount fixed released BlueprintTrace trajectories and their recorded Lean evidence."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "blueprint_trace_freeze.json"
PROVED = {"proved", "proved_and_used"}
MODES = {"toolsrc": "typed", "patchsrc": "patch", "rwsrc": "rewrite"}
MODEL_ORDER = ("deepseek/deepseek-v4-flash", "qwen/qwen3.6-flash")


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return sha256(raw).hexdigest()


def read_url(url, maximum):
    with urlopen(url, timeout=45) as response:
        raw = response.read(maximum + 1)
    need(len(raw) <= maximum, "Public source exceeds fixed read cap")
    return raw


def archive_for(row, base, github):
    leaf = Path(row["path"]).name
    cached = Path(tempfile.gettempdir()) / f"blueprint_trace_{row['sha256'][:12]}_{leaf}"
    if cached.exists():
        raw = cached.read_bytes()
        need(digest(raw) == row["sha256"], "Cached author archive differs")
        return cached
    errors = []
    for url in (base + row["path"], github + "data/" + leaf):
        try:
            raw = read_url(url, 64 * 1024 * 1024)
            need(digest(raw) == row["sha256"], "Downloaded author archive differs")
        except (OSError, ValueError) as err:
            errors.append(f"{url} {err}")
            continue
        with cached.open("xb") as stream:
            stream.write(raw)
        return cached
    raise ValueError("Cannot obtain pinned author archive: " + "; ".join(errors))


def current_graph(messages):
    graph = target = source_index = None
    for index, msg in enumerate(messages):
        text = msg.get("content")
        if not isinstance(text, str):
            continue
        if msg["role"] == "user" and text.startswith("Failed blueprint state"):
            graph, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
            target = graph["target_node_id"]
            source_index = index
            continue
        if msg["role"] == "tool" and text.startswith("{"):
            feedback = json.loads(text)
        elif msg["role"] == "user" and text.startswith("Verifier feedback:"):
            feedback, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
        else:
            continue
        if feedback.get("applied") is True and isinstance(feedback.get("graph"), dict):
            graph, source_index = feedback["graph"], index
    need(graph is not None and target is not None and source_index is not None, "Missing recorded starting graph")
    return target, graph, source_index


def support_nodes(target, graph):
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    matches = [name for name in nodes if name.rsplit(":", 1)[-1] == target.rsplit(":", 1)[-1]]
    if len(matches) != 1:
        return {"status": "TARGET_BINDING_UNRESOLVED", "target_node": None, "declared_support": [], "proved_prerequisites": []}
    root, = matches
    edges = []
    for edge in graph["edges"]:
        if isinstance(edge, dict):
            edges.append((edge["src"], edge["dst"]))
        else:
            need(isinstance(edge, list) and len(edge) == 2, "Unrecognized author edge representation")
            edges.append(tuple(edge))
    closure, todo = set(), [root]
    while todo:
        dst = todo.pop()
        for source, destination in edges:
            if destination == dst and source in nodes and source not in closure and source != root:
                closure.add(source)
                todo.append(source)
    support = [{key: nodes[node_id].get(key) for key in ("node_id", "formal_statement", "status")}
               for node_id in sorted(closure)]
    proved = [node for node in support if node["status"] in PROVED]
    return {"status": "DECLARED_TARGET_CLOSURE", "target_node": root, "declared_support": support,
            "proved_prerequisites": proved}


def raw_member(tar, members, name):
    member = members[name]
    need(member.size <= 12 * 1024 * 1024, "Selected transcript member exceeds read cap")
    with tar.extractfile(member) as stream:
        return stream.read()


def inspect_step(tar, members, folder, episode, step, runtime_pins):
    step_number = step["step"]
    prefix = f"{folder}/step{step_number:02d}"
    step_bytes = raw_member(tar, members, prefix + ".json")
    detail = json.loads(step_bytes)
    execution, meta = detail["tool_execution"], detail["meta"]
    need(meta["state_id"] == episode["state_id"] and meta["run_id"] == episode["run_id"]
         and meta["step"] == step_number and meta["model"] == episode["model"]
         and meta["protocol"] == episode["protocol"], "Provider step belongs to another episode")
    for key in ("applied", "solved", "tool", "module_sha256"):
        need(execution.get(key) == step.get(key), "Step and episode action disagree")
    choices = detail["response"].get("choices", [])
    authored = any(choice.get("message", {}).get("content") or choice.get("message", {}).get("tool_calls") for choice in choices)
    messages = detail["request"]["messages"]
    target, graph, snapshot = current_graph(messages)
    prestate = support_nodes(target, graph)
    prestate["prompt_message_index"] = snapshot
    prestate["prompt_message_sha256"] = digest(messages[snapshot]["content"].encode())
    checks = []
    for name in sorted(path for path in members if path.startswith(prefix + ".") and path.endswith(".elab.json")):
        raw = raw_member(tar, members, name)
        lean = json.loads(raw)
        need(lean["pins"] == runtime_pins, "Lean subprocess pin differs from author artifact")
        errors = [{"line": item.get("line"), "col": item.get("col"), "message": item.get("message")}
                  for item in lean["diagnostics"] if item.get("severity") == "error"]
        source = name.replace(".elab.json", ".lean")
        checks.append({"archive_member": name, "sha256": digest(raw), "exit_code": lean["exit_code"],
                       "timed_out": lean["timed_out"], "error_count": len(errors), "errors": errors[:2],
                       "source_member": source if source in members else None,
                       "source_sha256": digest(raw_member(tar, members, source)) if source in members else None})
    actual_error = any(c["exit_code"] not in (None, 0) and not c["timed_out"] and c["error_count"] for c in checks)
    if not authored:
        outcome = "NO_OBSERVED_MODEL_ACTION"
    elif execution.get("solved") is True:
        outcome = "AUTHOR_ACCEPTED_TARGET"
    elif actual_error:
        outcome = "ARCHIVED_LEAN_ERROR"
    elif any(c["timed_out"] for c in checks):
        outcome = "ARCHIVED_TIMEOUT"
    elif execution.get("applied") is False:
        outcome = "HARNESS_REJECTED"
    else:
        outcome = "APPLIED_BUT_UNSOLVED"
    return {"step": step_number, "step_member": prefix + ".json", "step_sha256": digest(step_bytes),
            "model_action_recorded": authored, "tool": execution.get("tool"), "applied": execution.get("applied"),
            "solved": execution.get("solved"), "outcome": outcome, "harness_error": execution.get("error"),
            "prerequisites_before_attempt": prestate, "lean_checks": checks}


def collect_archive(path, source, wanted, runtime_pins, model):
    results = {}
    with tarfile.open(path, mode="r:gz") as tar:
        selected = [member for member in tar.getmembers() if member.isfile() and not member.name.rsplit("/", 1)[-1].startswith("._")]
        members = {member.name: member for member in selected}
        need(len(members) == len(selected), "Ambiguous author archive member path")
        for state_id, row in wanted.items():
            for tag, mode in MODES.items():
                marker = f"/{row['stem']}_{tag}"
                names = [name for name in members if marker in name and name.endswith("/episode.json")]
                need(len(names) == 1, f"Missing or ambiguous episode for {state_id}, {mode}, {model}")
                name, = names
                folder = name.rsplit("/", 1)[0]
                ep_raw = raw_member(tar, members, name)
                ep = json.loads(ep_raw)
                need(ep["state_id"] == state_id and ep["model"] == model and ep.get("mode", "typed") == mode
                     and ep["protocol"] == "equal_source_v2", "Author episode identity or protocol differs")
                steps = [inspect_step(tar, members, folder, ep, step, runtime_pins) for step in ep["steps"]]
                need(len(steps) == ep["llm_calls"] and [step["step"] for step in steps] == list(range(1, len(steps) + 1)),
                     "Published episode step count or order differs")
                final_member = folder + "/final.module.lean"
                final_sha = digest(raw_member(tar, members, final_member)) if final_member in members else None
                need(final_sha == ep["final_module_sha256"] and (final_sha is not None or mode == "rewrite"),
                     "Author final module identity differs")
                results[state_id, mode] = {"state_id": state_id, "initial_defect_family": row["error_family"],
                                           "model": model, "mode": mode, "author_outcome": ep["outcome"],
                                           "archive": source["path"], "episode_member": name,
                                           "episode_sha256": digest(ep_raw), "final_module_sha256": final_sha,
                                           "final_module_evidence": "STANDALONE_FILE_SHA256" if final_sha else "STEP_LEVEL_ONLY",
                                           "author_verifier_calls": ep["verifier_calls"], "steps": steps}
    return results


def run():
    frozen = FROZEN.read_bytes()
    freeze = json.loads(frozen)
    base = f"https://huggingface.co/datasets/{freeze['dataset']}/resolve/{freeze['dataset_revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{freeze['artifact_commit']}/"
    raw = read_url(base + freeze["state_source"]["path"], 16 * 1024 * 1024)
    need(digest(raw) == freeze["state_source"]["sha256"], "Selected population differs")
    states = {state["state_id"]: state for line in raw.splitlines() if line.strip() and (state := json.loads(line))}
    chosen = sorted(states, key=lambda x: (digest(f"{freeze['salt']}:{x}".encode()), x))[:6]
    need(chosen == freeze["state_ids"] and len(states) == freeze["state_count"], "Frozen selection differs")
    selected = {key: states[key] for key in chosen}
    toolchain = read_url(github + "BlueprintRepair/lean-toolchain", 1024)
    manifest = read_url(github + "BlueprintRepair/lake-manifest.json", 32 * 1024)
    packages = {p["name"]: p["rev"] for p in json.loads(manifest)["packages"]}
    pins = {"lean_toolchain": toolchain.decode().strip(), "mathlib_rev": packages["mathlib"],
            "leanarchitect_rev": packages["LeanArchitect"]}
    episodes = []
    for model, row in zip(MODEL_ORDER, freeze["trajectory_archives"], strict=True):
        path = archive_for(row, base, github)
        by_key = collect_archive(path, row, selected, pins, model)
        episodes.extend(by_key[state, mode] for state in chosen for mode in MODES.values())
    steps = [step for episode in episodes for step in episode["steps"]]
    external = [step for step in steps if step["outcome"] == "ARCHIVED_LEAN_ERROR"
                and step["prerequisites_before_attempt"]["proved_prerequisites"]]
    runtime = json.loads((ROOT / "lean_runtime_controls.json").read_bytes())
    return {"status": "CLOSED_EXTERNAL_ARCHIVE_RECOUNT", "freeze_sha256": digest(frozen),
            "scope": "Actual released provider responses and author-verifier logs on controlled starting failures. No local proof replay or natural-failure claim.",
            "runtime_compatibility": {"status": "BLOCKED_EXACT_REPLAY_TOOLCHAIN_MISMATCH", "author": pins,
                                       "author_toolchain_sha256": digest(toolchain), "author_lake_manifest_sha256": digest(manifest),
                                       "local_verified_version": runtime["version"]["stdout"].strip(),
                                       "required": "Lean 4.31.0 plus the exact Mathlib and LeanArchitect revisions before revalidating these .lean artifacts."},
            "states": chosen, "episodes_count": len(episodes), "model_attempts_count": len(steps),
            "episode_outcomes": dict(Counter(ep["author_outcome"] for ep in episodes)),
            "attempt_outcomes": dict(Counter(step["outcome"] for step in steps)),
            "archived_lean_errors_with_proved_declared_prerequisite": len(external), "episodes": episodes}


def p159_preservation(result):
    """Check whether one author-accepted same-state patch retained the initial proved declarations."""
    selected, = (ep for ep in result["episodes"] if ep["state_id"] == "p159_bad.state0"
                 and ep["model"] == MODEL_ORDER[1] and ep["mode"] == "patch")
    need(selected["author_outcome"] == "solved" and selected["steps"][-1]["outcome"] == "AUTHOR_ACCEPTED_TARGET",
         "No archive-accepted patch in this diagnostic")
    freeze = json.loads(FROZEN.read_bytes())
    source, = (row for row in freeze["trajectory_archives"] if row["path"] == selected["archive"])
    base = f"https://huggingface.co/datasets/{freeze['dataset']}/resolve/{freeze['dataset_revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{freeze['artifact_commit']}/"
    with tarfile.open(archive_for(source, base, github), mode="r:gz") as tar:
        members = {member.name: member for member in tar.getmembers() if member.isfile()}
        first = selected["steps"][0]
        raw = raw_member(tar, members, first["step_member"])
        need(digest(raw) == first["step_sha256"], "First patch request changed")
        snapshot = first["prerequisites_before_attempt"]
        message = json.loads(raw)["request"]["messages"][snapshot["prompt_message_index"]]["content"]
        need(digest(message.encode()) == snapshot["prompt_message_sha256"], "Patch context changed")
        blocks = re.findall(r"```lean\n(.*?)```", message, flags=re.S)
        need(len(blocks) == 1, "Initial patch request must expose exactly one Lean module")
        final_member = selected["episode_member"].rsplit("/", 1)[0] + "/final.module.lean"
        final = raw_member(tar, members, final_member)
        need(digest(final) == selected["final_module_sha256"], "Accepted patch module changed")

    def declarations(text):
        starts = list(re.finditer(r'(?m)^@\[blueprint\s+"([^"]+)"', text))
        return {match[1]: text[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
                for i, match in enumerate(starts)}

    before, after = declarations(blocks[0]), declarations(final.decode())
    comparisons = []
    for node in snapshot["proved_prerequisites"]:
        key = node["node_id"]
        need(key in before and key in after and before[key] == after[key], "Proved declaration was changed by patch")
        comparisons.append({"node_id": key, "boundary_trimmed_declaration_sha256": digest(before[key].encode()),
                            "source_equal": True})
    need(len(comparisons) == 3, "Expected the three original proved prerequisite declarations")
    return {"status": "THREE_INITIAL_PROVED_DECLARATIONS_RETAINED", "state_id": selected["state_id"],
            "scope": "Post-intake one-state diagnostic. Matches source from each blueprint annotation to the next, trimming outer whitespace. Author accepted the patch, with no new local Lean replay or full dependency equivalence claim.",
            "archive": selected["archive"], "initial_step_member": first["step_member"], "initial_step_sha256": first["step_sha256"],
            "accepted_final_module_member": final_member, "accepted_final_module_sha256": selected["final_module_sha256"],
            "verified_source_spans": comparisons}


def write_once(path, report):
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists():
        need(path.read_bytes() == encoded, "Prior archive recount differs")
    else:
        with path.open("xb") as stream:
            stream.write(encoded)


if __name__ == "__main__":
    result = run()
    write_once(ROOT / "blueprint_trace_intake.json", result)
    write_once(ROOT / "blueprint_trace_preservation.json", p159_preservation(result))
    print(json.dumps({key: value for key, value in result.items() if key != "episodes"}, indent=2))
