"""Audit actual worker receipt structure with a scripted stream and frozen tokenizer."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from audit_d36_receipts import audit_receipt_row
import test_wcpr_worker as runtime
from wcpr_worker import capture_snapshot, cues, observed_plan, run_arm, source_prefix


FREEZE = {"primary_point_budget": 16, "arithmetic_work_budget": 1024, "feedback_budget": 4,
          "terminal_repair_attempts": 1}


class ReceiptAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.RuntimeTest.setUpClass()
        cls.context = runtime.RuntimeTest

    def run_script(self, arm, samples, *, feedback_budget=4):
        c = self.context
        engine = runtime.ScriptEngine(c.tokenizer, samples)
        packet = {**c.packet, "checkpoint_step": 464}
        ids, prompt = packet["generated_ids"], packet["prompt_ids"]
        initial = source_prefix(engine, c.identity, packet, ids, "plan")
        support = observed_plan(initial, c.contract)
        snapshot = capture_snapshot(engine, identity=c.identity, prompt_ids=prompt, generated_ids=ids,
                                    cache=runtime.ScriptCache(len(prompt) + len(ids)), next_logits=torch.zeros(4),
                                    rng=engine.rng(seed=123), thinking_open=True, checkpoint_id="test")
        with tempfile.TemporaryDirectory() as folder:
            row = run_arm(engine, c.identity, c.ref, snapshot, packet, c.contract, support, "historical", arm,
                          cues(support.left, support.right)[arm], {**runtime.BUDGETS, "feedback_budget": feedback_budget},
                          1, Path(folder), {})
        return row, (packet, c.contract, c.tokenizer, c.identity.tokenizer_sha256,
                     {**FREEZE, "feedback_budget": feedback_budget}, support)

    def test_reconstruct_rejected_draft_and_refuse_nested_receipt_tampering(self):
        row, args = self.run_script("ProgressiveWitness", (
            "Therefore, 10112358 is a valid fibbish number.\n\n",
            "</think>\n\n" + r"The answer is \boxed{10112357}.", None,
            "</think>\n\n" + r"The answer is \boxed{10112369}.", None,
        ))
        counted = audit_receipt_row(row, *args)
        self.assertEqual(counted["point_events_verified"], 5)
        self.assertEqual(counted["rejected_drafts_reconstructed"], 1)
        self.assertFalse(counted["terminal_withheld"])
        for label, corrupt in (
            ("thinking event", lambda x: x["point_audit_events"][0]["decision"]["receipt"].update(status="UNKNOWN")),
            ("forced event_feedback", lambda x: x["forced_feedback"][1]["token_ids"].__setitem__(0, 100)),
            ("rejected draft digest", lambda x: x["rejected_drafts"][0]["discarded_sampled_ids"].__setitem__(-1, 101)),
        ):
            with self.subTest(label=label):
                tampered = deepcopy(row)
                corrupt(tampered)
                with self.assertRaisesRegex(ValueError, label):
                    audit_receipt_row(tampered, *args)

    def test_passive_verified_cue_replays_only_the_seed_receipts(self):
        row, args = self.run_script("VerifiedWitness", (
            "</think>\n\n" + r"The answer is \boxed{10112369}.", None,
        ))
        counted = audit_receipt_row(row, *args)
        self.assertEqual(counted["point_events_verified"], 2)
        self.assertEqual(counted["feedback_obligations"], 0)

    def test_a_known_invalid_final_stays_withheld_without_feedback_quota(self):
        row, args = self.run_script("ProgressiveWitness", (
            "</think>\n\n" + r"The answer is \boxed{10112357}.", None,
        ), feedback_budget=0)
        counted = audit_receipt_row(row, *args)
        self.assertTrue(counted["terminal_withheld"])
        self.assertEqual(counted["feedback_applied"], 0)
        self.assertEqual(counted["rejected_drafts_reconstructed"], 0)


if __name__ == "__main__":
    unittest.main()
