#!/usr/bin/env python3
"""Five-arm, same-position Qwen3 cache-state diagnostic; no training or queue launch.

Real run (inside an allocated PBS GPU job with CUDA_VISIBLE_DEVICES):
  python real_model_p0.py --model /local/Qwen3-1.7B --cases proposed_p0_cases.json \
      --output /local/p0-output
CPU interface control only (random weights, no pretrained-model evidence):
  python real_model_p0.py --model tiny-random --device cpu --cpu-interface-check \
      --cases proposed_p0_cases.json --output /local/p0-tiny

The five arms retain all tensor slots. Masks do NOT establish memory savings.
All interventions are forced on all cases, including false-Wait controls.
Gold-valued candidates enter isolated OFFLINE scoring calls only, after greedy.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import random
import re
import string
import subprocess
import sys
import threading
import time
import traceback


VISIBLE_FIELDS = ("question", "old_branch", "revision")
U_TEXT = "\n继续依据题目给定定义进行核算。\n" * 4
S_TEXT = "\n按题目原始定义核算，最终 z="
STATE_HEADER = "\n人工提供的计算记录：\n"
ARMS = (
    ("full", "none", False),
    ("target_late", "target", False),
    ("target_early_reprefill", "target", True),
    ("random_late", "random", False),
    ("random_early_reprefill", "random", True),
)
FROZEN_ORDER = ["E01", "C01", "W01", "E02", "E03", "C02", "W02", "E04",
                "E05", "C03", "W03", "E06", "E07", "C04", "W04", "E08"]
CONTROL_CASES = {"E01", "C01", "W01"}
LIMITATIONS = [
    "Handwritten teacher-forced injected states; not natural errors, detection or self-correction.",
    "Revisions are shared visible injections, including wrong revisions; no independent verifier message.",
    "All cache tensors keep their original shapes; masking establishes no memory saving.",
    "Target is a whole provided branch; random is a token subset of B union U, with overlap recorded.",
    "Random scattered B-union-U masking matches only count: not age/contiguous span or Random Attention; beating it does not establish semantic specificity.",
    "No causal correctness, general accuracy, long-CoT efficiency, novelty or deployment claim.",
    "Only one fixed seed/mode; no selection of cases or continuations by observed performance.",
]
torch = None
np = None


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_seed(case_id, seed):
    return (seed + int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)) % (2 ** 32)


def bind_device(args):
    """Reject GPU use before torch import unless the scheduler allocation is explicit."""
    if args.device == "cpu":
        if not args.cpu_interface_check:
            raise ValueError("CPU is limited to --cpu-interface-check; no full CPU benchmark.")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return {"device": "cpu", "scope": "interface_only"}
    if args.device not in ("cuda", "cuda:0"):
        raise ValueError("Use only cpu or cuda:0, the first scheduler-visible GPU.")
    if args.standalone_gpu is not None:
        requested = args.standalone_gpu.strip()
        if not requested or "," in requested or os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() != requested:
            raise RuntimeError("Standalone requires CUDA_VISIBLE_DEVICES to equal the one explicitly named physical index/UUID.")
        raw = subprocess.check_output(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"], text=True)
        identities = [tuple(part.strip() for part in line.split(",")) for line in raw.splitlines() if line.strip()]
        chosen = next((row for row in identities if requested in row), None)
        if not chosen:
            raise RuntimeError("Explicit standalone index/UUID is absent from nvidia-smi; no automatic alternative.")
        processes = subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                                             "--format=csv,noheader,nounits"], text=True)
        if any(line.split(",")[0].strip() == chosen[1] for line in processes.splitlines()):
            raise RuntimeError("Standalone GPU already has a compute process; refusing to share it.")
        # Resolve a user-specified NVML index to that exact UUID before CUDA initializes;
        # CUDA's numeric enumeration need not have the same order as nvidia-smi.
        os.environ["CUDA_VISIBLE_DEVICES"] = chosen[1]
        return {"device": "cuda:0", "allocation_mode": "explicit_authorized_standalone",
                "physical_index": chosen[0], "physical_uuid": chosen[1],
                "requested_visible_identifier": requested, "CUDA_VISIBLE_DEVICES": chosen[1],
                "compute_process_check": "empty before torch import",
                "PBS_JOBID": os.environ.get("PBS_JOBID")}
    if not os.environ.get("PBS_JOBID"):
        raise RuntimeError("GPU refused: PBS_JOBID is absent. This script never launches jobs.")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    gpu_file = os.environ.get("PBS_GPUFILE")
    if not visible and gpu_file and Path(gpu_file).is_file():
        lines = [x.strip() for x in Path(gpu_file).read_text().splitlines() if x.strip()]
        indices = []
        for item in lines:
            match = re.search(r"(?:-gpu|/)(\d+)$", item)
            if not match:
                raise RuntimeError("Cannot parse PBS_GPUFILE; set the scheduler-assigned CUDA_VISIBLE_DEVICES.")
            if match[1] not in indices:
                indices.append(match[1])
        visible = ",".join(indices)
        os.environ["CUDA_VISIBLE_DEVICES"] = visible
    if not visible or visible == "-1":
        raise RuntimeError("GPU refused: scheduler-visible CUDA_VISIBLE_DEVICES or parseable PBS_GPUFILE required.")
    return {"device": "cuda:0", "allocation_mode": "PBS", "PBS_JOBID": os.environ["PBS_JOBID"],
            "CUDA_VISIBLE_DEVICES": visible, "PBS_GPUFILE": gpu_file}


class TinyTokenizer:
    """Deterministic character fixture for an explicitly labelled random CPU control."""
    specials = ("<|im_start|>", "<|im_end|>", "<think>", "</think>")
    eos_token_id = 4
    pad_token_id = 0
    chat_template = "CPU fixture only; mirrors the non-thinking header, not a real tokenizer."

    def __init__(self, cases):
        chars = set(string.printable + U_TEXT + S_TEXT + STATE_HEADER)
        for case in cases:
            for key in VISIBLE_FIELDS:
                chars.update(case[key])
        self.encoder = {word: i + 3 for i, word in enumerate(self.specials)}
        self.encoder.update({ch: i + 7 for i, ch in enumerate(sorted(chars))})
        self.decoder = {v: k for k, v in self.encoder.items()}
        self.vocab_size = max(self.decoder) + 1
        self.special_tokens_map = {"eos_token": "<|im_end|>", "pad_token": "<pad>"}

    def encode(self, value, add_special_tokens=False):
        result, cursor = [], 0
        while cursor < len(value):
            special = next((s for s in self.specials if value.startswith(s, cursor)), None)
            if special:
                result.append(self.encoder[special])
                cursor += len(special)
            else:
                result.append(self.encoder.get(value[cursor], 1))
                cursor += 1
        return result

    def decode(self, ids, skip_special_tokens=False):
        return "".join(self.decoder.get(int(i), "") for i in ids
                       if not (skip_special_tokens and int(i) < 7))

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        assert enable_thinking is False and tokenize is False
        return ("<|im_start|>user\n" + messages[0]["content"] + "<|im_end|>\n"
                "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def render_case(case, tokenizer, seed):
    # Whitelist access: no dictionary serialization and no oracle-based rendering or intervention.
    visible = {key: case[key] for key in VISIBLE_FIELDS}
    prefix = tokenizer.apply_chat_template(
        [{"role": "user", "content": visible["question"]}], tokenize=False,
        add_generation_prompt=True, enable_thinking=False)
    if "</think>" not in prefix:
        raise RuntimeError("Non-thinking Qwen3 template acceptance failed; no silent thinking-mode fallback.")
    pieces = {"P": prefix + STATE_HEADER, "B": visible["old_branch"],
              "U": U_TEXT, "R": "\n" + visible["revision"], "S": S_TEXT}
    ids, spans = [], {}
    for name in ("P", "B", "U", "R"):
        piece_ids = tokenizer.encode(pieces[name], add_special_tokens=False)
        spans[name] = [len(ids), len(ids) + len(piece_ids)]
        ids.extend(piece_ids)
    readout = tokenizer.encode(pieces["S"], add_special_tokens=False)
    spans["S"] = [len(ids), len(ids) + len(readout)]
    if not readout or not (0 < len(ids) <= 512):
        raise ValueError(f"Prefix/readout bound failed: prefix={len(ids)}, readout={len(readout)}")
    target = list(range(*spans["B"]))
    pool = list(range(spans["B"][0], spans["U"][1]))
    if not target or len(pool) < len(target):
        raise ValueError("Target span empty or random pool too short.")
    random_columns = sorted(random.Random(stable_seed(case["case_id"], seed)).sample(pool, len(target)))
    return {"visible_fields": visible, "rendered_pieces": pieces, "segments": spans,
            "prefix_ids": ids, "readout_ids": readout,
            "position_ids": list(range(len(ids) + len(readout))),
            "target_columns": target, "random_columns": random_columns,
            "random_seed": stable_seed(case["case_id"], seed),
            "random_hits_B": len(set(random_columns) & set(target)),
            "random_hits_U": len(random_columns) - len(set(random_columns) & set(target)),
            "tokenization": "Independently encode P/B/U/R/S without extra special tokens; freeze and concatenate IDs."}


def cache_pairs(cache):
    if hasattr(cache, "layers"):
        return [(layer.keys, layer.values) for layer in cache.layers]
    if hasattr(cache, "key_cache"):
        return list(zip(cache.key_cache, cache.value_cache))
    return [(layer[0], layer[1]) for layer in cache]


def cache_metadata(cache):
    pairs = cache_pairs(cache)
    return {"class": type(cache).__name__, "layers": [
        {"layer": i, "key_shape": list(k.shape), "value_shape": list(v.shape),
         "dtype": str(k.dtype), "device": str(k.device)} for i, (k, v) in enumerate(pairs)]}


def kv_metrics(first, second, groups):
    result = []
    left, right = cache_pairs(first), cache_pairs(second)
    if len(left) != len(right):
        raise RuntimeError("Cache layer count mismatch")
    for layer, ((ak, av), (bk, bv)) in enumerate(zip(left, right)):
        row = {"layer": layer, "groups": {}}
        for name, indices in groups.items():
            stats = {}
            for label, a, b in (("K", ak, bk), ("V", av, bv)):
                if a.shape != b.shape:
                    raise RuntimeError("Cache shape mismatch")
                if not indices:
                    stats[label] = None
                    continue
                index = torch.tensor(indices, device=a.device, dtype=torch.long)
                aa, bb = a.index_select(-2, index).float(), b.index_select(-2, index).float()
                delta = aa - bb
                stats[label] = {"max_abs": float(delta.abs().max().item()),
                                "relative_l2": float((delta.norm() / aa.norm().clamp_min(1e-12)).item()),
                                "finite": bool(torch.isfinite(aa).all() and torch.isfinite(bb).all())}
            row["groups"][name] = stats
        result.append(row)
    return result


def max_kv_abs(rows, groups=None, layer=None):
    values = []
    for row in rows:
        if layer is not None and row["layer"] != layer:
            continue
        for name, tensors in row["groups"].items():
            if groups is not None and name not in groups:
                continue
            values.extend(value["max_abs"] for value in tensors.values() if value is not None)
    return max(values, default=0.0)


def distribution_metrics(first, second):
    a, b = first.double().cpu(), second.double().cpu()
    if not torch.isfinite(a).all() or not torch.isfinite(b).all():
        raise RuntimeError("Non-finite readout logits")
    la, lb = a.log_softmax(-1), b.log_softmax(-1)
    p, q = la.exp(), lb.exp()
    log_mid = ((p + q) * 0.5).clamp_min(1e-300).log()
    return {"logit_max_abs": float((a - b).abs().max()),
            "logit_relative_l2": float((a - b).norm() / a.norm().clamp_min(1e-30)),
            "TV": float((p - q).abs().sum() * 0.5),
            "JS_nats": max(0.0, float((p * (la - log_mid)).sum() * 0.5 +
                                      (q * (lb - log_mid)).sum() * 0.5)),
            "argmax_equal": bool(a.argmax() == b.argmax()), "exact_equal": bool(torch.equal(a, b))}


class Runner:
    def __init__(self, model, tokenizer, device, output, progress):
        self.model, self.tokenizer, self.device = model, tokenizer, device
        self.output, self.progress = output, progress
        self.timing = []
        self.explicit_cache_position = "cache_position" in inspect.signature(model.forward).parameters

    def sync(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

    def timed(self, stage, function, **metadata):
        self.progress.update(stage=stage, **metadata)
        self.sync()
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)
        start = time.monotonic()
        value = function()
        self.sync()
        row = {"stage": stage, "seconds": time.monotonic() - start, **metadata,
               "peak_allocated_bytes": None, "peak_reserved_bytes": None}
        if self.device.type == "cuda":
            row.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(self.device),
                       peak_reserved_bytes=torch.cuda.max_memory_reserved(self.device))
        self.timing.append(row)
        return value, row

    def forward(self, ids, total_mask, start, cache=None, attentions=False, all_logits=False):
        kwargs = {"input_ids": torch.tensor([ids], dtype=torch.long, device=self.device),
                  "position_ids": torch.arange(start, start + len(ids), device=self.device).unsqueeze(0),
                  "attention_mask": torch.tensor([total_mask], dtype=torch.long, device=self.device),
                  "past_key_values": cache, "use_cache": True, "return_dict": True,
                  "output_attentions": attentions, "logits_to_keep": 0 if all_logits else 1}
        if self.explicit_cache_position:
            kwargs["cache_position"] = torch.arange(start, start + len(ids), device=self.device)
        return self.model(**kwargs)

    def prefill(self, ids, columns):
        mask = [1] * len(ids)
        for i in columns:
            mask[i] = 0
        return self.forward(ids, mask, 0).past_key_values

    def readout(self, rendered, cache, columns, attentions=False):
        length = len(rendered["prefix_ids"])
        mask = [1] * (length + len(rendered["readout_ids"]))
        for i in columns:
            mask[i] = 0
        out = self.forward(rendered["readout_ids"], mask, length, copy.deepcopy(cache), attentions=attentions)
        logits = out.logits[0, -1].float().cpu()
        attention = None
        if attentions:
            if not out.attentions or any(a is None for a in out.attentions):
                raise RuntimeError("Eager attention readout is unavailable")
            masked_mass, future_mass = [], []
            qpos = torch.arange(length, len(mask), device=self.device)
            kpos = torch.arange(len(mask), device=self.device)
            future = kpos.unsqueeze(0) > qpos.unsqueeze(1)
            for a in out.attentions:
                # Probability mass, summed over forbidden keys, then max over heads and queries.
                masked_mass.append(float(a[..., columns].float().sum(-1).max()) if columns else 0.0)
                future_mass.append(float((a.float() * future).sum(-1).max()))
            attention = {"masked_key_mass_max_per_layer": masked_mass,
                         "future_key_mass_max_per_layer": future_mass,
                         "all_finite": all(bool(torch.isfinite(a).all()) for a in out.attentions)}
        return logits, out.past_key_values, attention

    def prefill_attention_check(self, rendered, columns):
        """Check forbidden key columns and causality during prefix encoding itself."""
        length = len(rendered["prefix_ids"])
        mask = [0 if i in set(columns) else 1 for i in range(length)]
        out = self.forward(rendered["prefix_ids"], mask, 0, attentions=True)
        if not out.attentions or any(a is None for a in out.attentions):
            raise RuntimeError("Eager prefill attention inspection unavailable")
        pos = torch.arange(length, device=self.device)
        future = pos.unsqueeze(0) > pos.unsqueeze(1)
        surviving = torch.tensor([i for i in range(length) if i not in set(columns)], device=self.device)
        info = {"query_scope": "All prefix queries; separate surviving-query check includes U and R.",
                "masked_columns": columns, "prefix_tokens": length,
                "masked_key_mass_max_per_layer": [], "future_key_mass_max_per_layer": [],
                "surviving_query_masked_key_mass_max_per_layer": [], "all_finite": True}
        for attention in out.attentions:
            mass = attention[..., columns].float().sum(-1)
            info["masked_key_mass_max_per_layer"].append(float(mass.max()))
            info["surviving_query_masked_key_mass_max_per_layer"].append(float(mass.index_select(-1, surviving).max()))
            info["future_key_mass_max_per_layer"].append(float((attention.float() * future).sum(-1).max()))
            info["all_finite"] = info["all_finite"] and bool(torch.isfinite(attention).all())
        return info

    def greedy(self, rendered, cache, initial_logits, columns, max_new_tokens):
        # This cache is never used for candidate teacher forcing.
        cache, logits = copy.deepcopy(cache), initial_logits
        base = len(rendered["prefix_ids"]) + len(rendered["readout_ids"])
        tokens, stop = [], "token_budget"
        eos = self.tokenizer.eos_token_id
        eos = set(eos if isinstance(eos, (list, tuple)) else [eos])
        for step in range(max_new_tokens):
            token = int(logits.argmax())
            tokens.append(token)
            if token in eos:
                stop = "eos"
                break
            text = self.tokenizer.decode(tokens, skip_special_tokens=True)
            if "\n" in text and re.fullmatch(r"[+-]?\d+", text.strip()):
                stop = "integer_newline"
                break
            if step + 1 == max_new_tokens:
                break
            mask = [1] * (base + len(tokens))
            for i in columns:
                mask[i] = 0
            out = self.forward([token], mask, base + len(tokens) - 1, cache)
            cache, logits = out.past_key_values, out.logits[0, -1].float().cpu()
        text = self.tokenizer.decode(tokens, skip_special_tokens=True)
        parsed = int(text.strip()) if re.fullmatch(r"[+-]?\d+", text.strip()) else None
        return {"token_ids": tokens, "text": text, "strict_integer": parsed, "stop_reason": stop,
                "new_tokens": len(tokens), "additional_forward_tokens": max(0, len(tokens) - 1)}

    def score_candidates(self, rendered, cache, initial_logits, columns, case):
        # These evaluator-only values never enter prompt/render/mask construction or greedy generation.
        roles = {"correct": case["required_final_value"], "old_branch": case["old_branch_final_value"],
                 "revision_implied": case["revision_implied_final_value"]}
        scores = {}
        base = len(rendered["prefix_ids"]) + len(rendered["readout_ids"])
        for value in dict.fromkeys(roles.values()):
            text = str(value) + "\n"
            ids = self.tokenizer.encode(text, add_special_tokens=False)
            if not ids:
                raise RuntimeError("Empty candidate")
            terms = [float(initial_logits.log_softmax(-1)[ids[0]])]
            if len(ids) > 1:
                mask = [1] * (base + len(ids) - 1)
                for i in columns:
                    mask[i] = 0
                out = self.forward(ids[:-1], mask, base, copy.deepcopy(cache), all_logits=True)
                terms.extend(float(out.logits[0, j].float().log_softmax(-1)[token])
                             for j, token in enumerate(ids[1:]))
            scores[str(value)] = {"continuation": text, "token_ids": ids, "logP": sum(terms),
                                  "token_logP": terms, "teacher_forced_tokens": len(ids) - 1,
                                  "length_normalization": "none"}
        correct = scores[str(roles["correct"])]["logP"]
        margins = {role: (None if value == roles["correct"] else correct - scores[str(value)]["logP"])
                   for role, value in roles.items() if role != "correct"}
        return {"roles": roles, "unique_candidates": scores, "correct_log_odds_over": margins,
                "used_to_choose_output": False}


def groups_for(rendered, excluded=()):
    spans = rendered["segments"]
    skip = set(excluded)
    keep = lambda lo, hi: [i for i in range(lo, hi) if i not in skip]
    return {"before_B": keep(0, spans["B"][0]), "U": keep(*spans["U"]),
            "R": keep(*spans["R"]), "surviving_all": keep(0, len(rendered["prefix_ids"]))}


def run_controls(runner, rendered, base_cache, early_cache, full_logits, early_logits, tolerance):
    controls, identity_groups = {}, groups_for(rendered)
    repeat, timing = runner.timed("control_no_delete_reprefill", lambda: runner.prefill(rendered["prefix_ids"], []))
    repeat_logits, _, _ = runner.readout(rendered, repeat, [], attentions=True)
    controls["same_mask_no_delete"] = distribution_metrics(full_logits, repeat_logits)
    controls["same_mask_no_delete"]["KV"] = kv_metrics(base_cache, repeat, identity_groups)
    full_ids = rendered["prefix_ids"] + rendered["readout_ids"]
    dense, _ = runner.timed("control_cached_vs_whole_recompute", lambda: runner.forward(full_ids, [1] * len(full_ids), 0))
    controls["cached_vs_whole_recompute"] = distribution_metrics(full_logits, dense.logits[0, -1].float().cpu())
    target = rendered["target_columns"]
    early_repeat, _ = runner.timed("control_early_rebuild", lambda: runner.prefill(rendered["prefix_ids"], target))
    early_repeat_logits, _, attn = runner.readout(rendered, early_repeat, target, attentions=True)
    controls["same_mask_early_rebuild"] = distribution_metrics(early_logits, early_repeat_logits)
    controls["same_mask_early_rebuild"]["KV"] = kv_metrics(early_cache, early_repeat, groups_for(rendered, target))
    clean_kv = kv_metrics(base_cache, early_cache, groups_for(rendered, target))
    controls["prefix_invariance_max_abs"] = max_kv_abs(clean_kv, {"before_B"})
    controls["first_layer_invariance_max_abs"] = max_kv_abs(clean_kv, {"surviving_all"}, layer=0)
    poisoned = copy.deepcopy(base_cache)
    for _, value in cache_pairs(poisoned):
        index = torch.tensor(target, device=value.device)
        sentinel = torch.full_like(value.index_select(-2, index), 8.0)
        sentinel[..., ::2] = -8.0
        value.index_copy_(-2, index, sentinel)
    late_plain, _, late_attn = runner.readout(rendered, base_cache, target, attentions=True)
    late_poison, _, _ = runner.readout(rendered, poisoned, target, attentions=True)
    controls["masked_value_sentinel_8"] = distribution_metrics(late_plain, late_poison)
    controls["attention_check_early"] = attn
    controls["attention_check_late"] = late_attn
    controls["target_prefill_attention"], _ = runner.timed("control_target_early_prefill_attention", lambda: runner.prefill_attention_check(rendered, target))
    controls["random_prefill_attention"], _ = runner.timed("control_random_early_prefill_attention", lambda: runner.prefill_attention_check(rendered, rendered["random_columns"]))
    checks = {
        "same_mask_no_delete": controls["same_mask_no_delete"]["logit_max_abs"] <= tolerance,
        "same_mask_no_delete_KV": max_kv_abs(controls["same_mask_no_delete"]["KV"]) <= tolerance,
        "same_mask_early_rebuild": controls["same_mask_early_rebuild"]["logit_max_abs"] <= tolerance,
        "same_mask_early_rebuild_KV": max_kv_abs(controls["same_mask_early_rebuild"]["KV"]) <= tolerance,
        "prefix_invariance": controls["prefix_invariance_max_abs"] <= tolerance,
        "first_layer_invariance": controls["first_layer_invariance_max_abs"] <= tolerance,
        "masked_sentinel": controls["masked_value_sentinel_8"]["logit_max_abs"] <= tolerance,
        "masked_and_future_attention_zero": all(
            info["all_finite"] and max(info["masked_key_mass_max_per_layer"] + info["future_key_mass_max_per_layer"]) == 0.0
            for info in (attn, late_attn)),
        "early_prefill_target_and_random_forbidden_mass_zero": all(
            info["all_finite"] and max(info["masked_key_mass_max_per_layer"] +
                                      info["surviving_query_masked_key_mass_max_per_layer"] +
                                      info["future_key_mass_max_per_layer"]) == 0.0
            for info in (controls["target_prefill_attention"], controls["random_prefill_attention"])),
    }
    controls["tolerance_logit_and_KV_max_abs"] = tolerance
    controls["checks"] = checks
    controls["passed"] = all(checks.values())
    controls["note"] = "Cached/dense shape noise is recorded separately, not mistaken for same-path no-op noise."
    return controls


def model_file_manifest(model_path):
    root = Path(model_path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("--model must be an existing local snapshot directory; no downloads.")
    weights = sorted(root.glob("*.safetensors")) or sorted(root.glob("pytorch_model*.bin"))
    if not weights:
        raise ValueError("No local safetensors or pytorch_model*.bin weights found")
    assets = sorted(set(root.glob("*.json")) | set(root.glob("*.txt")) | set(root.glob("*.jinja")))
    files = [{"name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
             for path in weights + assets]
    aggregate = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"local_model_directory": str(root), "files": files, "manifest_sha256": aggregate,
            "hash_scope": "All root model weight files plus JSON/TXT/Jinja tokenizer/config assets."}


def summarize(records, status, started, args, manifest):
    result = {"status": status, "completed_cases": len(records), "planned_cases": 16,
              "elapsed_seconds": time.monotonic() - started, "hard_limit_seconds": args.max_seconds,
              "model_manifest_sha256": manifest.get("model_manifest_sha256"),
              "interface_only": args.cpu_interface_check, "limitations": LIMITATIONS,
              "arms": {}, "per_case_pairs": []}
    for name, _, _ in ARMS:
        selected = [(r, r["arms"][name]) for r in records if name in r.get("arms", {})]
        result["arms"][name] = {"n": len(selected), "strict_correct": sum(a["evaluation"]["strict_correct"] for _, a in selected),
                               "strict_integer_parseable": sum(a["greedy"]["strict_integer"] is not None for _, a in selected),
                               "by_group": {}}
        for record, arm in selected:
            group = record["evaluation_metadata"]["group"]
            row = result["arms"][name]["by_group"].setdefault(group, {"n": 0, "correct": 0, "old_branch_value": 0,
                                                                         "revision_implied_value": 0})
            row["n"] += 1
            row["correct"] += arm["evaluation"]["strict_correct"]
            row["old_branch_value"] += arm["evaluation"]["matches_old_branch_value"]
            row["revision_implied_value"] += arm["evaluation"]["matches_revision_implied_value"]
    for record in records:
        result["per_case_pairs"].append({"case_id": record["case_id"], "comparisons": record.get("pairwise_readout", {}),
                                          "controls_passed": record.get("controls", {}).get("passed")})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--standalone-gpu", help="Explicit authorized physical index/UUID; CVD must contain exactly it.")
    parser.add_argument("--cpu-interface-check", action="store_true")
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args()
    if not 1 <= args.max_new_tokens <= 32 or not 1 <= args.max_seconds <= 1800:
        parser.error("max-new-tokens must be 1..32; max-seconds must be 1..1800.")
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "manifest.json").exists():
        raise RuntimeError("Output already has manifest.json; use a fresh directory, never overwrite a run.")
    progress = {"stage": "startup"}
    finished = threading.Event()

    def watchdog():
        if not finished.wait(args.max_seconds):
            atomic_json(args.output / "deadline.json", {"status": "HARD_DEADLINE", "progress": progress.copy(),
                        "elapsed_seconds": time.monotonic() - started, "complete": False})
            os._exit(124)

    threading.Thread(target=watchdog, daemon=True).start()
    manifest, records, runner = {}, [], None
    status = "P0_STARTED"
    try:
        binding = bind_device(args)
        payload = json.loads(args.cases.read_text(encoding="utf-8-sig"))
        cases = payload["cases"]
        by_id = {case["case_id"]: case for case in cases}
        if len(cases) != 16 or set(by_id) != set(FROZEN_ORDER):
            raise ValueError("Exactly the frozen 16 distinct P0 cases are required; no result-based selection.")
        for case in cases:
            if not all(isinstance(case.get(key), str) for key in VISIBLE_FIELDS):
                raise ValueError("Visible fields must be strings")
        import torch as torch_module
        import numpy as numpy_module
        import transformers
        global torch, np
        torch, np = torch_module, numpy_module
        if not args.cpu_interface_check:
            if transformers.__version__ != "4.55.2" or torch.__version__.split("+")[0] not in ("2.4.1", "2.8.0"):
                raise RuntimeError(f"Real P0 requires torch2.4.1 or2.8.0 / transformers4.55.2; got {torch.__version__}/{transformers.__version__}")
        elif args.device != "cpu":
            raise ValueError("--cpu-interface-check requires explicit --device cpu")
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        torch.manual_seed(args.seed)
        device = torch.device(binding["device"])
        manifest = {"schema_version": "qwen3_injected_cache_p0_v1", "source_sha256": sha256_file(__file__),
                    "input_sha256": sha256_file(args.cases), "binding": binding,
                    "versions": {"python": sys.version, "torch": torch.__version__, "transformers": transformers.__version__},
                    "visible_field_whitelist": list(VISIBLE_FIELDS),
                    "excluded_from_prompt": ["independent_conclusion"] + payload.get("evaluator_only_fields", []),
                    "dtype": "float32" if args.cpu_interface_check else "float16", "attention": "eager",
                    "max_new_tokens": args.max_new_tokens, "seed": args.seed, "thinking": False,
                    "hard_limit_seconds": args.max_seconds, "limitations": LIMITATIONS,
                    "frozen_order": FROZEN_ORDER, "runtime_includes": "Imports, hashes, load, all forwards, scoring and controls."}
        progress["stage"] = "model_manifest_and_load"
        load_start = time.monotonic()
        if args.model == "tiny-random":
            if not args.cpu_interface_check:
                raise ValueError("tiny-random is permitted only for explicit CPU interface checks")
            from transformers import Qwen3Config, Qwen3ForCausalLM
            tokenizer = TinyTokenizer(cases)
            config = Qwen3Config(vocab_size=tokenizer.vocab_size, hidden_size=32, intermediate_size=64,
                                num_hidden_layers=3, num_attention_heads=4, num_key_value_heads=2,
                                head_dim=8, max_position_embeddings=1024, attention_dropout=0.0,
                                pad_token_id=0, bos_token_id=1, eos_token_id=4,
                                layer_types=["full_attention"] * 3)
            config._attn_implementation = "eager"
            model = Qwen3ForCausalLM(config).eval().to(device)
            weights_hash = hashlib.sha256()
            for name, tensor in model.state_dict().items():
                weights_hash.update(name.encode())
                weights_hash.update(tensor.detach().cpu().numpy().tobytes())
            manifest["model_files"] = {"scope": "RANDOM TINY CPU INTERFACE FIXTURE", "state_sha256": weights_hash.hexdigest()}
            manifest["model_manifest_sha256"] = weights_hash.hexdigest()
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            manifest["model_files"] = model_file_manifest(args.model)
            manifest["model_manifest_sha256"] = manifest["model_files"]["manifest_sha256"]
            tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
            model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, trust_remote_code=False,
                    torch_dtype=torch.float32 if args.cpu_interface_check else torch.float16,
                    attn_implementation="eager", low_cpu_mem_usage=True).eval().to(device)
        layer_types = getattr(model.config, "layer_types", None)
        if model.config.model_type != "qwen3" or (layer_types and any(x != "full_attention" for x in layer_types)):
            raise RuntimeError("Only Qwen3 full-attention layers accepted; no silent sliding/hybrid adaptation")
        if getattr(model.config, "_attn_implementation", None) != "eager":
            raise RuntimeError("Actual model attention implementation is not eager")
        if device.type == "cuda":
            manifest["gpu"] = {"name": torch.cuda.get_device_name(device),
                               "total_memory_bytes": torch.cuda.get_device_properties(device).total_memory,
                               "capability": list(torch.cuda.get_device_capability(device))}
        manifest["load_and_hash_seconds"] = time.monotonic() - load_start
        manifest["model_config"] = model.config.to_dict()
        manifest["tokenizer"] = {"class": type(tokenizer).__name__, "special_tokens_map": tokenizer.special_tokens_map,
                                  "chat_template": tokenizer.chat_template}
        manifest["parameter_dtype"] = str(next(model.parameters()).dtype)
        order = [case_id for case_id in FROZEN_ORDER if not args.cpu_interface_check or case_id in CONTROL_CASES]
        manifest["executed_order"] = order
        manifest["interface_only"] = args.cpu_interface_check
        atomic_json(args.output / "manifest.json", manifest)
        runner = Runner(model, tokenizer, device, args.output, progress)
        tolerance = 1e-6 if args.cpu_interface_check else 1e-3
        with torch.inference_mode():
            for case_id in order:
                if time.monotonic() - started > args.max_seconds - 20:
                    status = "P0_PARTIAL_TIME_BUDGET"
                    break
                case_start, timing_start = time.monotonic(), len(runner.timing)
                progress.update(case_id=case_id)
                case = by_id[case_id]
                rendered = render_case(case, tokenizer, args.seed)
                record = {"case_id": case_id, "rendering": rendered, "arms": {},
                          "evaluation_metadata": {key: case[key] for key in ("group", "required_final_value",
                              "old_branch_final_value", "revision_implied_final_value", "oracle_trigger_label", "revision_is_correct")},
                          "input_sha256": manifest["input_sha256"], "source_sha256": manifest["source_sha256"],
                          "model_manifest_sha256": manifest["model_manifest_sha256"], "status": "IN_PROGRESS"}
                atomic_json(args.output / f"{case_id}.json", record)
                base_cache, base_time = runner.timed("shared_full_prefill", lambda: runner.prefill(rendered["prefix_ids"], []), case_id=case_id)
                record["shared_full_prefill"] = {"timing": base_time, "input_tokens": len(rendered["prefix_ids"]),
                                                 "cache": cache_metadata(base_cache)}
                logits_bank, early_target_cache = {}, None
                for name, selection, early in ARMS:
                    columns = [] if selection == "none" else rendered[selection + "_columns"]
                    arm = {"masked_columns": columns, "masked_token_count": len(columns), "mask_rank": 2,
                           "same_full_tensor_shape": True, "physical_eviction": False,
                           "prefill_path": "masked_fresh_reprefill" if early else "shared_full_prefill_clone",
                           "prefill_added_forward_tokens": len(rendered["prefix_ids"]) if early else 0}
                    if early:
                        cache, arm["prefill_timing"] = runner.timed(name + "_prefill", lambda: runner.prefill(rendered["prefix_ids"], columns), case_id=case_id, arm=name)
                        arm["prefill_KV_vs_full"] = kv_metrics(base_cache, cache, groups_for(rendered, columns))
                    else:
                        cache = base_cache  # readout always deep-copies before the mutable append.
                    (logits, read_cache, attention), arm["readout_timing"] = runner.timed(name + "_readout", lambda: runner.readout(rendered, cache, columns, attentions=case_id in CONTROL_CASES), case_id=case_id, arm=name)
                    logits_bank[name] = logits
                    if name == "target_early_reprefill":
                        early_target_cache = cache
                    arm["attention_check"] = attention
                    arm["readout_cache"] = cache_metadata(read_cache)
                    top_values, top_ids = logits.log_softmax(-1).topk(min(12, len(logits)))
                    arm["next_token_top12"] = [{"id": int(i), "text": tokenizer.decode([int(i)]), "logP": float(v)}
                                                for v, i in zip(top_values, top_ids)]
                    arm["greedy"], arm["greedy_timing"] = runner.timed(name + "_greedy", lambda: runner.greedy(rendered, read_cache, logits, columns, args.max_new_tokens), case_id=case_id, arm=name)
                    # Free output is complete before candidate values are supplied to isolated scoring calls.
                    arm["candidate_scores"], arm["scoring_timing"] = runner.timed(name + "_offline_candidate_scoring", lambda: runner.score_candidates(rendered, read_cache, logits, columns, case), case_id=case_id, arm=name)
                    answer = arm["greedy"]["strict_integer"]
                    arm["evaluation"] = {"strict_correct": answer == case["required_final_value"],
                                         "matches_old_branch_value": answer == case["old_branch_final_value"],
                                         "matches_revision_implied_value": answer == case["revision_implied_final_value"]}
                    arm["readout_vs_full"] = distribution_metrics(logits_bank["full"], logits)
                    record["arms"][name] = arm
                    atomic_json(args.output / f"{case_id}.json", record)
                    del read_cache
                record["pairwise_readout"] = {
                    "target_late_vs_early": distribution_metrics(logits_bank["target_late"], logits_bank["target_early_reprefill"]),
                    "random_late_vs_early": distribution_metrics(logits_bank["random_late"], logits_bank["random_early_reprefill"])}
                if case_id in CONTROL_CASES:
                    record["controls"], _ = runner.timed("all_interface_controls", lambda: run_controls(runner, rendered, base_cache, early_target_cache, logits_bank["full"], logits_bank["target_early_reprefill"], tolerance), case_id=case_id)
                else:
                    record["controls"] = {"passed": None, "note": "Controls use frozen E01/C01/W01 only."}
                np.savez_compressed(args.output / f"{case_id}_readout_logits.npz", **{name: x.numpy() for name, x in logits_bank.items()})
                record["logits_artifact"] = f"{case_id}_readout_logits.npz"
                record["all_stage_timings"] = runner.timing[timing_start:]
                record["case_seconds"] = time.monotonic() - case_start
                failed = record["controls"]["passed"] is False
                record["status"] = "P0_INTERFACE_NO_GO" if failed else "COMPLETE"
                atomic_json(args.output / f"{case_id}.json", record)
                records.append(record)
                status = "P0_INTERFACE_NO_GO" if failed else "P0_RUNNING"
                atomic_json(args.output / "summary.json", summarize(records, status, started, args, manifest))
                print(json.dumps({"case_id": case_id, "status": record["status"], "seconds": record["case_seconds"],
                                  "greedy": {name: arm["greedy"]["text"] for name, arm in record["arms"].items()}}, ensure_ascii=False), flush=True)
                del base_cache, early_target_cache, logits_bank
                if failed:
                    break
            else:
                status = "CPU_INTERFACE_ONLY_COMPLETE" if args.cpu_interface_check else "P0_COMPLETE"
        summary = summarize(records, status, started, args, manifest)
        atomic_json(args.output / "summary.json", summary)
        lines = [f"# P0 result: {status}", "", f"Completed {len(records)} injected states; elapsed {summary['elapsed_seconds']:.2f}s.",
                 "", "The five arms preserve all KV tensor slots. No memory-saving claim is supported.", "",
                 "| Arm | Completed | Strictly correct |", "|---|---:|---:|"]
        lines.extend(f"| {name} | {row['n']} | {row['strict_correct']} |" for name, row in summary["arms"].items())
        lines += ["", "## Limits", ""] + ["- " + text for text in LIMITATIONS]
        if args.cpu_interface_check:
            lines += ["", "Random tiny CPU weights and fixture tokenizer: no pretrained Qwen3 performance evidence."]
        (args.output / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 2 if status == "P0_INTERFACE_NO_GO" else 0
    except Exception as exc:
        status = "P0_EXECUTION_ERROR"
        atomic_json(args.output / "error.json", {"status": status, "error": str(exc), "traceback": traceback.format_exc(),
                                                  "progress": progress, "elapsed_seconds": time.monotonic() - started})
        if runner:
            atomic_json(args.output / "timings_on_error.json", runner.timing)
        atomic_json(args.output / "summary.json", summarize(records, status, started, args, manifest))
        traceback.print_exc()
        return 1
    finally:
        finished.set()


if __name__ == "__main__":
    raise SystemExit(main())
