"""CPU controls for dispatch, scope, implication direction and authorization."""

from dataclasses import replace
import unittest

from proposal_check import ConstraintSet, RoleAuthority, check_event, check_proposal, replay_certificate, resolve_event_scope
from symbol_scope import ScopeState
from typed_math_events import extract_events


class CharacterTokenizer:
    def decode(self, ids, **kwargs):
        return "".join(map(chr, ids))


TOKENIZER = CharacterTokenizer()


def ids(text):
    return tuple(map(ord, text))


def var(name):
    return {"op": "var", "name": name}


def example(text, domains=None, *, prefix=""):
    problem = ids("The problem states the variable domains and required conditions.")
    original = ScopeState.create(problem, (0, len(problem)))
    evidence = original.evidence("PROBLEM", "PROBLEM_GIVEN", (0, len(problem)), TOKENIZER)
    for name, domain in (domains or {}).items():
        original = original.declare(name, domain, evidence)
    scope = original.advance_prefix(ids(prefix + text))
    step = {"step": 0, "start": len(prefix), "end": len(prefix + text), "text": text}
    event, = extract_events(step, observed_prefix_sha256=scope.observed_prefix_sha256)
    return event, scope


class ProposalCheckTests(unittest.TestCase):
    def test_closed_direct_dispatch_uses_no_witness_parser(self):
        correct, _ = example("2+2=4")
        result = check_proposal(correct, "ordinary audit prose")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertIsNone(result["parser"])
        self.assertEqual(result["exact_checks"][0]["target"]["certificate_type"], "ARITHMETIC_EQ")
        self.assertTrue(replay_certificate(result["certificate"], correct, "ordinary audit prose"))
        self.assertFalse(replay_certificate(result["certificate"], correct, "different audit prose"))

    def test_false_literal_requires_a_separately_bound_role_to_retire_proof(self):
        event, _ = example("2+2=5")
        role = RoleAuthority(event.event_id, event.source.observed_prefix_sha256, "ASSERTED_JUSTIFICATION", "review-01")
        self.assertEqual(check_event(event)["status"], "FALSE_LITERAL")
        self.assertEqual(check_event(event, role_authority=vars(role))["action"], "NONE")
        self.assertEqual(check_event(event, role_authority=replace(role, event_id="other"))["action"], "NONE")
        proof = check_event(event, role_authority=role)
        claim = check_event(event, role_authority=replace(role, role="ASSERTED_CLAIM"))
        self.assertEqual((proof["status"], proof["action"]), ("INVALID_JUSTIFICATION", "INVALIDATE_JUSTIFICATION"))
        self.assertEqual((claim["status"], claim["action"]), ("REFUTED_CLAIM", "REFUTE_CLAIM"))
        self.assertNotEqual(proof["certificate"], claim["certificate"])

    def test_symbolic_identity_requires_a_matching_bound_scope(self):
        event, scope = example("Identity: $x^2+2*x+1=(x+1)^2$", {"x": {"kind": "real"}})
        self.assertEqual(check_event(event)["status"], "FORMAL_IDENTITY_VERIFIED")
        result = check_event(event, scope=scope)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["binding"]["scope_provenance"]["authority"], "PROBLEM")
        self.assertEqual(check_event(event, scope=scope.advance_prefix(scope.generated_ids + ids("\n")))["reason"],
                         "scope_source_prefix_mismatch")
        self.assertTrue(replay_certificate(result["certificate"], event, scope=scope))

    def test_original_denominator_guard_is_preserved(self):
        open_event, open_scope = example("Identity: $x/x=1$", {"x": {"kind": "real"}})
        guarded_event, guarded_scope = example("Identity: $x/x=1$", {"x": {"kind": "real", "exclude": [0]}})
        self.assertEqual(check_event(open_event, scope=open_scope)["reason"], "original_denominator_guard_unproven")
        self.assertEqual(check_event(guarded_event, scope=guarded_scope)["status"], "VERIFIED")

    def test_implication_and_equivalence_are_different(self):
        domain = {"x": {"kind": "real"}}
        good, scope = example(r"$x=1 \Rightarrow x^2=1$", domain)
        self.assertEqual(check_event(good, scope=scope)["status"], "VERIFIED_TRANSITION")
        bad, scope = example(r"$x=1 \Leftrightarrow x^2=1$", domain)
        result = check_event(bad, scope=scope)
        self.assertEqual(result["status"], "FALSE_TRANSITION")
        self.assertEqual(result["witness"], {"assignment": {"x": -1}, "antecedent": False, "consequent": True})
        reverse, scope = example(r"$x^2=1 \Leftarrow x=1$", domain)
        self.assertEqual(check_event(reverse, scope=scope)["status"], "VERIFIED_TRANSITION")

    def test_cross_paragraph_transition_requires_the_earlier_scope(self):
        previous = "$x=1$\n\n"
        domains = {"x": {"kind": "real"}}
        for text, expected in (("This implies $x^2=1$.\n\n", "VERIFIED_TRANSITION"),
                               ("This is equivalent to $x^2=1$.\n\n", "FALSE_TRANSITION")):
            with self.subTest(text=text):
                _, scope = example(text, domains, prefix=previous)
                predecessor = replace(scope, generated_ids=ids(previous))
                history = [{"step": 0, "start": 0, "end": len(previous), "text": previous, "boundary": "paragraph"}]
                step = {"step": 1, "start": len(previous), "end": len(previous + text), "text": text, "boundary": "paragraph"}
                event, = extract_events(step, observed_prefix_sha256=scope.observed_prefix_sha256, prior_steps=history)
                self.assertEqual(event.kind, "EQUATION_TRANSITION")
                self.assertEqual(event.dependencies[0].token_span, (0, len(previous)))
                self.assertEqual(check_event(event, scope=scope)["reason"], "transition_predecessor_scope_snapshot_required")
                self.assertEqual(check_event(event, scope=scope, predecessor_scope=scope)["status"], "UNKNOWN")
                result = check_event(event, scope=scope, predecessor_scope=predecessor)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["binding"]["scope_provenance"]["transition_predecessor"]["prefix_sha256"],
                                 predecessor.observed_prefix_sha256)
                self.assertTrue(replay_certificate(result["certificate"], event, scope=scope, predecessor_scope=predecessor))
                self.assertEqual(check_event(event, scope=replace(scope, revision=scope.revision + 1),
                                             predecessor_scope=predecessor)["reason"], "transition_scope_changed_between_paragraphs")

    def test_cross_paragraph_transition_rejects_branch_exit(self):
        previous = "$x=1$\n\n"
        text = "This implies $x^2=1$.\n\n"
        _, scope = example(text, {"x": {"kind": "real"}}, prefix=previous)
        predecessor = replace(scope, generated_ids=ids(previous))
        source = predecessor.evidence("GENERATED", "LEXICAL_BOUNDARY", (0, len(previous)), TOKENIZER)
        child = predecessor.enter("CASE", source)
        guard = child.evidence("GENERATED", "CASE_ASSUMPTION", (0, len(previous)), TOKENIZER)
        child = child.assume({"op": "gt", "lhs": var("x"), "rhs": 0}, guard)
        later = child.advance_prefix(ids(previous + text))
        exit_source = later.evidence("GENERATED", "LEXICAL_BOUNDARY", (len(previous), len(previous + text)), TOKENIZER)
        exited = later.exit("CASE", exit_source)
        history = [{"step": 0, "start": 0, "end": len(previous), "text": previous, "boundary": "paragraph"}]
        step = {"step": 1, "start": len(previous), "end": len(previous + text), "text": text, "boundary": "paragraph"}
        event, = extract_events(step, observed_prefix_sha256=exited.observed_prefix_sha256, prior_steps=history)
        result = check_event(event, scope=exited, predecessor_scope=child)
        self.assertEqual(result["reason"], "transition_scope_changed_between_paragraphs")
        self.assertIsNone(result["certificate"])

    def test_undefined_transition_stays_unknown(self):
        event, scope = example(r"$x/x=1 \Rightarrow x=x$", {"x": {"kind": "real"}})
        self.assertEqual(check_event(event, scope=scope)["status"], "UNKNOWN")
        event, scope = example(r"$x/x=1 \Rightarrow x=x$", {"x": {"kind": "real", "exclude": [0]}})
        self.assertEqual(check_event(event, scope=scope)["status"], "VERIFIED_TRANSITION")

    def test_witness_scope_and_scope_free_control(self):
        event, scope = example("Identity: $x^2=x$", {"x": {"kind": "integer", "values": [0, 1]}})
        text = '{"assignment":{"x":2}}'
        scoped = check_proposal(event, text, scope=scope, mode="counterexample")
        unscoped = check_proposal(event, text, scope=scope, mode="counterexample", unscoped=True)
        self.assertEqual((scoped["status"], scoped["action"]), ("INVALID_COUNTEREXAMPLE", "REJECT_COUNTEREXAMPLE"))
        self.assertEqual((unscoped["status"], unscoped["action"]), ("CHECKED_COUNTEREXAMPLE", "NONE"))
        self.assertEqual(unscoped["binding"]["scope_provenance"]["authority"], "UNSCOPED_CONTROL")
        self.assertTrue(replay_certificate(scoped["certificate"], event, text, scope=scope, mode="counterexample"))
        self.assertFalse(replay_certificate(scoped["certificate"], event, text, scope=scope, mode="counterexample", unscoped=True))

    def test_version_bound_role_controls_false_symbolic_claim(self):
        event, scope = example("Identity: $x+1=x$", {"x": {"kind": "real"}})
        resolution = resolve_event_scope(event, scope)
        role = RoleAuthority(event.event_id, event.source.observed_prefix_sha256, "ASSERTED_CLAIM", "review-02",
                             resolution.scope_id, resolution.scope_version)
        self.assertEqual(check_event(event, scope=scope, role_authority=role)["status"], "REFUTED_CLAIM")
        stale = replace(role, scope_version=role.scope_version + 1)
        self.assertEqual(check_event(event, scope=scope, role_authority=stale)["action"], "NONE")

    def test_counterexample_requires_complete_exact_json(self):
        event, scope = example("Identity: $x+y=y+x$", {"x": {"kind": "real"}, "y": {"kind": "real"}})
        for text in ('{"assignment":{"x":1}}', '{"assignment":{"x":1,"x":2,"y":1}}',
                     '{"assignment":{"x":1.0,"y":1}}', '{"assignment":{"x":true,"y":1}}',
                     '{"assignment":{"x":{"op":"rat","num":1,"den":0},"y":1}}',
                     'Here: {"assignment":{"x":1,"y":1}}'):
            with self.subTest(text=text):
                result = check_proposal(event, text, scope=scope, mode="counterexample")
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIsNone(result["certificate"])

    def test_candidate_solution_requires_an_owned_complete_constraint_set(self):
        domains = {"x": {"kind": "integer"}, "y": {"kind": "integer"}}
        predicates = [{"op": "eq", "lhs": {"op": "add", "args": [var("x"), var("y")]}, "rhs": 3},
                      {"op": "lt", "lhs": var("x"), "rhs": var("y")}]
        for text, status in (("Candidate solution: x=1, y=2", "VERIFIED_CANDIDATE"),
                             ("Candidate solution: x=2, y=1", "INVALID_CANDIDATE")):
            with self.subTest(text=text):
                event, scope = example(text, domains)
                resolved = resolve_event_scope(event, scope)
                complete = ConstraintSet.create(variables=("x", "y"), scope_id=resolved.scope_id,
                    scope_version=resolved.scope_version, observed_prefix_sha256=scope.observed_prefix_sha256,
                    evidence_id="problem-constraint-review", predicates=predicates, complete=True)
                self.assertEqual(check_event(event, scope=scope)["status"], "UNKNOWN")
                self.assertEqual(check_event(event, scope=scope, constraints=replace(complete, complete=False))["status"], "UNKNOWN")
                result = check_event(event, scope=scope, constraints=complete)
                self.assertEqual(result["status"], status)
                self.assertEqual(len(result["witness"]["constraints"]), 2)

    def test_counterexample_event_binds_target_and_past_token_source(self):
        target, scope = example("Identity: $x^2=x$", {"x": {"kind": "real"}})
        proposal = 'Counterexample to ' + target.event_id + ': {"assignment":{"x":2}}'
        end = len(scope.generated_ids)
        later = scope.advance_prefix(scope.generated_ids + ids(proposal))
        step = {"step": 1, "start": end, "end": end + len(proposal), "text": proposal}
        event, = extract_events(step, observed_prefix_sha256=later.observed_prefix_sha256)
        self.assertEqual(event.kind, "COUNTEREXAMPLE")
        self.assertEqual(check_event(event, scope=later)["status"], "UNKNOWN")
        result = check_event(event, scope=later, target_event=target, target_scope=scope)
        self.assertEqual((result["kind"], result["status"]), ("COUNTEREXAMPLE", "CHECKED_COUNTEREXAMPLE"))
        self.assertEqual(result["target_event_id"], target.event_id)
        self.assertEqual(result["binding"]["proposal_source"]["event_id"], event.event_id)

    def test_formal_proof_has_no_natural_scope_or_refutation_authority(self):
        event, _ = example("$x^2-1=(x-1)(x+1)$")
        formal = check_event(event)
        self.assertEqual(formal["status"], "FORMAL_IDENTITY_VERIFIED")
        self.assertEqual(formal["binding"]["scope_provenance"]["authority"], "FORMAL_POLYNOMIAL_ONLY")
        self.assertEqual(formal["action"], "NONE")
        conditional, _ = example("$x=1$")
        bad = check_event(conditional)
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertIsNone(bad["certificate"])
        self.assertEqual(bad["action"], "NONE")
        rational_function, _ = example("$x/x=1$")
        self.assertEqual(check_event(rational_function)["status"], "UNKNOWN")

    def test_source_cutoff_prevents_self_or_future_grounding(self):
        event, scope = example("Identity: $x=1$", {"x": {"kind": "real"}})
        full = (0, len(scope.generated_ids))
        source = scope.evidence("GENERATED", "LOCAL_DEFINITION", full, TOKENIZER,
                                char_span=event.source.char_span)
        self_grounded = scope.assume({"op": "eq", "lhs": var("x"), "rhs": 1}, source)
        self.assertEqual(len(self_grounded.resolve_expression(("x",)).assumptions), 1)
        self.assertEqual(len(resolve_event_scope(event, self_grounded).assumptions), 0)
        self.assertEqual(check_event(event, scope=self_grounded)["status"], "FALSE_SCOPED_IDENTITY")

    def test_conditional_scope_cannot_authorize_symbolic_refutation(self):
        prefix = "Temporarily suppose x>0. "
        event, scope = example("Identity: $x+1=x$", {"x": {"kind": "real"}}, prefix=prefix)
        prior = replace(scope, generated_ids=ids(prefix))
        evidence = prior.evidence("GENERATED", "LOCAL_DEFINITION", (0, len(prefix)), TOKENIZER)
        scope = prior.assume({"op": "gt", "lhs": var("x"), "rhs": 0}, evidence).advance_prefix(scope.generated_ids)
        resolution = resolve_event_scope(event, scope)
        self.assertEqual(resolution.authority, "CONDITIONAL")
        role = RoleAuthority(event.event_id, event.source.observed_prefix_sha256, "ASSERTED_CLAIM", "review-03",
                             resolution.scope_id, resolution.scope_version)
        result = check_event(event, scope=scope, role_authority=role)
        self.assertEqual((result["status"], result["action"]), ("FALSE_SCOPED_IDENTITY", "NONE"))


if __name__ == "__main__":
    unittest.main()
