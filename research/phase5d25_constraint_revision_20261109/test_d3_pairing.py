"""CPU selection and exact witness-routing tests for D3."""

import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from d3_quality_worker import in_context_cue, route_audit
from select_d3_events import (SAMPLING, audit_requests, choose, complete_bank, digest, live_rng,
                              prompt_for, rebuild_selected, replay_steps, scope_binding, verify_record)


class Tokenizer:
    tags = {"<think>": 100001, "</think>": 100002, "<|im_end|>": 100003, "<|endoftext|>": 100004}
    reverse = {value: key for key, value in tags.items()}

    def encode(self, text, add_special_tokens=False):
        return [self.tags[text]] if text in self.tags else list(map(ord, text))

    def decode(self, values, skip_special_tokens=False):
        return "".join(self.reverse[value] if value in self.reverse else chr(value) for value in values)

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
        return self.encode("<|im_start|>user\n" + messages[0]["content"] + "<|im_end|>\n<|im_start|>assistant\n") + (
            [] if enable_thinking else [self.tags["<think>"], self.tags["</think>"]])


TOK = Tokenizer()


def raw_fixture(text="Identity: $x=1$\n\n"):
    case = {"case_id": "D3_E01", "question": "Let $x$ be a nonzero real number. Determine the relation.",
            "problem_hash": "fixture"}
    prompt = prompt_for(TOK, case["question"])
    observed = TOK.encode("<think>") + TOK.encode(text)
    generated = observed + TOK.encode("</think>") + TOK.encode("answer") + TOK.encode("<|im_end|>")
    step = {"step": 0, "start": 1, "end": len(observed), "text": text, "event_types": ["relation"], "boundary": "paragraph"}
    event = {"step": 0, "start": 1, "end": len(observed), "types": ["relation"], "thinking_open": True,
             "rng_state_base64": base64.b64encode(b"fixture RNG state").decode()}
    ledger = [{"stage": "native_prefill", "input_tokens": len(prompt), "past_tokens": 0, "position_start": 0}]
    ledger.extend({"stage": "native_decode", "input_tokens": 1, "past_tokens": i, "position_start": i}
                  for i in range(len(prompt), len(prompt) + len(generated) - 1))
    return case, {"status": "COMPLETE", "case_id": case["case_id"], "question_hash": case["problem_hash"],
                  "seed": 20261109, "sampling": SAMPLING, "prompt_ids": prompt, "generated_ids": generated,
                  "prompt_sha256": digest(prompt), "generated_sha256": digest(generated), "new_tokens": len(generated),
                  "stop_reason": "EOS", "EOS": True, "hit_context_cap": False, "context_capacity": 512,
                  "steps": [step], "events": [event], "ledger": ledger}


def candidate(case, seed=20261109, step=0, chars=(0, 3), event_id="e0"):
    return {"case_id": case, "seed": seed, "step": step, "event_id": event_id,
            "event": {"source": {"token_span": [10, 15], "char_span": list(chars)}}}


