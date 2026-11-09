"""Verify both complete D4.4 workers before opening the new cohort's labels."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
D43 = HERE.parent / "phase5d43_answer_refutation_20261110"
sys.path.append(str(D43))
from extract_candidates import STOP_TOKENS, THINK_CLOSE, final_readout, load_author_scorer
from obligation_trigger import approved_obligation, check, detect


ARMS = ("NativeContinue", "GenericReminder", "TypedObligation", "IndependentRestart")
NATIVE, GENERIC, TYPED, RESTART = ARMS
BASELINES = (NATIVE, GENERIC, RESTART)
PAID = ("forward_calls", "forward_input_tokens", "attention_pairs")
COORDINATES = PAID[1:]
GOLD_COLUMNS = ("problem_id", "year", "part", "problem_number", "draw_index", "source_record_sha256",
                "accepted_answer_integers")
EOS_TEXT = {STOP_TOKENS["im_end"]: "<|im_end|>", STOP_TOKENS["endoftext"]: "<|endoftext|>"}
MANIFEST_SHA256 = "f1b27b3528a8f6d8b23db46d394bade22067bdbae973d87f9bb5182746f86453"
EXACT_D43_READOUT_SHA256 = "7289666129fc31310bbc2bda7e2b089385055fc68d6c1d2b71975e7ce0ddae50"
GENERIC_CUE = "Recheck the reasoning so far. Continue solving the original question and verify the final result."
GENERIC_BASES = ("Review.", "Recheck your work and continue.", GENERIC_CUE)
GENERIC_CLAUSES = (
    "Check the assumptions you have used.", "Go over the important steps in order.",
    "Verify the calculations and transformations.", "Return to a step if its justification is unclear.",
    "Check whether the conclusion follows from the work.", "Make sure the final response addresses the original request.",
    "Continue until you can state the result clearly.",
)


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def canonical(value) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())


def ids_digest(ids: list[int]) -> str:
    return digest(json.dumps(ids, separators=(",", ":")).encode())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def index(rows: list[dict], key: str) -> dict:
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), f"Duplicate {key}")
    return result


def pinned(path: Path, expected: str) -> tuple[dict, str]:
    raw = path.read_bytes()
    observed = digest(raw)
    require(observed == expected, f"Frozen bytes differ for {path.name}")
    return json.loads(raw), observed


def work(ledger: list[dict]) -> dict:
    require(all(type(row["input_tokens"]) is int and row["input_tokens"] > 0
                and type(row["past_tokens"]) is int and row["past_tokens"] >= 0
                and row["position_start"] == row["past_tokens"] for row in ledger), "Invalid forward position ledger")
    return {"forward_calls": len(ledger),
            "forward_input_tokens": sum(row["input_tokens"] for row in ledger),
            "attention_pairs": sum(row["input_tokens"] * row["past_tokens"] +
                                   row["input_tokens"] * (row["input_tokens"] + 1) // 2 for row in ledger)}


def contiguous(ledger: list[dict], start: int, end: int) -> None:
    pos = start
    for row in ledger:
        require(row["past_tokens"] == pos, "Non-contiguous paid forward stream")
        pos += row["input_tokens"]
    require(pos == end, "Paid forward stream does not reach recorded terminal cache position")


def verify_terminal(arm: dict, capacity: int) -> None:
    ids = arm["generated_ids"]
    prompt = arm["prompt_ids"]
    stop = arm["stop_reason"]
    total = len(prompt) + len(ids)
    require(bool(ids) and bool(prompt) and all(type(token) is int and token >= 0 for token in prompt + ids)
            and arm["generated_sha256"] == ids_digest(ids) and arm["context_capacity"] == capacity
            and arm["final_cache_position"] == total - 1 and total <= capacity,
            "Invalid terminal token or context receipt")
    require(stop in {"EOS", "CONTEXT_CAP"} and arm["EOS"] is (stop == "EOS")
            and arm["hit_context_cap"] is (stop == "CONTEXT_CAP")
            and (stop == "EOS") == (ids[-1] in EOS_TEXT)
            and not any(token in EOS_TEXT for token in ids[:-1])
            and (stop != "CONTEXT_CAP" or total == capacity), "Invalid EOS or cap receipt")
    require(type(arm["text"]) is str and type(arm["think_closed"]) is bool, "Malformed terminal readout")
    if stop == "EOS":
        require(arm["text"].endswith(EOS_TEXT[ids[-1]]), "Decoded EOS control token differs")


def allocation(result: dict, capacity: int) -> tuple[dict, dict]:
    """Reconcile actual forward work and logically allocate the shared native prefix."""
    arms = result["arms"]
    native = arms[NATIVE]
    prompt = native["prompt_ids"]
    p = len(prompt)
    stages = {f"{name}:{stage}" for name, allowed in (
        (NATIVE, ("prefill", "decode")), (RESTART, ("prefill", "decode")),
        (GENERIC, ("bridge", "decode")), (TYPED, ("bridge", "decode"))) for stage in allowed}
    allowed = stages | {"ParityRestore:decode"}
    ledger = result["paid_forward_ledger"]
    require(all(row["stage"] in allowed for row in ledger), "Unknown charged model forward stage")
    require(work(ledger) == result["actual_paid_work"], "Physical forward work does not reconcile")
    per_arm = {name: [row for row in ledger if row["stage"].startswith(name + ":")] for name in ARMS}
    parity_rows = [row for row in ledger if row["stage"] == "ParityRestore:decode"]
    for name, arm in arms.items():
        verify_terminal(arm, capacity)
        require(arm["prompt_ids"] == prompt and work(per_arm[name]) == arm["paid_work"], "Changed prompt or arm paid work")
    for name in (NATIVE, RESTART):
        arm = arms[name]
        prefill = [row for row in per_arm[name] if row["stage"] == name + ":prefill"]
        decode = [row for row in per_arm[name] if row["stage"] == name + ":decode"]
        contiguous(prefill, 0, p)
        contiguous(decode, p, arm["final_cache_position"])
        require(per_arm[name] == prefill + decode and all(row["input_tokens"] == 1 for row in decode)
                and arm["sampled_continuation_tokens"] == len(arm["generated_ids"])
                and arm["teacher_forced_tokens"] == 0, "Native or restart work shape differs")
    logical = {name: dict(arms[name]["paid_work"]) for name in (NATIVE, RESTART)}
    parity = result["restore_parity"]
    trigger = result["trigger"]
    require(trigger["status"] in {"TRIGGERED", "NO_REVIEWED_OBLIGATION", "EARLY_BEFORE_CHECKPOINT",
                                  "NO_ELIGIBLE_TRIGGER", "MATCHED_BRIDGE_NO_CONTEXT"}, "Unknown trigger terminal state")
    if trigger["status"] != "TRIGGERED":
        require(parity["status"] == "NOT_TRIGGERED" and not parity_rows, "Unexpected parity work for no-trigger case")
        for name in (GENERIC, TYPED):
            arm = arms[name]
            require(arm["mode"] == "REUSED_NATIVE_NO_ACTION" and arm["reuse_reason"] == trigger["status"]
                    and not per_arm[name] and arm["sampled_continuation_tokens"] == arm["teacher_forced_tokens"] == 0
                    and all(arm[key] == native[key] for key in (
                        "generated_ids", "generated_sha256", "text", "final_response", "EOS", "hit_context_cap",
                        "stop_reason", "think_closed", "final_cache_position")), "No-trigger arm differs from native reuse")
            logical[name] = dict(logical[NATIVE])
        return logical, work(parity_rows)
    k = trigger["checkpoint_generated_tokens"]
    checkpoint = trigger["checkpoint"]
    prefix = native["generated_ids"][:k]
    end = p + k
    require(type(k) is int and 256 <= k < len(native["generated_ids"])
            and checkpoint["position"] == end and checkpoint["observed_generated_count"] == k
            and checkpoint["observed_prefix_sha256"] == ids_digest(prompt + prefix)
            and parity["status"] == "PASS" and parity["snapshot_logits_exact"] is True and parity["snapshot_rng_exact"] is True
            and parity["observed"] == parity["expected_from_native"] == native["generated_ids"][k:k + 12]
            and bool(parity["observed"]) and work(parity_rows) == parity["paid_work"], "Triggered native checkpoint parity differs")
    prefix_ledger = [row for row in per_arm[NATIVE] if row["past_tokens"] < end]
    contiguous(prefix_ledger, 0, end)
    require(all(row["input_tokens"] == 1 for row in parity_rows), "Unexpected triggered parity forwards")
    parity_forwarded = sum(row["input_tokens"] for row in parity_rows)
    contiguous(parity_rows, end, end + parity_forwarded)
    terminal_in_probe = k + len(parity["observed"]) == len(native["generated_ids"])
    require(parity_forwarded == len(parity["observed"]) - int(terminal_in_probe), "Unexpected parity token cost")
    require(arms[GENERIC]["teacher_forced_tokens"] == arms[TYPED]["teacher_forced_tokens"] > 0,
            "Matched bridge token lengths differ")
    for name in (GENERIC, TYPED):
        arm = arms[name]
        bridge = arm["bridge"]["token_ids"]
        n = len(bridge)
        bridge_rows = [row for row in per_arm[name] if row["stage"] == name + ":bridge"]
        decode_rows = [row for row in per_arm[name] if row["stage"] == name + ":decode"]
        require(arm["mode"] == "TRIGGERED" and arm["bridge"]["forced_tokens"] == arm["teacher_forced_tokens"] == n
                and arm["generated_ids"][:k + n] == prefix + bridge
                and arm["sampled_continuation_tokens"] == len(arm["generated_ids"]) - k - n
                and per_arm[name] == bridge_rows + decode_rows
                and all(row["input_tokens"] == 1 for row in per_arm[name]), "Branch prefix, bridge, or suffix cost differs")
        contiguous(bridge_rows, end, end + n)
        contiguous(decode_rows, end + n, arm["final_cache_position"])
        logical[name] = work(prefix_ledger + per_arm[name])
    return logical, work(parity_rows)


def answer_readout(scorer, arm: dict) -> tuple[int | None, str]:
    if arm["stop_reason"] != "EOS":
        return None, "CONTEXT_CAP"
    text = arm["text"].removesuffix(EOS_TEXT[arm["generated_ids"][-1]])
    start = len("<think>") if text.startswith("<think>") else 0
    end = text.find(THINK_CLOSE)
    if end < 0:
        return None, "NO_CLOSED_THINKING"
    if not arm["think_closed"] or text.count(THINK_CLOSE) != 1 or "<think>" in text[start:]:
        return None, "AMBIGUOUS_THINKING_BOUNDARY"
    answer = final_readout(scorer, text[end + len(THINK_CLOSE):], end + len(THINK_CLOSE))
    return answer["value"], answer["status"]


def verify_packet(packet: dict, frozen: dict, cohort: dict) -> dict:
    expected = index(cohort["rows"], "case_id")
    approved = index(frozen["rows"], "case_id")
    cases = index(packet["cases"], "case_id")
    require(list(expected) == list(approved) == list(cases) and len(expected) == 8, "Changed ordered live cohort")
    keys = ("case_id", "question_sha256", "seed", "restart_seed")
    for case_id, case in cases.items():
        reference = expected[case_id]
        review = approved[case_id]
        require(all(case[key] == reference[key] == review[key] for key in keys)
                and digest(case["question"].encode()) == reference["question_sha256"]
                and case["problem_kind"] == review["effective_problem_kind"]
                and case["obligation"] == review["obligation"], "Live packet does not match reviewed case")
        require(case["obligation"] is None or approved_obligation(case) is not None, "Invalid reviewed obligation")
    require(sum(case["obligation"] is not None for case in cases.values()) == frozen["reviewed_active_scope"],
            "Changed count of approved case obligations")
    return cases


def verify_trigger(result: dict, case: dict) -> None:
    trigger = result["trigger"]
    item = case["obligation"]
    status = trigger["status"]
    require((status == "NO_REVIEWED_OBLIGATION") == (item is None), "Inactive review and trigger disagree")
    if status not in {"TRIGGERED", "MATCHED_BRIDGE_NO_CONTEXT"}:
        return
    detected = trigger["detection"]
    value = detected["observed_candidate"]
    require(item is not None and type(value) is int and detected["status"] == "COMMITTED_INTEGER_REFUTED",
            "Missing actual arithmetic refutation at trigger")
    violated, arithmetic = check(value, item)
    require(violated and detected["arithmetic"] == arithmetic and detected["predicate_kind"] == item["kind"]
            and detected["predicate_args"] == item["args"]
            and all(detected[key] == item[key] for key in ("question_sha256", "proof_sha256", "review_sha256", "cue")),
            "Refutation is unbound or fails independent arithmetic")
    start, end = detected["source_char_span"]
    require(type(start) is int and type(end) is int and 0 <= start < end, "Malformed refutation text span")
    # Test the frozen receipt against visible native text only. The checkpoint
    # prefix's exact token identity is checked separately from these characters.
    fragments = result["arms"][NATIVE]["text"].split("<think>")
    require(any(len(fragment) >= end and detect(case, fragment[:end]) == detected for fragment in fragments),
            "Frozen frontier and scope anchors are not found in native text")
    if status == "TRIGGERED":
        generic, typed = (result["arms"][name]["bridge"] for name in (GENERIC, TYPED))
        variant = generic.get("fluent_variant")
        expected_generic = GENERIC_CUE
        if variant is not None:
            base, clauses = variant["base_index"], variant["clause_indices"]
            require(type(base) is int and 0 <= base < len(GENERIC_BASES)
                    and clauses == sorted(set(clauses))
                    and all(type(i) is int and 0 <= i < len(GENERIC_CLAUSES) for i in clauses),
                    "Unknown fluent generic variant")
            expected_generic = " ".join((GENERIC_BASES[base], *(GENERIC_CLAUSES[i] for i in clauses)))
            require(variant["unpadded_text"] == expected_generic, "Fluent variant text differs")
        for bridge in (generic, typed):
            if "unpadded_tokens" in bridge:
                pad = bridge["padding_tokens"]
                require(type(pad) is int and 0 <= pad <= 8
                        and bridge["unpadded_tokens"] + pad == bridge["forced_tokens"]
                        and (not pad or bridge["token_ids"][-pad:] == [bridge["padding_token_id"]] * pad),
                        "Bridge padding differs from frozen residual policy")
        require(generic["text"].strip() == expected_generic and typed["text"].strip() == item["cue"].strip(),
                "Delivered bridge differs from approved content")


def verify_manifest(manifest: dict, worker: dict, rules: dict, runtime_freeze: dict | None) -> dict:
    identity = manifest["execution_identity"]
    expected_model = rules["model_manifest_sha256"]
    require(manifest["mode"] == "main" and manifest["runtime_freeze_sha256"] == worker["runtime_freeze_sha256"]
            and identity["model_sha256"] == manifest["model_files"]["manifest_sha256"] == expected_model
            and manifest["backend"] == identity["backend"] == "sdpa"
            and manifest["dtype"] == identity["dtype"] == "FP16"
            and manifest["transformers"] == "4.55.2" and manifest["torch"] == "2.8.0+cu128"
            and manifest["context_capacity"] == rules["hard_context_capacity"]
            and manifest["scientific_new_token_cap"] is None and rules["scientific_output_token_limit"] is None
            and manifest["sampling"] == identity["sampling_config"]
            and all(manifest["sampling"][k] == v for k, v in rules["sampling"].items()),
            "Worker runtime/model does not match frozen rules")
    if runtime_freeze is not None:
        files = index(runtime_freeze["files"], "path")
        require(files["legacy/native_engine.py"]["sha256"] == identity["engine_sha256"], "Runtime engine asset differs")
        if "packet_sha256" in worker:
            require(worker["packet_sha256"] in {row["sha256"] for row in files.values()}, "Staged input packet hash differs")
    if "input_sha256" in manifest and "packet_sha256" in worker:
        require(manifest["input_sha256"] == worker["packet_sha256"], "Executed input packet hash differs")
    return {k: identity[k] for k in ("model_sha256", "tokenizer_sha256", "engine_sha256", "backend", "dtype", "sampling_config")}


def prepare(worker_roots: list[Path], workers: list[dict], rules: dict, cases: dict,
            runtime_freezes: list[Path]) -> tuple[dict, list[dict]]:
    """Validate all terminal artifacts and their accounting before any label read."""
    require(len(workers) == len(worker_roots) == 2 and len({p.resolve() for p in worker_roots}) == 2
            and len(runtime_freezes) in {0, 2}, "Exactly two independent worker roots required")
    prepared, reports, fingerprint = {}, [], None
    for i, (root, worker) in enumerate(zip(worker_roots, workers)):
        summary, _ = pinned(root / "summary.json", worker["summary_sha256"])
        manifest, _ = pinned(root / "manifest.json", worker["manifest_sha256"])
        require(summary["status"] == "COMPLETE", "Worker must finish cleanly before scoring")
        runtime = pinned(runtime_freezes[i], worker["runtime_freeze_sha256"])[0] if runtime_freezes else None
        bound = verify_manifest(manifest, worker, rules, runtime)
        require(fingerprint is None or bound == fingerprint, "Workers use different execution assets")
        fingerprint = bound
        expected = index(worker["cases"], "case_id")
        observed = index(summary["cases"], "case_id")
        require(bool(expected) and list(expected) == list(observed), "Worker summary and outcome freeze differ")
        for case_id, summary_row in observed.items():
            require(case_id in cases and case_id not in prepared, "Repeated or unknown worker case")
            case = cases[case_id]
            result, sha = pinned(root / case_id / "result.json", expected[case_id]["result_sha256"])
            require(all(result[key] == case[key] for key in ("case_id", "seed", "restart_seed", "question_sha256"))
                    and tuple(result["arm_order"]) == ARMS and tuple(result["arms"]) == ARMS
                    and result["trigger"]["status"] == summary_row["trigger_status"]
                    and result["restore_parity"]["status"] == summary_row["parity"]
                    and summary_row["terminal_by_arm"] == {name: result["arms"][name]["stop_reason"] for name in ARMS},
                    "Terminal case identity, arms or summary differs")
            verify_trigger(result, case)
            logical, parity_work = allocation(result, rules["hard_context_capacity"])
            checkpoint_blob_verified = False
            if result["trigger"]["status"] == "TRIGGERED":
                checkpoint = result["trigger"]["checkpoint"]
                require(digest(base64.b64decode(checkpoint["rng_state_base64"], validate=True)) == checkpoint["rng_sha256"],
                        "Checkpoint RNG hash differs")
                logits = checkpoint["full_next_logits"]
                require(logits["path"] == "checkpoint_logits.f32le" and logits["dtype"] == "little_endian_float32",
                        "Unexpected checkpoint logits format")
                path = root / case_id / logits["path"]
                if path.exists():
                    blob = path.read_bytes()
                    require(len(blob) == logits["numel"] * 4 and digest(blob) == logits["sha256"],
                            "Checkpoint logits blob hash differs")
                    checkpoint_blob_verified = True
            prepared[case_id] = {"result": result, "result_sha256": sha, "logical_work": logical,
                                 "parity_work": parity_work, "checkpoint_blob_verified": checkpoint_blob_verified}
        reports.append({"worker_index": i, "verified_manifest_sha256": worker["manifest_sha256"],
                        "verified_summary_sha256": worker["summary_sha256"],
                        "runtime_freeze_sha256": worker["runtime_freeze_sha256"],
                        "runtime_freeze_bytes_checked": bool(runtime_freezes),
                        "cases": len(expected), "execution_asset_identity": bound,
                        "model_load_wall_seconds": manifest["model_load_wall_seconds"],
                        "elapsed_including_model_load_seconds": summary["elapsed_including_model_load_seconds"]})
    require(set(prepared) == set(cases) and len(prepared) == rules["independent_questions"] == 8,
            "Both workers together must cover exactly eight questions")
    return prepared, reports


def load_gold(source: Path, cohort: dict) -> tuple[dict, dict]:
    """Open only the reviewed source identities and accepted integer sets."""
    import pyarrow.parquet as pq

    manifest, manifest_sha = pinned(source / "PUBLICATION_MANIFEST.json", MANIFEST_SHA256)
    require(manifest["repo_id"] == "suryadv/qwen3-8b-aime-2009-2024-16x", "Wrong upstream label manifest")
    file = index(manifest["files"], "path")["data/draw-00.parquet"]
    raw = (source / file["path"]).read_bytes()
    require(len(raw) == file["size"] and digest(raw) == file["sha256"] == cohort["question_source_shard_sha256"],
            "Draw00 bytes do not match the live cohort source")
    wanted = index(cohort["rows"], "case_id")
    rows = pq.read_table(BytesIO(raw), columns=list(GOLD_COLUMNS), use_threads=False,
                         filters=[("problem_id", "in", sorted(wanted))]).to_pylist()
    matches = index(rows, "problem_id")
    require(set(matches) == set(wanted), "Gold projection differs from the fixed new cohort")
    labels = {}
    for case_id, row in matches.items():
        source_row = wanted[case_id]
        require(row["draw_index"] == 0 and all(row[key] == source_row[key] for key in
                ("year", "part", "problem_number", "source_record_sha256")), "Gold projection identity differs")
        accepted = row["accepted_answer_integers"]
        require(isinstance(accepted, list) and bool(accepted)
                and all(type(n) is int and 0 <= n <= 999 for n in accepted), "Invalid projected accepted integers")
        labels[case_id] = frozenset(accepted)
    return labels, {"manifest_sha256": manifest_sha, "verified_shard": file, "projection_columns": list(GOLD_COLUMNS),
                    "projected_rows": len(rows), "gold_projection_sha256": canonical([matches[k] for k in sorted(matches)])}


def sum_work(rows: list[dict]) -> dict:
    return {key: sum(row[key] for row in rows) for key in PAID}


def transition(typed_correct: bool, baseline_correct: bool) -> str:
    if typed_correct and not baseline_correct:
        return "REPAIR"
    if baseline_correct and not typed_correct:
        return "HARM"
    return "BOTH_CORRECT" if typed_correct else "BOTH_NOT_CORRECT"


def score(prepared: dict, cases: dict, labels: dict, scorer) -> dict:
    require(set(prepared) == set(cases) == set(labels), "Scoring case identities differ")
    rows = []
    for case_id, case in cases.items():
        item = prepared[case_id]
        result = item["result"]
        accepted = labels[case_id]
        outputs = {}
        for name, arm in result["arms"].items():
            value, readout = answer_readout(scorer, arm)
            outputs[name] = {
                "terminal_status": arm["stop_reason"], "readout_status": readout,
                "correctness": "NO_ELIGIBLE_FINAL" if value is None else "CORRECT" if value in accepted else "INCORRECT",
                "reused_native_no_action": arm.get("mode") == "REUSED_NATIVE_NO_ACTION",
                "generated_tokens_in_full_trace": len(arm["generated_ids"]),
                "physically_sampled_tokens_for_arm": arm["sampled_continuation_tokens"],
                "teacher_forced_tokens": arm["teacher_forced_tokens"],
                "physical_forward_work": arm["paid_work"], "logical_forward_work": item["logical_work"][name],
                "observed_arm_wall_seconds": arm["elapsed_seconds"],
                "restore_copy_cost": arm.get("restore_cost"),
            }
        typed = outputs[TYPED]
        typed_correct = typed["correctness"] == "CORRECT"
        comparisons = {}
        for name in BASELINES:
            baseline = outputs[name]
            baseline_correct = baseline["correctness"] == "CORRECT"
            excess = [key for key in COORDINATES
                      if typed["logical_forward_work"][key] > baseline["logical_forward_work"][key]]
            credited = typed_correct and not excess
            comparisons[name] = {
                "raw_pair": transition(typed_correct, baseline_correct),
                "typed_endpoint_within_both_work_coordinates": not excess,
                "typed_endpoint_censored_by": excess,
                "typed_credited_correct": credited,
                "cost_censored_pair": transition(credited, baseline_correct),
            }
        trigger = result["trigger"]
        condition = case["obligation"]
        active_detection = trigger.get("detection")
        rows.append({
            "case_id": case_id, "question_sha256": case["question_sha256"], "terminal_result_sha256": item["result_sha256"],
            "trigger_status": trigger["status"], "trigger_checkpoint_generated_tokens": trigger.get("checkpoint_generated_tokens"),
            "restore_parity_status": result["restore_parity"]["status"],
            "checkpoint_logits_blob_bytes_verified": item.get("checkpoint_blob_verified", False),
            "approved_condition_refutes_an_accepted_value": bool(condition and any(check(x, condition)[0] for x in accepted)),
            "detected_refutation_value_is_accepted": None if active_detection is None else
                active_detection["observed_candidate"] in accepted,
            "arms": outputs, "comparisons": comparisons,
            "physical_all_arm_and_diagnostic_forward_work": result["actual_paid_work"],
            "physical_restore_parity_forward_work": item["parity_work"],
            "checkpoint_copy_cost": trigger.get("checkpoint", {}).get("copy_cost"),
            "restore_parity_copy_cost": result["restore_parity"].get("restore_cost"),
            "restore_parity_wall_seconds": result["restore_parity"].get("elapsed_seconds"),
            "detector_calls": result["detector_calls"], "detector_wall_seconds": result["detector_wall_seconds"],
            "detector_eligible_token_polls": result.get("detector_eligible_token_polls"),
            "detector_total_polling_wall_seconds": result.get("detector_total_polling_wall_seconds"),
            "full_case_wall_seconds": result["elapsed_seconds"], "peak_allocated_bytes": result["peak_allocated_bytes"],
            "peak_reserved_bytes": result.get("peak_reserved_bytes"),
        })
    by_arm = {}
    for name in ARMS:
        arm_rows = [row["arms"][name] for row in rows]
        by_arm[name] = {
            "correct": sum(row["correctness"] == "CORRECT" for row in arm_rows),
            "denominator": len(rows), "native_eos": sum(row["terminal_status"] == "EOS" for row in arm_rows),
            "context_cap": sum(row["terminal_status"] == "CONTEXT_CAP" for row in arm_rows),
            "native_eos_without_eligible_final": sum(row["terminal_status"] == "EOS" and
                                                   row["correctness"] == "NO_ELIGIBLE_FINAL" for row in arm_rows),
            "reused_native_no_action": sum(row["reused_native_no_action"] for row in arm_rows),
            "logical_forward_work": sum_work([row["logical_forward_work"] for row in arm_rows]),
            "physical_forward_work": sum_work([row["physical_forward_work"] for row in arm_rows]),
            "observed_arm_wall_seconds_sum": sum(row["observed_arm_wall_seconds"] for row in arm_rows),
        }
    strongest = min(BASELINES, key=lambda name: (
        -by_arm[name]["correct"], *[by_arm[name]["logical_forward_work"][key] for key in COORDINATES],
        BASELINES.index(name)))
    pairs = {}
    for name in BASELINES:
        compared = [row["comparisons"][name] for row in rows]
        pair_summary = {}
        for label, key in (("raw", "raw_pair"), ("cost_censored", "cost_censored_pair")):
            counts = Counter(row[key] for row in compared)
            pair_summary[label] = {"repairs": counts["REPAIR"], "harms": counts["HARM"],
                                   "net_repairs": counts["REPAIR"] - counts["HARM"],
                                   "both_correct": counts["BOTH_CORRECT"], "both_not_correct": counts["BOTH_NOT_CORRECT"]}
        pair_summary["typed_correct_within_work"] = sum(row["typed_credited_correct"] for row in compared)
        pair_summary["typed_censored_endpoints"] = sum(bool(row["typed_endpoint_censored_by"]) for row in compared)
        pairs[name] = pair_summary
    native_losses = Counter()
    for row in rows:
        if row["arms"][NATIVE]["correctness"] != "CORRECT":
            continue
        typed = row["arms"][TYPED]
        if typed["correctness"] == "INCORRECT":
            native_losses["explicit_incorrect"] += 1
        elif typed["correctness"] == "NO_ELIGIBLE_FINAL":
            native_losses["context_cap" if typed["terminal_status"] == "CONTEXT_CAP" else "native_eos_missing_final"] += 1
    net = pairs[strongest]["cost_censored"]["net_repairs"]
    return {
        "status": "D44_LIVE_FIXED_COHORT_SCORED", "question_count": len(rows), "by_arm": by_arm,
        "trigger_counts": dict(sorted(Counter(row["trigger_status"] for row in rows).items())),
        "typed_vs_baselines": pairs, "strongest_baseline": strongest,
        "native_correct_to_typed_losses": {key: native_losses[key] for key in (
            "explicit_incorrect", "context_cap", "native_eos_missing_final")},
        "retention_gate": {"minimum_net_repairs_at_strongest_work_envelope": 2,
                           "observed_net_repairs": net,
                           "maximum_unambiguous_native_correct_to_typed_wrong": 0,
                           "observed_unambiguous_native_correct_to_typed_wrong": native_losses["explicit_incorrect"],
                           "passed": net >= 2 and not native_losses["explicit_incorrect"]},
        "witness_conflicts_require_review": any(row["approved_condition_refutes_an_accepted_value"] or
                                               row["detected_refutation_value_is_accepted"] is True for row in rows),
        "experimental_physical_forward_work": sum_work([row["physical_all_arm_and_diagnostic_forward_work"] for row in rows]),
        "experimental_restore_parity_work": sum_work([row["physical_restore_parity_forward_work"] for row in rows]),
        "rows": rows,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("rules", "cohort", "inputs", "packet", "outcome", "source", "author-scorer", "output"):
        cli.add_argument("--" + key, type=Path, required=True)
    cli.add_argument("--expected-outcome-sha256", required=True)
    cli.add_argument("--worker-root", type=Path, action="append", required=True)
    cli.add_argument("--runtime-freeze", type=Path, action="append", default=[])
    cli.add_argument("--smoke", type=Path)
    args = cli.parse_args()
    require(not args.output.exists(), "Scoring output exists")
    outcome, outcome_sha = pinned(args.outcome, args.expected_outcome_sha256)
    rules, rule_sha = pinned(args.rules, outcome["rule_freeze_sha256"])
    cohort, cohort_sha = pinned(args.cohort, outcome["cohort_freeze_sha256"])
    inputs, input_sha = pinned(args.inputs, outcome["input_freeze_sha256"])
    require(rules["status"] == "FROZEN_BEFORE_FRESH_NATIVE_GENERATION"
            and rules["arms"] == ["native", "generic", "typed", "restart"]
            and cohort["status"] == "LIVE_PILOT_COHORT_FROZEN_WITHOUT_RESPONSES_OR_GOLD"
            and cohort["source_revision"] == "c34143c92856d9b90fdb9c808c7e66070dcab9a1"
            and inputs["status"] == "EXACT_LIVE_INPUT_FROZEN_BEFORE_NATIVE_GENERATION"
            and inputs["rules_sha256"] == rule_sha and inputs["cohort_freeze_sha256"] == cohort_sha
            and inputs["trigger_sha256"] == digest((HERE / "obligation_trigger.py").read_bytes())
            and EXACT_D43_READOUT_SHA256 == digest((D43 / "extract_candidates.py").read_bytes()),
            "Unbound pre-generation rules, cohort, parser or trigger")
    packet, packet_sha = pinned(args.packet, inputs["live_packet_sha256"])
    cases = verify_packet(packet, inputs, cohort)
    prepared, workers = prepare(args.worker_root, outcome["workers"], rules, cases, args.runtime_freeze)
    smoke_report = None
    if args.smoke is not None:
        smoke, smoke_sha = pinned(args.smoke, outcome["smoke_sha256"])
        require(smoke["status"] == "PASS" and work(smoke["paid_forward_ledger"]) == smoke["paid_work"],
                "Smoke physical work does not reconcile")
        smoke_report = {"sha256": smoke_sha, "paid_work": smoke["paid_work"],
                        "elapsed_seconds": smoke["elapsed_seconds"], "peak_allocated_bytes": smoke["peak_allocated_bytes"],
                        "peak_reserved_bytes": smoke.get("peak_reserved_bytes")}
    scorer = load_author_scorer(args.author_scorer)
    started_wall, started_cpu = perf_counter_ns(), thread_time_ns()
    labels, source = load_gold(args.source, cohort)
    report = score(prepared, cases, labels, scorer)
    report.update({
        "input_sha256": {"outcome": outcome_sha, "rules": rule_sha, "cohort": cohort_sha,
                         "reviewed_input": input_sha, "live_packet": packet_sha,
                         "author_scorer": digest(args.author_scorer.read_bytes())},
        "scorer_sha256": digest(Path(__file__).read_bytes()), "workers": workers, "gold_source": source,
        "separate_smoke_overhead": smoke_report, "scoring_wall_ns": perf_counter_ns() - started_wall,
        "scoring_cpu_ns": thread_time_ns() - started_cpu,
        "cost_scope": "Causal position pairs are counted model work, not measured FLOPs or runtime. "
                      "Restore parity and unrelated experimental forwards are separate from logically allocated arm work.",
    })
    with args.output.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
    print(f"{report['status']}: {len(report['rows'])} questions")


if __name__ == "__main__":
    main()
