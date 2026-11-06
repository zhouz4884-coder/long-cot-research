#!/usr/bin/env python3
"""Deterministic, CPU-only input adapter for shared-G prompt prototypes.

No model/tokenizer/GPU imports, network, training, inference or final-value
scoring. Actions accept ONLY the three visible fields. Program rules are parsed
from the original question, never from evaluator-only definitions or gold labels.
Only constant root expressions are evaluated: old derived y/z remain UNVERIFIED.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


METHODS = ("SharedGDirect", "SharedGCompact", "SharedGStepwise", "VersionFrame")
SELECTED6 = (
    "T1_support_before_fault_E", "T2_support_before_fault_E",
    "T1_support_before_fault_C", "T2_support_before_fault_C",
    "T1_support_before_fault_W", "T2_support_before_fault_W",
)
OLD_SHA = "6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27"
TOPOLOGY_SHA = "93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1"
SYSTEM = (
    "你要依据原题规则处理旧计算记录和修订记录。所给根值来自对原题常量根定义的精确核验；"
    "只有其列出的根值经过外部核验。旧派生值即使看起来正确也未被认证；模型新产生的推导仍是候选，"
    "不能把自称已验证当作外部认证。"
    "允许直接复用已核验的父值，不要求从头重算它们。数学定义以原题为准，输出样式按本方法要求。"
    "完成必要计算后，以“最终答案：整数”结束；不要仅因旧z存在就将它当作已认证结果。"
)
INSTRUCTIONS = {
    "SharedGDirect": "直接给出最终答案即可；可自行完成必要推导并复用已核验父值，旧派生值只是待核验线索。",
    "SharedGCompact": "紧凑展示必要代入或复合计算，再给最终答案。可复用已核验父值，不必重算全部根，也不强制只写一行。",
    "SharedGStepwise": (
        "使用充分的分步/自问自答求解：先识别目标还缺哪些未认证支持，按依赖只处理必要中间变量，"
        "可直接复用已核验父值和独立支持；允许复合计算或自行选择合理子问题，不要求机械地从根重做。"
        "不要遗漏合流父节点；完成后给最终答案。"
    ),
    "VersionFrame": (
        "依据下面版本工作帧组织候选推导：只把当前VERIFIED_ROOT根值当已认证父值；"
        "对goal所需的UNVERIFIED支持，沿ready计划提出计算。读父值时使用当前版本；"
        "dirty旧派生记录不能充当已认证结果。生成的派生值标为候选而非CERTIFIED；"
        "可复用独立根，不须从头重算。"
    ),
}
GENERATION = {
    "mode": "quality_first_draft_not_executed", "do_sample": False, "max_new_tokens": 512,
    "stopping": "normal model EOS; 512 is a safety cap, not a forced short answer window",
    "forced_y_prefix": False, "manual_tail_window": False,
    "budget_curve": "Separate later protocol; no equal-budget superiority claim in this draft.",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignments(text):
    return [(m[1], int(m[2])) for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([+-]?[0-9]+)\b", text)]


def expression_tree(expression):
    if len(expression)>256:
        raise ValueError("Expression length bound")
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
               ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.UAdd, ast.USub)
    nodes = list(ast.walk(tree))
    if len(nodes)>64 or any(not isinstance(n, allowed) for n in nodes):
        raise ValueError("Unsupported arithmetic grammar")
    for node in nodes:
        if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value)>10**9):
            raise ValueError("Noninteger or out-of-bound constant")
        if isinstance(node, ast.Name) and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
            raise ValueError("Invalid variable")
    return tree


def exact_constant_root(expression):
    """No environment argument: evaluating a derived expression is impossible."""
    tree = expression_tree(expression)
    if any(isinstance(n, ast.Name) for n in ast.walk(tree)):
        raise ValueError("Root verifier refuses derived-variable expressions")
    operations = 0
    def run(node):
        nonlocal operations
        if isinstance(node, ast.Constant): return node.value
        if isinstance(node, ast.UnaryOp):
            operations += 1
            value = run(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            operations += 1
            a,b = run(node.left),run(node.right)
            if isinstance(node.op,ast.Add): result=a+b
            elif isinstance(node.op,ast.Sub): result=a-b
            elif isinstance(node.op,ast.Mult): result=a*b
            elif isinstance(node.op,ast.FloorDiv) and b and a % b==0: result=a//b
            else: raise ValueError("Division is zero or not exact")
            if abs(result)>10**12: raise ValueError("Integer bound")
            return result
        raise ValueError("Unsupported root expression")
    return run(tree.body),operations


def parse_question(question):
    match = re.search(r"定义\s*(.+?)。",question)
    goal_match = re.search(r"求\s*([A-Za-z_][A-Za-z0-9_]*)",question)
    if match is None or goal_match is None:
        raise ValueError("Visible question outside the frozen definition/goal grammar")
    rules=[]
    for clause in re.split(r"[，,；;]",match[1]):
        found=re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*",clause)
        if found is None: raise ValueError("Malformed original definition")
        var,expr=found[1],found[2]
        tree=expression_tree(expr)
        parents=sorted({n.id for n in ast.walk(tree) if isinstance(n,ast.Name)})
        rules.append({"variable":var,"expression":expr,"parents":parents,
                      "origin":"original_visible_question_definition"})
    names=[r["variable"] for r in rules]
    if len(names)!=len(set(names)) or goal_match[1] not in names:
        raise ValueError("Repeated variable or unknown goal")
    known=set()
    for rule in rules:
        if not set(rule["parents"])<=known:
            raise ValueError("Rules not in a complete acyclic definition order")
        known.add(rule["variable"])
    return rules,goal_match[1]


def normalized_visible(raw):
    if "visible" in raw:
        source=raw["visible"]
        clauses=[{"variable":c["variable"],"text":c["text"]} for c in source["old_assignment_clauses"]]
        for clause in clauses:
            found=assignments(clause["text"])
            if len(found)!=1 or found[0][0]!=clause["variable"]:
                raise ValueError("Visible clause variable/literal mismatch")
        return {"question":source["question"],"old_assignment_clauses":clauses,"revision":source["revision"]}
    clauses=[]
    for text in re.split(r"[；，。;,\n]+",raw["old_branch"]):
        text=text.strip()
        if not text: continue
        found=assignments(text)
        if len(found)!=1: raise ValueError("Old development record outside clause grammar")
        clauses.append({"variable":found[0][0],"text":text})
    return {"question":raw["question"],"old_assignment_clauses":clauses,"revision":raw["revision"]}


def build_controller(visible):
    """Only this visible dictionary can influence G, root state or planning."""
    rules,goal=parse_question(visible["question"])
    graph={r["variable"]:r["parents"] for r in rules}
    order=[r["variable"] for r in rules]
    literal_claims={}
    for clause in visible["old_assignment_clauses"]:
        var,value=assignments(clause["text"])[0]
        if var in literal_claims: raise ValueError("Ambiguous repeated old-variable claim")
        literal_claims[var]=value
    roots={}; verifier_calls=[]
    for rule in rules:
        if rule["parents"]: continue
        value,count=exact_constant_root(rule["expression"])
        old=literal_claims.get(rule["variable"])
        roots[rule["variable"]]={"value":value,"version":0 if old==value else 1,
            "status":"VERIFIED_ROOT","expression":rule["expression"],
            "origin":"exact_constant_AST_from_original_question","old_literal":old,
            "old_literal_satisfies_definition":old==value,"semantic_only_no_KV_certification":True}
        verifier_calls.append({"variable":rule["variable"],"expression":rule["expression"],
                               "has_variable_reference":False,"arithmetic_operations":count})
    proposed=assignments(visible["revision"])
    if not proposed or set(v for v,_ in proposed)!={"x"} or "x" not in roots:
        gate={"action":"unknown","reason":"no_supported_single_root_revision",
              "proposal_installed":False,"proposal_variable":None,"proposal_value":None}
    else:
        new_value=proposed[-1][1]
        target=roots["x"]["value"]
        if new_value!=target:
            name,reason="rejected","proposal_violates_original_root_definition"
        elif literal_claims.get("x")==new_value:
            name,reason="nochange","same_root_literal_already_satisfies_definition"
        else:
            name,reason="accepted","proposal_matches_original_root_definition"
        gate={"action":name,"reason":reason,"proposal_installed":name=="accepted",
              "proposal_variable":"x","proposal_value":new_value,
              "root_evidence":{"expression":roots["x"]["expression"],"verified_value":target},
              "source":"visible_revision_and_original_question_only",
              "parse_policy":"Last explicit x literal in R; no Wait-word/group/gold trigger."}
    changed_roots=[v for v in roots if roots[v]["old_literal"]!=roots[v]["value"]]
    children={v:[] for v in order}
    for node,parents in graph.items():
        for parent in parents:children[parent].append(node)
    def descendants(root):
        reached=set(); stack=list(children[root])
        while stack:
            node=stack.pop()
            if node in reached: continue
            reached.add(node);stack.extend(children[node])
        return reached
    dirty=set().union(*(descendants(root) for root in changed_roots)) if changed_roots else set()
    goal_support={goal}; stack=[goal]
    while stack:
        for parent in graph[stack.pop()]:
            if parent not in goal_support:goal_support.add(parent);stack.append(parent)
    # Literal old derived values are retained as HISTORY, never promoted by equality with any gold value.
    derived={v:{"recorded_value":literal_claims.get(v),"certification_status":"UNVERIFIED",
                "dependency_status":"DIRTY" if v in dirty else "UNATTESTED",
                "dependency_versions":"UNATTESTED","invalidated_by_changed_roots":[r for r in changed_roots if v in descendants(r)]}
             for v in order if v not in roots}
    uncertified=[v for v in order if v in goal_support and v not in roots]
    scheduled=set(roots); pending=set(uncertified); layers=[]
    while pending:
        ready=[v for v in order if v in pending and set(graph[v])<=scheduled]
        if not ready: raise ValueError("Goal support cannot be scheduled from certified roots")
        layers.append(ready);scheduled.update(ready);pending.difference_update(ready)
    ready_now=layers[0] if layers else []
    plan=[{"layer":i,"nodes":[{"variable":v,"rule":next(r["expression"] for r in rules if r["variable"]==v),
                                "parents":graph[v],"operation":"REQUEST_MODEL_CANDIDATE_NOT_CERTIFICATION"} for v in nodes]}
          for i,nodes in enumerate(layers)]
    final_allowed=goal in roots and roots[goal]["status"]=="VERIFIED_ROOT"
    return {"rules":rules,"dependency_graph":graph,"goal":goal,"gate":gate,"current_roots":roots,
            "changed_from_old_literal_roots":changed_roots,"dirty_descendants":[v for v in order if v in dirty],
            "old_derived_records":derived,"goal_support":[v for v in order if v in goal_support],
            "goal_support_uncertified":uncertified,"ready_now":ready_now,"symbolic_ready_plan":plan,
            "deterministic_final_commit":{"allowed":final_allowed,"value":roots[goal]["value"] if final_allowed else None,
                "reason":"goal_is_a_verified_constant_root" if final_allowed else "goal_is_not_certified; old_z_is_not_an_authorized_commit"},
            "root_verifier_calls":verifier_calls,"derived_arithmetic_evaluations":0,
            "scope":"Symbolic input bookkeeping only; no Transformer state or model-output certification."}


def shared_evidence(visible,state):
    roots={v:{k:entry[k] for k in ("value","version","status","expression","old_literal","old_literal_satisfies_definition")}
           for v,entry in state["current_roots"].items()}
    gate={k:state["gate"][k] for k in ("action","reason","proposal_variable","proposal_value")}
    if "root_evidence" in state["gate"]:gate["root_evidence"]=state["gate"]["root_evidence"]
    return {"question":visible["question"],"old_assignment_clauses":visible["old_assignment_clauses"],
            "revision_record":visible["revision"],"original_rules":[{k:r[k] for k in ("variable","expression","parents")} for r in state["rules"]],
            "dependency_graph":state["dependency_graph"],"goal":state["goal"],"shared_G":gate,
            "certified_parent_values":roots,
            "old_derived_statuses":{v:{"certification_status":s["certification_status"],
                                      "dependency_status":s["dependency_status"],"dependency_versions":"UNATTESTED"}
                                    for v,s in state["old_derived_records"].items()},
            "permission":"允许复用全部VERIFIED_ROOT根值及原题规则，仅处理目标所需的未认证支持。"}


def prompts(visible,state):
    evidence=shared_evidence(visible,state)
    block="题目与已知证据：\n"+json.dumps(evidence,ensure_ascii=False,indent=2)+"\n"
    result={}
    for method in METHODS:
        instruction=INSTRUCTIONS[method]
        if method=="VersionFrame":
            frame={"current_roots":evidence["certified_parent_values"],"dirty_descendants":state["dirty_descendants"],
                   "goal_support_uncertified":state["goal_support_uncertified"],"ready_now":state["ready_now"],
                   "symbolic_ready_plan":[{"layer":p["layer"],"nodes":[{k:n[k] for k in ("variable","rule","parents")} for n in p["nodes"]]} for p in state["symbolic_ready_plan"]],
                   "old_derived_certification":"UNVERIFIED"}
            instruction+="\n版本工作帧：\n"+json.dumps(frame,ensure_ascii=False,indent=2)
            instruction+="\n这些是待评价的候选推导，按父依赖顺序给出数值代入式与候选最终答案；不需要拒绝作答。"
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":block+"\n输出要求：\n"+instruction}]
        result[method]={"messages":messages,"shared_evidence_sha256":digest(evidence),
                        "shared_block_sha256":hashlib.sha256(block.encode()).hexdigest(),
                        "messages_sha256":digest(messages),"generation_policy":GENERATION,
                        "prompt_characters":sum(len(m["content"]) for m in messages),
                        "tokenizer_tokens":"not measured; no tokenizer/model loaded"}
    return evidence,result


def normalize(raw,source_set):
    visible=normalized_visible(raw)
    state=build_controller(visible)
    evidence,draft=prompts(visible,state)
    if "visible" in raw:
        hidden=copy.deepcopy(raw.get("evaluator_only",{}))
        hidden["source_fixed_mask_rules_not_used"]=copy.deepcopy(raw.get("fixed_mask_rules",{}))
    else:
        hidden={k:copy.deepcopy(v) for k,v in raw.items() if k not in {"case_id","question","old_branch","revision"}}
    return {"schema_version":"shared_G_version_input_v1","case_id":raw["case_id"],"source_set":source_set,
            "visible":visible,"controller":state,"shared_evidence":evidence,"model_inputs":draft,
            "hidden_evaluation":hidden,"scope":"Input draft only; never serialize this whole record into a model prompt."}


def render_prompt(item,method=None):
    """Stable runner API. Returns only messages plus non-prompt provenance."""
    if item.get("kind") in {"P_only","P_plus_R"}:
        if method is not None: raise ValueError("Basis items use method=None")
        return {"messages":copy.deepcopy(item["messages"]),"provenance":copy.deepcopy(item["provenance"])}
    if method not in METHODS: raise ValueError("Unknown method")
    entry=item["model_inputs"][method]
    return {"messages":copy.deepcopy(entry["messages"]),"provenance":{
        "method":method,"case_id_not_prompted":item["case_id"],
        "messages_sha256":entry["messages_sha256"],"shared_evidence_sha256":entry["shared_evidence_sha256"],
        "shared_block_sha256":entry["shared_block_sha256"],"generation_policy":GENERATION,
        "input_fact_source":"Original visible question/old clauses/R; exact constant-root G shared by all methods.",
        "old_derived_status":"UNVERIFIED","one_shot_frame_only":True,
        "no_runtime_output_checking_or_certified_final_submission":True}}


def prepare_dataset(topology_path):
    """Stable runner API: six fixed before-fault cases plus 2P/4PR basis.

    Loads no old16 data. Selection is frozen by ID before model outputs; G still
    depends solely on visible text, never on ID/group/gold.
    """
    source=Path(topology_path)
    if file_sha(source)!=TOPOLOGY_SHA:raise ValueError("Topology-v2 source hash mismatch")
    raw=json.loads(source.read_text(encoding="utf-8-sig"))["cases"]
    lookup={r["case_id"]:r for r in raw}
    if len(lookup)!=12 or not set(SELECTED6)<=set(lookup):raise ValueError("Frozen topology-v2 pool expected")
    cases=[normalize(lookup[cid],"selected_quality_before_fault6") for cid in SELECTED6]
    # Basis is defined only by visible P or exact visible(P,R); never by G/B/validity.
    unique_questions={}
    unique_pr={}
    for case in cases:
        v=case["visible"]
        unique_questions.setdefault(v["question"],[]).append(case)
        unique_pr.setdefault((v["question"],v["revision"]),[]).append(case)
    basis=[];dedupe_map={cid:{} for cid in SELECTED6}
    system=("依据题目原始数学定义求解。若给出额外复核记录，不预设其正确。"
            "可使用必要计算，以“最终答案：整数”结束。")
    for kind,groups in (("P_only",unique_questions),("P_plus_R",unique_pr)):
        for number,(key,members) in enumerate(groups.items(),1):
            question=key if kind=="P_only" else key[0]
            revision=None if kind=="P_only" else key[1]
            content="原题：\n"+question
            if revision is not None:content+="\n额外复核记录（待核验，不预设正确）：\n"+revision
            messages=[{"role":"system","content":system},{"role":"user","content":content}]
            basis_id=("P" if kind=="P_only" else "PR")+f"_{number:02d}"
            hidden=copy.deepcopy(members[0]["hidden_evaluation"])
            basis.append({"basis_id":basis_id,"kind":kind,"visible":{"question":question,"revision":revision},
                "messages":messages,"provenance":{"basis_id":basis_id,"kind":kind,"messages_sha256":digest(messages),
                    "linked_case_ids_not_prompted":[c["case_id"] for c in members],
                    "contains_G_or_B":False,"revision_is_actual_visible_record_not_assumed_correct":True,
                    "generation_policy":GENERATION},"hidden_evaluation":hidden})
            for member in members:dedupe_map[member["case_id"]][kind]=basis_id
    if len(basis)!=6 or sum(b["kind"]=="P_only" for b in basis)!=2 or sum(b["kind"]=="P_plus_R" for b in basis)!=4:
        raise ValueError("Frozen six-basis cardinalities failed")
    input_payload={"selected_ids":list(SELECTED6),"methods":list(METHODS),"source_sha256":TOPOLOGY_SHA,
        "main_messages":{c["case_id"]:{m:c["model_inputs"][m]["messages_sha256"] for m in METHODS} for c in cases},
        "basis_messages":{b["basis_id"]:b["provenance"]["messages_sha256"] for b in basis},
        "dedupe_map":dedupe_map,"generation_policy":GENERATION}
    return {"schema_version":"phase5_quality_selected6_v1","cases":cases,"basis":basis,"dedupe_map":dedupe_map,
        "hash":digest(input_payload),"source_sha256":TOPOLOGY_SHA,"adapter_source_sha256":file_sha(__file__),
        "selected_order":list(SELECTED6),"methods":list(METHODS),"primary_output_count":24,"basis_output_count":6,
        "expected_model_outputs":30,"old16_loaded_for_this_dataset":False,"generation_policy_draft":GENERATION,
        "scope":"Two programs x E/C/W before-fault; exploratory toy, not six independent unseen tasks.",
        "one_shot_frame_only":True,"no_runtime_model_proposal_validation_implemented":True}


def cpu_checks(old_raw,top_raw,normalized):
    checks=[]
    def check(name,passed,details=None):
        checks.append({"check":name,"passed":bool(passed),"details":details})
    check("source_counts_16_dev_12_formal",len(old_raw)==16 and len(top_raw)==12)
    for raw,record in zip(old_raw+top_raw,normalized):
        cid=record["case_id"];s=record["controller"]
        check(cid+":only_constant_roots_evaluated",s["derived_arithmetic_evaluations"]==0 and
              all(not c["has_variable_reference"] for c in s["root_verifier_calls"]))
        check(cid+":old_y_z_unverified",all(v["certification_status"]=="UNVERIFIED" for v in s["old_derived_records"].values()))
        check(cid+":no_uncertified_final_commit",not s["deterministic_final_commit"]["allowed"] and s["deterministic_final_commit"]["value"] is None)
        check(cid+":shared_evidence_identical_across_methods",len({p["shared_evidence_sha256"] for p in record["model_inputs"].values()})==1 and
              len({p["shared_block_sha256"] for p in record["model_inputs"].values()})==1)
        # Strong metamorphic test: remove/poison every hidden field, including all gold/labels/hidden definitions.
        if "visible" in raw:
            altered={"case_id":raw["case_id"],"visible":copy.deepcopy(raw["visible"]),
                     "evaluator_only":{"group":"WRONG_LABEL","required_final_value":987654321,"definitions":[["x","999"]]}}
        else:
            altered={k:copy.deepcopy(raw[k]) for k in ("case_id","question","old_branch","revision")}
            altered.update(group="WRONG_LABEL",required_final_value=987654321,definitions=[{"variable":"x","expression":"999"}],oracle_values={"x":999})
        other=normalize(altered,record["source_set"])
        check(cid+":hidden_poison_cannot_change_action_or_prompt",other["controller"]==s and other["model_inputs"]==record["model_inputs"])
        # Gold equality never promotes an old dependent value: arbitrary old y/z poison keeps the plan and Gate.
        changed=copy.deepcopy(record["visible"])
        for clause in changed["old_assignment_clauses"]:
            if clause["variable"] not in s["current_roots"]:
                clause["text"]=f"{clause['variable']}=987654321；"
        poisoned=build_controller(changed)
        check(cid+":derived_literal_poison_does_not_certify_or_control_G",poisoned["gate"]==s["gate"] and
              poisoned["current_roots"]==s["current_roots"] and poisoned["ready_now"]==s["ready_now"] and
              all(r["certification_status"]=="UNVERIFIED" for r in poisoned["old_derived_records"].values()))
        # Metadata consistency is a check AFTER construction, not an input to construction.
        original_defs=raw["evaluator_only"]["definitions"] if "visible" in raw else [[d["variable"],d["expression"]] for d in raw["definitions"]]
        parsed=[[r["variable"],r["expression"]] for r in s["rules"]]
        check(cid+":visible_rule_parse_matches_source_metadata_afterward",parsed==original_defs)
    v=copy.deepcopy(normalized[0]["visible"])
    v["revision"]="复核记录尚未给出数值。"
    unknown=build_controller(v)
    check("unknown_R_is_not_accepted",unknown["gate"]["action"]=="unknown" and not unknown["gate"]["proposal_installed"])
    v["revision"]="复核记录：y=123。"
    check("unsupported_derived_revision_is_unknown",build_controller(v)["gate"]["action"]=="unknown")
    for v in ("3*x+2","x*x","y+r"):
        try:exact_constant_root(v);refused=False
        except ValueError:refused=True
        check("root_verifier_refuses_derived:"+v,refused)
    before_after={}
    for record in normalized[16:]:
        hidden=record["hidden_evaluation"]
        key=(hidden["program_id"],hidden["group"])
        before_after.setdefault(key,[]).append(record["controller"])
    check("support_before_after_same_semantic_controller",all(len(pair)==2 and pair[0]==pair[1] for pair in before_after.values()),
          "Old clause order differs in visible prompts; semantic roots/G/dirty/plan are independent of placement. No KV-state equivalence claim.")
    actual_groups=Counter(r["controller"]["gate"]["action"] for r in normalized)
    return {"status":"CPU_ADAPTER_PASS" if all(c["passed"] for c in checks) else "CPU_ADAPTER_FAIL",
            "checks":checks,"check_count":len(checks),"passed_count":sum(c["passed"] for c in checks),
            "gate_action_counts_all28":dict(actual_groups),
            "constant_root_fact_count":sum(len(r["controller"]["current_roots"]) for r in normalized),
            "derived_old_records_unverified_count":sum(len(r["controller"]["old_derived_records"]) for r in normalized),
            "model_calls":0,"GPU_calls":0,"derived_value_evaluations":0,
            "warning":"CPU/metamorphic interface results only; no accuracy, natural-trigger or prototype superiority evidence."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-cases",type=Path,required=True)
    parser.add_argument("--topology-cases",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if file_sha(args.old_cases)!=OLD_SHA or file_sha(args.topology_cases)!=TOPOLOGY_SHA:
        raise ValueError("Frozen source-file hash mismatch; no silent migration")
    old=json.loads(args.old_cases.read_text(encoding="utf-8-sig"))["cases"]
    topo=json.loads(args.topology_cases.read_text(encoding="utf-8-sig"))["cases"]
    records=[normalize(raw,"development_old16_not_unseen") for raw in old]+[normalize(raw,"initial_exploratory_topology12") for raw in topo]
    tests=cpu_checks(old,topo,records)
    selected=prepare_dataset(args.topology_cases)
    extra=[
        {"check":"selected6_order_and_old16_not_loaded","passed":selected["selected_order"]==list(SELECTED6) and not selected["old16_loaded_for_this_dataset"]},
        {"check":"basis_2P_4PR_no_G_B","passed":len(selected["basis"])==6 and all(not b["provenance"]["contains_G_or_B"] for b in selected["basis"])},
        {"check":"all_render_APIs_match_draft_messages","passed":all(render_prompt(c,m)["messages"]==c["model_inputs"][m]["messages"] for c in selected["cases"] for m in METHODS)},
        {"check":"basis_render_API_gold_blind","passed":all(render_prompt(b,None)["messages"]==b["messages"] and "VERIFIED_ROOT" not in canonical(b["messages"]) and "old_assignment_clauses" not in canonical(b["messages"]) for b in selected["basis"])},
        {"check":"model_messages_omit_experiment_meta_language","passed":all(not any(phrase in canonical(c["model_inputs"][m]["messages"]) for phrase in ("四种方法","所有方法","逐字相同","无额外数值答案","semantic_only_no_KV_certification","one_shot_frame","deterministic_final_commit","parse_policy")) for c in selected["cases"] for m in METHODS)},
        {"check":"VersionFrame_requests_candidates_without_refusal","passed":all(c["model_inputs"]["VersionFrame"]["messages"][-1]["content"].endswith("这些是待评价的候选推导，按父依赖顺序给出数值代入式与候选最终答案；不需要拒绝作答。") and not c["controller"]["deterministic_final_commit"]["allowed"] for c in selected["cases"])}]
    tests["checks"].extend(extra);tests["check_count"]+=len(extra);tests["passed_count"]+=sum(c["passed"] for c in extra)
    tests["status"]="CPU_ADAPTER_PASS" if all(c["passed"] for c in tests["checks"]) else "CPU_ADAPTER_FAIL"
    args.output.mkdir(parents=True,exist_ok=True)
    common={"schema_version":"phase5_cpu_input_adapter_v1","date":"2026-11-06","adapter_source_sha256":file_sha(__file__),
            "source_files":{"development_old16":{"path":str(args.old_cases.resolve()),"sha256":OLD_SHA},
                            "topology_v2":{"path":str(args.topology_cases.resolve()),"sha256":TOPOLOGY_SHA}},
            "algorithm_input_whitelist":["visible.question","visible.old_assignment_clauses[].variable/text","visible.revision"],
            "root_verification":"Only constant AST expressions parsed from visible original question; no hidden definitions/group/final gold for action.",
            "derived_status_contract":"Old y/z remain UNVERIFIED in E/C/W; model proposals are not external certification.",
            "methods":list(METHODS),"generation_policy_draft":GENERATION,
            "formal_initial_selection":"Only six fixed before-fault states T1E,T2E,T1C,T2C,T1W,T2W; 24 main + 6 basis outputs. Two programs, exploratory toy.",
            "topology12_role":"Full v2 design pool retained separately; after-fault states not selected in this quality round.",
            "old16_use":"Development and interface validation only; never pooled as unseen evaluation.",
            "source_scope":"Exact AST grammar and root verifier are privileged toy tools shared by all methods; no natural parser validation.",
            "cache_scope":"Logical versions/dirty nodes are not certificates for Transformer KV consistency; no cache operation performed.",
            "no_new_descendant_numeric_fact_injection":True,"old_literals_may_equal_gold":"Visible old literals are preserved, never removed merely because they equal hidden answers."}
    def write(name,obj):
        (args.output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    write("normalized_cases_all28.json",{**common,"cases":records})
    write("model_inputs_initial12_draft.json",{**common,"status":"SUPERSEDED_SELECTION_DESIGN_POOL_ONLY","case_count":12,"prompt_count":48,
          "cases":[{"case_id":r["case_id"],"source_set":r["source_set"],"methods":r["model_inputs"]} for r in records[16:]]})
    write("model_inputs_selected6_draft.json",selected)
    write("model_inputs_development16_draft.json",{**common,"case_count":16,"prompt_count":64,
          "cases":[{"case_id":r["case_id"],"source_set":r["source_set"],"methods":r["model_inputs"]} for r in records[:16]]})
    write("cpu_adapter_checks.json",{**common,**tests})
    lines=["# Phase5 CPU输入adapter检查", "", "本轮只准备输入和验证权限边界，没有模型/GPU/远程/训练。", "",
           f"状态：{tests['status']}；{tests['passed_count']}/{tests['check_count']}检查通过。",
           f"Gate（28开发/设计状态汇总）：{tests['gate_action_counts_all28']}。", "",
           "初轮模型输入只选新6个before-fault状态（T1E,T2E,T1C,T2C,T1W,T2W），4方法24主输出；另2个P-only和4个unique(P,R)共6个basis。全部12状态只作设计池保留；旧16单列开发数据。", "",
           "所有方法共享原题/规则/依赖、旧clause、R、同一G及核验根值；允许SelfAsk复用已核验父值。",
           "只核验常量根x和独立r，旧y/z全部UNVERIFIED；C/W也不能由金标正确而自动certify或提交旧z。",
           "VersionFrame的版本、dirty、goal未认证支持与ready计划只由共享可见事实推导，没有新增正确y/z数字。",
           "质量优先draft为max_new_tokens512、正常EOS、无强制y前缀/尾窗；尚未执行，token数/耗时/效果未知。", "",
           "主要检查：隐藏字段投毒不改动作或prompt；旧y/z可见值投毒不让其被认证；before/after的语义计划一致；派生表达式被根校验器拒绝。", "",
           "逻辑独立r不等于KV独立；本adapter没有神经状态恢复或新模型数字认证能力。"]
    (args.output/"CPU_ADAPTER_CHECKS_ZH.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"status":tests["status"],"checks":tests["check_count"],"passed":tests["passed_count"],
                      "gate_actions":tests["gate_action_counts_all28"],"selected_main_prompts":24,"basis_prompts":6,"development_prompts":64,
                      "model_calls":0,"derived_value_evaluations":0},ensure_ascii=True))
    if tests["status"]!="CPU_ADAPTER_PASS":raise SystemExit(2)


if __name__=="__main__":main()
