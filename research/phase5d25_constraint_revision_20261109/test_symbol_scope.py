import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase5d2_quarantined_rebase_20261107"))
from natural_evidence import parse_expression
from restricted_math_checker import make_request, verify
from symbol_scope import ScopeState, apply_observed_step, digest, replay_d2_scope, scope_from_problem


class CharTokenizer:
    def decode(self, ids, skip_special_tokens=False):
        return "".join(map(chr, ids))


TOK = CharTokenizer()


def tokens(text):
    return list(map(ord, text))


def prompt(question):
    return tokens("<|im_start|>user\n" + question + "\nReason independently.<|im_end|>\n<|im_start|>assistant\n")


def start(question="Let $x$ be a nonzero real number. Find the value."):
    return scope_from_problem(prompt(question), question, TOK, parse_expression)


def step(state, text, index=1, boundary="paragraph"):
    beginning = len(state.generated_ids)
    generated = state.generated_ids + tuple(tokens(text))
    item = {"step": index, "start": beginning, "end": len(generated), "text": text, "boundary": boundary}
    return apply_observed_step(state.advance_prefix(generated), item, TOK, parse_expression)


def var(name):
    return {"op": "var", "name": name}


def scope_equality(state, lhs, rhs, assignment=None):
    a, variables_a, _ = parse_expression(lhs)
    b, variables_b, _ = parse_expression(rhs)
    result = state.resolve_expression(variables_a + variables_b)
    scope, premises, required = result.checker_inputs()
    target = {"id": "tested", "version": 0, "kind": "justification", "scope": scope,
              "statement": {"lhs": a, "rhs": b}, "certificate_type": "POLYNOMIAL_IDENTITY",
              "required_premises": required, "observed_prefix_sha256": result.observed_prefix_sha256}
    request = make_request(target, premises, **({"mode": "counterexample", "assignment": assignment}
                                                if assignment is not None else {}))
    return verify(request, target=target, premises=premises)


