"""Meaningful CPU contracts before any new model outputs; no GPU/credentials."""
import copy
import hashlib
import itertools
import json
from pathlib import Path
import random
import time

import boundary_core as core

OUT = Path(__file__).resolve().parent


def main():
    started = time.monotonic(); checks = []
    def check(name, condition):
        if not condition: raise AssertionError(name)
        checks.append(name)
    positives = [("最终答案：80",80), ("最终答案：-8。",-8), (r"\boxed{80}",80),
                 ('{"final_answer":80}',80), ('{"candidate_derivations":[{"value":56}],"final_answer":80}',80),
                 ('```json\n{"final_answer":80}\n```',80), ("80。",80), ("−8",-8),
                 ("步骤x=3。\n最终答案：80",80), (r"最终答案：80。\boxed{80}",80),
                 ("**最终答案：80**",80), (r"$\boxed{80}$",80), (r"\[\boxed{80}\]",80)]
    negatives = ['{"final_answer":true}', '{"final_answer":80,"final_answer":81}', '{"final_answer":',
                 '{"final_answer":"80"}', '{"final_answer":80.0}', '{"candidate":{"final_answer":80}}',
                 '最后算了80，原来是81', '最终答案：80或者81', '最终答案：80\n最终答案：81',
                 r'\boxed{80}\boxed{81}', '最终答案：80.5', '{"final_answer":80}junk', '80\n81',
                 '最终答案：80\n待续', '[{"final_answer":80}]', r'\boxed{80']
    for i,(text,value) in enumerate(positives): check(f"parse_positive_{i}",core.extract_integer(text)["value"]==value)
    for i,text in enumerate(negatives): check(f"parse_negative_{i}",core.extract_integer(text)["value"] is None)
    rng = random.Random(20261106)
    for i in range(600):
        rules = {"n0": str(rng.randint(-9,9))}
        for k in range(1,rng.randint(3,17)):
            a,b=rng.randrange(k),rng.randrange(k)
            rules[f"n{k}"]=f"n{a}+n{b}-{rng.randint(0,9)}"
        values=core.cold(rules);keys=list(rules);goal=keys[-1]
        certs={v:{"value":values[v]} for v in keys[:-1] if rng.random()<0.4}
        view=core.project(rules,certs,goal);new=dict(view["boundary_values"])
        for v,expr in view["rules"].items(): new[v]=core.evaluate(expr,new)
        check(f"deterministic_projection_cold_equal_{i}",new[goal]==values[goal])
    data=core.build_dataset();jobs=[]
    for case in data["cases"]:
        state=core.controller(case["visible"]);group=case["evaluation_only"]["group"]
        check("G_"+group,state["G"]=={"E":"accepted","C":"nochange","W":"rejected"}[group])
        check("no_target_eval_"+group,state["target_branch_evaluations"]==0 and len(state["checked_operations"])==13)
        check("independent_support_"+group,state["projection"]["boundary_values"]=={"r":153,"x":23})
        check("pending7_"+group,state["projection"]["pending"]==["a","b","c","d","e","f","z"])
        check("goal_uncertified_"+group,"z" not in state["certificates"])
        if group!="E": check("clean_not_certified_"+group,not state["dirty_old_slots"] and bool(state["projection"]["pending"]))
        # Independently form a backwards DAG slice and compare the prompt, so an
        # ordinary equivalent cut is not presented as a different new algorithm.
        todo=[case["visible"]["goal"]];plain=set();boundary=set()
        while todo:
            v=todo.pop()
            if v in state["certificates"]:boundary.add(v);continue
            if v not in plain:plain.add(v);todo.extend(core.parents(case["visible"]["rules"][v]))
        porder=core.ordered(case["visible"]["rules"],plain)
        simple={"pending":porder,"boundary":sorted(boundary),"rules":{v:case["visible"]["rules"][v] for v in porder},
                "boundary_values":{v:state["certificates"][v]["value"] for v in sorted(boundary)},"goal":"z"}
        check("ordinary_slice_same_prompt_"+group,core.projected_text(simple)==core.projected_text(state["projection"]))
        for method in ("SharedGFull","BoundaryProjection"):
            messages=core.render(case["visible"],method,state)
            jobs.append({"job_id":case["case_id"]+"__"+method,"case_id":case["case_id"],"method":method,
                         "messages":messages,"messages_hash":core.digest(messages),"G_state_hash":core.digest(state)})
        poisoned=copy.deepcopy(case);poisoned["evaluation_only"]={"group":"ALIEN","gold":999999,"old_z":999999}
        check("hidden_poison_"+group,core.controller(poisoned["visible"])==state)
        for field in ("gold","evaluation_only","LongR_","dirty_old_slots","certificates","CANDIDATE"):
            check("no_private_field_"+group+"_"+field,field not in json.dumps(core.render(case["visible"],"BoundaryProjection",state),ensure_ascii=False))
    for case in data["cases"]:
        msg=core.render(case["visible"],"RawFull")
        jobs.append({"job_id":case["case_id"]+"__RawFull","case_id":case["case_id"],"method":"RawFull",
                     "messages":msg,"messages_hash":core.digest(msg),"G_state_hash":None})
    msg=core.render(data["cases"][0]["visible"],"RestartP")
    jobs.append({"job_id":"P_only_unique","case_id":None,"method":"RestartP","messages":msg,"messages_hash":core.digest(msg),"G_state_hash":None})
    check("RestartP_deduplicated",all(core.render(c["visible"],"RestartP")==msg for c in data["cases"]))
    # Fault injection: changing a proved rule or identity invalidates certificates.
    state=core.controller(data["cases"][0]["visible"])
    for kind in ("rule", "scope"):
        rr=copy.deepcopy(data["cases"][0]["visible"]["rules"]);cc=copy.deepcopy(state["certificates"])
        if kind=="rule":rr["s3"]="s2-12"
        else:cc["r"]["scope"]="x"
        try:core.verify_certificate_rules(rr,cc)
        except ValueError: check("reject_certificate_"+kind,True)
        else:check("reject_certificate_"+kind,False)
    altered=copy.deepcopy(data["cases"][0]["visible"]);altered["goal"]="f"
    try:core.render(altered,"BoundaryProjection",state)
    except ValueError:check("reject_stale_goal_projection",True)
    else:check("reject_stale_goal_projection",False)
    altered=copy.deepcopy(state);altered["projection"]["boundary_values"]["r"]+=1
    try:core.render(data["cases"][0]["visible"],"BoundaryProjection",altered)
    except ValueError:check("reject_projection_value_mismatch",True)
    else:check("reject_projection_value_mismatch",False)
    bad=copy.deepcopy(data["cases"][0]["visible"]);bad["old_values"]["s8"]+=1
    try:core.controller(bad)
    except ValueError:check("reject_wrong_independent_history",True)
    else:check("reject_wrong_independent_history",False)
    for rules in ({"x":"y+1","y":"x+1"},{"x":"h+1"},{"x":"abs(-1)"}):
        try:core.ancestors(rules,"x")
        except (ValueError,KeyError):check("reject_invalid_graph_"+core.digest(rules)[:8],True)
        else:check("reject_invalid_graph",False)
    # Exact witness for the real circular-seating over-doubt example, not model accuracy.
    count=0
    for perm in itertools.permutations(range(1,8)):
        seats=(0,)+perm
        if any(set(seats[(start+i)%8] for i in range(3))=={0,1,2} for start in range(8)):count+=1
    check("natural_rank39_exact720",count==720)
    check("natural_rank78_exact_probability",sum(k%3==0 for k in range(1,101))==33)
    from sympy import Symbol, rem, sqrt, simplify, sin, pi, Rational
    x=Symbol("x")
    check("natural_rank88_correct_candidate",rem(x**9+6*x**6+31*x**3-1,x**3-3*x**2+4*x-1,x)==0)
    check("natural_rank32_target",simplify(((sqrt(5)-1)/4)**2*(1+(sqrt(5)-1)/4))==Rational(1,8))
    check("natural_rank32_root",simplify(sin(pi/10)-(sqrt(5)-1)/4)==0)
    for filename,obj in [("CONTROL_DATASET.json",data),("PREPARED_JOBS.json",jobs)]:
        (OUT/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    result={"status":"PASS","checks":checks,"passed":len(checks),"seconds":time.monotonic()-started,
            "scope":"CPU deterministic semantics/interface contracts and exact natural witnesses; no model/GPU quality result.",
            "independent_programs":1,"groups":["E","C","W"],"planned_outputs":len(jobs),
            "order":[j["job_id"] for j in jobs],"source_sha256":hashlib.sha256((OUT/"boundary_core.py").read_bytes()).hexdigest(),
            "dataset_sha256":hashlib.sha256((OUT/"CONTROL_DATASET.json").read_bytes()).hexdigest(),
            "jobs_sha256":hashlib.sha256((OUT/"PREPARED_JOBS.json").read_bytes()).hexdigest()}
    (OUT/"CPU_PRECHECK.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("checks","order")},indent=2))


if __name__=="__main__":main()
