"""CPU-only controller fixtures. Fake decode cost tests the budget bracket."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

import repair_actions as actions
from natural_evidence import relations
from natural_ledger import ROLE_VERDICT, make_role_certificate
from native_snapshot import ExecutionIdentity, capture_snapshot


class Tokenizer:
    def __init__(self):
        self.controls = {"<think>": 1, "</think>": 2, "<|im_start|>": 3, "<|im_end|>": 4, "<|endoftext|>": 5}
        self.inverse = {value: text for text, value in self.controls.items()}

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        out = []
        while text:
            control = next((tag for tag in self.controls if text.startswith(tag)), None)
            if control:
                out.append(self.controls[control])
                text = text[len(control):]
            else:
                out.append(ord(text[0]) + 256)
                text = text[1:]
        return out

    def decode(self, ids, *, skip_special_tokens):
        return "".join(("" if skip_special_tokens else self.inverse[token]) if token in self.inverse else chr(token - 256) for token in ids)


class Cache:
    layers = ()

    def __init__(self, ids):
        self.ids = tuple(ids)

    def get_seq_length(self):
        return len(self.ids)


class Engine:
    def __init__(self):
        self.tokenizer = Tokenizer()
        self.torch = torch
        self.device = torch.device("cpu")
        self.capacity = 30000
        self.eos = {5}
        self.open_ids = [1]
        self.close_ids = [2]
        self.stage = "fixture"
        self.ledger = []

    def sync(self):
        return None

    def rng(self, seed=None, state=None):
        generator = torch.Generator(device="cpu")
        return generator.set_state(state) if state is not None else generator.manual_seed(seed)

    def prefill(self, ids):
        return self.forward(ids)

    def forward(self, ids, cache=None):
        old = () if cache is None else cache.ids
        self.ledger.append({"stage": self.stage, "input_tokens": len(ids), "past_tokens": len(old), "position_start": len(old)})
        result = Cache(old + tuple(ids))
        return result, torch.tensor([float(len(result.ids)), 1.0])


class Clock:
    value = 0.0

    def monotonic(self):
        return self.value


class Helpers:
    def __init__(self, clock):
        self.clock = clock
        self.finished = []
        self.injected = []
        self.deliver_boxed = True

    @staticmethod
    def cost(rows):
        return {"forward_calls": len(rows), "forward_input_tokens": sum(r["input_tokens"] for r in rows),
                "attention_pairs": sum(r["input_tokens"] * r["past_tokens"] + r["input_tokens"] * (r["input_tokens"] + 1) // 2 for r in rows)}

    def append_checked_text(self, engine, state, text, stage):
        if state.stop_reason != "RUNNING" or not state.thinking_open:
            raise ValueError("Closed fixture state")
        engine.stage = stage
        ids = engine.tokenizer.encode(text, add_special_tokens=False)
        if state.cache_position + len(ids) >= engine.capacity:
            return {"status": "INSUFFICIENT_CONTEXT", "tokens": 0}
        for token in ids:
            state.cache, state.next_logits = engine.forward([token], state.cache)
            state.generated_ids.append(token)
            state.cache_position += 1
        self.injected.append((stage, text))
        return {"status": "APPENDED", "tokens": len(ids), "text": text}

    def finish(self, engine, state, folder, arm):
        self.finished.append(arm)
        self.clock.value += {"GenericRewind": 4, "RebaseNoCarry": 3, "RebaseCarry": 5,
                             "FullRestart": 6, "SameEvidenceCompactBridge": 2}.get(arm, 2)
        answer = 3 if state.rng.initial_seed() % 2 else 4
        text = "\nFinal answer: \\boxed{" + str(answer) + "}" if self.deliver_boxed else "\nI have no completed object."
        suffix = [*engine.close_ids, *engine.tokenizer.encode(text, add_special_tokens=False), 5]
        for index, token in enumerate(suffix):
            state.generated_ids.append(token)
            if index < len(suffix) - 1:
                state.cache, state.next_logits = engine.forward([token], state.cache)
                state.cache_position += 1
        state.thinking_open = False
        state.stop_reason = "EOS"
        state.next_logits = None
        return {"continuation_tokens": len(suffix), "continuation_seconds": self.clock.value}

    @staticmethod
    def state_result(engine, state):
        position = state.generated_ids.index(engine.close_ids[0])
        return {"status": "COMPLETE", "prompt_ids": list(state.prompt_ids), "generated_ids": list(state.generated_ids),
                "EOS": state.stop_reason == "EOS", "think_closed": not state.thinking_open,
                "final_response": engine.tokenizer.decode(state.generated_ids[position + 1:], skip_special_tokens=True),
                "stop_reason": state.stop_reason, "hit_context_cap": False,
                "new_tokens": len(state.generated_ids), "context_capacity": engine.capacity}


def scenario(text_override=None):
    engine = Engine()
    identity = ExecutionIdentity("model", "tokenizer", "engine", "fixture", "float32", "cpu", "CPU only", {"temperature": .6})
    prompt = engine.tokenizer.encode("<|im_start|>user\nCompute the requested target.<|im_end|>\n<|im_start|>assistant\n", add_special_tokens=False)
    opening = engine.tokenizer.encode("<think>\n\n", add_special_tokens=False)
    text = text_override or "$1+2=3$ and $2+3=6$.\n\n"
    tokens = opening + engine.tokenizer.encode(text, add_special_tokens=False)
    start, end = len(opening), len(tokens)
    step = {"step": 0, "start": start, "end": end, "text": text, "boundary": "paragraph"}
    engine.stage = "native_prefill"
    cache, logits = engine.prefill(prompt)
    engine.stage = "native_decode"
    for token in tokens:
        cache, logits = engine.forward([token], cache)
    snapshot = capture_snapshot(engine, identity=identity, prompt_ids=prompt, generated_ids=tokens, cache=cache,
                                next_logits=logits, rng=engine.rng(seed=77), thinking_open=True, checkpoint_id="fixture")
    candidate = next(item for item in relations(step) if item["surface"] == "2+3=6")
    candidate["observed_prefix_sha256"] = snapshot.prefix_sha256
    selected = {"case_id": "fixture", "seed": 77, "generated_count": end, "step": 0,
                "observed_prefix_sha256": snapshot.prefix_sha256, "relation": candidate}
    baseline = {"case_id": "fixture", "seed": 77, "prompt_ids": prompt, "generated_ids": tokens + [9999],
                "steps": [step], "ledger": list(engine.ledger)}
    receipt = make_role_certificate(candidate, snapshot.prefix_sha256, [
        {"id": "/root", "verdict": ROLE_VERDICT}, {"id": "/root/independent", "verdict": ROLE_VERDICT}])
    return engine, snapshot, identity, selected, baseline, receipt


class RepairActionTests(unittest.TestCase):
    def test_no_role_receipt_records_ineligible_without_model_forward(self):
        engine, snapshot, identity, selected, baseline, _ = scenario()
        count = len(engine.ledger)
        with tempfile.TemporaryDirectory() as directory:
            result = actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, None, directory)
            self.assertEqual(result["status"], "NOT_ELIGIBLE")
            self.assertEqual(result["arms"], [])
            self.assertEqual(len(engine.ledger), count)
            self.assertTrue((Path(directory) / "repair/REPAIR_STATUS.json").is_file())

    def test_complete_arms_same_evidence_and_real_measured_bracket_schema(self):
        engine, snapshot, identity, selected, baseline, receipt = scenario()
        clock = Clock()
        helper = Helpers(clock)
        original_ids = snapshot._cache.ids
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "time", clock):
            result = actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, receipt, directory, helpers=helper)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(len(result["arms"]), 6)
            self.assertEqual(result["semantic_lost_support"], [])
            self.assertTrue(result["invalidated_proof_token_spans"])
            self.assertTrue(result["common_evidence"]["carried_claim_ids"])
            self.assertEqual(result["resampling"]["below"]["replicas"], 3)
            self.assertEqual(result["resampling"]["above"]["replicas"], 4)
            self.assertTrue(result["resampling"]["bracketed"])
            self.assertEqual(result["resampling"]["target_postcheckpoint_seconds"], 6)
            self.assertTrue(result["cut_equality"])
            self.assertTrue(result["GenericRewind_RebaseCarry_prefix_equal"])
            self.assertFalse(result["NoCarry_Carry_prefix_equal"])
            folder = Path(directory)
            records = {}
            for row in result["arms"]:
                path = folder / row["path"]
                record = json.loads(path.read_text(encoding="utf-8"))
                records[row["arm"]] = record
                for key in ("status", "case_id", "seed", "arm", "EOS", "think_closed", "final_response", "generated_ids", "prompt_ids", "stop_reason"):
                    self.assertIn(key, record)
                self.assertEqual(record["status"], "COMPLETE")
                self.assertTrue(record["EOS"])
            self.assertFalse(records["RebaseNoCarry"]["carry_serialized"])
            self.assertTrue(records["RebaseCarry"]["carry_serialized"])
            self.assertEqual(records["RebaseNoCarry"]["retained_observed_generated_tokens"], records["RebaseCarry"]["retained_observed_generated_tokens"])
            bad_hashes = {records[name]["common_evidence"]["bad_text_sha256"] for name in actions.ARMS}
            self.assertEqual(len(bad_hashes), 1)
            self.assertTrue(all(records[name]["common_evidence"]["carry_packet_sha256"] == result["common_evidence"]["carry_packet_sha256"] for name in actions.ARMS))
            self.assertEqual(records["FullRestart"]["retained_observed_generated_tokens"], 1)
            self.assertEqual(records["SameEvidenceCompactBridge"]["discarded_observed_generated_tokens"], 0)
            self.assertTrue(records["GenericRewind"]["common_observed_prefix"]["available"])
            self.assertIsNone(records["GenericRewind"]["common_observed_prefix"]["wall_seconds"])
            self.assertEqual(records["Resampling"]["chosen_replica_index"], 1)
            self.assertEqual(records["Resampling"]["replica_count"], 4)
            self.assertEqual(records["Resampling"]["completed_EOS_replicas"], 4)
            self.assertEqual(records["Resampling"]["postcheckpoint_paid_work"], helper.cost(records["Resampling"]["postcheckpoint_ledger"]))
            all_replica_work = [json.loads(path.read_text(encoding="utf-8"))["postcheckpoint_paid_work"]
                                for path in (folder / "repair").glob("resampling_replica_*.json")]
            self.assertEqual(records["Resampling"]["postcheckpoint_paid_work"]["forward_calls"], sum(item["forward_calls"] for item in all_replica_work))
            self.assertEqual(len(list((folder / "repair").glob("resampling_replica_*.json"))), 4)
            self.assertEqual(snapshot._cache.ids, original_ids)

    def test_ready_execution_failure_propagates_and_preserves_original(self):
        engine, snapshot, identity, selected, baseline, receipt = scenario()
        clock = Clock()
        helper = Helpers(clock)
        helper.append_checked_text = lambda *args, **kwargs: {"status": "INSUFFICIENT_CONTEXT", "tokens": 0}
        original = snapshot._cache.ids
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "time", clock):
            with self.assertRaisesRegex(RuntimeError, "READY repair"):
                actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, receipt, directory, helpers=helper)
            self.assertFalse((Path(directory) / "repair/REPAIR_STATUS.json").exists())
        self.assertEqual(snapshot._cache.ids, original)

    def test_source_text_tamper_raises_before_forward(self):
        engine, snapshot, identity, selected, baseline, receipt = scenario()
        baseline["steps"][0]["text"] = "A modified relation.\n\n"
        first = len(engine.ledger)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "source tokens differ"):
                actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, receipt, directory)
            self.assertEqual(len(engine.ledger), first)

    def test_observed_blank_boundary_inside_open_math_is_reported(self):
        engine, snapshot, identity, selected, baseline, receipt = scenario(r"\[" + "$1+2=3$ and $2+3=6$.\n\n")
        before = len(engine.ledger)
        with tempfile.TemporaryDirectory() as directory:
            result = actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, receipt, directory)
            self.assertEqual(result["status"], "NOT_ELIGIBLE")
            self.assertEqual(result["source_boundaries"]["rejected_paragraph_count"], 1)
            self.assertEqual(len(engine.ledger), before)

    def test_plurality_abstention_has_complete_scoring_schema(self):
        engine, snapshot, identity, selected, baseline, receipt = scenario()
        clock = Clock()
        helper = Helpers(clock)
        helper.deliver_boxed = False
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "time", clock):
            result = actions.run_repair_experiment(engine, snapshot, identity, selected, baseline, receipt, directory, helpers=helper)
            chosen = json.loads((Path(directory) / "repair/Resampling.json").read_text(encoding="utf-8"))
            self.assertEqual(chosen["stop_reason"], "PLURALITY_ABSTAINED")
            self.assertEqual(chosen["new_tokens"], 0)
            self.assertFalse(chosen["hit_context_cap"])
            self.assertEqual(chosen["context_capacity"], engine.capacity)
            self.assertEqual(chosen["completed_EOS_replicas"], 4)
            self.assertEqual(result["status"], "COMPLETE")

    def test_bracket_requires_completed_replicas_on_both_sides(self):
        self.assertEqual(actions._bracket([{"elapsed_seconds": 11, "EOS": True}], 10)["status"], "NO_COMPLETED_BELOW_TARGET")
        result = actions._bracket([{"elapsed_seconds": 1, "EOS": True} for _ in range(8)], 10)
        self.assertFalse(result["bracketed"])
        self.assertEqual(result["status"], "REPLICA_GUARD_BEFORE_UPPER")
        self.assertFalse(actions._bracket([{"elapsed_seconds": 11, "EOS": False}], 10)["bracketed"])

    def test_plurality_preserves_earliest_tie_and_no_gold(self):
        replicas = [{"final_response": r"\boxed{7}", "EOS": True}, {"final_response": r"\boxed{9}", "EOS": True}]
        self.assertEqual(actions.plurality(replicas), 0)
        replicas.append({"final_response": r"\boxed{9}", "EOS": True})
        self.assertEqual(actions.plurality(replicas), 1)
        self.assertIsNone(actions.plurality([{"final_response": "No delivered object", "EOS": True}]))
        self.assertIsNone(actions.plurality([{"final_response": r"\boxed{7}", "EOS": False}]))


if __name__ == "__main__":
    unittest.main()
