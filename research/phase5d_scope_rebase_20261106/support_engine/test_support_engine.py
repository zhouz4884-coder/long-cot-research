"""Generic CPU-only exact semantics and fault injection; no research sample IDs."""
from dataclasses import replace
from fractions import Fraction
import random
import unittest

from scope_rebase_hardened import (Claim, Challenge, EvidenceLedger, Justification,
    ProofCertificate, Scope, Verification, exact)

PROPERTY_COMPARISONS = 0


def ledger():
    return EvidenceLedger([Scope("S", assumptions=("All expressions interpreted over Q.",)), Scope("T")],
                          legal_token_boundaries=(0, 10, 20, 40, 80, 100, 120, 160, 200), observed_token_length=200)


def given(g, cid, subject, value, *, scope="S", version=0, span=(0, 1), proof=None):
    g.add_claim(Claim(cid, subject, value, scope, version, *span))
    source="source_"+cid
    g.trust_given(source, cid)
    result=g.prove_given(proof or "given_"+cid, cid, source, token_start=span[0], token_end=span[1])
    assert result.verdict=="PASS"


def derive(g, proof_id, conclusion, expression, bindings=(), **kwargs):
    # Controlled original-program fixture: rule provenance is supplied by the
    # trusted test input, never inferred from the proposed computation itself.
    rule_id="rule_"+proof_id
    c=g.claims[conclusion]
    g.trust_constraint(rule_id,c.scope_id,c.subject,expression)
    return g.prove_arithmetic(proof_id,conclusion,expression,bindings,constraint_id=rule_id,**kwargs)


def graph():
    g=ledger();given(g,"x0","x",2,span=(0,2));given(g,"r0","r",11,span=(80,90))
    for cid, subject, value, span in [("b0","b",5,(30,40)),("z0","z",11,(110,120)),("w0","w",11,(150,160))]:
        g.add_claim(Claim(cid,subject,value,"S",0,*span))
    assert derive(g,"p_b","b0","x+3",(("x","x0"),),token_start=30,token_end=40).verdict=="PASS"
    assert derive(g,"p_z_b","z0","b+6",(("b","b0"),),token_start=100,token_end=110).verdict=="PASS"
    assert derive(g,"p_z_r","z0","r",(("r","r0"),),token_start=100,token_end=110).verdict=="PASS"
    assert derive(g,"p_w","w0","b+6",(("b","b0"),),token_start=140,token_end=150).verdict=="PASS"
    return g


