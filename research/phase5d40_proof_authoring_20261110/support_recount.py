"""Static, provenance-separated proof support ledger for the frozen D4.0 archive cohort."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
D39 = ROOT.parent / "phase5d39_blueprint_trace_20261110"
sys.path.append(str(D39))
from corpus_recount import archive_for, bundles, need, write_once
from corpus_replay_nomination import current_module


COHORTS = {"unresolved": "unresolved", "same_family_author_rescan_solved": "same_family_solved"}
TACTICS = {
    "decompose": "intro intros rintro rcases cases induction by_cases by_contra obtain constructor refine apply exact assumption have let calc",
    "numeric": "omega linarith nlinarith norm_num positivity ring ring_nf gcongr field_simp decide native_decide grind",
    "rewrite": "rw erw simp simp_all simpa conv change subst push_neg dsimp simp_rw",
    "search": "exact? apply? simp? aesop library_search solve_by_elim first repeat",
    "finite": "interval_cases fin_cases by_cases interval_cases₂",
    "admitted": "sorry sorry_using admit",
}
KNOWN = frozenset(word for words in TACTICS.values() for word in words.split())
HOLES = frozenset(TACTICS["admitted"].split())
DECLARATION = re.compile(r"(?m)^[ \t]*(?:(?:private|protected|noncomputable)\s+)?(?:theorem|lemma)\s+([\w.'₀-₉]+)")
DECL_STOP = re.compile(r'(?m)^@\[blueprint\b|^#(?:print|check|eval)\b|^end(?:\s|$)')
TOKEN = re.compile(r"[^\W\d][\w']*[?!]?|\d+|:=|[^\s]", re.UNICODE)
FENCE = re.compile(r"```lean[ \t]*\r?\n(.*?)```", re.I | re.S)
PATCH = re.compile(r"(?ms)^<<<<<<< SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> REPLACE(?:\r?\n|$)")


def digest(data):
    return sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def lex(text):
    """Return position-bearing lexical tokens. Strings remain a single opaque token."""
    out = []
    i = 0
    while i < len(text):
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = len(text) if end == -1 else end + 1
        elif text.startswith("/-", i):
            depth = 1
            i += 2
            while depth and i < len(text):
                if text.startswith("/-", i):
                    depth += 1
                    i += 2
                elif text.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
        elif text[i] == '"':
            start = i
            i += 1
            while i < len(text):
                char = text[i]
                i += 1
                if char == "\\" and i < len(text):
                    i += 1
                elif char == '"':
                    break
            out.append((text[start:i], start, i, True))
        elif text[i].isspace():
            i += 1
        else:
            match = TOKEN.match(text, i)
            out.append((match[0], i, match.end(), False))
            i = match.end()
    return out


def token_id(tokens):
    return digest(json.dumps([x[0] for x in tokens], separators=(",", ":"), ensure_ascii=False))


def proof_record(text):
    tokens = lex(text)
    if tokens and tokens[0][0] == "by":
        tokens = tokens[1:]
    if not tokens:
        return None
    words = Counter(token for token, _, _, is_string in tokens if not is_string and token in KNOWN)
    return {"tokens_sha256": token_id(tokens), "token_count": len(tokens), "tactics": dict(sorted(words.items())),
            "has_explicit_placeholder": bool(set(words) & HOLES)}


def statement_record(text):
    if not isinstance(text, str) or not text.strip():
        return None
    return {"tokens_sha256": token_id(lex(text)), "source_sha256": digest(text),
            "statement_display": text[:1200], "display_truncated": len(text) > 1200}


def declarations(text):
    """Extract visible theorem/lemma heads and bodies, without Lean elaboration."""
    # Lexically mask comments and strings without moving source offsets.
    mask = ["\n" if char == "\n" else " " for char in text]
    for _, start, stop, is_string in lex(text):
        if not is_string:
            mask[start:stop] = text[start:stop]
    masked = "".join(mask)
    declarations = list(DECLARATION.finditer(masked))
    stops = sorted([match.start() for match in DECL_STOP.finditer(masked)] + [match.start() for match in declarations] + [len(text)])
    out = []
    for match in declarations:
        stop = next(point for point in stops if point > match.start())
        fragment = text[match.end():stop]
        body = re.search(r":=\s*by\b", masked[match.end():stop])
        if body is None:
            body = re.search(r":=", masked[match.end():stop])
        head = fragment[:body.start()].strip() if body else fragment.strip()
        statement = statement_record(head)
        proof = proof_record(fragment[body.start() + 2:].strip()) if body else None
        out.append({"name": match[1], "statement": statement, "proof": proof})
    return out


def source_payload(text, *, raw_fragment=False):
    nodes = declarations(text)
    bodies = [node["proof"] for node in nodes if node["proof"]]
    if not bodies and raw_fragment:
        single = proof_record(text)
        if single:
            bodies.append(single)
    return {"source_sha256": digest(text), "declarations": nodes, "proofs": bodies}


def tool_payload(function):
    name = function.get("name")
    argument = function.get("arguments")
    try:
        args = json.loads(argument) if isinstance(argument, str) else argument
    except json.JSONDecodeError:
        args = None
    out = {"tool": name, "args_readable": isinstance(args, dict), "nodes": [], "proofs": []}
    if not isinstance(args, dict):
        return out
    out["node_id"] = args.get("node_id") if isinstance(args.get("node_id"), str) else None
    if isinstance(args.get("new_statement"), str):
        binders = args.get("new_binders") if isinstance(args.get("new_binders"), str) else ""
        out["nodes"].append({"name": out["node_id"], "kind": "existing_statement_edit",
                             "statement": statement_record(binders + " : " + args["new_statement"])})
    for key in ("new_proof", "node_proof"):
        if isinstance(args.get(key), str) and (proof := proof_record(args[key])):
            out["proofs"].append(proof)
    children = args.get("new_nodes")
    if isinstance(children, list):
        for child in children:
            if not isinstance(child, dict) or not isinstance(child.get("statement"), str):
                continue
            binders = child.get("binders") if isinstance(child.get("binders"), str) else ""
            out["nodes"].append({"name": child.get("name"), "kind": "explicit_new_intermediate",
                                 "statement": statement_record(binders + " : " + child["statement"])})
            if isinstance(child.get("proof"), str) and (proof := proof_record(child["proof"])):
                out["proofs"].append(proof)
    return out


def provider_sources(response):
    tools, texts = [], []
    ignored_reasoning = False
    for choice in response.get("choices", []):
        message = choice.get("message", {})
        ignored_reasoning |= bool(message.get("reasoning") or message.get("reasoning_details"))
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                tools.append(tool_payload(call["function"]))
        content = message.get("content")
        if not isinstance(content, str):
            continue
        patches = list(PATCH.finditer(content))
        if patches:
            texts.extend({"kind": "exact_patch_replacement", **source_payload(match[2], raw_fragment=True)} for match in patches)
        else:
            texts.extend({"kind": "lean_fenced_code", **source_payload(block, raw_fragment=True)} for block in FENCE.findall(content))
    return tools, texts, ignored_reasoning


def initial_source(messages):
    for msg in messages:
        text = msg.get("content")
        if msg["role"] != "user" or not isinstance(text, str) or not text.startswith("Failed blueprint state"):
            continue
        found = FENCE.findall(text)
        return found[0] if len(found) == 1 else None
    return None


def proof_sha(node):
    return node["proof"]["tokens_sha256"] if node["proof"] else None


def statement_sha(node):
    return node["statement"]["tokens_sha256"] if node["statement"] else None


def declaration_diff(old, new):
    if old is None or new is None or not old["declarations"] or not new["declarations"]:
        return {"status": "UNKNOWN_UNRESOLVED_SOURCE"}
    older = {row["name"]: row for row in old["declarations"]}
    newer = {row["name"]: row for row in new["declarations"]}
    if len(older) != len(old["declarations"]) or len(newer) != len(new["declarations"]):
        return {"status": "UNKNOWN_DUPLICATE_DECLARATION_KEY"}
    shared = set(older) & set(newer)
    return {"status": "VISIBLE_NAME_KEY_DIFF", "new_declaration_names": sorted(set(newer) - set(older)),
            "removed_declaration_names": sorted(set(older) - set(newer)),
            "statement_tokens_changed": sorted(name for name in shared if statement_sha(older[name]) != statement_sha(newer[name])),
            "proof_tokens_changed": sorted(name for name in shared if proof_sha(older[name]) != proof_sha(newer[name]))}


def checked_module(files, step, suffix):
    stem = f"step{step['step']:02d}.{suffix}"
    source = files.get(stem + ".lean")
    check = next((c for c in step["author_elaborations"] if c["member"].endswith("/" + stem + ".elab.json")), None)
    log = files.get(stem + ".elab.json")
    if source is None or log is None or check is None:
        return None
    need(digest(log) == check["sha256"], "Materialized check log differs from verified corpus")
    return {"archive_member": check["member"].replace(".elab.json", ".lean"), "checked_by": check,
            **source_payload(source.decode())}


def handle_episode(row, files):
    episode_raw = files["episode.json"]
    need(digest(episode_raw) == row["episode_sha256"], "Archive episode differs from D3.9")
    initial, steps = None, []
    for step in row["steps"]:
        raw = files[step["archive_member"].rsplit("/", 1)[-1]]
        need(digest(raw) == step["sha256"], "Provider step differs from D3.9")
        raw_step = json.loads(raw)
        messages = raw_step["request"]["messages"]
        if initial is None and (before := initial_source(messages)) is not None:
            initial = source_payload(before)
        graph_index = step["prestate_prompt_index"]
        index, module = current_module(messages, graph_index) if isinstance(graph_index, int) else (None, None)
        prior = source_payload(module) if module is not None else None
        tools, delivered, ignored = provider_sources(raw_step.get("response", {}))
        candidate = checked_module(files, step, "check")
        assembled = checked_module(files, step, "assembled")
        visible_diff = declaration_diff(prior, candidate)
        if visible_diff["status"] == "VISIBLE_NAME_KEY_DIFF":
            # An open target proof is not a newly created intermediate. Bind the
            # target by the initial graph in this same recorded model request.
            target_name = None
            for msg in messages:
                text = msg.get("content")
                if msg["role"] == "user" and isinstance(text, str) and text.startswith("Failed blueprint state"):
                    graph = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
                    target, = (node for node in graph["nodes"] if node["node_id"] == graph["target_node_id"])
                    target_name = next((node["name"] for node in declarations(target["formal_statement"])), None)
                    break
            visible_diff["new_intermediate_names"] = [name for name in visible_diff["new_declaration_names"] if name != target_name]
        steps.append({"step": step["step"], "step_member": step["archive_member"], "step_sha256": step["sha256"],
                      "archived_outcome": step["outcome"], "archived_action": step["action"],
                      "provider_tools": tools, "provider_code": delivered, "provider_reasoning_ignored": ignored,
                      "visible_prestate": None if prior is None else {"message_index": index, **prior},
                      "materialized_check": candidate, "assembled_source": assembled, "candidate_vs_prestate": visible_diff,
                      "tactic_transition_evidence": "NO_COMPLETE_REPLAYABLE_TACTIC_STATE_GRAPH"})
    return {"run_id": row["run_id"], "state_id": row["state_id"], "target_id": row["target_id"], "model": row["model"],
            "mode": row["mode"], "episode_sha256": row["episode_sha256"], "author_verifier_calls": row["author_verifier_calls"],
            "author_rescan_pass": row["author_rescan_pass"], "initial_source": initial, "steps": steps}


def step_proofs(step):
    sources = {"provider": [proof for item in step["provider_tools"] + step["provider_code"] for proof in item["proofs"]]}
    for origin in ("visible_prestate", "materialized_check", "assembled_source"):
        item = step[origin]
        sources[origin] = [] if item is None else item["proofs"]
    return sources


def support_index(episodes):
    by_target = defaultdict(lambda: defaultdict(set))
    for episode in episodes:
        target = by_target[episode["target_id"]]

        def absorb(origin, proofs, nodes):
            for proof in proofs:
                target[origin + "_proofs"].add(proof["tokens_sha256"])
                target[origin + "_tactics"].update(proof["tactics"])
            target[origin + "_statements"].update(statement_sha(node) for node in nodes if node["statement"])

        if episode["initial_source"]:
            item = episode["initial_source"]
            absorb("initial", item["proofs"], item["declarations"])
        for step in episode["steps"]:
            for tool in step["provider_tools"]:
                absorb("provider", tool["proofs"], tool["nodes"])
            for item in step["provider_code"]:
                absorb("provider", item["proofs"], item["declarations"])
            for origin in ("visible_prestate", "materialized_check", "assembled_source"):
                if (item := step[origin]) is not None:
                    absorb(origin, item["proofs"], item["declarations"])
    return {target: {kind: sorted(values) for kind, values in sorted(data.items())} for target, data in sorted(by_target.items())}


def summarize(episodes):
    summary, by_state = {}, defaultdict(list)
    for episode in episodes:
        by_state[episode["state_id"]].append(episode)
    for cohort in (*COHORTS.values(), "same_target_overlap_sentinel"):
        subset = [ep for ep in episodes if ep["cohort"] == cohort]
        steps = [s for ep in subset for s in ep["steps"]]
        counts, types, steps_with_tactics = Counter(), Counter(), Counter()
        for s in steps:
            providers = s["provider_tools"]
            counts["visible_provider_code_or_structured_tool"] += bool(providers or s["provider_code"])
            counts["no_visible_provider_code_or_tool"] += not bool(providers or s["provider_code"])
            counts["provider_reasoning_ignored_steps"] += s["provider_reasoning_ignored"]
            counts["visible_current_module_steps"] += s["visible_prestate"] is not None
            counts["materialized_check_sources"] += s["materialized_check"] is not None
            counts["assembled_sources"] += s["assembled_source"] is not None
            counts["structured_split_calls"] += sum(tool["tool"] == "split_node" for tool in providers)
            counts["malformed_tool_json_calls"] += sum(not tool["args_readable"] for tool in providers)
            counts["explicit_new_intermediate_specs"] += sum(node["kind"] == "explicit_new_intermediate" for tool in providers for node in tool["nodes"])
            diff = s["candidate_vs_prestate"]
            counts["exact_visible_source_diff_steps"] += diff["status"] == "VISIBLE_NAME_KEY_DIFF"
            counts["steps_with_new_intermediate_names"] += bool(diff.get("new_intermediate_names"))
            for origin, proofs in step_proofs(s).items():
                types[origin] += len(proofs)
                for tactic in {tactic for proof in proofs for tactic in proof["tactics"]}:
                    steps_with_tactics[origin, tactic] += 1
        summary[cohort] = {"states": len({ep["state_id"] for ep in subset}), "independent_targets": len({ep["target_id"] for ep in subset}),
                           "episodes": len(subset), "steps": len(steps),
                           "author_verifier_calls": sum(ep["author_verifier_calls"] for ep in subset),
                           "source_counts": dict(counts), "proof_fragments_by_origin": dict(types),
                           "provider_tactic_steps": {t: n for (origin, t), n in sorted(steps_with_tactics.items()) if origin == "provider"},
                           "states_with_explicit_split_or_intermediate": len({ep["state_id"] for ep in subset for s in ep["steps"]
                                                                             if any(t["tool"] == "split_node" for t in s["provider_tools"])
                                                                             or s["candidate_vs_prestate"].get("new_intermediate_names")})}
    state_rows = []
    for state, group in sorted(by_state.items()):
        steps = [s for ep in group for s in ep["steps"]]
        state_rows.append({"state_id": state, "target_id": group[0]["target_id"], "cohort": group[0]["cohort"], "steps": len(steps),
                           "visible_provider_steps": sum(bool(s["provider_tools"] or s["provider_code"]) for s in steps),
                           "materialized_steps": sum(s["materialized_check"] is not None for s in steps),
                           "split_calls": sum(t["tool"] == "split_node" for s in steps for t in s["provider_tools"]),
                           "introduced_intermediate_names": sorted({n for s in steps for n in s["candidate_vs_prestate"].get("new_intermediate_names", [])}),
                           "provider_tactics": sorted({t for s in steps for p in step_proofs(s)["provider"] for t in p["tactics"]})})
    return {"scope": "Static archived support only. No full proof-state replay, semantic novelty, new Lean or model run.",
            "cohorts": summary, "by_state": state_rows}


def run():
    freeze_raw = (ROOT / "support_freeze.json").read_bytes()
    freeze = json.loads(freeze_raw)
    selection_raw = (ROOT / "D40_SOURCE_SELECTION_FREEZE.json").read_bytes()
    selection = json.loads(selection_raw)
    corpus_raw = (D39 / "corpus_inventory.json").read_bytes()
    need(digest(selection_raw) == freeze["d40_selection_sha256"] and digest(corpus_raw) == freeze["d39_inventory_sha256"]
         and digest((D39 / "corpus_recount.py").read_bytes()) == freeze["d39_recount_source_sha256"], "Frozen corpus scope differs")
    wanted = {row["state_id"]: (name, row) for key, name in COHORTS.items() for row in selection[key]}
    overlap = set(freeze["cohorts"]["same_target_overlap_sentinel"])
    source = json.loads((D39 / "corpus_freeze.json").read_bytes())["source"]
    base = f"https://huggingface.co/datasets/{source['dataset']}/resolve/{source['revision']}/"
    github = f"https://raw.githubusercontent.com/Karifannaa/BlueprintRepair/{source['artifact_commit']}/"
    episodes = []
    corpus = json.loads(corpus_raw)["episodes"]
    for archive in source["archives"]:
        grouped = bundles(archive_for(archive, base, github))
        for row in corpus:
            state = row["state_id"]
            if row["model"] != archive["model"] or state not in wanted and state not in overlap:
                continue
            out = handle_episode(row, grouped[row["episode_member"].rsplit("/", 1)[0]])
            out["cohort"] = wanted[state][0] if state in wanted else "same_target_overlap_sentinel"
            episodes.append(out)
    for state, (_, row) in wanted.items():
        selected = [e for e in episodes if e["state_id"] == state]
        need(len(selected) == row["archived_episodes"] and sum(len(e["steps"]) for e in selected) == row["archived_steps"]
             and sum(e["author_verifier_calls"] for e in selected) == row["author_reported_verifier_calls"]
             and sorted(e["episode_sha256"] for e in selected) == sorted(row["archive_episode_sha256"]),
             "Archive state denominator differs")
    episodes.sort(key=lambda row: (row["state_id"], row["model"], row["mode"]))
    ledger = {"status": "COMPLETE_ARCHIVE_ONLY_SUPPORT_LEDGER", "support_freeze_sha256": digest(freeze_raw),
              "episodes": episodes}
    ledger_sha = write_once(ROOT / "support_ledger.json", ledger)
    index_sha = write_once(ROOT / "support_index.json", support_index(episodes))
    summary = {"status": ledger["status"], "ledger_sha256": ledger_sha, "index_sha256": index_sha, **summarize(episodes)}
    write_once(ROOT / "support_summary.json", summary)
    print(json.dumps(summary["cohorts"], indent=2))


def compare(target, candidate):
    index = json.loads((ROOT / "support_index.json").read_bytes())
    need(target in index, "Target is outside frozen same-target support")
    prior = index[target]
    payload = source_payload(candidate.read_text(encoding="utf-8"), raw_fragment=True)
    origins = ("provider", "initial", "visible_prestate", "materialized_check", "assembled_source")
    compare_items = []
    for kind, entries in (("proofs", payload["proofs"]),
                          ("statements", [row["statement"] for row in payload["declarations"] if row["statement"]])):
        for entry in entries:
            seen = [origin for origin in origins if entry["tokens_sha256"] in prior.get(origin + "_" + kind, [])]
            compare_items.append({"kind": kind, "tokens_sha256": entry["tokens_sha256"], "same_visible_tokens_in": seen,
                                  "status": "VISIBLE_TOKEN_MATCH" if seen else "UNSEEN_IN_VISIBLE_ARCHIVE_ONLY"})
    tactics = sorted({tactic for proof in payload["proofs"] for tactic in proof["tactics"]})
    return {"scope": "Static candidate lookup. Hidden source, exact proof states and semantic equivalence are unknown.",
            "target_id": target, "candidate_source_sha256": payload["source_sha256"], "comparisons": compare_items,
            "candidate_tactics": tactics, "provider_tactics_already_seen": sorted(set(tactics) & set(prior.get("provider_tactics", [])))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-id")
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    if args.target_id is None and args.candidate is None:
        run()
    else:
        need(args.target_id is not None and args.candidate is not None, "Pass candidate and target together")
        print(json.dumps(compare(args.target_id, args.candidate), ensure_ascii=False, indent=2))