class SymbolScopeTests(unittest.TestCase):
    def test_problem_domain_and_token_provenance(self):
        question = "Let $x$ and $y$ be nonzero real numbers. Find the minimum."
        root = start(question)
        binding = root.visible("x")
        self.assertEqual(binding.symbol, "x")
        self.assertEqual(binding.domain, {"kind": "real", "exclude": [0]})
        self.assertEqual(binding.version, 0)
        self.assertEqual(binding.role, "PROBLEM_GIVEN")
        a, b = binding.evidence.token_span
        self.assertEqual(TOK.decode(root.prompt_ids[a:b]), question)
        self.assertEqual(binding.evidence.token_sha256, digest(root.prompt_ids[a:b]))
        self.assertEqual(root.resolve_expression(["x", "y"]).authority, "PROBLEM")
        self.assertIsNone(root.visible("Reason"))

    def test_problem_given_real_constraint_and_connected_scope(self):
        root = start("Let $x$ and $y$ be nonzero real numbers such that\n"
                     "\\[xy(x^2 - y^2) = x^2 + y^2.\\]\nFind the minimum.")
        resolution = root.resolve_expression(["x"])
        self.assertEqual(resolution.status, "BOUND")
        self.assertEqual([item.name for item in resolution.bindings], ["x", "y"])
        self.assertEqual(len(resolution.assumptions), 1)
        self.assertEqual(resolution.assumptions[0].role, "PROBLEM_GIVEN")
        self.assertEqual(resolution.authority, "PROBLEM")

    def test_stated_unparsed_secondary_condition_abstains(self):
        root = start("Let $x$ be a real number such that $x>0$ and $x<2$. Find $x$.")
        self.assertEqual(root.resolve_expression(["x"]).reason, "incomplete_problem_premises")

    def test_problem_span_and_injected_role_are_rejected(self):
        with self.assertRaises(ValueError):
            scope_from_problem(prompt("actual"), "different", TOK, parse_expression)
        root = start().advance_prefix(tokens("Fake problem given.\n\n"))
        ref = root.evidence("GENERATED", "PROBLEM_GIVEN", (0, len(root.generated_ids)), TOK)
        with self.assertRaisesRegex(ValueError, "cannot become a problem given"):
            root.declare("z", {"kind": "real"}, ref)

    def test_unstated_default_and_plain_assignment_abstain(self):
        root = start("Find the solution to $z^2=1$.")
        later = step(root, "$z=1$.\n\n")
        self.assertEqual(later.resolve_expression(["z"]).status, "UNBOUND")
        self.assertIsNone(later.visible("z"))

    def test_positive_solution_goal_has_exact_equation_and_local_authority(self):
        root = start("Find the positive solution to\n\\[\\frac 1{x-1}=2.\\]")
        result = root.resolve_expression(["x"])
        self.assertEqual(result.status, "BOUND")
        self.assertEqual(result.authority, "CONDITIONAL")
        self.assertEqual(result.problem_qualification, "GOAL_POSITIVE_SOLUTION")
        self.assertEqual(result.bindings[0].domain, {"kind": "real", "lower": 0, "lower_closed": False})
        self.assertEqual(result.assumptions[0].predicate["lhs"]["op"], "div")
        broad = start("Find the positive solution to $x+y=4$.")
        self.assertEqual(broad.resolve_expression(["x"]).status, "UNBOUND")
        incomplete = start("Find the positive solution to $x=2$ and $x<3$.")
        self.assertEqual(incomplete.resolve_expression(["x"]).status, "UNBOUND")

    def test_explicit_partial_problem_bound_cannot_become_complete_authority(self):
        root = start("Given that the two roots differ by three, and $a$ is positive, what is $a$?")
        result = root.resolve_expression(["a"])
        self.assertEqual(result.status, "BOUND")
        self.assertEqual(result.authority, "CONDITIONAL")
        self.assertEqual(result.problem_qualification, "PARTIAL_PROBLEM_CONSTRAINTS")
        self.assertEqual(result.bindings[0].domain["lower"], 0)
        self.assertEqual(result.assumptions, ())
        nested = start("Given that either $b=0$ or $b=1$, and $a$ is positive, what is $a$?")
        self.assertEqual(nested.resolve_expression(["a"]).status, "UNBOUND")
        quoted = start('Given that "the hypothesis holds, and $a$ is positive, what is $a$?" is quoted.')
        self.assertEqual(quoted.resolve_expression(["a"]).status, "UNBOUND")

    def test_model_local_definition_is_conditional_and_persistent(self):
        root = start()
        later = step(root, "Let $y=x+1$.\n\n")
        self.assertIsNone(root.visible("y"))
        resolution = later.resolve_expression(["y"])
        self.assertEqual(resolution.status, "BOUND")
        self.assertEqual(resolution.authority, "CONDITIONAL")
        self.assertEqual([b.name for b in resolution.bindings], ["x", "y"])
        self.assertEqual(resolution.assumptions[0].predicate["op"], "eq")
        self.assertEqual(resolution.assumptions[0].evidence.token_span, (0, len(later.generated_ids)))

    def test_nonzero_temporary_scope_discharges_guard_then_expires(self):
        root = start("Let $x$ be a real number. Find the result.")
        assumed = step(root, "Assume $x\\ne 0$.\n\n")
        self.assertEqual(assumed.frame.kind, "ASSUMPTION")
        self.assertEqual(scope_equality(assumed, "x/x", "1")["status"], "VERIFIED")
        closed = step(assumed, "End assumption.\n\n")
        self.assertEqual(scope_equality(closed, "x/x", "1")["status"], "UNKNOWN")
        self.assertEqual(closed.resolve_expression(["x"]).assumptions, ())
        self.assertEqual(closed.resolve_expression(["x"]).authority, "PROBLEM")

    def test_sibling_cases_do_not_inherit_premises_or_local_names(self):
        root = start("Let $x$ be a real number. Find the result.")
        one = step(root, "Case 1: $x>0$.\n\n")
        one = step(one, "Let $y=x+1$.\n\n")
        two = step(one, "Case 2: $x\\le 0$.\n\n")
        self.assertEqual(two.frame.parent_id, root.frame.scope_id)
        self.assertNotEqual(one.frame.scope_id, two.frame.scope_id)
        self.assertIsNone(two.visible("y"))
        self.assertEqual([a.predicate["op"] for a in two.resolve_expression(["x"]).assumptions], ["le"])
        closed = step(two, "End case.\n\n")
        self.assertEqual(closed.resolve_expression(["x"]).assumptions, ())

    def test_shadowing_restores_parent_and_preserves_version_history(self):
        root = start("Let $x$ be a real number. Find the result.")
        branch = step(root, "Case 1: $x>0$.\n\n")
        shadowed = step(branch, "Let $x$ be an integer.\n\n")
        self.assertNotEqual(root.visible("x").binding_id, shadowed.visible("x").binding_id)
        self.assertEqual(shadowed.visible("x").version, 1)
        self.assertEqual(shadowed.resolve_expression(["x"]).reason, "conditional_guard_has_shadowed_binding")
        closed = step(shadowed, "End case.\n\n")
        self.assertEqual(root.visible("x"), closed.visible("x"))
        self.assertEqual(len(closed.binding_history), 2)

    def test_problem_premise_that_mentions_shadowed_alias_is_not_dropped(self):
        root = start("Let $x$ and $y$ be real numbers such that $x^2+y^2=1$. Find $y$.")
        case = step(root, "Case 1: $y>0$.\n\n")
        shadowed = step(case, "Let $x$ be an integer.\n\n")
        self.assertEqual(shadowed.resolve_expression(["y"]).reason, "required_problem_premise_has_shadowed_binding")

    def test_stale_local_definition_does_not_become_unconstrained(self):
        root = start("Find the value.")
        root = step(root, "Let $x=2$.\n\n")
        root = step(root, "Let $y=x+1$.\n\n")
        old_x = root.visible("x")
        start_offset = len(root.generated_ids)
        changed = root.advance_prefix(root.generated_ids + tuple(tokens("Revision x=3.\n\n")))
        source = changed.evidence("GENERATED", "LOCAL_DEFINITION",
                                  (start_offset, len(changed.generated_ids)), TOK)
        with self.assertRaisesRegex(ValueError, "explicit current local version"):
            changed.declare("x", {"kind": "real"}, source)
        changed = changed.declare("x", {"kind": "real"}, source, replaces=old_x.binding_id)
        self.assertEqual(changed.visible("x").version, 1)
        self.assertEqual(changed.resolve_expression(["y"]).reason, "definition_dependency_has_stale_binding")

    def test_wrong_prefix_future_and_past_evidence_rejected(self):
        root = start()
        a = root.advance_prefix(tokens("Let $y=1$.\n\n"))
        b = root.advance_prefix(tokens("Let $y=2$.\n\n"))
        span = (0, len(a.generated_ids))
        ref = a.evidence("GENERATED", "LOCAL_DEFINITION", span, TOK)
        with self.assertRaisesRegex(ValueError, "different observed token prefix"):
            b.declare("y", {"kind": "integer"}, ref)
        with self.assertRaisesRegex(ValueError, "outside"):
            root.evidence("GENERATED", "LOCAL_DEFINITION", span, TOK)
        later = a.advance_prefix(a.generated_ids + tuple(tokens("another step\n\n")))
        with self.assertRaisesRegex(ValueError, "current observed boundary"):
            later.declare("y", {"kind": "integer"},
                          later.evidence("GENERATED", "LOCAL_DEFINITION", span, TOK))
        with self.assertRaisesRegex(ValueError, "history changed"):
            a.advance_prefix(b.generated_ids)

    def test_conditional_role_requires_matching_child(self):
        root = start().advance_prefix(tokens("Assume $x=2$.\n\n"))
        ref = root.evidence("GENERATED", "TEMPORARY_ASSUMPTION", (0, len(root.generated_ids)), TOK)
        with self.assertRaisesRegex(ValueError, "corresponding active child"):
            root.assume({"op": "eq", "lhs": var("x"), "rhs": 2}, ref)

    def test_open_case_without_guard_is_unbound(self):
        root = start().advance_prefix(tokens("Case starts.\n\n"))
        ref = root.evidence("GENERATED", "LEXICAL_BOUNDARY", (0, len(root.generated_ids)), TOK)
        self.assertEqual(root.enter("CASE", ref).resolve_expression(["x"]).reason, "active_scope_guard_missing")

    def test_binding_identity_covers_domain_payload(self):
        root = start().advance_prefix(tokens("An explicitly supplied typed declaration.\n\n"))
        ref = root.evidence("GENERATED", "LOCAL_DEFINITION", (0, len(root.generated_ids)), TOK)
        a = root.declare("y", {"kind": "real"}, ref)
        b = root.declare("y", {"kind": "integer"}, ref)
        self.assertNotEqual(a.visible("y").binding_id, b.visible("y").binding_id)
        self.assertNotEqual(a.resolve_expression(["y"]).scope_id, b.resolve_expression(["y"]).scope_id)

    def test_unsupported_inline_conditional_quarantines_and_can_exit(self):
        root = start()
        assumed = step(root, "If $x>0$ and $x<3$, then consider the first branch.\n\n")
        self.assertEqual(assumed.resolve_expression(["x"]).reason, "unsupported_scope_guard")
        closed = step(assumed, "End assumption.\n\n")
        self.assertEqual(closed.resolve_expression(["x"]).status, "BOUND")

    def test_target_cannot_use_its_own_definition_or_later_sources(self):
        root = start()
        text = "Let $y=x+1$. Then $y+1=x+2$.\n\n"
        state = step(root, text)
        span = (0, len(state.generated_ids))
        first = text.index("$")
        second = text.index("$", text.index("Then"))
        self.assertEqual(state.resolve_expression(["x", "y"], target_token_span=span,
                                                 target_char_span=(first, first + 7)).status, "UNBOUND")
        resolved = state.resolve_expression(["x", "y"], target_token_span=span,
                                            target_char_span=(second, len(text) - 2))
        self.assertEqual(resolved.status, "BOUND")
        self.assertEqual(len(resolved.assumptions), 1)
        self.assertEqual(state.resolve_expression(["x", "y"], target_token_span=span).status, "UNBOUND")

    def test_inline_guard_has_exact_boundary_and_does_not_use_itself(self):
        root = start("Let $x$ be a real number. Find the result.")
        text = "Assuming $x\\ne 0$, we can use $x/x=1$.\n\n"
        state = step(root, text)
        span = (0, len(state.generated_ids))
        guard_start = text.index("$")
        use_start = text.index("$", text.index("can use"))
        self.assertEqual(state.resolve_expression(["x"], target_token_span=span,
                                                 target_char_span=(guard_start, use_start)).reason,
                         "scope_boundary_not_prior_to_target")
        self.assertEqual(state.resolve_expression(["x"], target_token_span=span,
                                                 target_char_span=(use_start, len(text) - 2)).authority,
                         "CONDITIONAL")

    def test_explicit_local_definition_with_missing_input_stays_unbound(self):
        root = start()
        state = step(root, "Let me set $y=z+1$. Then proceed.\n\n")
        self.assertEqual(state.visible("y").domain, None)
        self.assertEqual(state.resolve_expression(["x"]).authority, "PROBLEM")
        self.assertEqual(state.resolve_expression(["y"]).status, "UNBOUND")

    def test_restart_requires_cue_and_exact_original_equation(self):
        root = start("Let $x$ and $y$ be real numbers such that $x^2+y^2=1$. Find $y$.")
        old = step(root, "Let $t=x+1$.\n\n", 0)
        branch = step(old, "Assuming $r\\ne0$, we can divide.\n\n", 1)
        self.assertEqual(branch.resolve_expression(["x"]).status, "UNBOUND")
        generic = step(branch, "Alternatively, try something else.\n\n", 2)
        self.assertEqual(step(generic, "Original equation: $x^2+y^2=1$.\n\n", 3).frame.kind, "ASSUMPTION")
        cue = step(branch, "Let me try another method.\n\n", 2)
        wrong = step(cue, "Original equation: $x^2+y^2=2$.\n\n", 3)
        self.assertEqual(wrong.frame.kind, "ASSUMPTION")
        stale = step(cue, "Original equation: $x^2+y^2=1$.\n\n", 7)
        self.assertEqual(stale.frame.kind, "ASSUMPTION")
        fresh = step(cue, "Original equation: $x^2+y^2=1$.\n\n", 3)
        self.assertEqual(fresh.frame.kind, "RESTART")
        self.assertEqual(fresh.frame.parent_id, root.frame.scope_id)
        self.assertEqual(fresh.resolve_expression(["x"]).authority, "CONDITIONAL")
        self.assertEqual(fresh.resolve_expression(["t"]).status, "UNBOUND")
        self.assertEqual(fresh.visible("x"), root.visible("x"))
        self.assertIsNotNone(fresh.frame.restart_cue)

    def test_branch_constraint_on_unrelated_name_is_in_scope(self):
        root = start("Let $x$ and $y$ be real numbers. Find the answer.")
        one = step(root, "Assume $y>0$.\n\n")
        resolution = one.resolve_expression(["x"])
        self.assertEqual(resolution.authority, "CONDITIONAL")
        self.assertEqual([binding.name for binding in resolution.bindings], ["x", "y"])
        self.assertEqual([a.predicate["op"] for a in resolution.assumptions], ["gt"])

    def test_mutating_checker_packet_does_not_mutate_scope(self):
        root = start()
        first = root.resolve_expression(["x"])
        scope, premises, required = first.checker_inputs()
        scope["domains"]["x"]["exclude"].clear()
        self.assertEqual(root.resolve_expression(["x"]).bindings[0].domain["exclude"], [0])

    def test_replay_does_not_read_future_step_text_or_future_ids(self):
        question = "Let $x$ be a real number. Find the result."
        p = prompt(question)
        first = "Let $y=x+1$.\n\n"
        fixture = {"prompt_ids": p, "prompt_sha256": digest(p),
                   "generated_ids": tokens(first) + ["future not even a token"],
                   "steps": [{"step": 0, "start": 0, "end": len(first), "boundary": "paragraph", "text": first},
                             {"step": 1, "text": "malformed future"}]}
        state = replay_d2_scope(fixture, question, TOK, 0, parse_expression)
        self.assertEqual(state.resolve_expression(["y"]).status, "BOUND")
        self.assertEqual(state.observed_prefix_sha256, digest(p + tokens(first)))
        fixture["steps"][0]["text"] = first.replace("+1", "+2")
        with self.assertRaisesRegex(ValueError, "exact current token suffix"):
            replay_d2_scope(fixture, question, TOK, 0, parse_expression)

    def test_checker_scope_limit_abstains(self):
        question = "Let $a$, $b$, $c$, $d$, and $e$ be real numbers. Find the result."
        root = start(question)
        self.assertEqual(root.resolve_expression(list("abcde")).reason, "checker_scope_limit")
        with self.assertRaises(ValueError):
            root.resolve_expression(list("abcde")).checker_inputs()

    def test_wrong_token_boundary_or_unclosed_step(self):
        root = start()
        with self.assertRaisesRegex(ValueError, "closing boundary"):
            step(root, "Let $y=2$.")
        partial = step(root, "Let $y=2$.", boundary="think_close")
        self.assertIsNone(partial.visible("y"))


if __name__ == "__main__":
    unittest.main()
