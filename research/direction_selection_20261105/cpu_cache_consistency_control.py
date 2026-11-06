"""CPU-only controlled example of non-prefix KV eviction and state consistency.

Run with Python and PyTorch only. No external model, GPU, network, or downloads.
This is a numerical mechanism control, not evidence of semantic error recurrence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F


DTYPE = torch.float64
DEVICE = torch.device("cpu")
TOLERANCE = 1e-11
MATERIAL_DIFFERENCE = 1e-8
MODEL_SEEDS = [7, 17, 29, 43, 71]
INPUT_SEED = 20261105
DELETION_SEED = 20261106
VOCAB_SIZE = 67
WIDTH = 32
HEADS = 4
LAYERS = 3
PREFIX_LENGTH = 16
DELETE_COUNT = 4


def random_tensor(shape: tuple[int, ...], generator: torch.Generator, scale=1.0):
    return torch.randn(shape, generator=generator, dtype=DTYPE, device=DEVICE) * scale


class TinyCausalTransformer:
    """Three dense pre-LN causal layers, RoPE, and no stochastic layers.

    Cached K are already RoPE-rotated at explicit position_ids; V are not rotated.
    Keeping an index in the cache does not recompute its historical hidden state.
    """

    def __init__(self, seed: int):
        self.generator = torch.Generator(device=DEVICE).manual_seed(seed)
        self.embedding = random_tensor((VOCAB_SIZE, WIDTH), self.generator)
        self.layers = []
        for _ in range(LAYERS):
            self.layers.append({
                "qkv": random_tensor((WIDTH, 3 * WIDTH), self.generator, WIDTH ** -0.5),
                "out": random_tensor((WIDTH, WIDTH), self.generator, WIDTH ** -0.5),
                "up": random_tensor((WIDTH, 2 * WIDTH), self.generator, WIDTH ** -0.5),
                "down": random_tensor((2 * WIDTH, WIDTH), self.generator, (2 * WIDTH) ** -0.5),
            })
        self.final_head = random_tensor((WIDTH, VOCAB_SIZE), self.generator, WIDTH ** -0.5)

    @staticmethod
    def norm(x):
        return F.layer_norm(x, (WIDTH,), eps=1e-5)

    @staticmethod
    def rope(x, positions):
        # x: heads x tokens x head_dim; position_ids need not be contiguous.
        head_dim = WIDTH // HEADS
        inv_freq = 10000.0 ** (-torch.arange(0, head_dim, 2, dtype=DTYPE, device=DEVICE) / head_dim)
        angles = positions.to(dtype=DTYPE)[:, None] * inv_freq[None, :]
        cosine, sine = angles.cos()[None, :, :], angles.sin()[None, :, :]
        even, odd = x[..., 0::2], x[..., 1::2]
        return torch.stack((even * cosine - odd * sine, even * sine + odd * cosine), dim=-1).flatten(-2)

    def project(self, x, layer, positions):
        q, k, v = (self.norm(x) @ layer["qkv"]).chunk(3, dim=-1)
        reshape = lambda z: z.reshape(z.shape[0], HEADS, WIDTH // HEADS).transpose(0, 1)
        return self.rope(reshape(q), positions), self.rope(reshape(k), positions), reshape(v)

    @staticmethod
    def attention(q, k, v, allowed):
        scores = (q @ k.transpose(-1, -2)) / math.sqrt(WIDTH // HEADS)
        probabilities = torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1)
        combined = (probabilities @ v).transpose(0, 1).reshape(q.shape[1], WIDTH)
        return combined, probabilities

    def finish_layer(self, x, attention_output, layer):
        x = x + attention_output @ layer["out"]
        return x + F.gelu(self.norm(x) @ layer["up"], approximate="none") @ layer["down"]

    def prefill(self, tokens, positions):
        assert tokens.device.type == "cpu" and positions.device.type == "cpu"
        x = self.embedding[tokens]
        n = len(tokens)
        causal = torch.ones((n, n), dtype=torch.bool, device=DEVICE).tril()[None, :, :]
        cache = []
        for layer in self.layers:
            q, k, v = self.project(x, layer, positions)
            cache.append((k.clone(), v.clone()))
            attention_output, _ = self.attention(q, k, v, causal)
            x = self.finish_layer(x, attention_output, layer)
        return self.norm(x) @ self.final_head, cache

    def decode_one(self, token, position, cache, readable):
        x = self.embedding[torch.tensor([token], dtype=torch.long, device=DEVICE)]
        positions = torch.tensor([position], dtype=torch.long, device=DEVICE)
        key_mask = torch.cat((readable, torch.ones(1, dtype=torch.bool, device=DEVICE)))[None, None, :]
        attentions = []
        for layer, (old_k, old_v) in zip(self.layers, cache):
            q, k, v = self.project(x, layer, positions)
            all_k = torch.cat((old_k, k), dim=1)
            all_v = torch.cat((old_v, v), dim=1)
            attention_output, probabilities = self.attention(q, all_k, all_v, key_mask)
            attentions.append(probabilities)
            x = self.finish_layer(x, attention_output, layer)
        return (self.norm(x) @ self.final_head)[0], attentions


def max_abs(x):
    return float(x.abs().max().item()) if x.numel() else 0.0


def logit_difference(a, b):
    pa, pb = a.softmax(-1), b.softmax(-1)
    return {
        "max_abs_logit_difference": max_abs(a - b),
        "mean_abs_logit_difference": float((a - b).abs().mean().item()),
        "max_abs_probability_difference": max_abs(pa - pb),
        "probability_total_variation": float((pa - pb).abs().sum().item() / 2),
        "kl_a_to_b": float((pa * (a.log_softmax(-1) - b.log_softmax(-1))).sum().item()),
        "argmax_a": int(a.argmax().item()),
        "argmax_b": int(b.argmax().item()),
        "argmax_changed": bool(a.argmax().item() != b.argmax().item()),
    }


def cache_difference(a, b, original_positions):
    rows = []
    for index, ((ka, va), (kb, vb)) in enumerate(zip(a, b)):
        rows.append({
            "layer_one_based": index + 1,
            "key_max_abs_difference": max_abs(ka - kb),
            "value_max_abs_difference": max_abs(va - vb),
            "per_surviving_position": [
                {"original_position": int(p),
                 "key_max_abs_difference": max_abs(ka[:, j] - kb[:, j]),
                 "value_max_abs_difference": max_abs(va[:, j] - vb[:, j])}
                for j, p in enumerate(original_positions.tolist())
            ],
        })
    return rows


def select_cache(cache, indices):
    return [(k[:, indices, :].clone(), v[:, indices, :].clone()) for k, v in cache]


def poison_deleted_rows(cache, deleted):
    # A finite, very large poison proves that deleted rows are actually unread.
    poisoned = [(k.clone(), v.clone()) for k, v in cache]
    for k, v in poisoned:
        k[:, deleted, :] = 1e6
        v[:, deleted, :] = -1e6
    return poisoned


def run_case(model, tokens, original_positions, probe_token, full_cache, model_seed, deletion):
    deleted = torch.tensor(deletion["deleted_positions"], dtype=torch.long, device=DEVICE)
    readable = torch.ones(PREFIX_LENGTH, dtype=torch.bool, device=DEVICE)
    readable[deleted] = False
    kept = torch.arange(PREFIX_LENGTH, device=DEVICE)[readable]
    kept_tokens, kept_positions = tokens[kept], original_positions[kept]
    kept_readable = torch.ones(len(kept), dtype=torch.bool, device=DEVICE)
    probe_position = PREFIX_LENGTH

    stale_selected = select_cache(full_cache, kept)
    _, clean_cache = model.prefill(kept_tokens, kept_positions)
    stale_logits, masked_attention = model.decode_one(probe_token, probe_position, full_cache, readable)
    evicted_logits, _ = model.decode_one(probe_token, probe_position, stale_selected, kept_readable)
    clean_logits, _ = model.decode_one(probe_token, probe_position, clean_cache, kept_readable)

    all_clean_tokens = torch.cat((kept_tokens, torch.tensor([probe_token], device=DEVICE)))
    all_clean_positions = torch.cat((kept_positions, torch.tensor([probe_position], device=DEVICE)))
    clean_recomputed_logits, _ = model.prefill(all_clean_tokens, all_clean_positions)
    clean_full_logits = clean_recomputed_logits[-1]

    poisoned_logits, _ = model.decode_one(probe_token, probe_position,
                                          poison_deleted_rows(full_cache, deleted), readable)
    unmasked_logits, unmasked_attention = model.decode_one(
        probe_token, probe_position, full_cache,
        torch.ones(PREFIX_LENGTH, dtype=torch.bool, device=DEVICE))

    compact_positions = torch.arange(len(kept), dtype=torch.long, device=DEVICE)
    _, compact_cache = model.prefill(kept_tokens, compact_positions)
    compact_logits, _ = model.decode_one(probe_token, len(kept), compact_cache, kept_readable)

    layer_differences = cache_difference(stale_selected, clean_cache, kept_positions)
    before_first_deleted = kept_positions < int(deleted.min())
    before_differences = [max_abs(a[:, before_first_deleted] - b[:, before_first_deleted])
                          for old_layer, new_layer in zip(stale_selected, clean_cache)
                          for a, b in zip(old_layer, new_layer)]
    deleted_mass = [float(att[:, :, deleted].sum(-1).max().item()) for att in masked_attention]
    original_deleted_mass = [float(att[:, :, deleted].sum(-1).max().item()) for att in unmasked_attention]
    controls = {
        "masked_deleted_key_probability_max_by_layer": deleted_mass,
        "unmasked_deleted_key_probability_mass_max_head_by_layer": original_deleted_mass,
        "poison_deleted_rows_masked_logit_max_abs_difference": max_abs(stale_logits - poisoned_logits),
        "physical_eviction_vs_masked_read_logit_max_abs_difference": max_abs(stale_logits - evicted_logits),
        "clean_cache_decode_vs_full_clean_recompute_logit_max_abs_difference": max_abs(clean_logits - clean_full_logits),
        "prefix_before_first_deleted_cache_max_abs_difference": max(before_differences),
        "first_layer_surviving_kv_max_abs_difference": max(
            layer_differences[0]["key_max_abs_difference"], layer_differences[0]["value_max_abs_difference"]),
    }
    assert max(deleted_mass) == 0.0, "Deleted keys were not truly masked."
    assert max(original_deleted_mass) > 0.0, "Deletion did not remove any previously read key."
    for key in ["poison_deleted_rows_masked_logit_max_abs_difference",
                "physical_eviction_vs_masked_read_logit_max_abs_difference",
                "clean_cache_decode_vs_full_clean_recompute_logit_max_abs_difference",
                "prefix_before_first_deleted_cache_max_abs_difference",
                "first_layer_surviving_kv_max_abs_difference"]:
        assert controls[key] <= TOLERANCE, (key, controls[key])
    later_difference = max(max(row["key_max_abs_difference"], row["value_max_abs_difference"])
                           for row in layer_differences[1:])
    assert later_difference > MATERIAL_DIFFERENCE, "This seeded example did not show stale later-layer cache."
    output_difference = logit_difference(stale_logits, clean_full_logits)
    assert output_difference["max_abs_logit_difference"] > MATERIAL_DIFFERENCE

    return {
        "model_seed": model_seed,
        "deletion_name": deletion["name"],
        "deleted_positions": deleted.tolist(),
        "surviving_token_ids": kept_tokens.tolist(),
        "surviving_original_position_ids": kept_positions.tolist(),
        "original_probe_position_id": probe_position,
        "compressed_position_ids": compact_positions.tolist(),
        "compressed_probe_position_id": len(kept),
        "surviving_stale_vs_clean_cache": layer_differences,
        "masked_old_cache_vs_clean_full_recompute": output_difference,
        "clean_original_positions_vs_clean_compressed_positions": logit_difference(clean_logits, compact_logits),
        "unmasked_old_cache_vs_masked_old_cache": logit_difference(unmasked_logits, stale_logits),
        "controls": controls,
        "assertions_passed": True,
    }


@torch.inference_mode()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_suffix(".json"))
    args = parser.parse_args()
    start = time.perf_counter()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    input_generator = torch.Generator(device=DEVICE).manual_seed(INPUT_SEED)
    tokens = torch.randint(VOCAB_SIZE, (PREFIX_LENGTH,), generator=input_generator, device=DEVICE)
    probe_token = int(torch.randint(VOCAB_SIZE, (1,), generator=input_generator, device=DEVICE).item())
    positions = torch.arange(PREFIX_LENGTH, dtype=torch.long, device=DEVICE)
    deletion_generator = torch.Generator(device=DEVICE).manual_seed(DELETION_SEED)
    # Protect the first three tokens and final two; all patterns remove four rows.
    deletion_pool = torch.arange(3, PREFIX_LENGTH - 2, device=DEVICE)
    deletions = [{"name": "fixed_contiguous_middle", "deleted_positions": [4, 5, 6, 7]}]
    for i in range(5):
        chosen = deletion_pool[torch.randperm(len(deletion_pool), generator=deletion_generator)[:DELETE_COUNT]]
        deletions.append({"name": f"equal_count_random_{i + 1}", "deleted_positions": chosen.sort().values.tolist()})
    cases, no_deletion_controls = [], []
    for seed in MODEL_SEEDS:
        model = TinyCausalTransformer(seed)
        _, full_cache = model.prefill(tokens, positions)
        cached_logits, _ = model.decode_one(probe_token, PREFIX_LENGTH, full_cache,
                                           torch.ones(PREFIX_LENGTH, dtype=torch.bool, device=DEVICE))
        full_logits, _ = model.prefill(torch.cat((tokens, torch.tensor([probe_token], device=DEVICE))),
                                      torch.arange(PREFIX_LENGTH + 1, device=DEVICE))
        difference = max_abs(cached_logits - full_logits[-1])
        assert difference <= TOLERANCE, ("no deletion control", seed, difference)
        no_deletion_controls.append({"model_seed": seed, "cached_decode_vs_full_recompute_max_abs_logit_difference": difference})
        for deletion in deletions:
            cases.append(run_case(model, tokens, positions, probe_token, full_cache, seed, deletion))

    output_diffs = [c["masked_old_cache_vs_clean_full_recompute"]["max_abs_logit_difference"] for c in cases]
    cache_diffs = [max(max(x["key_max_abs_difference"], x["value_max_abs_difference"])
                      for x in c["surviving_stale_vs_clean_cache"][1:]) for c in cases]
    compact_diffs = [c["clean_original_positions_vs_clean_compressed_positions"]["max_abs_logit_difference"] for c in cases]
    all_control_errors = [value for c in cases for key, value in c["controls"].items()
                          if key.endswith("max_abs_difference")]
    all_control_errors += [x["cached_decode_vs_full_recompute_max_abs_logit_difference"] for x in no_deletion_controls]
    summary = {
        "case_count": len(cases),
        "model_seed_count": len(MODEL_SEEDS),
        "deletion_patterns_per_model": len(deletions),
        "all_assertions_passed": all(c["assertions_passed"] for c in cases),
        "material_stale_surviving_cache_cases": sum(x > MATERIAL_DIFFERENCE for x in cache_diffs),
        "material_stale_vs_clean_output_cases": sum(x > MATERIAL_DIFFERENCE for x in output_diffs),
        "stale_later_layer_surviving_cache_max_abs_difference_range": [min(cache_diffs), max(cache_diffs)],
        "stale_vs_clean_max_abs_logit_difference_range": [min(output_diffs), max(output_diffs)],
        "original_vs_compressed_position_max_abs_logit_difference_range": [min(compact_diffs), max(compact_diffs)],
        "stale_vs_clean_argmax_changed_cases": sum(c["masked_old_cache_vs_clean_full_recompute"]["argmax_changed"] for c in cases),
        "max_identity_control_error": max(all_control_errors),
        "max_masked_deleted_key_probability": max(v for c in cases for v in c["controls"]["masked_deleted_key_probability_max_by_layer"]),
    }
    report = {
        "schema_version": 1,
        "status": "PASS_CACHE_INCONSISTENCY_MECHANISM_CONTROL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(Path(__file__).resolve()),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {"python": sys.version, "torch": torch.__version__, "platform": platform.platform(),
                        "device": "cpu", "dtype": "torch.float64", "torch_threads": torch.get_num_threads(),
                        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                        "gpu_used": False, "external_model_used": False, "network_used": False},
        "configuration": {"model": "random dense causal pre-LN Transformer with RoPE and GELU",
                          "layers": LAYERS, "width": WIDTH, "heads": HEADS, "vocab_size": VOCAB_SIZE,
                          "prefix_length": PREFIX_LENGTH, "deleted_row_count": DELETE_COUNT,
                          "model_seeds": MODEL_SEEDS, "input_seed": INPUT_SEED, "deletion_seed": DELETION_SEED,
                          "token_ids": tokens.tolist(), "probe_token_id": probe_token,
                          "original_position_ids": positions.tolist(),
                          "random_deletion_pool": deletion_pool.tolist(), "deletions": deletions,
                          "identity_tolerance": TOLERANCE, "material_difference_threshold": MATERIAL_DIFFERENCE},
        "method": [
            "Compute every layer KV on the original full prefix.",
            "Mask deleted old keys at read time or physically select the identical surviving rows.",
            "Recompute the surviving token prefix from scratch using its original, gapped position_ids.",
            "Compare one shared probe token at the original next position for stale and clean caches.",
            "Validate clean cached decode against full recomputation of clean prefix plus probe.",
            "Poison deleted rows to confirm a read mask truly excludes them; check attention mass is exactly zero.",
            "Separately recompute clean tokens at compressed positions to quantify the position confound.",
            "Repeat the same numerical controls for equal-count random deletion patterns and five model seeds.",
        ],
        "summary": summary,
        "no_deletion_identity_controls": no_deletion_controls,
        "cases": cases,
        "conclusions": [
            "In these fixed random-model cases, deleting middle KV rows does not reconstruct the clean-prefix cache at later layers.",
            "Deleted old keys receive exactly zero attention, yet surviving downstream KV retain the computational effect of their old prefix.",
            "Physical eviction and masked reading agree within numerical tolerance; all-cache clean recomputation restores consistency.",
            "The primary stale-versus-clean comparison preserves original positions; position compression is a separate intervention.",
        ],
        "limitations": [
            "This is an existence/mechanism control on small random Transformers, not a theorem about every input or architecture.",
            "The deleted span has no semantic error label, and the model has no language reasoning competence.",
            "No accuracy gain, natural correction relapse, useful online detector, or real-model performance is established.",
            "Matching positions does not make stale historical computation clean; recomputation cost is not benchmarked here.",
            "An output-distribution change need not change its argmax and is not evidence of a changed task answer.",
        ],
        "elapsed_seconds": time.perf_counter() - start,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "status": report["status"],
                      "elapsed_seconds": report["elapsed_seconds"], "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
