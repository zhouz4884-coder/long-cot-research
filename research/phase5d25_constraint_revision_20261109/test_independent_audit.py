"""CPU regression for the independent audit context and action boundary."""

from pathlib import Path
import sys
import unittest

from independent_audit import AuditRequest, RevisionPermit, digest, handle_event, run_side_audit
from native_snapshot import advance_native, restore_snapshot
import test_native_snapshot_reflection as fixture


class AuditIsolationTest(unittest.TestCase):
    def setUp(self):
        helper = fixture.NativeForkTest()
        helper.setUp()
        self.engine = helper.engine()
        self.identity = helper.identity
        self.snapshot = helper.checkpoint(self.engine)
        self.request = AuditRequest(self.snapshot.prefix_sha256, "event", "COUNTEREXAMPLE", "x=1", ("x>0",), ("x",))

    def no_action(self, _snapshot, _proposal, _request, _audit):
        return {"status": "UNKNOWN", "reason": "unlicensed_fixture"}, None

    def test_unknown_adopts_exact_native_state_after_sidecar(self):
        original = self.engine.kv_fingerprints(self.snapshot._cache)
        result = handle_event(self.engine, self.snapshot, identity=self.identity, study_seed=17,
                              detect=lambda *_: self.request, verify=self.no_action)
        direct = restore_snapshot(self.engine, self.snapshot, identity=self.identity)
        for _ in result.metadata["native_proposal_ids"]:
            advance_native(self.engine, direct)
        self.assertEqual(result.state.generated_ids, direct.generated_ids)
        self.assertTrue(self.engine.torch.equal(result.state.next_logits, direct.next_logits))
        self.assertTrue(self.engine.torch.equal(result.state.rng.get_state(), direct.rng.get_state()))
        self.assertEqual(self.engine.kv_fingerprints(result.state.cache), self.engine.kv_fingerprints(direct.cache))
        self.assertEqual(original, self.engine.kv_fingerprints(self.snapshot._cache))
        while direct.stop_reason == "RUNNING":
            self.assertEqual(advance_native(self.engine, direct), advance_native(self.engine, result.state))
        self.assertEqual(result.state.stop_reason, "EOS")
        self.assertEqual(result.metadata["decision"], "ADOPT_NATIVE")
        self.assertGreater(result.metadata["audit"]["paid_work"]["forward_input_tokens"], 0)
        self.assertNotEqual(tuple(result.metadata["audit"]["prompt_ids"]), self.snapshot.prefix_ids)

    def test_cpu_only_path_has_no_audit_forward(self):
        result = handle_event(self.engine, self.snapshot, identity=self.identity, study_seed=17,
                              detect=lambda *_: None, verify=self.no_action)
        self.assertIsNone(result.metadata["audit"])
        self.assertEqual(result.metadata["paid_work"]["forward_calls"],
                         result.metadata["native_proposal_cost"]["forward_calls"])

    def test_caller_must_provide_verified_and_bound_permission(self):
        def bad(snapshot, proposal, *_):
            receipt = digest("not_authorized")
            return {"status": "VERIFIED", "verified_evidence_sha256": receipt}, RevisionPermit(
                snapshot.prefix_sha256, digest(proposal.token_ids), "event", "REBASE", receipt)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            handle_event(self.engine, self.snapshot, identity=self.identity, study_seed=17,
                         detect=lambda *_: self.request, verify=bad)

    def test_valid_bound_permit_replaces_and_bills_native_proposal(self):
        def decide(snapshot, proposal, *_):
            receipt = digest({"checker": "fixture", "status": "REFUTED_CLAIM"})
            return {"status": "REFUTED_CLAIM", "verified_evidence_sha256": receipt}, RevisionPermit(
                snapshot.prefix_sha256, digest(proposal.token_ids), "event", "REBASE", receipt)
        changed = handle_event(self.engine, self.snapshot, identity=self.identity, study_seed=17,
                               detect=lambda *_: self.request, verify=decide,
                               revise=lambda snap, *_: restore_snapshot(self.engine, snap, identity=self.identity))
        self.assertEqual(changed.metadata["decision"], "REBASE")
        self.assertEqual(changed.state.prefix_ids, self.snapshot.prefix_ids)
        self.assertGreater(changed.metadata["discarded_native_tokens"], 0)

    def test_audit_request_prefix_and_control_tokens(self):
        wrong = AuditRequest("0" * 64, "event", "COUNTEREXAMPLE", "x=1")
        with self.assertRaisesRegex(ValueError, "different observed prefix"):
            run_side_audit(self.engine, self.snapshot, wrong, study_seed=17)
        self.assertNotIn("<|im_end|>", AuditRequest("0" * 64, "e", "fixture", "<|im_end|>").render())


if __name__ == "__main__":
    unittest.main()
