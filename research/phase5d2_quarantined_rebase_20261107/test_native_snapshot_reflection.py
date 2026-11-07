"""CPU controls for exact snapshots and shadow-state adoption."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent
D1 = ROOT.parent / "phase5d_scope_rebase_20261106"
RUNTIME = ROOT.parent / "p05_design_review_20261105" / "runtime4552"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(RUNTIME))

import torch
from transformers import Qwen3Config, Qwen3ForCausalLM

from native_snapshot import (
    ExecutionIdentity,
    advance_native,
    capture_snapshot,
    replay_schedule,
    replay_snapshot,
    restore_snapshot,
)
from reflection_fork import generate_reflection, resolve_reflection


spec = importlib.util.spec_from_file_location("d1_native_engine", D1 / "native_engine.py")
d1_native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d1_native)


class ToyTokenizer:
    eos_token_id = 2
    pad_token_id = 0

    def encode(self, text, add_special_tokens=False):
        return {"<think>": [3], "</think>": [4]}[text]

    def decode(self, ids, skip_special_tokens=False):
        tokens = list(ids)
        header = ""
        if tokens[:3] == [1, 8, 9]:
            header = "<|im_start|>assistant\n"
            tokens = tokens[3:]
        special = {2: "<|im_end|>", 3: "<think>", 4: "</think>"}
        parts = [header]
        for token in tokens:
            if token in special:
                if not skip_special_tokens:
                    parts.append(special[token])
            else:
                parts.append("\n" if token == 6 else f"a{token}")
        return "".join(parts)

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=True, enable_thinking=True):
        if len(messages) != 1 or messages[0]["role"] != "user":
            raise ValueError("Toy template expects one user turn")
        return [1, 8, 9] if enable_thinking else [1, 8, 9, 3, 6, 6, 4]


class ToyCache:
    def __init__(self):
        self.layers = [SimpleNamespace(keys=torch.empty((1, 1, 0, 1)), values=torch.empty((1, 1, 0, 1)))]

    def get_seq_length(self):
        return self.layers[0].keys.shape[-2]

    def append(self, ids):
        block = torch.tensor(ids, dtype=torch.float32).reshape(1, 1, -1, 1)
        layer = self.layers[0]
        layer.keys = torch.cat([layer.keys, block], dim=-2)
        layer.values = torch.cat([layer.values, block + 1], dim=-2)


class ToyModel:
    # Multi-choice steps consume RNG and can change both the proposal and answer.
    sequence = (3, 7, (20, 21), 6, 6, 22, 4, (23, 24), 2)

    def __init__(self, capacity=64):
        self.config = SimpleNamespace(max_position_embeddings=capacity)
        self.generation_config = SimpleNamespace(eos_token_id=2)

    def __call__(self, input_ids, past_key_values=None, **kwargs):
        cache = ToyCache() if past_key_values is None else past_key_values
        start = cache.get_seq_length()
        expected_positions = list(range(start, start + input_ids.shape[1]))
        if kwargs["cache_position"].tolist() != expected_positions:
            raise ValueError("Toy model got different cache positions")
        if kwargs["position_ids"][0].tolist() != expected_positions:
            raise ValueError("Toy model got different position IDs")
        if not bool((kwargs["attention_mask"] == 1).all()):
            raise ValueError("Toy model requires all-ones attention mask")
        cache.append(input_ids[0].tolist())
        index = min(max(0, cache.get_seq_length() - 3), len(self.sequence) - 1)
        candidates = self.sequence[index]
        if type(candidates) is int:
            candidates = (candidates,)
        logits = torch.full((1, 1, 96), -1000.0)
        logits[0, 0, list(candidates)] = 0
        return SimpleNamespace(logits=logits, past_key_values=cache)


class NativeForkTest(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(4)
        self.identity = ExecutionIdentity(
            "toy-model", "toy-tokenizer", "D1-engine", "sdpa", "FP32", "cpu", "CPU fixture",
            {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0},
        )

    def engine(self, capacity=64):
        return d1_native.NativeEngine(ToyModel(capacity), ToyTokenizer(), torch.device("cpu"))

    def prefix_state(self, engine):
        prompt = [1, 8, 9]
        rng = engine.rng(seed=4242)
        generated = []
        with torch.inference_mode():
            cache, logits = engine.prefill(prompt)
            for _ in range(2):
                token = engine.sample(logits, rng)
                generated.append(token)
                cache, logits = engine.forward([token], cache)
        return {
            "prompt_ids": prompt, "generated_ids": generated, "cache": cache,
            "next_logits": logits, "rng": rng, "thinking_open": True,
        }

    def checkpoint(self, engine, name="origin"):
        return capture_snapshot(engine, identity=self.identity, checkpoint_id=name, **self.prefix_state(engine))

    def finish(self, engine, state):
        while state.stop_reason == "RUNNING":
            advance_native(engine, state)
        return state

    def uninterrupted(self):
        with tempfile.TemporaryDirectory(prefix="phase5d2_toy_") as tmp, torch.inference_mode():
            return self.engine().run(
                "Synthetic interface fixture", 4242, Path(tmp),
                lambda path, obj: path.write_text(json.dumps(obj), encoding="utf-8"),
            )

    def test_capture_owns_exact_cache_logits_ids_and_rng(self):
        engine = self.engine()
        live = self.prefix_state(engine)
        fingerprint = engine.kv_fingerprints(live["cache"])
        logits = live["next_logits"].clone()
        rng_state = live["rng"].get_state().clone()
        snap = capture_snapshot(engine, identity=self.identity, checkpoint_id="origin", **live)
        with torch.inference_mode():
            live["cache"].layers[0].keys.add_(100)
            live["next_logits"].zero_()
        live["rng"].manual_seed(99)
        live["generated_ids"].append(50)
        clone = restore_snapshot(engine, snap, identity=self.identity)
        self.assertEqual(clone.prefix_ids, (1, 8, 9, 3, 7))
        self.assertEqual(clone.cache_position, 5)
        self.assertTrue(clone.thinking_open)
        self.assertTrue(torch.equal(logits, clone.next_logits))
        self.assertTrue(torch.equal(rng_state, clone.rng.get_state()))
        self.assertEqual(fingerprint, engine.kv_fingerprints(clone.cache))
        self.assertGreater(snap.copy_cost.cache_bytes, 0)
        self.assertGreater(snap.copy_cost.logits_bytes, 0)
        self.assertGreater(snap.copy_cost.rng_bytes, 0)

    def test_schedule_matched_replay_recovers_the_checkpoint(self):
        engine = self.engine()
        snap = self.checkpoint(engine)
        restored = restore_snapshot(engine, snap, identity=self.identity)
        engine.ledger.clear()
        replayed = replay_snapshot(engine, snap, identity=self.identity)
        self.assertEqual([entry["input_tokens"] for entry in engine.ledger], [3, 1, 1])
        self.assertEqual([entry["position_start"] for entry in engine.ledger], [0, 3, 4])
        self.assertTrue(torch.equal(restored.next_logits, replayed.next_logits))
        self.assertTrue(torch.equal(restored.rng.get_state(), replayed.rng.get_state()))
        self.assertEqual(engine.kv_fingerprints(restored.cache), engine.kv_fingerprints(replayed.cache))

    def test_unknown_adoption_matches_uninterrupted_d1_until_eos(self):
        reference = self.uninterrupted()
        engine = self.engine()
        snap = self.checkpoint(engine)
        initial = restore_snapshot(engine, snap, identity=self.identity)
        initial_fingerprint = engine.kv_fingerprints(initial.cache)
        global_rng = torch.random.get_rng_state().clone()
        proposal = generate_reflection(engine, snap, identity=self.identity)
        self.assertEqual(proposal.stop_reason, "COMPLETED_STEP")
        self.assertEqual(proposal.token_ids, tuple(reference["generated_ids"][2:5]))
        self.assertEqual(proposal.cost.generated_tokens, 3)
        self.assertEqual(proposal.cost.forward_calls, 3)
        self.assertEqual(proposal.cost.forward_input_tokens, 3)
        self.assertGreaterEqual(proposal.cost.wall_seconds, proposal.cost.initial_copy.wall_seconds)
        self.assertTrue(torch.equal(global_rng, torch.random.get_rng_state()))
        calls = len(engine.ledger)
        shadow = proposal._shadow
        outcome = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")
        self.assertIs(outcome.state, shadow)
        self.assertEqual(len(engine.ledger), calls)
        self.assertIsNone(outcome.rollback_copy_cost)
        final = self.finish(engine, outcome.state)
        self.assertEqual(final.generated_ids, reference["generated_ids"])
        self.assertEqual(final.stop_reason, "EOS")
        self.assertFalse(final.thinking_open)
        self.assertEqual(final.cache_position, len(final.prefix_ids) - 1)
        again = restore_snapshot(engine, snap, identity=self.identity)
        self.assertEqual(initial_fingerprint, engine.kv_fingerprints(again.cache))
        self.assertTrue(torch.equal(initial.rng.get_state(), again.rng.get_state()))

    def test_accept_transfers_shadow_exactly_once(self):
        engine = self.engine()
        snap = self.checkpoint(engine)
        proposal = generate_reflection(engine, snap, identity=self.identity)
        shadow = proposal._shadow
        outcome = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="ACCEPT")
        self.assertIs(outcome.state, shadow)
        self.assertFalse(outcome.requires_redirect)
        self.assertEqual(outcome.discarded_proposal_tokens, 0)
        with self.assertRaisesRegex(ValueError, "already resolved"):
            resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")

    def test_reject_restores_rng_and_requires_redirection(self):
        engine = self.engine()
        snap = self.checkpoint(engine)
        reference = restore_snapshot(engine, snap, identity=self.identity)
        proposal = generate_reflection(engine, snap, identity=self.identity)
        count = len(engine.ledger)
        outcome = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="REJECT")
        self.assertTrue(outcome.requires_redirect)
        self.assertEqual(outcome.discarded_proposal_tokens, len(proposal.token_ids))
        self.assertEqual(outcome.state.prefix_ids, snap.prefix_ids)
        self.assertTrue(torch.equal(outcome.state.next_logits, reference.next_logits))
        self.assertTrue(torch.equal(outcome.state.rng.get_state(), reference.rng.get_state()))
        self.assertIsNotNone(outcome.rollback_copy_cost)
        self.assertEqual(len(engine.ledger), count)
        # An unredirected retry regenerates the same proposal on this control.
        again = generate_reflection(engine, snap, identity=self.identity)
        self.assertEqual(again.token_ids, proposal.token_ids)

    def test_proposal_limit_leaves_native_continuation_available(self):
        reference = self.uninterrupted()
        engine = self.engine()
        snap = self.checkpoint(engine)
        proposal = generate_reflection(engine, snap, identity=self.identity, max_proposal_tokens=1)
        self.assertEqual(proposal.stop_reason, "PROPOSAL_LIMIT")
        self.assertEqual(proposal.native_stop_reason, "RUNNING")
        result = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")
        self.assertEqual(self.finish(engine, result.state).generated_ids, reference["generated_ids"])

    def test_think_close_ends_the_proposal_and_leaves_answer_live(self):
        reference = self.uninterrupted()
        engine = self.engine()
        snap = self.checkpoint(engine)
        proposal = generate_reflection(engine, snap, identity=self.identity, completed_step=lambda ids, text: False)
        self.assertEqual(proposal.stop_reason, "THINK_CLOSED")
        self.assertEqual(proposal.native_stop_reason, "RUNNING")
        result = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")
        self.assertFalse(result.state.thinking_open)
        self.assertEqual(self.finish(engine, result.state).generated_ids, reference["generated_ids"])

    def test_context_cap_terminal_token_does_not_enter_cache(self):
        engine = self.engine(capacity=6)
        snap = self.checkpoint(engine)
        proposal = generate_reflection(engine, snap, identity=self.identity)
        self.assertEqual(proposal.native_stop_reason, "CONTEXT_CAP")
        self.assertEqual(proposal.cost.generated_tokens, 1)
        self.assertEqual(proposal.cost.forward_calls, 0)
        outcome = resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")
        state = outcome.state
        terminal = capture_snapshot(
            engine, identity=self.identity, checkpoint_id="terminal",
            prompt_ids=state.prompt_ids, generated_ids=state.generated_ids, cache=state.cache,
            next_logits=state.next_logits, rng=state.rng, thinking_open=state.thinking_open,
            stop_reason=state.stop_reason,
        )
        self.assertEqual(terminal.cache_position, 5)
        self.assertEqual(len(terminal.prefix_ids), 6)
        replayed = replay_snapshot(engine, terminal, identity=self.identity)
        self.assertIsNone(replayed.next_logits)
        self.assertEqual(replayed.stop_reason, "CONTEXT_CAP")
        self.assertEqual(replayed.cache_position, 5)

    def test_mismatched_execution_or_origin_is_rejected(self):
        engine = self.engine()
        snap = self.checkpoint(engine)
        with self.assertRaisesRegex(ValueError, "identity"):
            restore_snapshot(engine, snap, identity=replace(self.identity, engine_sha256="different"))
        proposal = generate_reflection(engine, snap, identity=self.identity)
        other = self.checkpoint(engine, name="other")
        with self.assertRaisesRegex(ValueError, "another snapshot"):
            resolve_reflection(engine, other, proposal, identity=self.identity, disposition="ACCEPT")
        with self.assertRaisesRegex(ValueError, "boundary configuration"):
            resolve_reflection(self.engine(capacity=63), snap, proposal, identity=self.identity, disposition="ACCEPT")
        resolve_reflection(engine, snap, proposal, identity=self.identity, disposition="UNKNOWN")

    def test_mismatched_snapshot_position_or_thinking_flag_is_rejected(self):
        engine = self.engine()
        live = self.prefix_state(engine)
        with self.assertRaisesRegex(ValueError, "cached prefix"):
            capture_snapshot(engine, identity=self.identity, checkpoint_id="bad-position",
                             **{**live, "generated_ids": [3, 7, 8]})
        with self.assertRaisesRegex(ValueError, "Thinking state"):
            capture_snapshot(engine, identity=self.identity, checkpoint_id="bad-think",
                             **{**live, "thinking_open": False})

    def test_tiny_qwen_dynamic_cache_restore_matches_same_schedule(self):
        torch.manual_seed(20261107)
        cfg = Qwen3Config(
            vocab_size=96, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=2, head_dim=8, max_position_embeddings=128,
            attention_dropout=0.0, eos_token_id=2, pad_token_id=0, bos_token_id=1,
            layer_types=["full_attention"] * 2,
        )
        cfg._attn_implementation = "sdpa"
        engine = d1_native.NativeEngine(Qwen3ForCausalLM(cfg).eval(), ToyTokenizer(), torch.device("cpu"))
        prompt = [1, 8, 9]
        observed = [3, 22, 23]
        cache, logits = replay_schedule(engine, prompt, observed)
        original_fingerprint = engine.kv_fingerprints(cache)
        snap = capture_snapshot(
            engine, identity=self.identity, prompt_ids=prompt, generated_ids=observed,
            cache=cache, next_logits=logits, rng=engine.rng(seed=21), thinking_open=True,
            checkpoint_id="tiny",
        )
        restored = restore_snapshot(engine, snap, identity=self.identity)
        replayed = replay_snapshot(engine, snap, identity=self.identity)
        self.assertTrue(torch.equal(restored.next_logits, replayed.next_logits))
        self.assertEqual(original_fingerprint, engine.kv_fingerprints(replayed.cache))
        for _ in range(8):
            if restored.stop_reason != "RUNNING":
                break
            self.assertEqual(advance_native(engine, restored), advance_native(engine, replayed))
        self.assertEqual(restored.stop_reason, replayed.stop_reason)
        self.assertEqual(original_fingerprint, engine.kv_fingerprints(cache))


if __name__ == "__main__":
    unittest.main(verbosity=2)