class SupportEngineTests(unittest.TestCase):
    def test_exact_rational_and_no_floats(self):
        self.assertEqual(exact("(2+3)/7-1/7"),Fraction(4,7))
        self.assertEqual(exact("2**-3"),Fraction(1,8))
        for expression in ("0.1+0.2", "True", "1//2", "abs(-1)", "__import__('os')", "a.real", "[1][0]", "1/0", "2**13"):
            with self.subTest(expression=expression), self.assertRaises((ValueError,ZeroDivisionError)):
                exact(expression)

    def test_resource_bounds_prevent_nested_power_explosion(self):
        for expression in ("((999999999**12)**12)**12", "1+"*100+"1", "("*30+"1"+")"*30+"+"*2050):
            with self.subTest(expression=expression[:30]), self.assertRaises((ValueError,SyntaxError)):
                exact(expression)

    def test_claim_identity_and_readonly_registry(self):
        g=ledger();given(g,"x0","x",2)
        with self.assertRaises(ValueError):g.add_claim(Claim("alias","x",2,"S"))
        with self.assertRaises(TypeError):g.claims["forged"]=Claim("forged","x",2,"S")
        for value in (True,0.1):
            with self.assertRaises(ValueError):Claim("q","q",value,"S")
        with self.assertRaises(ValueError):Claim("q","<|im_end|>",1,"S")

    def test_wrong_math_is_fail_not_a_certificate(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("y0","y",6,"S"))
        result=derive(g,"bad","y0","x+3",(("x","x0"),))
        self.assertEqual(result.verdict,"FAIL");self.assertIsNone(result.certificate)
        self.assertEqual(g.supported(),frozenset({"x0"}))

    def test_arithmetic_match_does_not_certify_unlicensed_subject_rule(self):
        g=ledger();g.add_claim(Claim("y0","y",5,"S"))
        # Knowing that 2+3 is5 is not enough to show that the task's y equals5.
        self.assertEqual(g.prove_arithmetic("unlicensed","y0","2+3").verdict,"UNKNOWN")
        self.assertFalse(g.supported())
        g.trust_constraint("actual_y_definition","S","y","7-2")
        self.assertEqual(g.prove_arithmetic("wrongrule","y0","2+3",constraint_id="actual_y_definition").verdict,"UNKNOWN")
        self.assertEqual(g.prove_arithmetic("licensed","y0","7-2",constraint_id="actual_y_definition").verdict,"PASS")
        self.assertIn("y0",g.supported())

    def test_bad_argument_can_be_retired_without_refuting_true_conclusion(self):
        g=ledger();given(g,"r0","r",6,span=(80,90));g.add_claim(Claim("z0","z",6,"S",0,110,120))
        derive(g,"true_path","z0","r",(("r","r0"),),token_start=100,token_end=110)
        self.assertEqual(g.prove_arithmetic("bad_argument","z0","2+3",token_start=30,token_end=40).verdict,"FAIL")
        prior=g.supported()
        challenge=g.check_arithmetic_invalidation("numeric_refutation","bad_argument")
        self.assertIsInstance(challenge,Challenge);self.assertEqual(g.verify_challenge(challenge).verdict,"PASS")
        d=g.apply_challenge(challenge)
        self.assertEqual(g.supported(),prior);self.assertFalse(d.claim_refuted);self.assertFalse(d.lost_support)
        self.assertEqual(d.invalidated_justifications,("bad_argument",));self.assertEqual(d.safe_cut_token,20)
        self.assertIn("z = 6",g.bridge(d))

    def test_x2_to_square5_rejects_step_not_the_parent(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("square0","square",5,"S",0,20,30))
        g.prove_arithmetic("bad_square","square0","x**2",(("x","x0"),),token_start=20,token_end=30)
        challenge=g.check_arithmetic_invalidation("checked_counterstep","bad_square")
        delta=g.apply_challenge(challenge)
        self.assertEqual(delta.verdict,"PASS");self.assertFalse(delta.claim_refuted)
        self.assertEqual(g.supported(),frozenset({"x0"}))
        self.assertFalse(g.proofs["given_x0"].revoked)

    def test_arithmetic_challenge_needs_grounded_scoped_premises(self):
        g=ledger();g.add_claim(Claim("x0","x",2,"S"));g.add_claim(Claim("y0","y",6,"S"))
        g.prove_arithmetic("wrong_unproved","y0","x+3",(("x","x0"),),token_start=20,token_end=30)
        self.assertEqual(g.check_arithmetic_invalidation("cannot_refute_yet","wrong_unproved").verdict,"UNKNOWN")
        g.trust_given("x_source","x0");g.prove_given("x_proof","x0","x_source")
        ch=g.check_arithmetic_invalidation("can_refute_step","wrong_unproved")
        self.assertEqual(g.verify_challenge(ch).verdict,"PASS")
        self.assertEqual(g.apply_challenge(replace(ch,scope_id="T")).verdict,"UNKNOWN")
        self.assertEqual(g.apply_challenge(replace(ch,target_id="x_proof")).verdict,"UNKNOWN")

    def test_valid_arithmetic_step_is_not_refuted_by_bad_objection(self):
        g=graph();before=g.supported();v=g.check_arithmetic_invalidation("false_objection","p_b")
        self.assertEqual(v.verdict,"FAIL");self.assertEqual(g.apply_challenge(v).verdict,"UNKNOWN")
        self.assertEqual(g.supported(),before)

    def test_unknown_and_cross_scope_do_not_pass(self):
        g=ledger();given(g,"x0","x",2,scope="T");g.add_claim(Claim("y0","y",5,"S"))
        self.assertEqual(derive(g,"cross","y0","x+3",(("x","x0"),)).verdict,"UNKNOWN")
        self.assertEqual(derive(g,"missing","y0","x+3",()).verdict,"UNKNOWN")
        self.assertEqual(derive(g,"wrongentity","y0","y+3",(("y","x0"),)).verdict,"UNKNOWN")

    def test_free_pass_and_forged_certificate_rejected(self):
        g=ledger();g.add_claim(Claim("x0","x",999,"S"))
        fake=ProofCertificate("arbitrary","trusted-input-v1","justify","anything",())
        proposal=Justification("fake","x0",(),"S",None,(),"trusted-input-v1",fake,"PASS","source")
        self.assertEqual(g.ingest_justification(proposal).verdict,"UNKNOWN")
        self.assertFalse(g.supported())

    def test_certificate_cannot_be_transplanted_to_different_proof(self):
        g=graph();p=g.proofs["p_b"]
        result=g.ingest_justification(replace(p,id="transplant"))
        self.assertEqual(result.verdict,"UNKNOWN")
        # A changed binding, checker identity or receipt payload is likewise not accepted.
        for idx, change in enumerate(({"checker_id":"llm_self_judge"},{"certificate":replace(p.certificate,binding_hash="false")},
                                      {"certificate":replace(p.certificate,witness=(("computed","100"),))})):
            self.assertEqual(g.ingest_justification(replace(p,id="badcert"+str(idx),**change)).verdict,"UNKNOWN")

    def test_scope_bound_challenge_and_fake_pass_noop(self):
        g=graph();before=g.supported()
        for word in ("PASS","FAIL","UNKNOWN"):
            c=Challenge("fake_"+word,"invalidate_justification","p_b","S",None,word)
            d=g.apply_challenge(c)
            self.assertEqual(g.supported(),before);self.assertFalse(d.invalidated_justifications)
        real=g.issue_withdrawal("real","p_b",reason="trusted source retracts this evidence license")
        for changed in (replace(real,scope_id="T"),replace(real,target_id="p_z_b"),replace(real,kind="refute_claim")):
            self.assertEqual(g.apply_challenge(changed).verdict,"UNKNOWN")
            self.assertEqual(g.supported(),before)

    def test_withdraw_one_proof_keeps_independent_conclusion_and_descendant(self):
        g=graph();d=g.apply_challenge(g.issue_withdrawal("withdraw_b","p_b",reason="source event"))
        self.assertEqual(d.lost_support,frozenset({"b0","w0"}))
        self.assertEqual(g.supported(),frozenset({"x0","r0","z0"}))
        self.assertFalse(d.claim_refuted)
        self.assertEqual(d.safe_cut_token,20)
        self.assertEqual(d.carried_claims,("r0","z0"))
        text=g.bridge(d)
        self.assertIn("z = 11",text);self.assertIn("assumptions_json",text)
        self.assertNotIn("b = 5",text);self.assertNotIn(g.proofs["p_z_b"].certificate.id,text)

    def test_lost_empty_still_retires_bad_proof_text(self):
        g=graph();before=g.supported()
        d=g.apply_challenge(g.issue_withdrawal("retire_z_path","p_z_b",reason="provenance obsolete"))
        self.assertEqual(g.supported(),before);self.assertFalse(d.lost_support)
        self.assertEqual(d.invalidated_justifications,("p_z_b",))
        self.assertEqual(d.invalidated_text_spans,((100,110),))
        self.assertEqual(d.proposed_cut_token,100);self.assertEqual(d.safe_cut_token,100)
        self.assertIn("z0",d.carried_claims)

    def test_unmapped_boundary_and_stale_delta_are_not_silently_used(self):
        g=EvidenceLedger([Scope("S")],legal_token_boundaries=(),observed_token_length=20)
        given(g,"x0","x",1,span=(10,11))
        d=g.apply_challenge(g.issue_withdrawal("cut","given_x0",reason="evidence withdrawn"))
        self.assertIsNone(d.safe_cut_token);self.assertEqual(g.bridge(d),"")
        g.add_claim(Claim("q0","q",2,"S"))
        with self.assertRaises(ValueError):g.bridge(d)

    def test_cyclic_conditional_proofs_need_independent_ground(self):
        g=ledger();g.add_claim(Claim("x0","x",1,"S"));g.add_claim(Claim("y0","y",1,"S"))
        self.assertEqual(derive(g,"px","x0","y",(("y","y0"),)).verdict,"PASS")
        self.assertEqual(derive(g,"py","y0","x",(("x","x0"),)).verdict,"PASS")
        self.assertFalse(g.supported())
        g.trust_given("ground","x0");g.prove_given("groundproof","x0","ground")
        self.assertEqual(g.supported(),frozenset({"x0","y0"}))
        d=g.apply_challenge(g.issue_withdrawal("remove_ground","groundproof",reason="source event"))
        self.assertEqual(d.lost_support,frozenset({"x0","y0"}))

    def test_and_requires_all_current_premises(self):
        g=ledger();given(g,"a0","a",1);g.add_claim(Claim("b0","b",1,"S"));g.add_claim(Claim("c0","c",2,"S"))
        derive(g,"pc","c0","a+b",(("a","a0"),("b","b0")))
        self.assertEqual(g.supported(),frozenset({"a0"}))

    def test_two_paths_sharing_the_same_withdrawn_root_are_not_independent(self):
        g=ledger();given(g,"x0","x",2);given(g,"r0","r",7)
        for cid,subject,value in [("a0","a",3),("b0","b",4),("z0","z",5)]:g.add_claim(Claim(cid,subject,value,"S"))
        derive(g,"pa","a0","x+1",(("x","x0"),));derive(g,"pb","b0","x+2",(("x","x0"),))
        derive(g,"pz_a","z0","a+2",(("a","a0"),));derive(g,"pz_b","z0","b+1",(("b","b0"),))
        d=g.apply_challenge(g.issue_withdrawal("withdraw_shared_root","given_x0",reason="trusted source event"))
        self.assertEqual(d.lost_support,frozenset({"x0","a0","b0","z0"}))
        self.assertEqual(g.supported(),frozenset({"r0"}))

    def test_same_subject_in_distinct_scopes_is_not_a_conflict(self):
        g=ledger();given(g,"s_x","x",2,scope="S");given(g,"t_x","x",3,scope="T")
        self.assertEqual(g.support_state().status,"OK")
        self.assertEqual(g.supported(),frozenset({"s_x","t_x"}))

    def test_version_update_drops_old_dependent_support_not_truth(self):
        g=graph();given(g,"x1","x",3,version=1)
        d=g.activate_version("x1")
        self.assertEqual(d.verdict,"PASS")
        self.assertEqual(d.lost_support,frozenset({"x0","b0","w0"}))
        self.assertEqual(g.supported(),frozenset({"x1","r0","z0"}))
        self.assertIn("x0",g.claims);self.assertFalse(g.proofs["given_x0"].revoked)
        self.assertFalse(d.claim_refuted)

    def test_atomic_multi_root_update(self):
        g=ledger();given(g,"x0","x",2);given(g,"r0","r",3)
        g.add_claim(Claim("z0","z",5,"S"));derive(g,"sum","z0","x+r",(("x","x0"),("r","r0")))
        given(g,"x1","x",7,version=1);given(g,"r1","r",8,version=1)
        d=g.activate_versions(("x1","r1"))
        self.assertEqual(d.lost_support,frozenset({"x0","r0","z0"}))
        self.assertEqual(g.supported(),frozenset({"x1","r1"}))

    def test_new_version_cannot_depend_on_archived_self_or_unproved_parent(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("x1","x",3,"S",1))
        derive(g,"increment","x1","x+1",(("x","x0"),))
        d=g.activate_version("x1")
        self.assertEqual(d.verdict,"UNKNOWN");self.assertEqual(g.current_versions[("S","x")],0)
        self.assertEqual(g.supported(),frozenset({"x0"}))

    def test_contradictory_certificates_quarantined_not_arbitrarily_resolved(self):
        g=ledger();given(g,"xA","x",2);given(g,"xB","x",3);given(g,"r0","r",11)
        s=g.support_state();self.assertEqual(s.status,"INCONSISTENT_CERTIFICATES")
        self.assertEqual(s.conflict_claims,frozenset({"xA","xB"}));self.assertEqual(s.supported,frozenset({"r0"}))
        self.assertFalse(g.proofs["given_xA"].revoked);self.assertFalse(g.proofs["given_xB"].revoked)

    def test_claim_refutation_is_not_proof_withdrawal(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("z0","z",5,"S"))
        g.trust_constraint("definition_z","S","z","x+2")
        ch=g.check_claim_refutation("counter_z","z0","definition_z",(("x","x0"),))
        self.assertIsInstance(ch,Challenge);self.assertEqual(g.verify_challenge(ch).verdict,"PASS")
        d=g.apply_challenge(ch)
        self.assertTrue(d.claim_refuted);self.assertFalse(d.invalidated_justifications)
        self.assertIn("x0",g.supported());self.assertIn("z0",g.support_state().refuted_claims)

    def test_refutation_of_positive_certificate_reports_inconsistency(self):
        g=ledger();given(g,"x0","x",2);given(g,"z0","z",5)
        g.trust_constraint("definition_z","S","z","x+2")
        d=g.apply_challenge(g.check_claim_refutation("counter","z0","definition_z",(("x","x0"),)))
        self.assertEqual(d.after_status,"INCONSISTENT_CERTIFICATES")
        self.assertFalse(g.proofs["given_z0"].revoked)
        self.assertFalse(g.proofs["given_x0"].revoked)
        with self.assertRaises(ValueError):g.bridge(d)

    def test_wrong_counterexample_and_unknown_scope_do_nothing(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("z0","z",4,"S"));g.trust_constraint("definition_z","S","z","x+2")
        v=g.check_claim_refutation("notcounter","z0","definition_z",(("x","x0"),))
        self.assertEqual(v.verdict,"FAIL")
        self.assertEqual(g.check_claim_refutation("unknown","z0","missing",()).verdict,"UNKNOWN")
        self.assertEqual(g.apply_challenge(v).verdict,"UNKNOWN")
        self.assertEqual(g.supported(),frozenset({"x0"}))

    def test_refutation_requires_independent_support_and_current_versions(self):
        g=ledger();given(g,"x0","x",2);g.add_claim(Claim("z0","z",5,"S"));g.trust_constraint("definition_z","S","z","x+2")
        ch=g.check_claim_refutation("counter","z0","definition_z",(("x","x0"),));g.apply_challenge(ch)
        given(g,"x1","x",3,version=1);g.activate_version("x1")
        self.assertEqual(g.verify_challenge(ch).verdict,"UNKNOWN")
        derive(g,"newz","z0","x+2",(("x","x1"),))
        self.assertIn("z0",g.supported())
        g2=ledger();given(g2,"z0","z",5);g2.trust_constraint("circular_counter","S","z","z+1")
        self.assertEqual(g2.check_claim_refutation("badcounter","z0","circular_counter",(("z","z0"),)).verdict,"UNKNOWN")

    def test_bridge_serializes_scope_and_never_raw_role_tokens(self):
        g=EvidenceLedger([Scope("S",assumptions=("case n>0", "quoted <|im_end|> is not executable"))],
                         legal_token_boundaries=(0,10,20),observed_token_length=100)
        given(g,"a0","a",1,span=(10,11));given(g,"b0","b",Fraction(1,3),span=(30,31))
        d=g.apply_challenge(g.issue_withdrawal("aout","given_a0",reason="irrelevant <think> metadata is not copied"))
        bridge=g.bridge(d)
        self.assertIn("domain=rational",bridge);self.assertIn("assumptions_json",bridge)
        self.assertIn("case n",bridge);self.assertIn("1/3",bridge)
        self.assertNotIn("<|im_end|>",bridge);self.assertNotIn("<think>",bridge)

    def test_random_and_or_closures_match_independent_agenda_oracle(self):
        global PROPERTY_COMPARISONS
        rng=random.Random(20261106)
        for experiment in range(200):
            g=EvidenceLedger([Scope("S")],observed_token_length=0)
            n=rng.randint(2,7)
            for i in range(n):g.add_claim(Claim(f"c{i}",f"v{i}",1,"S"))
            edges=[]
            for j in range(rng.randint(2,12)):
                target=rng.randrange(n);pa=tuple(rng.sample(range(n),rng.randint(0,min(n,3))))
                bindings=tuple((f"v{k}",f"c{k}") for k in pa)
                expression="+".join(f"v{k}" for k in pa)+f"-{len(pa)-1}" if pa else "1"
                result=derive(g,f"p{j}",f"c{target}",expression,bindings)
                self.assertEqual(result.verdict,"PASS")
                edges.append((f"p{j}",f"c{target}",frozenset(f"c{k}" for k in pa)))
            dead=set()
            def oracle():
                # Agenda propagation, separate from the engine's synchronous iterations.
                supported=set();changed=True
                while changed:
                    changed=False
                    for pid, target, pa in edges:
                        if pid not in dead and target not in supported and pa<=supported:
                            supported.add(target);changed=True
                return frozenset(supported)
            for step in range(3):
                self.assertEqual(g.supported(),oracle(),(experiment,step));PROPERTY_COMPARISONS+=1
                if step<2:
                    pid=edges[rng.randrange(len(edges))][0];dead.add(pid)
                    g.apply_challenge(g.issue_withdrawal(f"event{step}",pid,reason="controlled admissibility event"))


if __name__=="__main__":unittest.main()
