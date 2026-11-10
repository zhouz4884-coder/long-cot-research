"""Independently replay D4.4's live prefix detector from frozen terminal token IDs."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter


HERE = Path(__file__).resolve().parent
TOKENIZER = HERE.parents[1] / "outputs" / "d2_tokenizer_20261107"
FLOOR, STRIDE, CLAIM_WINDOW, SCOPE_WINDOW = 256, 64, 720, 3000
NATIVE, GENERIC, TYPED = "NativeContinue", "GenericReminder", "TypedObligation"
HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:[✅✓][ \t]*)?(?:\*\*)?"
    r"final[ \t]+answer\b(?:[ \t]*:)?(?:\*\*)?(?:[ \t]*:)?[ \t]*"
)
BOX = re.compile(r"\\boxed\s*\{\s*([+-]?[0-9]{1,18})\s*\}")
TAIL = re.compile(r"(?:\s|[.$!。*]|\\[\]\)])*")
HEX = re.compile(r"[a-f0-9]{64}")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value):
    return sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def ids_digest(ids):
    return digest(json.dumps(ids, separators=(",", ":")))


def pinned(path, expected):
    raw = path.read_bytes()
    require(isinstance(expected, str) and HEX.fullmatch(expected) and digest(raw) == expected,
            f"Frozen bytes differ for {path.name}")
    return json.loads(raw)


def unique_index(rows, key):
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), f"Duplicate {key}")
    return result


class TextCodec:
    def __init__(self, folder, preflight):
        from transformers import AutoTokenizer, __version__ as transformers_version
        from tokenizers import __version__ as tokenizers_version

        expected = preflight["tokenizer_manifest_sha256"]
        manifest = pinned(folder / "TOKENIZER_FETCH_MANIFEST.json", expected)
        require(manifest["model_manifest"] == preflight["model_manifest_sha256"], "Tokenizer model identity differs")
        allowed = {"tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "config.json", "generation_config.json"}
        require({row["path"] for row in manifest["files"]} == allowed, "Unexpected tokenizer assets")
        for item in manifest["files"]:
            content = (folder / item["path"]).read_bytes()
            require(len(content) == item["bytes"] and digest(content) == item["sha256"], "Tokenizer asset bytes differ")
        self.tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
        self.open, = self.tokenizer.encode("<think>", add_special_tokens=False)
        self.close, = self.tokenizer.encode("</think>", add_special_tokens=False)
        eos = json.loads((folder / "generation_config.json").read_bytes())["eos_token_id"]
        self.eos = set(eos if isinstance(eos, list) else [eos])
        self.info = {"manifest_sha256": expected, "transformers": transformers_version,
                     "tokenizers": tokenizers_version, "open_id": self.open, "close_id": self.close,
                     "eos_ids": sorted(self.eos)}
        self._brace = {}

    def decode(self, ids):
        return self.tokenizer.decode(ids, skip_special_tokens=False)

    def brace(self, token):
        if token not in self._brace:
            self._brace[token] = "}" in self.decode([token])
        return self._brace[token]

    def prompt(self, question):
        content = question + "\nPlease reason step by step, and put your final answer within \\boxed{}."
        return self.tokenizer.apply_chat_template([{"role": "user", "content": content}], tokenize=True,
                                                  add_generation_prompt=True, enable_thinking=True, return_dict=False)


def arithmetic(value, obligation):
    kind, args = obligation["kind"], obligation["args"]
    if kind == "congruence":
        modulus, residue = args
        observed = value % modulus
        return observed != residue, {"modulus": modulus, "expected_residue": residue, "observed_residue": observed}
    if kind == "closed_interval":
        lo, hi = args
        return value < lo or value > hi, {"lo": lo, "hi": hi}
    require(kind == "finite_exclusions", "Unsupported frozen condition")
    return value in args, {"excluded_values": args}


def frontier(text, case):
    """Read one observed prefix without calling the deployed detector."""
    heads = list(HEADING.finditer(text, max(0, len(text) - CLAIM_WINDOW)))
    if not heads:
        return "NO_TERMINAL_HEADING", None
    head = heads[-1]
    boxes = list(BOX.finditer(text, head.end()))
    if len(boxes) != 1:
        return "HEADING_WITHOUT_UNIQUE_INTEGER_BOX", None
    box, = boxes
    if not TAIL.fullmatch(text, box.end()) or r"\boxed" in text[head.end():box.start()]:
        return "INTEGER_BOX_NOT_AT_FRONTIER", None
    value = int(box[1])
    excerpt = {"observed_candidate": value, "source_char_span": [head.start(), box.end()],
               "source_excerpt_sha256": digest(text[head.start():box.end()])}
    obligation = case["obligation"]
    if obligation is None:
        return "NO_REVIEWED_OBLIGATION", excerpt
    offset = max(0, head.start() - SCOPE_WINDOW)
    window = text[offset:box.end()]
    anchors, missing = [], []
    for index, pattern in enumerate(obligation["scope_patterns"]):
        matches = list(re.finditer(pattern, window, re.I | re.S))
        if not matches:
            missing.append(index)
        else:
            last = matches[-1]
            anchors.append({"source_char_span": [offset + last.start(), offset + last.end()],
                            "source_excerpt_sha256": digest(last[0])})
    if missing:
        return "LOCAL_SCOPE_ANCHOR_MISSING", {**excerpt, "matched_scope_anchors": anchors,
                                               "missing_pattern_indices": missing}
    violated, details = arithmetic(value, obligation)
    receipt = {**excerpt, "status": "COMMITTED_INTEGER_REFUTED" if violated else "NECESSARY_CONDITION_SATISFIED",
               "question_sha256": case["question_sha256"], "proof_sha256": obligation["proof_sha256"],
               "review_sha256": obligation["review_sha256"], "predicate_kind": obligation["kind"],
               "predicate_args": obligation["args"], "scope_anchors": anchors, "arithmetic": details,
               "cue": obligation["cue"]}
    return ("CONTRADICTION" if violated else "CONDITION_SATISFIED"), receipt


def character_diagnostics(codec, ids, prompt_open, case):
    """Use completed text only for diagnostics, without mixing separate channel spans."""
    start = 0 if prompt_open else None
    closed, last_open, thought = [], None, []
    for i, token in enumerate(ids):
        if token in {codec.open, codec.close}:
            if start is not None:
                thought.append(codec.decode(ids[start:i]))
            start = i + 1 if token == codec.open else None
        if token == codec.open:
            last_open = i
        elif token == codec.close:
            closed.append(i)
    if start is not None:
        thought.append(codec.decode(ids[start:]))
    final = codec.decode(ids[closed[-1] + 1:]) if closed and (last_open is None or last_open < closed[-1]) else ""
    unmarked = codec.decode(ids) if not thought and not closed else ""
    character_counts = Counter()
    for segment in thought:
        for box in BOX.finditer(segment):
            status, _ = frontier(segment[:box.end()], case)
            character_counts[status] += 1
    return closed, character_counts, len(list(BOX.finditer(final))), bool(BOX.search(unmarked))


def replay(codec, case, native, bridge_count):
    prompt, ids = native["prompt_ids"], native["generated_ids"]
    capacity = native["context_capacity"]
    require(bool(ids) and prompt == codec.prompt(case["question"]), "Exact frozen prompt or completion differs")
    require(all(type(x) is int and x >= 0 for x in ids) and native["generated_sha256"] == ids_digest(ids)
            and native["text"] == codec.decode(ids), "Native IDs do not reproduce terminal text")
    last_eos = ids[-1] in codec.eos
    stop = "EOS" if last_eos else "CONTEXT_CAP"
    require(not any(x in codec.eos for x in ids[:-1]) and native["stop_reason"] == stop
            and len(prompt) + len(ids) <= capacity and (last_eos or len(prompt) + len(ids) == capacity),
            "Native token history is outside EOS/context protocol")
    require(native["final_cache_position"] == len(prompt) + len(ids) - 1, "Terminal cache position differs")

    latest_prompt_control = next((x for x in reversed(prompt) if x in {codec.open, codec.close}), None)
    prompt_open = thinking = latest_prompt_control == codec.open
    open_start, eligible, count_calls = 0, 0, 0
    first = {}
    counts = Counter()
    active = case["obligation"] is not None
    found = None
    for count, token in enumerate(ids, 1):
        if token == codec.open:
            thinking, open_start = True, count
        elif token == codec.close:
            thinking = False
        if not (active and thinking and FLOOR <= count < len(ids)):
            continue
        eligible += 1
        cadence = count % STRIDE == 0
        if not cadence and not codec.brace(token):
            continue
        count_calls += 1
        thought = codec.decode(ids[open_start:count])
        if "</think>" in thought[-CLAIM_WINDOW:]:
            status, evidence = "CLOSED_THINKING_TEXT", None
        else:
            status, evidence = frontier(thought, case)
        counts[status] += 1
        if evidence is not None:
            first.setdefault(status, {"generated_tokens": count, **{k: v for k, v in evidence.items() if k != "cue"}})
        if status == "CONTRADICTION":
            require(type(bridge_count) is int and bridge_count > 0, "Missing exact bridge budget")
            fit = len(prompt) + count + bridge_count < capacity
            found = {"status": "TRIGGERED" if fit else "MATCHED_BRIDGE_NO_CONTEXT", "detection": evidence,
                     "checkpoint_generated_tokens": count,
                     "observation_reason": "CADENCE" if cadence else "OBSERVED_BRACE_TOKEN"}
            break

    closed, extra_counts, final_boxes, unmarked_box = character_diagnostics(codec, ids, prompt_open, case)
    status = ("NO_REVIEWED_OBLIGATION" if not active else
              "EARLY_BEFORE_CHECKPOINT" if len(ids) < FLOOR else "NO_ELIGIBLE_TRIGGER")
    expected = found or {"status": status}
    if found:
        reason = found["status"]
    elif not active:
        reason = "INACTIVE_SCOPE_CONTROL"
    elif status == "EARLY_BEFORE_CHECKPOINT":
        reason = status
    elif counts["CONDITION_SATISFIED"]:
        reason = "SCOPED_CLAIM_SATISFIED_NECESSARY_CONDITION"
    elif counts["LOCAL_SCOPE_ANCHOR_MISSING"]:
        reason = "OBSERVED_CLAIM_WITHOUT_REQUIRED_LOCAL_SCOPE"
    elif extra_counts["CONTRADICTION"]:
        reason = "CHARACTER_FRONTIER_CONTRADICTION_OUTSIDE_OBSERVED_POLLS"
    elif not extra_counts and final_boxes:
        reason = "INTEGER_BOX_ONLY_IN_FINAL"
    elif extra_counts:
        reason = "THINKING_INTEGER_BOX_WITHOUT_ELIGIBLE_SCOPED_DECLARATION"
    elif unmarked_box:
        reason = "INTEGER_BOX_WITHOUT_OBSERVED_THINKING_CHANNEL"
    elif stop == "CONTEXT_CAP":
        reason = "CAP_WITHOUT_ELIGIBLE_INTEGER_DECLARATION"
    else:
        reason = "NO_EXPLICIT_INTEGER_BOX"
    return expected, {"reason": reason, "native_stop": stop, "native_generated_tokens": len(ids),
                      "native_prompt_tokens": len(prompt), "thinking_boundary_count": len(closed),
                      "eligible_token_polls": eligible, "detector_calls": count_calls,
                      "observation_status_counts": dict(sorted(counts.items())),
                      "first_examples_at_actual_polls": first,
                      "full_text_character_box_diagnostics": dict(sorted(extra_counts.items())),
                      "final_explicit_integer_box_count": final_boxes,
                      "integer_box_without_thinking_or_closure": unmarked_box}


def confirm_checkpoint(expected, actual, native, folder, pinned_logits, bridge_count, result):
    receipt = actual["checkpoint"]
    k = expected["checkpoint_generated_tokens"]
    prefix = native["prompt_ids"] + native["generated_ids"][:k]
    require(receipt["position"] == len(prefix) and receipt["observed_generated_count"] == k
            and receipt["observed_prefix_sha256"] == ids_digest(prefix), "Recorded checkpoint prefix differs")
    rng = base64.b64decode(receipt["rng_state_base64"], validate=True)
    logits = receipt["full_next_logits"]
    require(rng and digest(rng) == receipt["rng_sha256"] and logits["path"] == "checkpoint_logits.f32le"
            and logits["sha256"] == pinned_logits, "Snapshot evidence bytes are unbound")
    raw = (folder / "checkpoint_logits.f32le").read_bytes()
    require(len(raw) == 4 * logits["numel"] and digest(raw) == pinned_logits, "Frozen checkpoint logits differ")
    for arm_name in (GENERIC, TYPED):
        arm = result["arms"][arm_name]
        bridge = arm["bridge"]["token_ids"]
        require(len(bridge) == bridge_count == arm["teacher_forced_tokens"]
                and arm["generated_ids"][:k + bridge_count] == native["generated_ids"][:k] + bridge,
                "Actual branch bridge or input prefix differs")


def load_context(outcome_path, outcome_sha, packet_path):
    outcome = pinned(outcome_path, outcome_sha)
    require(outcome["status"] == "TWO_COMPLETE_WORKER_OUTCOMES_FROZEN_BEFORE_GOLD"
            and outcome["independent_questions"] == 8, "Requires both frozen terminal outcomes")
    rules = pinned(HERE / "D44_LIVE_RULE_FREEZE.json", outcome["rule_freeze_sha256"])
    stage = pinned(HERE / "D44_LIVE_STAGE_FREEZE.json", outcome["live_stage_freeze_sha256"])
    inputs = pinned(HERE / "D44_LIVE_INPUT_FREEZE_V2.json", outcome["input_freeze_sha256"])
    cohort = pinned(HERE / "D44_LIVE_COHORT_FREEZE.json", outcome["cohort_freeze_sha256"])
    launch = pinned(HERE / "D44_GPU_MAIN_LAUNCH.json", outcome["launch_sha256"])
    preflight = pinned(HERE / "D44_CPU_BRIDGE_PREFLIGHT_V2.json", stage["cpu_bridge_preflight_sha256"])
    packet_sha = stage["full_packet_sha256"]
    require(inputs["live_packet_sha256"] == launch["full_packet_sha256"] == preflight["packet_sha256"] == packet_sha
            and rules["model_manifest_sha256"] == preflight["model_manifest_sha256"]
            and digest((HERE / "d44_native_runner.py").read_bytes()) == stage["live_runner_sha256"]
            and digest((HERE / "obligation_trigger.py").read_bytes()) == inputs["trigger_sha256"]
            == preflight["trigger_source_sha256"], "Frozen detector, runner or packet identity differs")
    cases = unique_index(pinned(packet_path, packet_sha)["cases"], "case_id")
    approvals = unique_index(inputs["rows"], "case_id")
    budgets = unique_index(preflight["rows"], "case_id")
    require(list(cases) == list(approvals) == list(budgets) == [row["case_id"] for row in cohort["rows"]],
            "Question order differs from original frozen cohort")
    for case_id, case in cases.items():
        review = approvals[case_id]
        require(set(case) == {"case_id", "question", "question_sha256", "seed", "restart_seed", "obligation", "problem_kind"}
                and digest(case["question"]) == case["question_sha256"] == review["question_sha256"]
                and case["obligation"] == review["obligation"] and case["problem_kind"] == review["effective_problem_kind"],
                "Question-only runtime packet does not match its review")
    return outcome, rules, stage, preflight, cases, budgets


def run_audit(args):
    started = perf_counter()
    outcome, rules, stage, preflight, cases, budgets = load_context(args.outcome_freeze, args.expected_outcome_sha256,
                                                                    args.packet)
    codec = TextCodec(args.tokenizer_dir, preflight)
    rows = {}
    for i, (root, worker, bound) in enumerate(zip(args.worker_roots, outcome["workers"], stage["workers"], strict=True)):
        manifest = pinned(root / "manifest.json", worker["manifest_sha256"])
        summary = pinned(root / "summary.json", worker["summary_sha256"])
        planned = [row["case_id"] for row in worker["cases"]]
        require(i == worker["worker"] == manifest["worker"] and summary["status"] == "COMPLETE"
                and planned == bound["case_ids"] == manifest["case_ids"] == [r["case_id"] for r in summary["cases"]]
                and worker["runtime_freeze_sha256"] == bound["runtime_freeze_sha256"] == manifest["runtime_freeze_sha256"]
                and worker["packet_sha256"] == bound["staged_packet_sha256"] == manifest["shard_packet_sha256"]
                and manifest["full_packet_sha256"] == stage["full_packet_sha256"]
                and manifest["model_files"]["manifest_sha256"] == rules["model_manifest_sha256"]
                and manifest["context_capacity"] == rules["hard_context_capacity"], "Completed worker identity differs")
        for item, summary_row in zip(worker["cases"], summary["cases"], strict=True):
            case_id = item["case_id"]
            require(case_id in cases and case_id not in rows, "Unknown or duplicate completed case")
            folder = root / case_id
            result = pinned(folder / "result.json", item["result_sha256"])
            case, budget = cases[case_id], budgets[case_id].get("forced_tokens_per_arm")
            require(all(result[k] == case[k] for k in ("case_id", "question_sha256", "seed", "restart_seed")),
                    "Terminal result is not bound to its exact visible case")
            native = result["arms"][NATIVE]
            require(native["context_capacity"] == rules["hard_context_capacity"], "Native context differs")
            expected, diagnostic = replay(codec, case, native, budget)
            actual = result["trigger"]
            require({k: v for k, v in actual.items() if k != "checkpoint"} == expected
                    and actual["status"] == summary_row["trigger_status"], "Independent trigger receipt differs")
            require(diagnostic["eligible_token_polls"] == result["detector_eligible_token_polls"]
                    and diagnostic["detector_calls"] == result["detector_calls"], "Independent polling schedule differs")
            if expected["status"] == "TRIGGERED":
                confirm_checkpoint(expected, actual, native, folder, item["checkpoint_logits_sha256"], budget, result)
            else:
                require("checkpoint" not in actual and "checkpoint_logits_sha256" not in item,
                        "Unexpected checkpoint on an inactive decision")
            safe = {k: v for k, v in expected.items() if k != "detection"}
            if "detection" in expected:
                safe["detection"] = {k: v for k, v in expected["detection"].items() if k != "cue"}
            rows[case_id] = {"case_id": case_id, "result_sha256": item["result_sha256"], "verified_trigger": safe, **diagnostic}
    require(set(rows) == set(cases), "The audit must include the complete live cohort")
    ordered = [rows[case_id] for case_id in cases]
    return {"status": "PASS_EXACT_LIVE_TRIGGER_REPLAY_WITHOUT_LABELS", "outcome_freeze_sha256": args.expected_outcome_sha256,
            "tokenizer": codec.info, "rows": ordered, "reasons": dict(Counter(row["reason"] for row in ordered)),
            "scope": "Exact observed-token replay. Character-level diagnostics use finished native text only and authorize no action or accuracy claim.",
            "elapsed_seconds": perf_counter() - started}


def self_test(tokenizer_dir):
    preflight = json.loads((HERE / "D44_CPU_BRIDGE_PREFLIGHT_V2.json").read_bytes())
    codec = TextCodec(tokenizer_dir, preflight)
    case = {"question": "Find the least value.", "question_sha256": "a" * 64,
            "obligation": {"kind": "closed_interval", "args": [11, 70], "scope_patterns": [r"least value"],
                           "proof_sha256": "b" * 64, "review_sha256": "c" * 64, "cue": "Synthetic test cue."}}
    prompt = codec.prompt(case["question"])
    eos = min(codec.eos)
    opening = [codec.open]
    lead = "The ongoing proof continues. " * 140
    box = lambda n: "\n**Final Answer**\n\\boxed{" + str(n) + "}"

    def build(text, final="", capacity=None, eos_stop=True):
        ids = opening + codec.tokenizer.encode(text, add_special_tokens=False)
        if final:
            ids += [codec.close] + codec.tokenizer.encode(final, add_special_tokens=False)
        if eos_stop:
            ids.append(eos)
        return {"prompt_ids": prompt, "generated_ids": ids, "generated_sha256": ids_digest(ids),
                "context_capacity": capacity or (len(prompt) + len(ids) + (500 if eos_stop else 0)),
                "stop_reason": "EOS" if eos_stop else "CONTEXT_CAP", "final_cache_position": len(prompt) + len(ids) - 1,
                "text": codec.decode(ids)}

    examples = [
        (case, build(lead + "Least value." + box(90)), "TRIGGERED"),
        (case, build(lead + "Least value." + box(22)), "SCOPED_CLAIM_SATISFIED_NECESSARY_CONDITION"),
        (case, build(lead + "Intermediate object." + box(90)), "OBSERVED_CLAIM_WITHOUT_REQUIRED_LOCAL_SCOPE"),
        (case, build(lead, final=box(90)), "INTEGER_BOX_ONLY_IN_FINAL"),
        (case, build("Least value." + box(90)), "EARLY_BEFORE_CHECKPOINT"),
        (case, build(lead, eos_stop=False), "CAP_WITHOUT_ELIGIBLE_INTEGER_DECLARATION"),
        ({**case, "obligation": None}, build(lead + box(90)), "INACTIVE_SCOPE_CONTROL"),
    ]
    for question, native, reason in examples:
        _, audited = replay(codec, question, native, 25)
        require(audited["reason"] == reason, f"Synthetic reason differs: {audited['reason']} instead of {reason}")
    native = build(lead + "Least value." + box(90))
    native["context_capacity"] = len(native["prompt_ids"]) + len(native["generated_ids"]) + 1
    actual, audited = replay(codec, case, native, 25)
    require(actual["status"] == audited["reason"] == "MATCHED_BRIDGE_NO_CONTEXT", "Insufficient context control differs")
    return {"status": "PASS_SYNTHETIC_EXACT_TOKENIZER_TRIGGER_AUDIT", "synthetic_controls": len(examples) + 1,
            "tokenizer": codec.info}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--self-test", action="store_true")
    cli.add_argument("--tokenizer-dir", type=Path, default=TOKENIZER)
    cli.add_argument("--outcome-freeze", type=Path)
    cli.add_argument("--expected-outcome-sha256")
    cli.add_argument("--worker-roots", type=Path, nargs=2)
    cli.add_argument("--packet", type=Path)
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    if args.self_test:
        print(json.dumps(self_test(args.tokenizer_dir)))
    else:
        if not all((args.outcome_freeze, args.expected_outcome_sha256, args.worker_roots, args.packet, args.output)):
            cli.error("A terminal audit requires the outcome freeze and SHA, both worker roots, the frozen packet, and a new output")
        require(not args.output.exists() and len({path.resolve() for path in args.worker_roots}) == 2,
                "Requires distinct terminal roots and a new output")
        report = run_audit(args)
        encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        with args.output.open("xb") as stream:
            stream.write(encoded)
        print(json.dumps({"status": report["status"], "sha256": digest(encoded), "reasons": report["reasons"]}))
