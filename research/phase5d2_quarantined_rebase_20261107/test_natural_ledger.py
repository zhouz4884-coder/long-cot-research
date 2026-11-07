"""Generic CPU contracts for literal facts and separately reviewed proof roles."""

import unittest

import natural_ledger as adapter
from natural_evidence import parse_expression


def relation(surface, *, span=(1, 5), step=0):
    left, right = surface.split("=")
    la, lv, le = parse_expression(left)
    ra, rv, re = parse_expression(right)
    return {"status": "parsed", "reason": None, "surface": surface, "step": step,
            "token_span": list(span), "equation_index": 0, "char_span_in_step": [0, len(surface)],
            "statement": {"lhs": la, "rhs": ra}, "variables": sorted(set(lv) | set(rv)),
            "normalized": [le, re], "certificate_type": "ARITHMETIC_EQ", "role_certified": False}


def observed(relations):
    return adapter.make_observed_relations([100, 101], list(range(1, 21)), (0, 5, 10, 15, 20), relations)


def reviews():
    return [{"id": "/root", "verdict": adapter.ROLE_VERDICT},
            {"id": "/root/independent", "verdict": adapter.ROLE_VERDICT}]


class NaturalLedgerTests(unittest.TestCase):
    def test_true_closed_expression_facts_have_executed_checks_and_no_givens(self):
        true = relation("2+2=4")
        false = relation("2+2=5", span=(5, 10), step=1)
        envelope = observed([true, false])
        built = adapter.build_natural_ledger(envelope, 20, false, None)
        self.assertIsNone(built.challenge)
        self.assertEqual(built.metadata["role_status"], "MISSING")
        self.assertEqual(len(built.ledger.supported()), 1)
        self.assertEqual(built.ledger._givens, {})
        self.assertEqual(built.metadata["trusted_given_calls"], 0)
        records = built.metadata["processed_relations"]
        self.assertEqual([r["literal_result"]["status"] for r in records], ["VERIFIED", "INVALID_JUSTIFICATION"])
        self.assertEqual([r["ledger_verdict"] for r in records], ["PASS", "FAIL"])
        self.assertTrue(all(c.subject.startswith("expr_") for c in built.ledger.claims.values()))

    def test_two_observed_occurrences_give_one_claim_multiple_proofs(self):
        first = relation("2+2=4")
        second = relation("2 + 2=8/2", span=(5, 10), step=1)
        built = adapter.build_natural_ledger(observed([first, second]), 20, second, None)
        self.assertEqual(len(built.ledger.claims), 1)
        self.assertEqual(len(built.ledger.proofs), 2)
        self.assertEqual(len(built.ledger.supported()), 1)

    def test_unanimous_receipt_allows_proof_invalidation_without_claim_refutation(self):
        good = relation("2+2=4")
        bad = relation("2+2=5", span=(5, 10), step=1)
        envelope = observed([good, bad])
        receipt = adapter.make_role_certificate(bad, envelope["source_prefix_sha256"], reviews())
        built = adapter.build_natural_ledger(envelope, 20, bad, receipt)
        self.assertEqual(built.status, "ACTIONABLE_LITERAL_INVALIDATION")
        self.assertEqual(built.ledger.verify_challenge(built.challenge).verdict, "PASS")
        before = built.ledger.supported()
        delta = built.ledger.apply_challenge(built.challenge)
        self.assertFalse(delta.claim_refuted)
        self.assertEqual(delta.lost_support, frozenset())
        self.assertEqual(delta.invalidated_text_spans, ((5, 10),))
        self.assertEqual(built.ledger.supported(), before)
        self.assertEqual(built.ledger._refutations, {})

    def test_lexical_assertion_and_external_verified_strings_cannot_grant_role(self):
        bad = relation("2+2=5")
        bad.update(actionable_role_candidate=True, role_certified=True, verification={"status": "VERIFIED"})
        built = adapter.build_natural_ledger(observed([bad]), 20, bad, None)
        self.assertIsNone(built.challenge)
        self.assertFalse(built.ledger.supported())
        proof = next(iter(built.ledger.proofs.values()))
        self.assertEqual(proof.verdict, "FAIL")
        self.assertIsNone(proof.certificate)
        self.assertEqual(built.ledger._constraints, {})

    def test_reviewers_must_be_distinct_unanimous_and_pre_gold(self):
        bad = relation("2+2=5")
        envelope = observed([bad])
        reviewer_sets = [reviews()[:1], [reviews()[0], reviews()[0]],
                         [reviews()[0], {"id": "/root/independent", "verdict": "UNKNOWN"}],
                         [{"id": "/root/a", "verdict": adapter.ROLE_VERDICT}, {"id": "/root/b", "verdict": adapter.ROLE_VERDICT}]]
        for entries in reviewer_sets:
            receipt = adapter.make_role_certificate(bad, envelope["source_prefix_sha256"], entries)
            self.assertIsNone(adapter.build_natural_ledger(envelope, 20, bad, receipt).challenge)
        receipt = adapter.make_role_certificate(bad, envelope["source_prefix_sha256"], reviews())
        receipt["review_phase"] = "AFTER_GOLD"
        receipt["receipt_sha256"] = adapter.support.digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        self.assertIsNone(adapter.build_natural_ledger(envelope, 20, bad, receipt).challenge)

    def test_receipt_binds_exact_relation_and_actual_source_ids(self):
        bad = relation("2+2=5")
        envelope = observed([bad])
        receipt = adapter.make_role_certificate(bad, envelope["source_prefix_sha256"], reviews())
        for field, value in (("relation_sha256", "other"), ("source_prefix_sha256", "other"), ("receipt_sha256", "other")):
            forged = {**receipt, field: value}
            self.assertIsNone(adapter.build_natural_ledger(envelope, 20, bad, forged).challenge)
        changed = {**envelope, "generated_ids": [99, *envelope["generated_ids"][1:]]}
        with self.assertRaisesRegex(ValueError, "SHA differs"):
            adapter.build_natural_ledger(changed, 20, bad, receipt)
        with self.assertRaisesRegex(ValueError, "length differs"):
            adapter.build_natural_ledger(envelope, 19, bad, receipt)
        stale_relation = {**bad, "observed_prefix_sha256": "an_older_prefix"}
        built = adapter.build_natural_ledger(observed([stale_relation]), 20, stale_relation, None)
        self.assertFalse(built.ledger.claims)
        rebound_relation = {**bad, "observed_prefix_sha256": envelope["source_prefix_sha256"]}
        rebound_source = observed([rebound_relation])
        rebound_receipt = adapter.make_role_certificate(rebound_relation, rebound_source["source_prefix_sha256"], reviews())
        built = adapter.build_natural_ledger(rebound_source, 20, rebound_relation, rebound_receipt)
        self.assertEqual(built.status, "ACTIONABLE_LITERAL_INVALIDATION")

    def test_plain_list_keeps_true_facts_but_lacks_actionable_source(self):
        good = relation("2+2=4")
        bad = relation("2+2=5", span=(5, 10), step=1)
        envelope = observed([good, bad])
        receipt = adapter.make_role_certificate(bad, envelope["source_prefix_sha256"], reviews())
        built = adapter.build_natural_ledger([good, bad], 20, bad, receipt)
        self.assertEqual(len(built.ledger.supported()), 1)
        self.assertIsNone(built.challenge)
        self.assertEqual(built.metadata["role_status"], "SOURCE_IDS_MISSING")

    def test_surface_ast_and_normalized_bindings_must_match(self):
        good = relation("2+2=4")
        for patched in ({**good, "surface": "2+2=5"}, {**good, "normalized": ["3+2", "4"]},
                        {**good, "statement": {"lhs": 5, "rhs": 5}}):
            built = adapter.build_natural_ledger(observed([patched]), 20, patched, None)
            self.assertFalse(built.ledger.claims)
            self.assertEqual(built.metadata["skipped_relations"][0]["status"], "UNKNOWN")

    def test_named_subject_meaning_and_nonclosed_types_stay_unresolved(self):
        symbolic = relation("x+1=3")
        symbolic["variables"] = []
        polynomial = relation("2+2=4")
        polynomial["certificate_type"] = "POLYNOMIAL_IDENTITY"
        for candidate in (symbolic, polynomial):
            built = adapter.build_natural_ledger(observed([candidate]), 20, candidate, None)
            self.assertFalse(built.ledger.claims)
            self.assertIsNone(built.challenge)

    def test_unobserved_or_noninteger_spans_cannot_create_facts(self):
        for span in ((False, 5), (5, 5), (1, 21), (-1, 5)):
            candidate = relation("2+2=4", span=span)
            built = adapter.build_natural_ledger(observed([candidate]), 20, candidate, None)
            self.assertFalse(built.ledger.claims)
            self.assertIsNone(built.challenge)

    def test_correct_equation_and_unlisted_candidate_cannot_be_withdrawn(self):
        true = relation("2+2=4")
        envelope = observed([true])
        receipt = adapter.make_role_certificate(true, envelope["source_prefix_sha256"], reviews())
        built = adapter.build_natural_ledger(envelope, 20, true, receipt)
        self.assertIsNone(built.challenge)
        absent = relation("2+2=5", span=(5, 10), step=1)
        receipt = adapter.make_role_certificate(absent, envelope["source_prefix_sha256"], reviews())
        self.assertIsNone(adapter.build_natural_ledger(envelope, 20, absent, receipt).challenge)

    def test_exact_rational_literals_pass_and_invalid_arithmetic_abstains(self):
        valid = relation(r"\frac{1}{2}+\frac{1}{2}=1")
        built = adapter.build_natural_ledger(observed([valid]), 20, valid, None)
        self.assertEqual(len(built.ledger.supported()), 1)
        for text in ("1/0=1", "0.5+0.5=1", "2^13=8192"):
            candidate = relation(text)
            built = adapter.build_natural_ledger(observed([candidate]), 20, candidate, None)
            self.assertFalse(built.ledger.claims)
            self.assertEqual(built.metadata["skipped_relations"][0]["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
