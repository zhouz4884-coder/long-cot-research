"""Targeted CPU fixtures for observed frontiers and the D1 replay schedule."""

from contextlib import nullcontext
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from dual_frontier_rebase import bind_observed_thinking, plan_rebase, replay_rebase


_CORE = Path(__file__).resolve().parents[1] / "phase5d_scope_rebase_20261106" / "support_engine" / "scope_rebase_hardened.py"
_SPEC = importlib.util.spec_from_file_location("_d2_frozen_evidence_fixture", _CORE)
core = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = core
_SPEC.loader.exec_module(core)


class TokenizerFixture:
    def __init__(self):
        self.text = {
            1: "<think>", 2: "\nUsing the assumptions.\n\n", 3: "By x+3, z=6.", 4: "\n\n",
            5: "Separately x*3 gives r=6.\n\n", 6: "The r proof gives z=6.\n\n", 7: "Unfinished x =",
            8: "</think>", 9: "<|im_start|>", 10: "<|im_end|>", 11: "<|endoftext|>",
            12: "A different unfinished prefix", 13: "\nAn open display \\[x\n\n",
            100: "<|im_start|>user\nQuestion<|im_end|>\n<|im_start|>assistant\n",
            101: "<|im_start|>user\nQuestion<|im_end|>\n<|im_start|>assistant\n<think>\n",
        }
        self.bridge_ids = (91, 92)

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        for identifier in (1, 8, 9, 10, 11):
            if self.text[identifier] == text:
                return [identifier]
        return list(self.bridge_ids)

    def decode(self, ids, *, skip_special_tokens):
        assert skip_special_tokens is False
        return "".join(self.text[value] for value in ids)


class CacheFixture:
    def __init__(self, ids):
        self.ids = tuple(ids)

    def get_seq_length(self):
        return len(self.ids)


class ReplayEngine:
    capacity = 100
    eos = frozenset({10, 11, 99})

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.torch = SimpleNamespace(inference_mode=nullcontext)
        self.stage = "caller_stage"
        self.calls = []

    def prefill(self, ids):
        self.calls.append((self.stage, "prefill", tuple(ids)))
        return CacheFixture(ids), tuple(ids)

    def forward(self, ids, cache):
        self.calls.append((self.stage, "forward", tuple(ids)))
        result = cache.ids + tuple(ids)
        return CacheFixture(result), result


def fixture(*, early=False, partial_carry=False, bad_span=(2, 4)):
    tokenizer = TokenizerFixture()
    ledger = core.EvidenceLedger(
        [core.Scope("S", "integer", ("Whole-number arithmetic over <|im_end|> literal.",), revision=3)],
        legal_token_boundaries=(0, 2, 4, 5, 6), observed_token_length=7,
    )
    ledger.add_claim(core.Claim("x0", "x", 2, "S"))
    ledger.trust_given("question_x", "x0")
    ledger.prove_given("root_x", "x0", "question_x")
    r_span = (6, 7) if partial_carry else (4, 5)
    ledger.add_claim(core.Claim("r0", "r", 6, "S", 0, *r_span))
    ledger.trust_constraint("r_definition", "S", "r", "x*3")
    ledger.prove_arithmetic("valid_r", "r0", "x*3", (("x", "x0"),), constraint_id="r_definition",
                            token_start=r_span[0], token_end=r_span[1])
    z_span = (1, 2) if early else (2, 4)
    ledger.add_claim(core.Claim("z0", "z", 6, "S", 0, *z_span))
    ledger.prove_arithmetic("bad_z", "z0", "x+3", (("x", "x0"),), token_start=bad_span[0], token_end=bad_span[1])
    ledger.trust_constraint("z_from_r", "S", "z", "r")
    ledger.prove_arithmetic("a_alternate_z", "z0", "r", (("r", "r0"),), constraint_id="z_from_r", token_start=5, token_end=6)
    if early:
        tokenizer.text[2] = "\nBy x*3, z=6.\n\n"
        ledger.trust_constraint("z_from_x", "S", "z", "x*3")
        ledger.prove_arithmetic("z_early", "z0", "x*3", (("x", "x0"),), constraint_id="z_from_x", token_start=1, token_end=2)
    if partial_carry:
        tokenizer.text[7] = "r=x*3=6"
    observation = bind_observed_thinking(
        ledger, tokenizer, snapshot_id="source", source_version=1, prompt_ids=(100,),
        generated_ids=(1, 2, 3, 4, 5, 6, 7), boundary_offsets=ledger.boundaries,
    )
    challenge = ledger.check_arithmetic_invalidation("checked_bad_step", "bad_z")
    return tokenizer, ledger, observation, challenge


