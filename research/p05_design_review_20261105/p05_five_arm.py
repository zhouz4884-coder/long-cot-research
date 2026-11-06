#!/usr/bin/env python3
"""Frozen five-arm P0.5. No scheduler submission, downloads, training or retry.

Real: set CVD to one allocated/explicit UUID, then pass --standalone-gpu UUID.
CPU: --model tiny-random --device cpu --cpu-interface-check (three control cases).
Primary free generations run first. Auxiliary Y/Z forced-prefix diagnostics run
afterwards, with separate completion flags and real forward/token accounting.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import traceback
from collections import Counter


BASE_SHA = "246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b"
CASES_SHA = "6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27"
EXTRACTOR_SHA = "c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed"
MODEL_SHA = "37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"
COMMON = "按题目原始定义核算，不预设复核记录正确。\n"
DIRECT = "只写“最终答案：整数”。\n"
ONELINE = "先写一行必要计算，再写“最终答案：整数”。\n"
Z_SCAFFOLD = "最终答案："
Y_SCAFFOLD = "y ="
CLOSE_ASSISTANT = "<|im_end|>\n"
ARMS = (
    ("FullDirect", False, False, False),
    ("FullOneLine", True, False, False),
    ("WholeEarlyDirect", False, True, True),
    ("WholeEarlyOneLine", True, True, True),
    ("WholeLateOneLine", True, True, False),
)
GROUPS = ("falsified_old_correct_revision", "correct_old_no_error_control", "wait_wrong_revision_control")
LIMITS = [
    "Sixteen teacher-forced short injected states, not natural long-CoT or model self-correction.",
    "Ordinary OneLine instruction; free generation is not forcibly started at y=.",
    "Auxiliary Y/Z are pre-generation forced-prefix queries, not observed intermediate beliefs.",
    "Four roles are deduplicated to unique continuations; W revision-consistent is not necessarily true.",
    "Complete sequence likelihood requires candidate forward work; first-token margins are separate.",
    "Full-shaped key masks establish no memory savings; checkpoint retention is experimental overhead.",
    "No statistical-power, induction-head, orthogonality, safety, causal-mechanism or novelty claim.",
    "New user-turn/readout protocol differs from old P0; cross-run accuracy changes are not method gains.",
    "Standalone UUID binding is not a scheduler exclusion lock or continuous process monitoring.",
]
torch = None
np = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def load_module(path, name, expected):
    path = Path(path).resolve(strict=True)
    if sha(path) != expected:
        raise RuntimeError(f"Frozen dependency SHA mismatch: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def dependency_path(explicit, local_name, fallback):
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve().parent
    direct = here / local_name
    return direct if direct.is_file() else here.parent / fallback


def core_render(base, case, tokenizer, seed):
    original = base.render_case(case, tokenizer, seed)
    close_ids = tokenizer.encode(CLOSE_ASSISTANT, add_special_tokens=False)
    length = len(original["prefix_ids"])
    ids = original["prefix_ids"] + close_ids
    if len(ids) > 512:
        raise ValueError("Closed prefix exceeds fixed 512-token cap")
    return {"visible_fields": original["visible_fields"],
            "rendered_pieces": {k: original["rendered_pieces"][k] for k in ("P", "B", "U", "R")},
            "close_assistant_text": CLOSE_ASSISTANT, "close_assistant_ids": close_ids,
            "prefix_ids": ids, "prefix_position_ids": list(range(len(ids))),
            "segments": {**{k: original["segments"][k] for k in ("P", "B", "U", "R")}, "close_assistant": [length, len(ids)]},
            "target_columns": original["target_columns"], "random_columns": original["random_columns"],
            "random_seed": original["random_seed"], "random_hits_B": original["random_hits_B"],
            "random_hits_U": original["random_hits_U"],
            "note": "P/B/U/R token addresses match frozen P0; close old assistant, then append new user turn."}


def readout_render(core, tokenizer, one_line, family):
    message = COMMON + (ONELINE if one_line else DIRECT)
    template = tokenizer.apply_chat_template([{"role": "user", "content": message}], tokenize=False,
                                             add_generation_prompt=True, enable_thinking=False)
    if "</think>" not in template:
        raise RuntimeError("Nonthinking follow-up template validation failed")
    scaffold = Y_SCAFFOLD if family == "y" else Z_SCAFFOLD if family == "z" or not one_line else ""
    text = template + scaffold
    ids = tokenizer.encode(text, add_special_tokens=False)
    result = dict(core)
    result.update(readout_ids=ids, position_ids=list(range(len(core["prefix_ids"]) + len(ids))),
                  rendered_pieces={**core["rendered_pieces"], "S": text},
                  segments={**core["segments"], "S": [len(core["prefix_ids"]), len(core["prefix_ids"]) + len(ids)]},
                  readout_spec={"family": family, "one_line": one_line, "user_content": message,
                                "assistant_scaffold": scaffold, "text": text,
                                "meaning": "Actual free continuation" if family == "free" else "Auxiliary forced-prefix query before free generation"})
    return result


def eval_integer(expression, environment):
    def calculate(node):
        if isinstance(node, ast.Constant) and type(node.value) is int: return node.value
        if isinstance(node, ast.Name): return environment[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -calculate(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = calculate(node.left), calculate(node.right)
            if isinstance(node.op, ast.Add): return a+b
            if isinstance(node.op, ast.Sub): return a-b
            if isinstance(node.op, ast.Mult): return a*b
            if isinstance(node.op, ast.FloorDiv) and b and a % b == 0: return a//b
        raise ValueError("Unsupported/nonexact fixture arithmetic")
    return calculate(ast.parse(expression, mode="eval").body)


def offline_roles(case):
    expressions = {d["variable"]: d["expression"] for d in case["definitions"]}
    old_x, new_x = case["old_root_value"], case["revision_root_value"]
    old_y = eval_integer(expressions["y"], {"x": old_x})
    revision_y = eval_integer(expressions["y"], {"x": new_x})
    literal_old = re.search(r"y\s*=\s*([+-]?[0-9]+)", case["old_branch"])
    if literal_old is None or int(literal_old[1]) != old_y:
        raise ValueError("Frozen fixtures require old-y literal to match old-root-derived y")
    return {
        "z": {"trusted_final": case["required_final_value"], "old_final": case["old_branch_final_value"],
              "revision_consistent_final": eval_integer(expressions["z"], {"x": new_x, "y": revision_y}),
              "skip_signature": eval_integer(expressions["z"], {"x": new_x, "y": new_x})},
        "y": {"trusted_y": case["oracle_values"]["y"], "old_y": old_y,
              "revision_consistent_y": revision_y, "root_misbind": new_x}}


def score_family(runner, rendered, cache, logits, columns, roles):
    original_cache_length = cache.get_seq_length()
    by_ids = {}
    for role, value in roles.items():
        text = str(int(value)) + "\n"
        ids = tuple(runner.tokenizer.encode(text, add_special_tokens=False))
        if not ids:
            raise ValueError("Empty canonical continuation")
        item = by_ids.setdefault(ids, {"continuation": text, "token_ids": list(ids), "role_aliases": []})
        if item["continuation"] != text:
            raise ValueError("Different numeric strings alias to same token sequence")
        item["role_aliases"].append(role)
    unique = []
    start = len(rendered["prefix_ids"]) + len(rendered["readout_ids"])
    for ids, candidate in by_ids.items():
        terms = [float(logits.float().log_softmax(-1)[ids[0]])]
        before = len(runner.forward_ledger)
        if len(ids) > 1:
            mask = [1] * (start + len(ids)-1)
            for column in columns: mask[column] = 0
            out = runner.forward(list(ids[:-1]), mask, start, copy.deepcopy(cache), all_logits=True)
            terms.extend(float(out.logits[0, i].float().log_softmax(-1)[token]) for i, token in enumerate(ids[1:]))
        candidate.update(logP=sum(terms), token_logP=terms, first_token_id=ids[0], first_token_logP=terms[0],
                         candidate_forward_calls=len(runner.forward_ledger)-before,
                         teacher_forced_input_tokens=len(ids)-1, log_softmax_dtype="float32", scalar_sum="Python float64",
                         length_normalization="none", terminating_string="\n")
        unique.append(candidate)
    if cache.get_seq_length() != original_cache_length:
        raise RuntimeError("Candidate teacher forcing mutated the read-only branch checkpoint")
    lookup = {role: entry for entry in unique for role in entry["role_aliases"]}
    pairwise = []
    names = list(roles)
    for i, left in enumerate(names):
        for right in names[i+1:]:
            a, b = lookup[left], lookup[right]
            alias = a["token_ids"] == b["token_ids"]
            first_collision = a["first_token_id"] == b["first_token_id"]
            pairwise.append({"left": left, "right": right, "same_full_candidate": alias,
                             "full_log_odds_left_minus_right": None if alias else a["logP"]-b["logP"],
                             "same_first_token": first_collision,
                             "first_token_identifiable": not first_collision,
                             "first_token_log_odds_raw": a["first_token_logP"]-b["first_token_logP"],
                             "first_token_log_odds_interpretable": None if first_collision else a["first_token_logP"]-b["first_token_logP"]})
    return {"roles_evaluator_only": roles, "unique_candidates": unique, "pairwise_role_margins": pairwise,
            "used_to_choose_free_output": False, "role_count": len(roles), "unique_count": len(unique),
            "full_logP_is_not_first_token_marginal": True,
            "readout_cache_length_before_after": [original_cache_length, cache.get_seq_length()]}


def make_runner(base, model, tokenizer, device, output, progress):
    class CostRunner(base.Runner):
        def __init__(self):
            super().__init__(model, tokenizer, device, output, progress)
            self.forward_ledger = []
        def forward(self, ids, total_mask, start, cache=None, attentions=False, all_logits=False):
            self.sync()
            begin = time.monotonic()
            result = super().forward(ids, total_mask, start, cache, attentions=attentions, all_logits=all_logits)
            self.sync()
            self.forward_ledger.append({"stage": self.progress.get("stage"), "case_id": self.progress.get("case_id"),
                "arm": self.progress.get("arm"), "input_tokens": len(ids), "attention_key_length": len(total_mask),
                "position_start": start, "uses_past_cache": cache is not None, "returns_attentions": attentions,
                "all_logits": all_logits, "seconds": time.monotonic()-begin,
                "allocated_bytes_after": torch.cuda.memory_allocated(device) if device.type == "cuda" else None})
            if not bool(torch.isfinite(result.logits).all()):
                raise RuntimeError("Nonfinite logits: stop the interface experiment before scoring or generation")
            return result
    return CostRunner()


def brief_cost(ledger):
    counts = {}
    for row in ledger:
        bucket = counts.setdefault(row["stage"], {"forward_calls": 0, "input_tokens": 0, "seconds": 0.0})
        bucket["forward_calls"] += 1
        bucket["input_tokens"] += row["input_tokens"]
        bucket["seconds"] += row["seconds"]
    return {"forward_calls": len(ledger), "input_tokens": sum(x["input_tokens"] for x in ledger),
            "synchronized_forward_seconds": sum(x["seconds"] for x in ledger), "by_stage": counts}


def summarize(records, status, started, manifest, runner):
    paired = [r for r in records if r.get("primary_complete")]
    arm_names = [a[0] for a in ARMS]
    result = {"status": status, "elapsed_seconds": time.monotonic()-started,
              "planned_cases": len(manifest.get("executed_order", [])), "started_cases": len(records),
              "primary_complete_cases": len(paired), "diagnostic_complete_cases": sum(r.get("diagnostic_complete", False) for r in records),
              "primary_complete_ids": [r["case_id"] for r in paired],
              "diagnostic_complete_ids": [r["case_id"] for r in records if r.get("diagnostic_complete")],
              "partial_case_ids": [r["case_id"] for r in records if not r.get("diagnostic_complete")],
              "primary_denominator": "Only cases with all five free generations complete; no score-based selection.",
              "primary_accuracy": {}, "individual_available_free_counts": {}, "pairwise": {}, "limitations": LIMITS}
    for name in arm_names:
        result["individual_available_free_counts"][name] = sum("free" in r.get("arms", {}).get(name, {}) for r in records)
        result["primary_accuracy"][name] = {}
        for group in ("all",) + GROUPS:
            selected = [r for r in paired if group == "all" or r["evaluation_metadata"]["group"] == group]
            items = [r["arms"][name]["evaluation"] for r in selected]
            result["primary_accuracy"][name][group] = {"n": len(items), "correct": sum(x["correct"] for x in items),
                                                        "parsed": sum(x["parsed_value"] is not None for x in items)}
    for left, right in (("FullDirect", "FullOneLine"), ("WholeEarlyDirect", "WholeEarlyOneLine"),
                        ("FullDirect", "WholeEarlyDirect"), ("FullOneLine", "WholeEarlyOneLine"),
                        ("FullOneLine", "WholeLateOneLine"), ("WholeLateOneLine", "WholeEarlyOneLine")):
        result["pairwise"][left+"__to__"+right] = {}
        for group in ("all",) + GROUPS:
            selected = [r for r in paired if group == "all" or r["evaluation_metadata"]["group"] == group]
            gain, loss = [], []
            for r in selected:
                a, b = r["arms"][left]["evaluation"]["correct"], r["arms"][right]["evaluation"]["correct"]
                if b and not a: gain.append(r["case_id"])
                if a and not b: loss.append(r["case_id"])
            result["pairwise"][left+"__to__"+right][group] = {"n": len(selected), "gain": gain, "loss": loss,
                                                                "net_right_minus_left": len(gain)-len(loss)}
    interactions = []
    for r in paired:
        score = lambda a: int(r["arms"][a]["evaluation"]["correct"])
        interactions.append({"case_id": r["case_id"], "descriptive_interaction":
            score("WholeEarlyOneLine")-score("WholeEarlyDirect")-score("FullOneLine")+score("FullDirect")})
    result["descriptive_interaction_per_case"] = interactions
    result["interaction_note"] = "Descriptive factorial contrast; no independence, orthogonality, power or innovation guarantee."
    if runner:
        result["actual_forward_cost"] = brief_cost(runner.forward_ledger)
        peaks = [t["peak_allocated_bytes"] for t in runner.timing if t["peak_allocated_bytes"] is not None]
        result["observed_postload_peak_allocated_bytes"] = max(peaks) if peaks else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-path")
    parser.add_argument("--extractor-path")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--standalone-gpu")
    parser.add_argument("--cpu-interface-check", action="store_true")
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--max-seconds", type=int, default=275)
    args = parser.parse_args()
    if not 1 <= args.max_seconds <= 275:
        parser.error("max-seconds must be 1..275; no internal budget extension.")
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output/"manifest.json").exists():
        raise RuntimeError("Fresh output directory required; no run overwrite/retry.")
    progress, finished = {"stage": "startup"}, threading.Event()
    def watchdog():
        if not finished.wait(args.max_seconds):
            write_json(args.output/"deadline.json", {"status": "HARD_DEADLINE", "progress": progress.copy(),
                       "elapsed_seconds": time.monotonic()-started, "note": "Per-case primary records are retained; no retry/fill."})
            if runner is not None:
                write_json(args.output/"forward_ledger_at_deadline.json", list(runner.forward_ledger))
            os._exit(124)
    threading.Thread(target=watchdog, daemon=True).start()
    records, manifest, runner, status = [], {}, None, "P05_STARTED"
    def remaining(): return args.max_seconds-(time.monotonic()-started)
    def save_state():
        for record in records:
            write_json(args.output/(record["case_id"]+".json"), record)
        write_json(args.output/"summary.json", summarize(records, status, started, manifest, runner))
        if runner:
            write_json(args.output/"forward_ledger.json", runner.forward_ledger)
            write_json(args.output/"stage_timings.json", runner.timing)
    try:
        base_path = dependency_path(args.base_path, "p0_base_frozen.py", "direction_selection_20261105/real_model_p0.py")
        ext_path = dependency_path(args.extractor_path, "frozen_answer_extractor.py", "next_design_20261105/frozen_answer_extractor.py")
        base, base_path = load_module(base_path, "p0_base_frozen", BASE_SHA)
        extractor, ext_path = load_module(ext_path, "frozen_answer_extractor", EXTRACTOR_SHA)
        if sha(args.cases) != CASES_SHA:
            raise RuntimeError("Frozen 16-case file SHA mismatch")
        binding = base.bind_device(args)
        payload = json.loads(args.cases.read_text(encoding="utf-8-sig"))
        by_id = {c["case_id"]: c for c in payload["cases"]}
        if len(by_id) != 16 or set(by_id) != set(base.FROZEN_ORDER):
            raise ValueError("Frozen case identities required")
        global torch, np
        import torch as tm
        import numpy as nm
        import transformers
        torch, np = tm, nm
        base.torch, base.np = torch, np
        if args.cpu_interface_check:
            if args.device != "cpu" or args.model != "tiny-random":
                raise ValueError("CPU check requires --device cpu --model tiny-random")
        elif transformers.__version__ != "4.55.2" or torch.__version__.split("+")[0] not in ("2.4.1", "2.8.0"):
            raise RuntimeError("Real P0.5 requires transformers4.55.2 and torch2.4.1/2.8.0")
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        torch.manual_seed(args.seed)
        device = torch.device(binding["device"])
        order = [cid for cid in base.FROZEN_ORDER if not args.cpu_interface_check or cid in base.CONTROL_CASES]
        manifest = {"schema_version": "p05_five_arm_v1", "source_sha256": sha(__file__), "base_source_sha256": BASE_SHA,
                    "base_path": str(base_path), "answer_extractor_sha256": EXTRACTOR_SHA, "extractor_path": str(ext_path),
                    "input_sha256": CASES_SHA, "binding": binding, "versions": {"python": sys.version, "torch": torch.__version__,
                    "transformers": transformers.__version__}, "interface_only": args.cpu_interface_check,
                    "hard_limit_seconds": args.max_seconds, "executed_order": order, "seed": args.seed,
                    "free_max_new_tokens": 8 if args.cpu_interface_check else 64,
                    "primary_parser": "Frozen extract_answer(free.text), not candidate selection",
                    "prompt_field_whitelist": list(base.VISIBLE_FIELDS), "independent_conclusion_visible": False,
                    "all_other_case_fields_evaluation_only": True,
                    "new_turn_protocol": {"close_old_assistant": CLOSE_ASSISTANT, "common": COMMON, "direct": DIRECT,
                    "one_line": ONELINE, "direct_free_scaffold": Z_SCAFFOLD, "one_line_free_scaffold": "",
                    "Z_probe_scaffold": Z_SCAFFOLD, "Y_probe_scaffold": Y_SCAFFOLD, "enable_thinking": False},
                    "primary_before_diagnostics": True, "retained_checkpoints": "Full/early prefix and Direct free-readout caches held only for later diagnostics; never mutated/shared for appends.",
                    "limitations": LIMITS}
        write_json(args.output/"manifest.json", manifest)
        load_begin = time.monotonic()
        progress["stage"] = "hash_and_model_load"
        if args.cpu_interface_check:
            from transformers import Qwen3Config, Qwen3ForCausalLM
            tokenizer = base.TinyTokenizer(payload["cases"])
            extra_chars = set(COMMON+DIRECT+ONELINE+Z_SCAFFOLD+Y_SCAFFOLD+CLOSE_ASSISTANT)-set(tokenizer.encoder)
            next_id = max(tokenizer.decoder)+1
            for char in sorted(extra_chars):
                tokenizer.encoder[char] = next_id
                tokenizer.decoder[next_id] = char
                next_id += 1
            tokenizer.vocab_size = next_id
            config = Qwen3Config(vocab_size=next_id, hidden_size=32, intermediate_size=64, num_hidden_layers=3,
                        num_attention_heads=4, num_key_value_heads=2, head_dim=8, max_position_embeddings=1024,
                        attention_dropout=0.0, pad_token_id=0, bos_token_id=1, eos_token_id=4,
                        layer_types=["full_attention"]*3)
            config._attn_implementation = "eager"
            model = Qwen3ForCausalLM(config).eval().to(device)
            h = hashlib.sha256()
            for name, tensor in model.state_dict().items():
                h.update(name.encode()); h.update(tensor.detach().cpu().numpy().tobytes())
            manifest["model_manifest_sha256"] = h.hexdigest()
            manifest["model_files"] = {"scope": "Random tiny CPU interface fixture only"}
        else:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            files = base.model_file_manifest(args.model)
            manifest["model_files"] = files
            manifest["model_manifest_sha256"] = files["manifest_sha256"]
            write_json(args.output/"manifest.json", manifest)
            if files["manifest_sha256"] != MODEL_SHA:
                raise RuntimeError("Only the frozen Qwen3-4B snapshot is accepted; model manifest mismatch")
            tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
            model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, trust_remote_code=False,
                            torch_dtype=torch.float16, attn_implementation="eager", low_cpu_mem_usage=True).eval().to(device)
        if model.config.model_type != "qwen3" or getattr(model.config, "_attn_implementation", None) != "eager":
            raise RuntimeError("Only Qwen3 eager accepted")
        if any(x != "full_attention" for x in (getattr(model.config, "layer_types", None) or [])):
            raise RuntimeError("Sliding/hybrid layers unsupported")
        manifest.update(load_and_hash_seconds=time.monotonic()-load_begin, parameter_dtype=str(next(model.parameters()).dtype),
                        model_config=model.config.to_dict(), tokenizer={"class": type(tokenizer).__name__,
                            "chat_template": tokenizer.chat_template, "special_tokens_map": tokenizer.special_tokens_map})
        if device.type == "cuda":
            manifest["gpu"] = {"name": torch.cuda.get_device_name(device), "total_memory_bytes": torch.cuda.get_device_properties(device).total_memory}
        write_json(args.output/"manifest.json", manifest)
        runner = make_runner(base, model, tokenizer, device, args.output, progress)
        pending, banks = {}, {}
        tolerance = 1e-6 if args.cpu_interface_check else 1e-3
        with torch.inference_mode():
            # Phase 1: primary outcomes first. No candidate values are constructed until phase 2.
            for cid in order:
                if remaining() < 15:
                    status = "P05_PARTIAL_TIME_BUDGET"
                    break
                case, case_begin = by_id[cid], time.monotonic()
                core = core_render(base, case, tokenizer, args.seed)
                record = {"case_id": cid, "primary_complete": False, "diagnostic_complete": False, "status": "PRIMARY_IN_PROGRESS",
                          "rendering_core": core, "arms": {}, "controls": None,
                          "evaluation_metadata": {k: case[k] for k in ("group", "required_final_value", "old_branch_final_value",
                              "revision_implied_final_value", "oracle_trigger_label", "revision_is_correct")},
                          "source_sha256": manifest["source_sha256"], "input_sha256": CASES_SHA,
                          "base_source_sha256": BASE_SHA, "answer_extractor_sha256": EXTRACTOR_SHA,
                          "model_manifest_sha256": manifest["model_manifest_sha256"]}
                records.append(record)
                progress.update(case_id=cid, arm=None)
                write_json(args.output/(cid+".json"), record)
                full, full_time = runner.timed("shared_full_prefill", lambda: runner.prefill(core["prefix_ids"], []), case_id=cid, arm=None)
                early, early_time = runner.timed("shared_whole_early_prefill", lambda: runner.prefill(core["prefix_ids"], core["target_columns"]), case_id=cid, arm=None)
                record["prefix_cache_metadata"] = {"full": base.cache_metadata(full), "early": base.cache_metadata(early)}
                record["prefill_timing"] = {"full": full_time, "early": early_time}
                record["early_KV_vs_full"] = base.kv_metrics(full, early, base.groups_for(core, core["target_columns"]))
                pending[cid] = {"full": full, "early": early, "direct_readouts": {}}
                bank = banks[cid] = {}
                for name, one_line, masked, from_start in ARMS:
                    if remaining() < 6:
                        status = "P05_PARTIAL_TIME_BUDGET"
                        break
                    render = readout_render(core, tokenizer, one_line, "free")
                    columns = core["target_columns"] if masked else []
                    prefix_cache = early if from_start else full
                    (logits, cache, attention), read_time = runner.timed(name+"_free_readout", lambda: runner.readout(render, prefix_cache, columns,
                            attentions=cid in base.CONTROL_CASES), case_id=cid, arm=name)
                    generated, gen_time = runner.timed(name+"_free_greedy", lambda: runner.greedy(render, cache, logits, columns, manifest["free_max_new_tokens"]), case_id=cid, arm=name)
                    extracted = extractor.extract_answer(generated["text"])
                    combined = render["readout_spec"]["assistant_scaffold"]+generated["text"]
                    record["arms"][name] = {"one_line": one_line, "mask_columns": columns, "mask_from_prefill": from_start,
                        "physical_eviction": False, "free_rendering": {"spec": render["readout_spec"], "ids": render["readout_ids"],
                            "position_ids": list(range(len(core["prefix_ids"]), len(core["prefix_ids"])+len(render["readout_ids"])))},
                        "free": generated, "extraction": extracted,
                        "evaluation": {"parsed_value": extracted["value"], "correct": extracted["value"] == case["required_final_value"] if extracted["value"] is not None else False,
                                       "strict_integer_without_scaffold": generated["strict_integer"],
                                       "matches_old_final": extracted["value"] == case["old_branch_final_value"],
                                       "matches_revision_final": extracted["value"] == case["revision_implied_final_value"]},
                        "format_features": {"assistant_text_including_fixed_scaffold": combined,
                            "contains_final_answer_marker": "最终答案" in combined,
                            "contains_equation_sign": "=" in generated["text"], "nonempty_lines": len([s for s in combined.splitlines() if s.strip()])},
                        "readout_attention_check": attention, "timing": {"readout": read_time, "greedy": gen_time},
                        "diagnostics_complete": False}
                    bank[name+"__free"] = logits.numpy()
                    if not one_line:
                        pending[cid]["direct_readouts"][name] = (logits, cache)
                    record["primary_complete"] = len(record["arms"]) == 5
                    write_json(args.output/(cid+".json"), record)
                # Persist every completed readout, including a partial primary case or failed control.
                np.savez_compressed(args.output/(cid+"_logits.npz"), **bank)
                record["logits_artifact"] = cid+"_logits.npz"
                if not record["primary_complete"]:
                    record["status"] = "PRIMARY_PARTIAL_TIME_BUDGET"
                    save_state()
                    break
                if cid in base.CONTROL_CASES:
                    render = readout_render(core, tokenizer, True, "free")
                    progress.update(case_id=cid, arm="interface_control")
                    controls, control_time = runner.timed("interface_controls", lambda: base.run_controls(runner, render, full, early,
                        torch.from_numpy(bank["FullOneLine__free"]), torch.from_numpy(bank["WholeEarlyOneLine__free"]), tolerance), case_id=cid, arm="interface_control")
                    record["controls"], record["control_timing"] = controls, control_time
                    if not controls["passed"]:
                        record["status"] = status = "P05_INTERFACE_NO_GO"
                        save_state()
                        break
                else:
                    record["controls"] = {"passed": None, "note": "Controls frozen to E01/C01/W01; not run on other cases."}
                record["status"] = "PRIMARY_COMPLETE_DIAGNOSTICS_PENDING"
                record["primary_case_seconds"] = time.monotonic()-case_begin
                status = "P05_PRIMARY_RUNNING"
                save_state()
                print(json.dumps({"phase": "primary", "case_id": cid, "primary_complete": True,
                                  "remaining_seconds": remaining(), "values": {n: a["extraction"]["value"] for n, a in record["arms"].items()}}, ensure_ascii=True), flush=True)
            # Phase 2: all available complete primary pairs survive even if diagnostics time out.
            if status != "P05_INTERFACE_NO_GO":
                for record in records:
                    if not record["primary_complete"] or remaining() < 8:
                        status = "P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL"
                        break
                    cid, core = record["case_id"], record["rendering_core"]
                    case, bank, held = by_id[cid], banks[cid], pending[cid]
                    roles = offline_roles(case)  # First candidate/gold construction, after primary generation.
                    diagnostic_begin = time.monotonic()
                    for name, one_line, masked, from_start in ARMS:
                        if remaining() < 5:
                            status = "P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL"
                            break
                        arm = record["arms"][name]
                        columns = core["target_columns"] if masked else []
                        prefix_cache = held["early"] if from_start else held["full"]
                        arm.setdefault("probes", {})
                        for family in ("z", "y"):
                            if remaining() < 4:
                                status = "P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL"
                                break
                            render = readout_render(core, tokenizer, one_line, family)
                            before = len(runner.forward_ledger)
                            if family == "z" and not one_line:
                                free_ids = arm["free_rendering"]["ids"]
                                if free_ids != render["readout_ids"]:
                                    raise RuntimeError("Direct free/Z prefix mismatch: reuse forbidden")
                                logits, cache = held["direct_readouts"][name]
                                read_time = {"stage": name+"_z_readout_reused", "seconds": 0.0, "forward_calls": 0,
                                             "note": "Exact token/context/cache identity to pre-gold Direct free readout."}
                            else:
                                (logits, cache, _), read_time = runner.timed(name+"_"+family+"_probe_readout", lambda: runner.readout(render, prefix_cache, columns), case_id=cid, arm=name)
                            read_calls = len(runner.forward_ledger)-before
                            scores, score_time = runner.timed(name+"_"+family+"_candidate_scoring", lambda: score_family(runner, render, cache, logits, columns, roles[family]), case_id=cid, arm=name)
                            bank[name+"__"+family] = logits.numpy()
                            arm["probes"][family] = {"forced_before_generation_query": True,
                                "not_a_natural_intermediate_belief": True, "rendering": {"spec": render["readout_spec"], "ids": render["readout_ids"],
                                    "position_ids": list(range(len(core["prefix_ids"]), len(core["prefix_ids"])+len(render["readout_ids"])))},
                                "readout_additional_forward_calls": read_calls, "scores": scores,
                                "timing": {"readout": read_time, "candidate": score_time}}
                            write_json(args.output/(cid+".json"), record)
                        arm["diagnostics_complete"] = set(arm["probes"]) == {"z", "y"}
                        if not arm["diagnostics_complete"]: break
                    record["diagnostic_complete"] = all(a.get("diagnostics_complete", False) for a in record["arms"].values())
                    record["diagnostic_case_seconds"] = time.monotonic()-diagnostic_begin
                    record["status"] = "COMPLETE" if record["diagnostic_complete"] else "PRIMARY_COMPLETE_DIAGNOSTIC_PARTIAL"
                    record["pairwise_probe_logits"] = {}
                    for family in ("free", "z", "y"):
                        for left, right in (("FullDirect", "WholeEarlyDirect"), ("FullOneLine", "WholeEarlyOneLine"),
                                            ("WholeLateOneLine", "WholeEarlyOneLine"), ("FullOneLine", "WholeLateOneLine")):
                            a, b = left+"__"+family, right+"__"+family
                            if a in bank and b in bank:
                                record["pairwise_probe_logits"][family+"__"+left+"__"+right] = base.distribution_metrics(torch.from_numpy(bank[a]), torch.from_numpy(bank[b]))
                    np.savez_compressed(args.output/(cid+"_logits.npz"), **bank)
                    record["logits_artifact"] = cid+"_logits.npz"
                    del pending[cid]
                    save_state()
                    print(json.dumps({"phase": "diagnostics", "case_id": cid, "diagnostic_complete": record["diagnostic_complete"],
                                      "remaining_seconds": remaining()}, ensure_ascii=True), flush=True)
                    if not record["diagnostic_complete"]: break
                if len(records) == len(order) and all(r.get("diagnostic_complete") for r in records):
                    status = "P05_CPU_INTERFACE_ONLY_COMPLETE" if args.cpu_interface_check else "P05_COMPLETE"
                elif status != "P05_INTERFACE_NO_GO":
                    status = "P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL"
        save_state()
        summary = summarize(records, status, started, manifest, runner)
        text = ["# P0.5 "+status, "", f"Primary complete cases: {summary['primary_complete_cases']}; diagnostic complete cases: {summary['diagnostic_complete_cases']}.",
                "", "Primary = frozen parser on free.text; probes are separately priced pre-generation forced queries.", "",
                "| Arm | Correct / complete five-arm pairs |", "|---|---:|"]
        for name in summary["primary_accuracy"]:
            row = summary["primary_accuracy"][name]["all"]
            text.append(f"| {name} | {row['correct']}/{row['n']} |")
        text += ["", "## Limits", ""]+["- "+s for s in LIMITS]
        if args.cpu_interface_check: text += ["", "Random tiny CPU fixture only; no pretrained-model evidence."]
        (args.output/"RESULT.md").write_text("\n".join(text)+"\n", encoding="utf-8")
        return 2 if status == "P05_INTERFACE_NO_GO" else 0
    except Exception as error:
        status = "P05_EXECUTION_ERROR"
        write_json(args.output/"error.json", {"status": status, "error": str(error), "traceback": traceback.format_exc(),
                    "progress": progress, "elapsed_seconds": time.monotonic()-started})
        save_state()
        traceback.print_exc()
        return 1
    finally:
        finished.set()


if __name__ == "__main__":
    raise SystemExit(main())
