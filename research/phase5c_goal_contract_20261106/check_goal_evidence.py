"""Synthetic CPU contracts only; no historical bank, evaluator, model or GPU."""
import copy
import hashlib
import json
from pathlib import Path

import goal_evidence as g


def main():
    checks=[]
    def ok(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    samples=[("How many ordered pairs (u,v) satisfy the condition?","count",None),
             ("Enter the ordered triple (u,v,w).","ordered_tuple",3),
             ("What is the probability of success?","probability",None),
             ("Which vector does this transformation produce?","vector",None),
             ("Find the value of the expression.","unknown",None)]
    for i,(q,kind,n) in enumerate(samples):
        c=g.derive_contract(q);ok("type_"+str(i),c["answer_type_hint"]==kind and c["tuple_arity_hint"]==n)
        ok("contract_source_span_"+str(i),q[slice(*c["target_span"])]==c["target_quote"])
        ok("no_numeric_blacklist_"+str(i),c["forbidden_intermediate_values"]==[])
    c=g.derive_contract("What is the probability as a percentage?")
    ok("percent_scale_not_forced_fraction",c["representation_hint"]=="percentage")
    ok("probability_zero_one_legal","0和1合法" in g.derive_contract("What is the probability?")["instruction"])
    ok("no_solver_map",c["terminal_map"]=="NOT_AUTOMATICALLY_DERIVED")
    ok("count_without_article",g.derive_contract("Find number of ordered pairs (u,v). ")["answer_type_hint"]=="count")
    c=g.derive_contract("Find x. [asy] draw((0,0)); find bogus [/asy]")
    ok("diagram_not_later_goal",c["target_quote"]=="Find x.")
    q="Find the probability of the stated event."
    trace=("Exploration without conclusion.\n\nThe answer is \\boxed{1/2}.\n\n"
           +"Checking another route. "*100+"\n\nWait, this may be wrong. The answer is \\boxed{0.5}.\n\n"
           +"Therefore probability = 1/2; equivalent form may be 0.5.")
    p=g.build_evidence_packet(q,trace,max_chars=512,max_spans=4)
    ok("bounded_quotes",p["selected_quote_chars"]<=512 and len(p["spans"])<=4)
    ok("quotes_exact",all(trace[v["start"]:v["end"]]==v["text"] for v in p["spans"]))
    ok("all_unverified",all(v["status"]=="UNVERIFIED" for v in p["spans"]))
    ok("no_fake_G",p["G_status"]=="NOT_IMPLEMENTED_NO_TRUTH_ARBITRATION" and not p["certified_parent_boundary"])
    ok("equivalent_forms_not_true_conflict",p["surface_conflict_signal"] and p["semantic_conflict_verdict"]=="UNKNOWN")
    ok("early_latest_candidates_preserved",any("1/2" in v["text"] for v in p["spans"]) and any("0.5" in v["text"] for v in p["spans"]))
    ok("standalone_answer_colon",g.build_evidence_packet("Find x.","Answer: 7.",512,4)["status"]=="UNVERIFIED_CANDIDATE_QUOTES")
    ok("deterministic",p==g.build_evidence_packet(q,trace,512,4))
    for i,t in enumerate(["", "Some uncertain prose with no signal.", "Wait. Wait. Wait."]):
        pp=g.build_evidence_packet("Unspecified task.",t,512,4)
        ok("unknown_fallback_"+str(i),pp["status"]=="UNKNOWN_NO_CANDIDATE_FALLBACK_TAIL")
        ok("fallback_exact_"+str(i),all(t[v["start"]:v["end"]]==v["text"] for v in pp["spans"]))
        ok("fallback_truth_schema_"+str(i),pp["G_status"]=="NOT_IMPLEMENTED_NO_TRUTH_ARBITRATION" and pp["semantic_conflict_verdict"]=="UNKNOWN")
    for i,t in enumerate(["\\boxed{\\frac{3}{7}}", "\\boxed{(2,4)}", "\\boxed{incomplete"]):
        pp=g.build_evidence_packet("Find the value.",t,512,4)
        ok("nested_or_incomplete_"+str(i),pp.get("boxed_surface_variants_count",0)==(1 if i<2 else 0))
    tail=g.last_tail_packet(trace,512)
    ok("tail_same_character_budget",tail["selected_quote_chars"]<=512 and tail["spans"][0]["text"]==trace[-512:])
    outer={"question":q,"trace":trace,"evaluation_only":{"gold":"hidden_a","correct":False}}
    poisoned=copy.deepcopy(outer);poisoned["evaluation_only"]={"gold":"hidden_b","correct":True}
    ok("hidden_poison_invariant",g.build_evidence_packet(outer["question"],outer["trace"])==g.build_evidence_packet(poisoned["question"],poisoned["trace"]))
    for i,args in enumerate([(outer,trace),(q,outer)]):
        try:g.build_evidence_packet(*args)
        except TypeError:ok("reject_dictionary_input_"+str(i),True)
        else:ok("reject_dictionary_input_"+str(i),False)
    shared_packet=g.build_evidence_packet(q,trace)
    ok("same_packet_render_reuse",g.render_evidence(shared_packet)==g.render_evidence(copy.deepcopy(shared_packet)))
    ok("render_not_certified","未经核验" in g.render_evidence(shared_packet))
    path=Path(__file__).resolve().parent
    report={"status":"PASS","passed":len(checks),"checks":checks,
            "source_sha256":hashlib.sha256((path/"goal_evidence.py").read_bytes()).hexdigest(),
            "scope":"Synthetic CPU interface/provenance/unknown controls only; no historical bank, Gold, model or GPU.",
            "implementation":"Question-only target hints + unverified candidate quote selection. No truth G, automatic semantic DAG or final map."}
    (path/"CPU_CONTRACT_CHECKS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="checks"},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
