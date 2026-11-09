"""Exact tokenizer/source tests with a deterministic CPU model interface."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import torch

from wcpr_worker import (CHECKPOINTS, D35, capture_snapshot, compile_contract, cues,
                         id_sha, observed_plan, paragraph_matches, reference_runtime,
                         reject_invalid_control, run_arm, seed_controller, source_prefix,
                         terminal_candidate)
from audit_dev_checkpoints import make_tokenizer
from native_snapshot import ExecutionIdentity


BUDGETS = {"point_budget": 16, "work_budget": 1024, "feedback_budget": 4}


class ScriptCache:
    def __init__(self, position):
        self.position = position
        self.layers = [SimpleNamespace(keys=torch.zeros(1, 1, 1, 2), values=torch.zeros(1, 1, 1, 2))]

    def get_seq_length(self):
        return self.position

    def crop(self, position):
        self.position = position


class ScriptEngine:
    """Emit explicit IDs while exercising the real event, EOS, and accounting code."""

    def __init__(self, tokenizer, samples=()):
        self.tokenizer = tokenizer
        self.torch = torch
        self.device = torch.device("cpu")
        self.capacity = 40_960
        self.ledger = []
        self.stage = "setup"
        self.eos = {tokenizer.eos_token_id}
        self.open_ids = tokenizer.encode("<think>", add_special_tokens=False)
        self.close_ids = tokenizer.encode("</think>", add_special_tokens=False)
        stream = []
        for segment in samples:
            ids = [tokenizer.eos_token_id] if segment is None else tokenizer.encode(segment, add_special_tokens=False)
            stream.extend(ids)
        self.stream = iter(stream)

    def sync(self):
        pass

    def rng(self, seed=None, state=None):
        generator = torch.Generator(device="cpu")
        return generator.set_state(state) if state is not None else generator.manual_seed(seed)

    def sample(self, logits, rng):
        torch.rand(1, generator=rng)
        return next(self.stream)

    def forward(self, ids, cache):
        position = cache.position
        cache.position += len(ids)
        self.ledger.append({"stage": self.stage, "input_tokens": len(ids),
                            "past_tokens": position, "position_start": position})
        return cache, torch.zeros(4)


class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokenizer = make_tokenizer()
        cls.identity = ExecutionIdentity("0" * 64, "0" * 64, "0" * 64, "scripted", "FP32",
                                         "cpu", "CPU test only", {"batch": 1})
        cls.packet = json.loads((D35 / "prepared/e15_checkpoint.json").read_bytes())
        d3 = D35.parent / "phase5d25_constraint_revision_20261109"
        cls.raw = json.loads((d3 / cls.packet["source"]).read_bytes())
        cls.contract = compile_contract(cls.packet["question"])
        cls.ref = reference_runtime()

    def test_two_frozen_cuts_share_observed_local_witness(self):
        engine = ScriptEngine(self.tokenizer)
        for name, (_, end) in CHECKPOINTS.items():
            with self.subTest(name=name):
                prefix = source_prefix(engine, self.identity, self.packet, self.raw["generated_ids"][:end], name)
                support = observed_plan(prefix, self.contract)
                controller, setup = seed_controller(prefix, self.contract, support, BUDGETS, "event")
                self.assertEqual((support.left, support.right), (1011235, 303369))
                self.assertLessEqual(support.source_span.token_end, end)
                self.assertEqual(controller.state.incumbent.objective, 1011235)
                self.assertEqual(controller.report()["point_calls"], 2)
                self.assertEqual(len(setup), 2)
                self.assertFalse(reject_invalid_control(prefix, self.contract, support)["exposed_to_model"])
                text = cues(support.left, support.right)
                self.assertEqual(text["VerifiedWitness"], text["ProgressiveWitness"])
                self.assertEqual(text["NeutralReminder"], text["InvalidWitnessControl"])
                self.assertNotIn("10112369", text["VerifiedWitness"])

    def test_no_tentative_or_digit_length_commitment(self):
        self.assertFalse(list(paragraph_matches("Maybe the number is 10112357.")))
        self.assertFalse(list(paragraph_matches("The number is 6 digits long.")))
        self.assertTrue(list(paragraph_matches("Therefore, 10112358 is a valid fibbish number.")))

    def test_actual_archived_terminal_is_a_scoped_regression(self):
        engine = ScriptEngine(self.tokenizer)
        initial = source_prefix(engine, self.identity, self.packet, self.packet["generated_ids"], "native")
        support = observed_plan(initial, self.contract)
        controller, _ = seed_controller(initial, self.contract, support, BUDGETS, "event")
        ids = self.raw["generated_ids"]
        final_start = max(i for i, token in enumerate(ids) if token in engine.close_ids) + 1
        terminal = source_prefix(engine, self.identity, self.packet, ids, "native")
        proposal, selection = terminal_candidate(engine, terminal, self.contract, final_start, self.raw["final_response"])
        self.assertEqual(selection["status"], "ok")
        self.assertEqual(proposal.value, 303369)
        verdict = controller.admit(terminal, proposal, terminal=True, authored_span=(final_start, len(ids)))
        self.assertEqual(verdict.action, "BLOCK_REGRESSION")
        self.assertTrue(verdict.veto)

    def test_real_worker_loop_rejects_paid_draft_and_resumes(self):
        engine = ScriptEngine(self.tokenizer, (
            "Therefore, 10112358 is a valid fibbish number.\n\n",
            r"</think>" + "\n\n" + r"The answer is \boxed{10112357}.", None,
            r"</think>" + "\n\n" + r"The answer is \boxed{10112369}.", None,
        ))
        ids = self.packet["generated_ids"]
        prompt = self.packet["prompt_ids"]
        initial = source_prefix(engine, self.identity, self.packet, ids, "plan")
        support = observed_plan(initial, self.contract)
        snapshot = capture_snapshot(engine, identity=self.identity, prompt_ids=prompt, generated_ids=ids,
                                    cache=ScriptCache(len(prompt) + len(ids)), next_logits=torch.zeros(4),
                                    rng=engine.rng(seed=123), thinking_open=True, checkpoint_id="test")
        with tempfile.TemporaryDirectory() as folder:
            row = run_arm(engine, self.identity, self.ref, snapshot, self.packet, self.contract, support,
                          "historical", "ProgressiveWitness", cues(support.left, support.right)["ProgressiveWitness"],
                          BUDGETS, 1, Path(folder), {})
        self.assertTrue(row["EOS"])
        self.assertIn(r"\boxed{10112369}", row["delivered_final_response"])
        self.assertFalse(row["certified_optimality"])
        self.assertEqual([event["decision"]["action"] for event in row["point_audit_events"]],
                         ["UPDATE_BOUND", "REPAIR_INFEASIBLE", "UPDATE_BOUND"])
        self.assertEqual([record["phase"] for record in row["forced_feedback"]],
                         ["initial_cue", "event_feedback", "terminal_feedback"])
        self.assertEqual(len(row["rejected_drafts"]), 1)
        self.assertIn(r"\boxed{10112357}", row["rejected_drafts"][0]["final_response"])
        restore = row["terminal_restores"][0]
        self.assertEqual(restore["post_draft_rng_before_restore_sha256"], restore["rng_after_restore_sha256"])
        self.assertEqual(row["paid_work_after_cut"]["forward_input_tokens"],
                         row["sampled_continuation_tokens"] + row["teacher_forced_tokens"] - 2)
        self.assertEqual(row["generated_sha256"], id_sha(row["generated_ids"]))


if __name__ == "__main__":
    unittest.main()