class D3PairingTests(unittest.TestCase):
    def test_fixed_ties_and_four_distinct_problems(self):
        preferred = candidate("A", chars=(0, 2), event_id="e1")
        rows = [candidate("E"), candidate("D"), candidate("A", 20261110), candidate("A", step=1),
                candidate("C"), candidate("A", chars=(0, 2), event_id="e2"), candidate("B"), preferred]
        selected, exclusions = choose(rows)
        self.assertEqual([row["case_id"] for row in selected], ["A", "B", "C", "D"])
        self.assertEqual(selected[0], preferred)
        self.assertEqual(exclusions, {"same_problem_already_selected": 3, "four_distinct_problem_limit": 1})
        self.assertEqual(choose([])[0], [])

    def test_incomplete_bank_refuses_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "BANK_RETRIEVAL.json").write_text(json.dumps({"status": "PARTIAL", "mode": "bank", "launcher": {
                "status": "RUNNING", "workers": [{"worker": 0, "exit_code": None}, {"worker": 1, "exit_code": None}]
            }}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "both formal workers"):
                list(complete_bank(root, TOK))

    def test_reconstruct_live_bound_event_from_exact_record(self):
        case, row = raw_fixture()
        step, scope, before, (event,) = next(replay_steps(row, case["question"], TOK))
        binding, _ = scope_binding(event, scope, before)
        selected = {"seed": row["seed"], "step": 0, "event_id": event.event_id, "event": event.as_dict(),
                    "generated_count": step["end"], "observed_prefix_sha256": scope.observed_prefix_sha256,
                    "scope_binding_sha256": digest(binding), "rng_state_sha256": live_rng(row, step, TOK)}
        rebuilt, _, _, resolved = rebuild_selected(row, case, selected, TOK)
        self.assertEqual(rebuilt, event)
        self.assertEqual(binding, resolved)
        for field in ("event_id", "observed_prefix_sha256", "scope_binding_sha256", "rng_state_sha256"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                rebuild_selected(row, case, {**selected, field: "changed"}, TOK)
        corrupt = deepcopy(row)
        corrupt["steps"][0]["text"] = "Identity: $x=2$\n\n"
        with self.assertRaisesRegex(ValueError, "differs from its recorded tokens"):
            rebuild_selected(corrupt, case, selected, TOK)

    def test_scope_packet_changes_only_the_side_audit_context(self):
        case, row = raw_fixture()
        _, scope, before, (event,) = next(replay_steps(row, case["question"], TOK))
        binding, _ = scope_binding(event, scope, before)
        requests = audit_requests(event, binding)
        unrestricted, restricted = requests["UnscopedIndependent"], requests["ScopedIndependent"]
        self.assertEqual(unrestricted.prefix_sha256, restricted.prefix_sha256)
        self.assertEqual(unrestricted.event_id, restricted.event_id)
        self.assertEqual(unrestricted.target, restricted.target)
        self.assertEqual(unrestricted.variables, restricted.variables)
        self.assertEqual(unrestricted.premises, ())
        self.assertNotEqual(unrestricted.render(), restricted.render())
        self.assertIn("x = 1", in_context_cue(event))
        self.assertNotIn("nonzero", in_context_cue(event))
        proposal = {"text": '{"assignment":{"x":0}}'}
        scoped, scoped_permit = route_audit(event, scope, before, proposal, unscoped=False)
        unscoped, unscoped_permit = route_audit(event, scope, before, proposal, unscoped=True)
        self.assertEqual(scoped["audit_witness_disposition"], "REJECTED_AUDIT_WITNESS")
        self.assertEqual(unscoped["audit_witness_disposition"], "VALID_AUDIT_WITNESS_DIAGNOSTIC")
        self.assertFalse(scoped["native_revision_authorized"] or unscoped["native_revision_authorized"])
        self.assertIsNone(scoped_permit)
        self.assertIsNone(unscoped_permit)

    def test_unclassified_equation_or_closed_step_has_no_eligibility(self):
        case, row = raw_fixture("$x=1$\n\n")
        _, scope, before, (event,) = next(replay_steps(row, case["question"], TOK))
        self.assertEqual(event.kind, "EQUATION")
        self.assertIsNone(scope_binding(event, scope, before)[0])
        row["events"][0]["thinking_open"] = False
        self.assertIsNone(live_rng(row, row["steps"][0], TOK))

    def test_native_record_rejects_early_eos_and_wrong_schedule(self):
        case, row = raw_fixture()
        verify_record(row, case, row["seed"], TOK)
        stale = deepcopy(row)
        stale["ledger"][1]["position_start"] += 1
        with self.assertRaisesRegex(ValueError, "forward ledger"):
            verify_record(stale, case, stale["seed"], TOK)
        stale = deepcopy(row)
        stale["generated_ids"][2] = TOK.tags["<|im_end|>"]
        stale["generated_sha256"] = digest(stale["generated_ids"])
        with self.assertRaisesRegex(ValueError, "EOS record"):
            verify_record(stale, case, stale["seed"], TOK)


if __name__ == "__main__":
    unittest.main()