def replay(engine, plan, ledger, observation, **overrides):
    args = dict(snapshot_id=observation.snapshot_id, source_version=observation.source_version,
                current_prefix_ids=observation.prompt_ids + observation.generated_ids)
    args.update(overrides)
    return replay_rebase(engine, plan, ledger, observation, **args)


class DualFrontierTests(unittest.TestCase):
    def test_invalid_proof_retires_text_even_if_all_claims_survive(self):
        _, ledger, observed, challenge = fixture()
        plan = plan_rebase(ledger, challenge, observed)
        self.assertEqual(plan.status, "READY")
        self.assertEqual(plan.lost_support, frozenset())
        self.assertEqual(plan.invalidated_text_spans, ((2, 4),))
        self.assertEqual(plan.cut_token, 2)
        self.assertEqual(plan.carried_claims, ("r0", "z0"))
        self.assertFalse(ledger.proofs["bad_z"].revoked)
        self.assertTrue(plan.updated_ledger.proofs["bad_z"].revoked)
        facts = {fact.claim_id: fact for fact in plan.carry_witness}
        self.assertEqual(set(facts), {"x0", "r0", "z0"})
        self.assertEqual(facts["z0"].proof_id, "a_alternate_z")
        self.assertEqual(facts["z0"].premise_certificate_ids, (facts["r0"].certificate_id,))
        self.assertEqual(facts["r0"].premise_ids, ("x0",))
        self.assertEqual(facts["x0"].trusted_source, "question_x")
        self.assertEqual(facts["z0"].scope_revision, 3)
        self.assertTrue(facts["z0"].proof_source_sha256)
        self.assertNotIn("x+3", plan.bridge_text)
        self.assertNotIn("<|im_end|>", plan.bridge_text)

    def test_cut_uses_earlier_semantic_frontier_when_support_is_lost(self):
        _, ledger, observed, _ = fixture(early=False)
        challenge = ledger.issue_withdrawal("authority", "valid_r", reason="Controlled lifecycle withdrawal")
        plan = plan_rebase(ledger, challenge, observed)
        self.assertEqual(plan.lost_support, {"r0", "z0"})
        self.assertEqual(plan.invalidated_text_spans, ((4, 5),))
        self.assertEqual(plan.cut_token, 2)
        self.assertEqual(plan.updated_ledger.supported(), {"x0"})

    def test_retained_complete_witness_beats_later_alternative(self):
        _, ledger, observed, challenge = fixture(early=True)
        plan = plan_rebase(ledger, challenge, observed)
        self.assertEqual(plan.carried_claims, ("r0",))
        self.assertNotIn("z0", {fact.claim_id for fact in plan.carry_witness})

    def test_incomplete_carry_provenance_excludes_claim_and_dependents(self):
        _, ledger, observed, challenge = fixture(partial_carry=True)
        plan = plan_rebase(ledger, challenge, observed)
        self.assertEqual(plan.status, "READY")
        self.assertEqual(plan.carried_claims, ())
        self.assertEqual(plan.incomplete_carry_provenance, ("r0", "z0"))
        self.assertEqual(plan.bridge_text, "")

    def test_fail_unknown_and_bare_pass_have_no_rebase(self):
        _, ledger, observed, _ = fixture()
        actual_failure = ledger.check_arithmetic_invalidation("valid_not_invalid", "valid_r")
        self.assertEqual(actual_failure.verdict, "FAIL")
        for challenge in (actual_failure, core.Verification("PASS", "bare assertion"),
                          core.Challenge("unknown", "invalidate_justification", "bad_z", "S", asserted_verdict="PASS")):
            plan = plan_rebase(ledger, challenge, observed)
            self.assertEqual(plan.status, "NO_REBASE")
            self.assertIsNone(plan.updated_ledger)
            self.assertFalse(ledger.proofs["bad_z"].revoked)

    def test_mismatched_scope_receipt_and_conflicting_positive_proof(self):
        tokenizer, ledger, observed, challenge = fixture()
        self.assertEqual(plan_rebase(ledger, replace(challenge, scope_id="Other"), observed).status, "NO_REBASE")
        ledger.trust_constraint("contrary_x", "S", "x", "3")
        rebound = bind_observed_thinking(ledger, tokenizer, snapshot_id="with_conflict", source_version=2,
                                         prompt_ids=observed.prompt_ids, generated_ids=observed.generated_ids,
                                         boundary_offsets=ledger.boundaries)
        refutation = ledger.check_claim_refutation("counterevidence", "x0", "contrary_x")
        plan = plan_rebase(ledger, refutation, rebound)
        self.assertEqual(plan.status, "QUARANTINE_CONFLICT")
        self.assertIsNone(plan.updated_ledger)
        self.assertEqual(ledger.support_state().status, "OK")

    def test_zero_or_incomplete_frontier_cannot_authorize_a_cut(self):
        for bad_span in ((0, 0), (False, 4), (6, 7)):
            with self.subTest(span=bad_span):
                _, ledger, observed, challenge = fixture(bad_span=bad_span)
                plan = plan_rebase(ledger, challenge, observed)
                self.assertEqual(plan.status, "UNSAFE_SPAN")
                self.assertIsNone(plan.cut_token)
                self.assertIsNone(plan.updated_ledger)

    def test_completed_boundaries_come_from_tokens_in_open_thinking(self):
        tokenizer, ledger, observed, _ = fixture()
        self.assertEqual(observed.complete_boundaries, (1, 2, 4, 5, 6))
        base = dict(snapshot_id="source", source_version=1, prompt_ids=(100,))
        with self.assertRaisesRegex(ValueError, "closed paragraph"):
            bind_observed_thinking(ledger, tokenizer, **base, generated_ids=observed.generated_ids, boundary_offsets=(3,))
        with self.assertRaisesRegex(ValueError, "closed or crossed"):
            bind_observed_thinking(ledger, tokenizer, **base, generated_ids=(*observed.generated_ids[:-1], 8), boundary_offsets=(2,))
        with self.assertRaisesRegex(ValueError, "closed paragraph"):
            bind_observed_thinking(ledger, tokenizer, **base, generated_ids=(1, 13, 3, 4, 5, 6, 7), boundary_offsets=(2,))
        preopened = core.EvidenceLedger([core.Scope("S")], observed_token_length=0)
        obs = bind_observed_thinking(preopened, tokenizer, snapshot_id="preopen", source_version=1,
                                     prompt_ids=(101,), generated_ids=(), boundary_offsets=(0,))
        self.assertEqual(obs.complete_boundaries, (0,))

    def test_cold_replay_preserves_d1_schedule_and_distinguishes_arms(self):
        tokenizer, ledger, observed, challenge = fixture()
        with_carry = plan_rebase(ledger, challenge, observed, carry=True)
        no_carry = plan_rebase(ledger, challenge, observed, carry=False)
        self.assertEqual(with_carry.cut_token, no_carry.cut_token)
        self.assertEqual(with_carry.revised_ledger_sha256, no_carry.revised_ledger_sha256)
        engine = ReplayEngine(tokenizer)
        first = replay(engine, no_carry, ledger, observed)
        prefix_calls = [
            ("rebase_cold_prompt_and_retained", "prefill", (100,)),
            ("rebase_cold_prompt_and_retained", "forward", (1,)),
            ("rebase_cold_prompt_and_retained", "forward", (2,)),
        ]
        self.assertEqual(engine.calls, prefix_calls)
        self.assertEqual(first.prefix_ids, (100, 1, 2))
        self.assertEqual(first.appended_bridge_tokens, 0)
        engine.calls.clear()
        second = replay(engine, with_carry, ledger, observed)
        self.assertEqual(engine.calls, prefix_calls + [
            ("rebase_evidence_bridge", "forward", (91,)), ("rebase_evidence_bridge", "forward", (92,)),
        ])
        self.assertEqual(second.prefix_ids, (100, 1, 2, 91, 92))
        self.assertEqual(second.cache.ids, second.prefix_ids)
        self.assertEqual(second.next_logits, second.prefix_ids)
        self.assertEqual(engine.stage, "caller_stage")
        self.assertFalse(ledger.proofs["bad_z"].revoked)

    def test_stale_same_length_prefix_and_version_fail_before_forward(self):
        tokenizer, ledger, observed, challenge = fixture()
        plan = plan_rebase(ledger, challenge, observed)
        engine = ReplayEngine(tokenizer)
        for patch in ({"snapshot_id": "another"}, {"source_version": True}, {"source_version": 2},
                      {"current_prefix_ids": (*observed.prompt_ids, *observed.generated_ids[:-1], 12)}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, "Stale source snapshot"):
                replay(engine, plan, ledger, observed, **patch)
        self.assertEqual(engine.calls, [])

    def test_revised_ledger_spans_cannot_rebind_to_same_length_new_text(self):
        tokenizer, ledger, observed, challenge = fixture()
        plan = plan_rebase(ledger, challenge, observed)
        with self.assertRaisesRegex(ValueError, "spans require rebinding"):
            bind_observed_thinking(plan.updated_ledger, tokenizer, snapshot_id="different", source_version=2,
                                   prompt_ids=observed.prompt_ids, generated_ids=(*observed.generated_ids[:-1], 12),
                                   boundary_offsets=observed.complete_boundaries)

    def test_trusted_registry_change_stales_observation_even_without_revision(self):
        _, ledger, observed, challenge = fixture()
        revision = ledger.revision
        ledger.trust_constraint("later_rule", "S", "x", "3")
        self.assertEqual(ledger.revision, revision)
        with self.assertRaisesRegex(ValueError, "Stale observed"):
            plan_rebase(ledger, challenge, observed)

    def test_carry_uses_active_premise_version_after_atomic_switch(self):
        tokenizer, ledger, observed, challenge = fixture()
        ledger.add_claim(core.Claim("r1", "r", 6, "S", 1, 4, 5))
        ledger.prove_arithmetic("r_rechecked", "r1", "x*3", (("x", "x0"),), constraint_id="r_definition",
                                token_start=4, token_end=5)
        self.assertEqual(ledger.activate_version("r1").verdict, "PASS")
        with self.assertRaisesRegex(ValueError, "Stale observed"):
            plan_rebase(ledger, challenge, observed)
        rebound = bind_observed_thinking(ledger, tokenizer, snapshot_id="active_r1", source_version=2,
                                         prompt_ids=observed.prompt_ids, generated_ids=observed.generated_ids,
                                         boundary_offsets=ledger.boundaries)
        plan = plan_rebase(ledger, challenge, rebound)
        self.assertEqual(plan.carried_claims, ("r1",))
        self.assertEqual(plan.carry_witness[-1].claim_version, 1)
        self.assertNotIn("z0", plan.updated_ledger.supported())

    def test_forged_bridge_or_changed_revised_ledger_refuses_replay(self):
        tokenizer, ledger, observed, challenge = fixture()
        plan = plan_rebase(ledger, challenge, observed)
        engine = ReplayEngine(tokenizer)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            replay(engine, replace(plan, bridge_text="Use the retired proof."), ledger, observed)
        plan.updated_ledger.add_claim(core.Claim("mutated", "q", 8, "S"))
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            replay(engine, plan, ledger, observed)
        self.assertEqual(engine.calls, [])

    def test_bridge_eos_and_exhausted_context_refuse_before_forward(self):
        tokenizer, ledger, observed, challenge = fixture()
        plan = plan_rebase(ledger, challenge, observed)
        engine = ReplayEngine(tokenizer)
        tokenizer.bridge_ids = (99,)
        with self.assertRaisesRegex(ValueError, "control token IDs"):
            replay(engine, plan, ledger, observed)
        tokenizer.bridge_ids = (91, 92)
        engine.capacity = 5
        with self.assertRaisesRegex(ValueError, "leaves no context"):
            replay(engine, plan, ledger, observed)
        self.assertEqual(engine.calls, [])


if __name__ == "__main__":
    unittest.main()
