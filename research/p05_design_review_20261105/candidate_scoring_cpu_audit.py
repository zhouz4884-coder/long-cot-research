#!/usr/bin/env python3
"""Read-only P0 scorer recount and random tiny-Qwen3 CPU sequence-score control.

No real model loading, network, GPU, training or mutation of old run artifacts.
The synthetic context IDs used by the tiny model are explicitly arbitrary fixture
IDs, not a reconstruction of the real Qwen tokenizer's y=/z= prefixes.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from collections import Counter


def arithmetic(expression, environment):
    node = ast.parse(expression, mode="eval").body
    def run(value):
        if isinstance(value, ast.Constant) and type(value.value) is int:
            return value.value
        if isinstance(value, ast.Name):
            return environment[value.id]
        if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub):
            return -run(value.operand)
        if isinstance(value, ast.BinOp):
            a, b = run(value.left), run(value.right)
            if isinstance(value.op, ast.Add): return a + b
            if isinstance(value.op, ast.Sub): return a - b
            if isinstance(value.op, ast.Mult): return a * b
            if isinstance(value.op, ast.FloorDiv):
                if b == 0 or a % b: raise ValueError("Nonexact integer division in fixture")
                return a // b
        raise ValueError("Unsupported fixture AST")
    return run(node)


def alias_map(roles):
    by_text = {}
    for role, value in roles.items():
        by_text.setdefault(str(value) + "\n", []).append(role)
    return [{"canonical_continuation": text, "aliases": aliases} for text, aliases in by_text.items()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--p0-dir", required=True, type=Path)
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.p0_dir.glob("[ECW][0-9][0-9].json"))]
    if len(records) != 16:
        raise ValueError("Exactly 16 original records required")
    calls, tokens, collisions = 0, 0, []
    lengths = Counter()
    for record in records:
        for arm_name, arm in record["arms"].items():
            candidates = list(arm["candidate_scores"]["unique_candidates"].values())
            for candidate in candidates:
                ids = candidate["token_ids"]
                assert candidate["teacher_forced_tokens"] == len(ids) - 1
                calls += int(len(ids) > 1)
                tokens += len(ids) - 1
                lengths[len(ids)] += 1
            for i, a in enumerate(candidates):
                for b in candidates[i+1:]:
                    if a["token_ids"][0] == b["token_ids"][0]:
                        collisions.append({"case_id": record["case_id"], "arm": arm_name,
                            "a": a["continuation"], "b": b["continuation"],
                            "a_ids": a["token_ids"], "b_ids": b["token_ids"],
                            "a_first_logP": a["token_logP"][0], "b_first_logP": b["token_logP"][0],
                            "a_full_logP": a["logP"], "b_full_logP": b["logP"]})
    manifest = json.loads((args.p0_dir / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(args.cases.read_text(encoding="utf-8-sig"))
    policy = {"schema": "fixed_four_roles_not_four_distinct_numbers_v1", "scope": "Evaluator-only; never render values into a model prompt.",
              "terminator": "\n", "numeric_format": "str(int(value)), no leading plus or zeros",
              "z_prefix_scope": "A distinct branch ending in a frozen final-z readout; cannot reuse y-query logits.",
              "y_prefix_scope": "A separately budgeted branch ending in a frozen next-y readout; cannot reuse z-query logits.",
              "dedup": "Canonical continuation/token sequence once per identical context; preserve role aliases; alias margins NA.",
              "cases": []}
    for case in payload["cases"]:
        expressions = {d["variable"]: d["expression"] for d in case["definitions"]}
        old_x, revision_x = case["old_root_value"], case["revision_root_value"]
        old_y = arithmetic(expressions["y"], {"x": old_x})
        revision_y = arithmetic(expressions["y"], {"x": revision_x})
        z_roles = {"trusted_final": case["required_final_value"], "old_final": case["old_branch_final_value"],
                   "revision_consistent_final": arithmetic(expressions["z"], {"x": revision_x, "y": revision_y}),
                   "skip_signature": arithmetic(expressions["z"], {"x": revision_x, "y": revision_x})}
        y_roles = {"trusted_y": case["oracle_values"]["y"], "old_y": old_y,
                   "revision_consistent_y": revision_y, "root_misbind": revision_x}
        policy["cases"].append({"case_id": case["case_id"], "z_roles": z_roles, "z_unique": alias_map(z_roles),
                                "y_roles": y_roles, "y_unique": alias_map(y_roles)})
    # Explicit CPU fixture: never touch CUDA; no learned-model performance evidence.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch
    import transformers
    from transformers import Qwen3Config, Qwen3ForCausalLM
    torch.set_num_threads(1)
    torch.manual_seed(20261105)
    config = Qwen3Config(vocab_size=256, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                        num_attention_heads=4, num_key_value_heads=2, head_dim=8,
                        max_position_embeddings=128, attention_dropout=0.0, layer_types=["full_attention"]*2)
    config._attn_implementation = "eager"
    model = Qwen3ForCausalLM(config).eval().to("cpu")
    common = [40, 41, 42]
    cy, cz = common + [80, 15], common + [81, 15]
    continuation_ids = {"30_newline": [18, 15, 198], "33_newline": [18, 18, 198]}
    def forward(ids, cache=None):
        length = 0 if cache is None else cache.get_seq_length()
        return model(input_ids=torch.tensor([ids]), attention_mask=torch.ones(1, length+len(ids), dtype=torch.long),
                     position_ids=torch.arange(length, length+len(ids)).unsqueeze(0), past_key_values=cache,
                     use_cache=True, return_dict=True)
    tiny = {"scope": "RANDOM TINY CPU INTERFACE CONTROL ONLY", "versions": {"torch": torch.__version__, "transformers": transformers.__version__},
            "prefix_ids_y_fixture": cy, "prefix_ids_z_fixture": cz, "prefixes_are_real_tokenizer_ids": False, "contexts": {}}
    with torch.inference_mode():
        logits = {}
        for label, context in (("y_fixture", cy), ("z_fixture", cz)):
            prefill = forward(context)
            initial = prefill.logits[0, -1].double()
            logits[label] = initial
            values = {}
            original_cache_length = prefill.past_key_values.get_seq_length()
            for name, ids in continuation_ids.items():
                first = float(initial.log_softmax(-1)[ids[0]])
                continuation = forward(ids[:-1], copy.deepcopy(prefill.past_key_values))
                tail = [float(continuation.logits[0, i].double().log_softmax(-1)[token]) for i, token in enumerate(ids[1:])]
                dense = forward(context + ids[:-1])
                direct = sum(float(dense.logits[0, len(context)-1+i].double().log_softmax(-1)[token]) for i, token in enumerate(ids))
                values[name] = {"ids": ids, "first_token_logP": first, "full_logP": first+sum(tail),
                                "dense_reference_logP": direct, "cached_dense_abs_error": abs(first+sum(tail)-direct),
                                "extra_candidate_forward_calls": 1, "extra_candidate_input_tokens": len(ids)-1}
            tiny["contexts"][label] = values
            assert prefill.past_key_values.get_seq_length() == original_cache_length
        tiny["y_vs_z_initial_logits_max_abs"] = float((logits["y_fixture"]-logits["z_fixture"]).abs().max())
    output = {"schema": "candidate_scoring_semantics_audit_v1", "old_tokenizer_class": manifest["tokenizer"]["class"],
              "old_model_manifest_sha256": manifest["model_manifest_sha256"], "old_runner_sha256": manifest["source_sha256"],
              "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "old_P0_recount": {"unique_candidate_sequences": sum(lengths.values()),
                    "additional_candidate_forward_calls": calls, "additional_candidate_input_tokens": tokens,
                    "sequence_length_histogram_including_terminator": dict(lengths),
                    "same_first_token_distinct_sequence_pairs": len(collisions), "collisions": collisions},
              "tiny_CPU": tiny}
    (args.output_dir / "candidate_scoring_cpu_evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (args.output_dir / "fixed_candidate_roles.json").write_text(json.dumps(policy, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"old_calls": calls, "old_teacher_forced_tokens": tokens, "old_first_token_collisions": len(collisions),
                      "tiny_prefix_logit_difference": tiny["y_vs_z_initial_logits_max_abs"],
                      "max_tiny_cached_dense_error": max(v["cached_dense_abs_error"] for c in tiny["contexts"].values() for v in c.values())}))


if __name__ == "__main__":
    main()
