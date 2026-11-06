from scope_rebase_core import Claim, Justification, Challenge, EvidenceLedger, verify_numeric_equality


def make_graph():
    claims = [
        Claim("x@0", "x=2", "S", 0, 10),
        Claim("b@0", "b=5", "S", 100, 120),
        Claim("r@0", "r=11 from independent source", "S", 180, 200),
        Claim("z@0", "z=11", "S", 220, 245),
        Claim("w@0", "w=11", "S", 250, 275),
    ]
    proofs = [
        Justification("root_x", "x@0", (), "S", "PASS", "trusted_root", "source_x"),
        Justification("root_r", "r@0", (), "S", "PASS", "trusted_root", "source_r"),
        Justification("bad_step", "b@0", ("x@0",), "S", "PASS", "verified_rule", "old_certificate"),
        Justification("p_z_via_b", "z@0", ("b@0",), "S", "PASS", "verified_rule", "cert1"),
        Justification("p_z_via_r", "z@0", ("r@0",), "S", "PASS", "verified_rule", "cert2"),
        Justification("p_w", "w@0", ("b@0",), "S", "PASS", "verified_rule", "cert3"),
    ]
    return EvidenceLedger(claims, proofs)


def test_invalid_new_counterexample_must_not_destroy_support():
    g=make_graph()
    before=g.supported()
    d=g.revoke_by_challenge(Challenge("bad_step", "FAIL", "S", "invalid_counterexample"))
    assert g.supported()==before
    assert not d.lost_support


def test_unknown_or_out_of_scope_cannot_revoke():
    g=make_graph()
    before=g.supported()
    for e in [Challenge("bad_step", "UNKNOWN", "S", "ambiguous"),
              Challenge("bad_step", "PASS", "other_scope", "valid_only_elsewhere")]:
        d=g.revoke_by_challenge(e)
        assert not d.lost_support and g.supported()==before


def test_bad_justification_revoked_but_independent_support_survives():
    g=make_graph()
    d=g.revoke_by_challenge(Challenge("bad_step", "PASS", "S", "independent_exact_refutation"))
    assert d.lost_support==frozenset({"b@0", "w@0"})
    assert {"x@0","r@0","z@0"}.issubset(d.retained_support)
    assert d.crop_at_token==100
    assert d.carried_claims == ("r@0", "z@0")
    txt=g.bridge(d)
    assert "r@0" in txt and "z@0" in txt and "b@0" not in txt


def test_scope_and_cycles_not_silently_certified():
    x=Claim("x","x", "S", 0,1); y=Claim("y","y", "S", 1,2)
    g=EvidenceLedger([x,y], [Justification("a","x",("y",),"S","PASS","verified_rule","c1"),
                             Justification("b","y",("x",),"S","PASS","verified_rule","c2")])
    assert g.supported()==frozenset()


def test_arithmetic_checks_are_exact_and_abstain_on_unknown_scope():
    assert verify_numeric_equality("2 * (7 - 3)","8",scope_complete=True)=="PASS"
    assert verify_numeric_equality("2 * (7 - 3)","9",scope_complete=True)=="FAIL"
    assert verify_numeric_equality("2 * (7 - 3)","8",scope_complete=False)=="UNKNOWN"
    assert verify_numeric_equality("eval('5')","5",scope_complete=True)=="UNKNOWN"
    assert verify_numeric_equality("1/0","1",scope_complete=True)=="UNKNOWN"
