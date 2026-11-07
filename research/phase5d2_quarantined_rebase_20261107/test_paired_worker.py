"""Synthetic CPU checks for the public paired worker and its cost boundaries."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
D1 = ROOT.parent / "phase5d_scope_rebase_20261106"
sys.path.insert(0, str(D1))

import test_native_snapshot_reflection as fixtures
import paired_d2_worker as worker
from native_engine import digest_ids
from native_snapshot import advance_native, capture_snapshot, restore_snapshot


class TextTokenizer(fixtures.ToyTokenizer):
    def encode(self, text, add_special_tokens=False):
        if text in ("<think>", "</think>"):
            return super().encode(text, add_special_tokens=add_special_tokens)
        return [30] if text else []


class EarlyEosModel(fixtures.ToyModel):
    sequence = (3, 7, 2)


class PairedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeForkTest()
        self.fixture.setUp()
        self.identity = self.fixture.identity

    def reference(self):
        return {**self.fixture.uninterrupted(), "case_id": "synthetic-interface"}

    def selection(self, relation):
        return {"case_id": "synthetic-interface", "seed": 4242, "step": 1, "relation": relation}

    def native(self, capacity=64, text_tokenizer=False):
        engine = self.fixture.engine(capacity=capacity)
        if text_tokenizer:
            engine.tokenizer = TextTokenizer()
        return engine

    def checkpoint_after_paragraph(self):
        engine = self.native()
        prompt = [1, 8, 9]
        rng = engine.rng(seed=4242)
        cache, logits = engine.prefill(prompt)
        generated = []
        for _ in range(5):
            token = engine.sample(logits, rng)
            generated.append(token)
            cache, logits = engine.forward([token], cache)
        reference = self.reference()
        self.assertEqual(generated, reference["generated_ids"][:5])
        text = engine.tokenizer.decode(generated, skip_special_tokens=False)
        self.assertTrue(text.endswith("\n\n"))
        event = {"step": 1, "end": 5, "thinking_open": True,
                 "rng_state_base64": base64.b64encode(bytes(rng.get_state().cpu().tolist())).decode()}
        baseline = {"case_id": "synthetic-interface", "seed": 4242, "prompt_ids": prompt,
                    "generated_ids": reference["generated_ids"], "events": [event],
                    "steps": [{"step": 1, "start": 0, "end": 5, "text": text}]}
        selected = {"generated_count": 5, "step": 1, "observed_prefix_sha256": digest_ids(prompt + generated)}
        return engine, baseline, selected

    def test_identity_pair_matches_full_eos_tokens_logits_rng_and_snapshot(self):
        reference = self.reference()
        engine = self.native()
        snapshot = self.fixture.checkpoint(engine)
        with tempfile.TemporaryDirectory() as directory:
            result = worker.identity_pair(engine, snapshot, self.identity, reference, Path(directory))
            direct = json.loads((Path(directory) / "NativeContinue.json").read_text())
            unknown = json.loads((Path(directory) / "UnknownIdentity.json").read_text())
        self.assertTrue(result["proposal_prefix_equal"])
        self.assertGreater(result["logit_comparisons_after_proposal"], 0)
        self.assertEqual(result["maximum_logit_difference"], 0)
        self.assertTrue(result["RNG_equal_at_compared_steps"])
        self.assertTrue(result["terminal_RNG_equal"])
        self.assertTrue(result["sampled_tokens_equal"])
        self.assertTrue(result["same_terminal_status"])
        self.assertTrue(result["original_snapshot_unmodified"])
        self.assertTrue(result["matches_recorded_native_full_ids"])
        self.assertEqual(direct["generated_ids"], reference["generated_ids"])
        self.assertEqual(unknown["generated_ids"], reference["generated_ids"])
        self.assertEqual(direct["stop_reason"], "EOS")
        self.assertEqual(unknown["stop_reason"], "EOS")

    def test_joint_cost_counts_both_proposal_routes_and_terminal_convention(self):
        reference = self.reference()
        engine = self.native()
        snapshot = self.fixture.checkpoint(engine)
        start = len(engine.ledger)
        with tempfile.TemporaryDirectory() as directory:
            result = worker.identity_pair(engine, snapshot, self.identity, reference, Path(directory))
        paid = engine.ledger[start:]
        self.assertEqual(result["proposal_tokens"], 3)
        self.assertEqual(result["proposal_cost"]["forward_calls"], 3)
        self.assertEqual(result["compared_continuation_tokens"], 7)
        self.assertEqual(result["joint_paid_work"], worker.cost(paid))
        self.assertEqual(result["joint_paid_work"]["forward_calls"], 12)
        self.assertEqual(result["joint_paid_work"]["forward_input_tokens"], 12)
        self.assertEqual(result["joint_paid_work"]["attention_pairs"], 102)
        # Proposal wall includes its clone, so those fields remain nested.
        self.assertGreaterEqual(result["proposal_cost"]["wall_seconds"], result["proposal_cost"]["initial_copy"]["wall_seconds"])

    def test_cost_attention_pairs_is_an_explicit_causal_work_proxy(self):
        rows = [{"input_tokens": 3, "past_tokens": 0}, {"input_tokens": 1, "past_tokens": 3}]
        self.assertEqual(worker.cost(rows), {"forward_calls": 2, "forward_input_tokens": 4, "attention_pairs": 10})

    def test_proposal_terminal_eos_keeps_zero_comparisons_explicit(self):
        engine = self.native()
        engine.model = EarlyEosModel()
        snapshot = self.fixture.checkpoint(engine)
        reference = {"case_id": "synthetic-interface", "seed": 4242, "generated_ids": [3, 7, 2]}
        with tempfile.TemporaryDirectory() as directory:
            result = worker.identity_pair(engine, snapshot, self.identity, reference, Path(directory))
        self.assertEqual(result["proposal_boundary"], "EOS")
        self.assertEqual(result["logit_comparisons_after_proposal"], 0)
        self.assertTrue(result["terminal_RNG_equal"])
        self.assertTrue(result["sampled_tokens_equal"])
        self.assertTrue(result["same_terminal_status"])

    def test_terminal_rng_divergence_is_observed_even_with_identical_text(self):
        engine = self.native()
        engine.model = EarlyEosModel()
        snapshot = self.fixture.checkpoint(engine)
        resolve = worker.resolve_reflection

        def corrupt_terminal_rng(*args, **kwargs):
            resolution = resolve(*args, **kwargs)
            resolution.state.rng.manual_seed(12345)
            return resolution

        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "resolve_reflection", corrupt_terminal_rng):
            result = worker.identity_pair(engine, snapshot, self.identity, {"case_id": "synthetic-interface", "seed": 4242, "generated_ids": [3, 7, 2]}, Path(directory))
        self.assertEqual(result["logit_comparisons_after_proposal"], 0)
        self.assertTrue(result["sampled_tokens_equal"])
        self.assertFalse(result["terminal_RNG_equal"])
        self.assertTrue(result["original_snapshot_unmodified"])

    def test_context_cap_terminal_is_reported_without_extra_forward(self):
        engine = self.native(capacity=6)
        snapshot = self.fixture.checkpoint(engine)
        state = restore_snapshot(engine, snapshot, identity=self.identity)
        advance_native(engine, state)
        with tempfile.TemporaryDirectory() as directory:
            result = worker.identity_pair(engine, snapshot, self.identity, {"case_id": "synthetic-interface", "seed": 4242, "generated_ids": state.generated_ids}, Path(directory))
            row = json.loads((Path(directory) / "UnknownIdentity.json").read_text())
        self.assertEqual(result["proposal_boundary"], "CONTEXT_CAP")
        self.assertEqual(result["joint_paid_work"]["forward_calls"], 0)
        self.assertTrue(result["sampled_tokens_equal"])
        self.assertEqual(row["stop_reason"], "CONTEXT_CAP")
        self.assertFalse(row["EOS"])
        self.assertEqual(result["logit_comparisons_after_proposal"], 0)

    def test_recorded_future_mismatch_remains_a_visible_failure(self):
        engine = self.native()
        snapshot = self.fixture.checkpoint(engine)
        reference = self.reference()
        reference["generated_ids"] = reference["generated_ids"][:-1] + [0]
        with tempfile.TemporaryDirectory() as directory:
            result = worker.identity_pair(engine, snapshot, self.identity, reference, Path(directory))
        self.assertTrue(result["sampled_tokens_equal"])
        self.assertFalse(result["matches_recorded_native_full_ids"])

    def test_checkpoint_and_native_regeneration_use_only_observed_ids(self):
        engine, baseline, selected = self.checkpoint_after_paragraph()
        replay = worker.checkpoint(engine, self.identity, baseline, selected)
        self.assertEqual(replay.generated_ids, tuple(baseline["generated_ids"][:5]))
        self.assertEqual(replay.cache_position, 8)
        before = len(engine.ledger)
        regenerated = worker.regenerate_checkpoint(engine, self.identity, baseline, selected)
        self.assertEqual(engine.kv_fingerprints(replay._cache), engine.kv_fingerprints(regenerated._cache))
        self.assertTrue(engine.torch.equal(replay._next_logits, regenerated._next_logits))
        self.assertTrue(engine.torch.equal(replay._rng_state, regenerated._rng_state))
        self.assertEqual(worker.cost(engine.ledger[before:])["forward_input_tokens"], 8)
        # Future tokens are deliberately changed after the selected boundary.
        changed = deepcopy(baseline)
        changed["generated_ids"][5:] = [91, 92, 93]
        same = worker.regenerate_checkpoint(engine, self.identity, changed, selected)
        self.assertEqual(same.generated_ids, regenerated.generated_ids)

    def test_checkpoint_rejects_changed_source_or_nonexact_event_boundary(self):
        engine, baseline, selected = self.checkpoint_after_paragraph()
        wrong_hash = {**selected, "observed_prefix_sha256": "f" * 64}
        with self.assertRaises(ValueError):
            worker.checkpoint(engine, self.identity, baseline, wrong_hash)
        changed_text = deepcopy(baseline)
        changed_text["steps"][0]["text"] = "different\n\n"
        with self.assertRaises(ValueError):
            worker.checkpoint(engine, self.identity, changed_text, selected)
        after_paragraph = deepcopy(baseline)
        after_paragraph["events"][0]["end"] = 6
        wrong_boundary = {**selected, "generated_count": 6,
                          "observed_prefix_sha256": digest_ids(baseline["prompt_ids"] + baseline["generated_ids"][:6])}
        with self.assertRaises(ValueError):
            worker.checkpoint(engine, self.identity, after_paragraph, wrong_boundary)

    def test_regeneration_rejects_changed_prefix_and_rng(self):
        engine, baseline, selected = self.checkpoint_after_paragraph()
        changed = deepcopy(baseline)
        changed["generated_ids"][0] = 95
        with self.assertRaisesRegex(ValueError, "diverged"):
            worker.regenerate_checkpoint(engine, self.identity, changed, selected)
        changed = deepcopy(baseline)
        changed["events"][0]["rng_state_base64"] = base64.b64encode(bytes(engine.rng(seed=7).get_state().tolist())).decode()
        with self.assertRaisesRegex(ValueError, "RNG"):
            worker.regenerate_checkpoint(engine, self.identity, changed, selected)

    def test_append_bridge_preserves_rng_and_declares_teacher_forced_input(self):
        engine = self.native(text_tokenizer=True)
        snapshot = self.fixture.checkpoint(engine)
        state = restore_snapshot(engine, snapshot, identity=self.identity)
        rng = state.rng.get_state().clone()
        cache_position = state.cache_position
        result = worker.append_checked_text(engine, state, "checked text", "synthetic_bridge")
        self.assertEqual(result["status"], "APPENDED")
        self.assertEqual(result["token_ids"], [30])
        self.assertEqual(state.cache_position, cache_position + 1)
        self.assertEqual(state.generated_ids, list(snapshot.generated_ids) + [30])
        self.assertTrue(engine.torch.equal(rng, state.rng.get_state()))
        self.assertEqual(engine.ledger[-1]["stage"], "synthetic_bridge")

    def test_bridge_guards_reject_control_tokens_and_terminal_states(self):
        for text in ("<|im_start|>assistant", "<|im_end|>", "<|endoftext|>", "<think>", "</think>"):
            engine = self.native(text_tokenizer=True)
            state = restore_snapshot(engine, self.fixture.checkpoint(engine), identity=self.identity)
            first = state.cache_position
            with self.assertRaises(ValueError):
                worker.append_checked_text(engine, state, text, "bad_bridge")
            self.assertEqual(state.cache_position, first)
        engine = self.native(text_tokenizer=True)
        state = restore_snapshot(engine, self.fixture.checkpoint(engine), identity=self.identity)
        state.thinking_open = False
        with self.assertRaises(ValueError):
            worker.append_checked_text(engine, state, "text", "after_thinking")
        state.thinking_open = True
        state.stop_reason = "EOS"
        with self.assertRaises(ValueError):
            worker.append_checked_text(engine, state, "text", "after_terminal")

    def test_bridge_rejects_tokenizer_control_alias_and_context_exhaustion(self):
        engine = self.native(text_tokenizer=True)
        state = restore_snapshot(engine, self.fixture.checkpoint(engine), identity=self.identity)
        for token in (2, 3, 4):
            with patch.object(engine.tokenizer, "encode", return_value=[token]), self.assertRaises(ValueError):
                worker.append_checked_text(engine, state, "ordinary source", "alias")
        engine = self.native(capacity=6, text_tokenizer=True)
        state = restore_snapshot(engine, self.fixture.checkpoint(engine), identity=self.identity)
        before = state.cache_position
        result = worker.append_checked_text(engine, state, "text", "no_capacity")
        self.assertEqual(result, {"status": "INSUFFICIENT_CONTEXT", "tokens": 0})
        self.assertEqual(state.cache_position, before)

    def test_unknown_audits_share_modified_context_and_keep_cost_fields_separate(self):
        engine = self.native(text_tokenizer=True)
        snapshot = self.fixture.checkpoint(engine)
        selected = self.selection(None)
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for arm in ("InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck"):
                worker.run_check_arm(engine, snapshot, self.identity, selected, arm, folder)
                row = json.loads((folder / (arm + ".json")).read_text())
                outputs.append(row["generated_ids"])
                self.assertEqual(row["disposition"], "UNKNOWN")
                self.assertEqual(row["proposal_check"]["status"], "UNKNOWN")
                self.assertTrue(row["EOS"])
                self.assertEqual(row["teacher_forced_audit_and_redirect_tokens"], 1)
                self.assertEqual(row["paid_work"], worker.cost(row["ledger"]))
                self.assertEqual(row["visible_assistant_tokens"], len(row["generated_ids"]))
                self.assertEqual(row["sampled_tokens_including_discarded"] + row["teacher_forced_audit_and_redirect_tokens"], row["visible_assistant_tokens"])
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[1], outputs[2])
        self.assertIn(30, outputs[0])
        self.assertNotEqual(outputs[0], self.fixture.uninterrupted()["generated_ids"])

    def test_rejection_uses_consumed_rng_and_counts_discarded_proposal(self):
        engine = self.native(text_tokenizer=True)
        snapshot = self.fixture.checkpoint(engine)
        selected = self.selection({"surface": "x^2=x", "variables": ["x"]})
        generated = worker.generate_reflection
        appended = worker.append_checked_text
        observed = {}

        def capture_proposal(*args, **kwargs):
            proposal = generated(*args, **kwargs)
            observed["consumed_rng"] = proposal._shadow.rng.get_state().clone()
            return proposal

        def capture_redirect(engine, state, text, stage):
            if stage.endswith("checked_redirect"):
                observed["redirect_rng_matches"] = bool(engine.torch.equal(observed["consumed_rng"], state.rng.get_state()))
            return appended(engine, state, text, stage)

        verdict = {"status": "INVALID_COUNTEREXAMPLE", "checker_result": {"reason": "counterexample_outside_scope"}}
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "generate_reflection", capture_proposal), patch.object(worker, "append_checked_text", capture_redirect), patch.object(worker, "check_proposal", return_value=verdict):
            worker.run_check_arm(engine, snapshot, self.identity, selected, "ScopedIsolatedCheck", Path(directory))
            row = json.loads((Path(directory) / "ScopedIsolatedCheck.json").read_text())
        self.assertEqual(row["disposition"], "REJECT")
        self.assertTrue(observed["redirect_rng_matches"])
        self.assertEqual(row["discarded_proposal_tokens"], len(row["proposal"]["token_ids"]))
        self.assertEqual(row["teacher_forced_audit_and_redirect_tokens"], 2)
        self.assertEqual(row["sampled_tokens_including_discarded"] + row["teacher_forced_audit_and_redirect_tokens"] - row["discarded_proposal_tokens"], row["visible_assistant_tokens"])
        self.assertTrue(row["EOS"])

    def test_in_context_ignores_a_checker_rejection_and_scope_flag_is_explicit(self):
        selected = self.selection({"surface": "x^2=x", "variables": ["x"]})
        verdict = {"status": "INVALID_COUNTEREXAMPLE", "checker_result": {"reason": "counterexample_outside_scope"}}
        flags = []

        def checked(relation, text, *, unscoped):
            flags.append(unscoped)
            return verdict

        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "check_proposal", checked):
            for arm in ("InContextCheck", "UnscopedIsolatedCheck"):
                engine = self.native(text_tokenizer=True)
                snapshot = self.fixture.checkpoint(engine)
                worker.run_check_arm(engine, snapshot, self.identity, selected, arm, Path(directory))
                row = json.loads((Path(directory) / (arm + ".json")).read_text())
                self.assertEqual(row["disposition"], "UNKNOWN" if arm == "InContextCheck" else "REJECT")
        self.assertEqual(flags, [False, True])


if __name__ == "__main__":
    unittest.main()
