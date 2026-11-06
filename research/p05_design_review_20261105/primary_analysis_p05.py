"""Independent, read-only CPU analysis of this turn's five-arm P0.5 run.

No default run directory: results are read only after explicitly supplied.
Raw run files are never modified. No old-P0 scores or model execution are used.
"""

from __future__ import annotations
import argparse
import ast
import collections
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import sys

HERE = Path(__file__).parent
EXTRACTOR_SHA = "c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed"
CASES_SHA = "6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27"
CATALOG_SHA = "84f1f15d5faa7c34e0b8a100bf6a6fcbfa53acfd4f055c32f529361cbe564c9b"
ARMS = ("FullDirect", "FullOneLine", "WholeEarlyDirect", "WholeEarlyOneLine", "WholeLateOneLine")
GROUPS = {"E": "falsified_old_correct_revision", "C": "correct_old_no_error_control", "W": "wait_wrong_revision_control"}
PAIRS = (("FullDirect", "FullOneLine"), ("WholeEarlyDirect", "WholeEarlyOneLine"),
         ("FullDirect", "WholeEarlyDirect"), ("FullOneLine", "WholeEarlyOneLine"),
         ("FullOneLine", "WholeLateOneLine"), ("WholeLateOneLine", "WholeEarlyOneLine"))
PROBE_PAIRS = (("FullDirect", "WholeEarlyDirect"), ("FullOneLine", "WholeEarlyOneLine"),
               ("FullOneLine", "WholeLateOneLine"), ("WholeLateOneLine", "WholeEarlyOneLine"))


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest_ids(ids): return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def near(a,b,tol=1e-6): return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tol
def md(value): return str(value).replace("|", "\\|").replace("`", "\\u0060").replace("\n", "\\n")
def raw_json(value): return md(json.dumps(value, ensure_ascii=False))


def frozen_extractor(path):
    if sha(path) != EXTRACTOR_SHA: raise ValueError("Frozen extractor SHA mismatch")
    spec=importlib.util.spec_from_file_location("p05_fixed_answer_extractor",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.extract_answer


def exact(expression, env):
    def visit(n):
        if isinstance(n,ast.Constant) and type(n.value) is int:return n.value
        if isinstance(n,ast.Name):return env[n.id]
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.USub):return -visit(n.operand)
        if isinstance(n,ast.BinOp):
            a,b=visit(n.left),visit(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.Mult):return a*b
            if isinstance(n.op,ast.FloorDiv) and b and a%b==0:return a//b
        raise ValueError("Unsupported exact oracle expression")
    return visit(ast.parse(expression,mode="eval").body)


def oracle_values(case, override=None):
    env={}
    for d in case["definitions"]:
        env[d["variable"]]=override if d["variable"]=="x" and override is not None else exact(d["expression"],env)
    return env


def expected_roles(case):
    truth=oracle_values(case);old=oracle_values(case,case["old_root_value"]);rev=oracle_values(case,case["revision_root_value"])
    expr={d["variable"]:d["expression"] for d in case["definitions"]}
    return {"z":{"trusted_final":truth["z"],"old_final":old["z"],"revision_consistent_final":rev["z"],
                 "skip_signature":exact(expr["z"],{"x":rev["x"],"y":rev["x"]})},
            "y":{"trusted_y":truth["y"],"old_y":old["y"],"revision_consistent_y":rev["y"],"root_misbind":rev["x"]}}


def paired(items,left,right):
    both=[r for r in items if left in r["arms"] and right in r["arms"]]
    gain=[r["case_id"] for r in both if not r["arms"][left]["correct"] and r["arms"][right]["correct"]]
    loss=[r["case_id"] for r in both if r["arms"][left]["correct"] and not r["arms"][right]["correct"]]
    return {"n":len(both),"left_correct":sum(r["arms"][left]["correct"] for r in both),
            "right_correct":sum(r["arms"][right]["correct"] for r in both),
            "repair_ids":gain,"harm_ids":loss,"net_right_minus_left":len(gain)-len(loss),
            "both_correct_ids":[r["case_id"] for r in both if r["arms"][left]["correct"] and r["arms"][right]["correct"]],
            "both_incorrect_ids":[r["case_id"] for r in both if not r["arms"][left]["correct"] and not r["arms"][right]["correct"]],
            "repair_from_unparsed_ids":[r["case_id"] for r in both if r["case_id"] in gain and r["arms"][left]["extraction"]["value"] is None],
            "harm_to_unparsed_ids":[r["case_id"] for r in both if r["case_id"] in loss and r["arms"][right]["extraction"]["value"] is None]}


def interaction(items):
    rows=[]
    for r in items:
        c=lambda a:int(r["arms"][a]["correct"])
        rows.append({"case_id":r["case_id"],"contrast":c("WholeEarlyOneLine")-c("WholeEarlyDirect")-c("FullOneLine")+c("FullDirect")})
    n=len(rows)
    return {"n":n,"sum_contrast":sum(r["contrast"] for r in rows),
            "mean_accuracy_contrast":sum(r["contrast"] for r in rows)/n if n else None,
            "per_case":rows,"interpretation":"Descriptive within-run strategy interaction; no orthogonality/induction/causal independence inference"}


def audit_probe(cid,arm,family,probe,core,roles,protocol,issues):
    loc=f"{cid}/{arm}/{family}"
    def check(ok,message):
        if not ok:issues.append({"location":loc,"issue":message})
    rendered=probe.get("rendering",{});spec=rendered.get("spec",{});scores=probe.get("scores",{})
    expected_scaffold=protocol["readout"]["Y_probe_scaffold" if family=="y" else "Z_probe_scaffold"]
    check(spec.get("family")==family,"Probe family does not match its rendering")
    check(spec.get("assistant_scaffold")==expected_scaffold,"Forced probe scaffold differs from frozen protocol")
    check(probe.get("forced_before_generation_query") is True,"Probe must be a pre-generation-state forced query")
    check(probe.get("not_a_natural_intermediate_belief") is True,"Missing non-natural-belief boundary")
    check(scores.get("used_to_choose_free_output") is False,"Probe selection isolation flag fails")
    check(scores.get("roles_evaluator_only")==roles,"Recorded candidate roles differ from independent integer oracle")
    before_after=scores.get("readout_cache_length_before_after",[])
    check(len(before_after)==2 and before_after[0]==before_after[1],"Probe checkpoint cache changed")
    lookup={};candidates=[]
    for candidate in scores.get("unique_candidates",[]):
        ids=candidate.get("token_ids",[]);terms=candidate.get("token_logP",[]);aliases=candidate.get("role_aliases",[])
        check(bool(ids) and len(ids)==len(terms),"Candidate conditional-token count mismatch")
        finite=all(type(x) in (int,float) and math.isfinite(x) for x in terms)
        check(finite,"Nonfinite candidate token logP")
        recomputed=math.fsum(terms) if finite else None
        check(near(recomputed,candidate.get("logP")),"Full logP does not sum recorded conditionals")
        check(bool(ids) and candidate.get("first_token_id")==ids[0],"First token ID mismatch")
        check(bool(terms) and near(candidate.get("first_token_logP"),terms[0]),"First-token marginal mismatch")
        check(candidate.get("terminating_string")=="\n","Candidate terminator is not frozen newline")
        check(candidate.get("length_normalization")=="none","Unexpected length normalization")
        for role in aliases:
            check(role in roles and candidate.get("continuation")==str(roles.get(role))+"\n","Role continuation mismatch")
            check(role not in lookup,"Role appears in multiple candidates")
            lookup[role]=candidate
        candidates.append({**candidate,"logP_sum_recomputed_cpu_float64":recomputed,
                           "recomputation_scope":"Sum of saved autoregressive conditionals; later-token logits not regenerated"})
    check(set(lookup)==set(roles),"Missing/extra role aliases")
    check(len({tuple(c.get("token_ids",[])) for c in candidates})==len(candidates),"Identical token candidates not deduplicated")
    margins=[]
    role_names=list(roles)
    for i,left in enumerate(role_names):
        for right in role_names[i+1:]:
            if left not in lookup or right not in lookup:continue
            a,b=lookup[left],lookup[right];alias=a["token_ids"]==b["token_ids"];collision=a["first_token_id"]==b["first_token_id"]
            margins.append({"left":left,"right":right,"same_full_candidate":alias,
                            "full_log_odds_left_minus_right":None if alias else a["logP"]-b["logP"],
                            "same_first_token":collision,
                            "first_token_log_odds_raw":a["first_token_logP"]-b["first_token_logP"],
                            "first_token_log_odds_interpretable":None if collision else a["first_token_logP"]-b["first_token_logP"]})
    stored={(x["left"],x["right"]):x for x in scores.get("pairwise_role_margins",[])}
    for margin in margins:
        old=stored.get((margin["left"],margin["right"]),{})
        for key,value in margin.items():
            if key in ("left","right"):continue
            check(old.get(key)==value if value is None or type(value) is bool else near(old.get(key),value),f"Stored role margin mismatch: {key}")
    context={"spec":spec,"readout_token_ids":rendered.get("ids",[]),"readout_position_ids":rendered.get("position_ids",[]),
             "core_prefix_ids_sha256":digest_ids(core.get("prefix_ids",[])),
             "readout_ids_sha256":digest_ids(rendered.get("ids",[])),
             "context_note":"Auxiliary query on pre-free-generation state, executed after primary. Not generated Y or OneLine intermediate belief."}
    context["context_id"]=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {"case_id":cid,"arm":arm,"family":family,"context":context,"roles":roles,
            "unique_candidates":candidates,"pairwise_role_margins_recomputed":margins,
            "role_logP":{r:lookup[r]["logP"] for r in roles if r in lookup},
            "recorded_timing":probe.get("timing"),"readout_additional_forward_calls":probe.get("readout_additional_forward_calls")}


def analyze(args):
    run=args.run_dir.resolve();out=args.output_dir.resolve()
    if run==out or run in out.parents:raise ValueError("Analysis outputs must be outside original run directory")
    protocol=load(args.protocol);case_doc=load(args.cases);catalog=load(args.catalog)
    if sha(args.cases)!=CASES_SHA or sha(args.catalog)!=CATALOG_SHA:raise ValueError("Frozen case/catalog identity mismatch")
    if protocol["answer_parser_sha256"]!=EXTRACTOR_SHA:raise ValueError("Protocol parser binding mismatch")
    extract=frozen_extractor(args.extractor)
    manifest=load(run/"manifest.json")
    if manifest.get("interface_only") or "tiny_cpu" in str(run):raise ValueError("Interface-only data must not be presented as GPU primary results")
    expected={c["case_id"]:c for c in case_doc["cases"]};catalog_by={c["case_id"]:c for c in catalog["cases"]}
    order=protocol["frozen_order"];issues=[];records=[];raw_outputs=[];probes=[];input_hashes={}
    for name in ["manifest.json","summary.json","stage_timings.json","forward_ledger.json"]:
        p=run/name
        if p.exists():input_hashes[name]=sha(p)
    for cid in order:
        path=run/(cid+".json")
        if not path.exists():continue
        data=load(path);input_hashes[path.name]=sha(path);case=expected[cid];oracle=oracle_values(case)
        if data.get("case_id")!=cid:issues.append({"location":cid,"issue":"Filename/case ID mismatch"})
        if data.get("answer_extractor_sha256")!=EXTRACTOR_SHA:issues.append({"location":cid,"issue":"Per-case parser hash mismatch"})
        if data.get("input_sha256")!=CASES_SHA:issues.append({"location":cid,"issue":"Per-case input hash mismatch"})
        for key in ["source_sha256","model_manifest_sha256"]:
            if key in manifest and data.get(key)!=manifest[key]:issues.append({"location":cid,"issue":key+" disagrees with run manifest"})
        if oracle["z"]!=case["required_final_value"]:raise ValueError("Frozen fixture final-value oracle mismatch")
        group=next((k for k,v in GROUPS.items() if v==case["group"]),None)
        meta=data.get("evaluation_metadata",{})
        for key in ["group","required_final_value","old_branch_final_value","revision_implied_final_value"]:
            if meta.get(key)!=case[key]:issues.append({"location":cid,"issue":"Recorded evaluator metadata mismatch: "+key})
        r={"case_id":cid,"group":group,"arms":{},"primary_complete_declared":bool(data.get("primary_complete")),
           "diagnostic_complete_declared":bool(data.get("diagnostic_complete")),"status_recorded":data.get("status")}
        roles=expected_roles(case)
        for family in ["z","y"]:
            if catalog_by[cid][family+"_roles"]!=roles[family]:raise ValueError("Fixed catalog/oracle roles disagree")
        for arm in ARMS:
            a=data.get("arms",{}).get(arm,{})
            if "free" not in a or "text" not in a["free"]:continue
            free=a["free"];reparsed=extract(free["text"]);correct=reparsed["value"] is not None and reparsed["value"]==oracle["z"]
            if a.get("extraction")!=reparsed:issues.append({"location":cid+"/"+arm,"issue":"Stored frozen extraction differs from independent reapplication"})
            evaluation=a.get("evaluation",{})
            if evaluation.get("parsed_value")!=reparsed["value"] or evaluation.get("correct")!=correct:issues.append({"location":cid+"/"+arm,"issue":"Stored primary correctness mismatch"})
            spec=a.get("free_rendering",{}).get("spec",{})
            entry={"case_id":cid,"group":group,"arm":arm,"text":free["text"],"fixed_scaffold":spec.get("assistant_scaffold"),
                   "text_sha256_utf8":hashlib.sha256(free["text"].encode()).hexdigest(),
                   "free_readout_spec":spec,"free_readout_ids_sha256":digest_ids(a.get("free_rendering",{}).get("ids",[])),
                   "extraction":reparsed,"correct":correct,"expected_final":oracle["z"],
                   "stop_reason":free.get("stop_reason"),"new_tokens":free.get("new_tokens"),
                   "stored_format_features":a.get("format_features"),"recorded_timing":a.get("timing"),
                   "within_run_only":True,"numeric_match_does_not_identify_old_value_source_or_induction":True}
            r["arms"][arm]=entry;raw_outputs.append(entry)
            for family,p in a.get("probes",{}).items():
                if family in ("z","y") and "scores" in p:
                    probes.append(audit_probe(cid,arm,family,p,data.get("rendering_core",{}),roles[family],protocol,issues))
        r["primary_complete_recomputed"]=len(r["arms"])==len(ARMS)
        if r["primary_complete_declared"]!=r["primary_complete_recomputed"]:issues.append({"location":cid,"issue":"Primary completion flag differs from all-five-free availability"})
        available={(p["arm"],p["family"]) for p in probes if p["case_id"]==cid}
        r["diagnostic_complete_recomputed"]=all((a,f) in available for a in ARMS for f in ["z","y"])
        controls=data.get("controls") or {}
        r["control_scope"]={"full_bundle_present":bool(controls.get("checks")),"passed_recorded":controls.get("passed"),
                             "checks_recorded":controls.get("checks"),"note":controls.get("note")}
        if r["diagnostic_complete_declared"]!=r["diagnostic_complete_recomputed"]:issues.append({"location":cid,"issue":"Diagnostic completion flag differs from available five-arm Y/Z scoring"})
        records.append(r)
    if not raw_outputs:raise ValueError("No available P0.5 free outputs; no result report written")
    complete=[r for r in records if r["primary_complete_recomputed"] and r["primary_complete_declared"]]
    by_group={g:[r for r in complete if g=="all" or r["group"]==g] for g in ("all",*GROUPS)}
    primary={a:{g:{"n":len(rs),"correct":sum(r["arms"][a]["correct"] for r in rs),
                    "parsed":sum(r["arms"][a]["extraction"]["value"] is not None for r in rs),
                    "unparsed_ids":[r["case_id"] for r in rs if r["arms"][a]["extraction"]["value"] is None],
                    "accuracy":sum(r["arms"][a]["correct"] for r in rs)/len(rs) if rs else None}
                for g,rs in by_group.items()} for a in ARMS}
    pairs={a+"__to__"+b:{g:paired(rs,a,b) for g,rs in by_group.items()} for a,b in PAIRS}
    interactions={g:interaction(rs) for g,rs in by_group.items()}
    probe_lookup={(p["case_id"],p["arm"],p["family"]):p for p in probes};probe_deltas=[]
    for cid in order:
        for family in ["z","y"]:
            for left,right in PROBE_PAIRS:
                l=probe_lookup.get((cid,left,family));r=probe_lookup.get((cid,right,family))
                if not l or not r:continue
                matched=l["context"]["readout_token_ids"]==r["context"]["readout_token_ids"] and l["context"]["core_prefix_ids_sha256"]==r["context"]["core_prefix_ids_sha256"] and l["context"]["readout_position_ids"]==r["context"]["readout_position_ids"]
                probe_deltas.append({"case_id":cid,"family":family,"left":left,"right":right,"same_input_prefix_ids_and_positions":matched,
                                     "role_logP_right_minus_left":{role:r["role_logP"][role]-l["role_logP"][role] for role in l["role_logP"] if role in r["role_logP"]},
                                     "meaning":"Conditional forced-query score change under differing mask/history; not observed generated intermediate state"})
                if not matched:issues.append({"location":cid+"/"+family+"/"+left+"->"+right,"issue":"Nominally matched probe pair has different readout/core/positions"})
    existing_summary=load(run/"summary.json") if (run/"summary.json").exists() else {}
    for a in ARMS:
        for g,name in [("all","all"),*[(k,v) for k,v in GROUPS.items()]]:
            stored=existing_summary.get("primary_accuracy",{}).get(a,{}).get(name)
            if stored and any(stored.get(k)!=primary[a][g][k] for k in ["n","correct","parsed"]):issues.append({"location":a+"/"+g,"issue":"Runner summary differs from independent primary counts"})
    cap_format={}
    for a in ARMS:
        xs=[x for x in raw_outputs if x["arm"]==a]
        cap=[x for x in xs if x["stop_reason"]=="token_budget"]
        cap_format[a]={"available_outputs":len(xs),"generated_new_tokens_recorded_sum":sum(x["new_tokens"] for x in xs),
                       "stop_reason_counts":dict(collections.Counter(x["stop_reason"] for x in xs)),
                       "token_budget_ids":[x["case_id"] for x in cap],
                       "budget_unparsed_ids":[x["case_id"] for x in cap if x["extraction"]["value"] is None],
                       "budget_parsed_correct_ids":[x["case_id"] for x in cap if x["correct"]],
                       "budget_parsed_incorrect_ids":[x["case_id"] for x in cap if x["extraction"]["value"] is not None and not x["correct"]]}
    ledger=load(run/"forward_ledger.json") if (run/"forward_ledger.json").exists() else []
    cost={"runner_elapsed_seconds_recorded":existing_summary.get("elapsed_seconds"),
          "hash_and_load_seconds_included_recorded":manifest.get("load_and_hash_seconds"),
          "forward_calls_recounted":len(ledger),"forward_input_tokens_recounted":sum(x["input_tokens"] for x in ledger),
          "synchronized_forward_seconds_recounted":math.fsum(x["seconds"] for x in ledger),
          "free_new_tokens_recorded_total":sum(x["new_tokens"] for x in raw_outputs),
          "observed_postload_peak_allocated_bytes_recorded":existing_summary.get("observed_postload_peak_allocated_bytes"),
          "note":"Launcher/runner/load/forward timings are nested; do not add. Shared prefixes, held checkpoints, controls and probes are experimental costs, not production speedup."}
    if args.launcher_record:
        launch=load(args.launcher_record)
        cost["launcher_record_path"]=str(args.launcher_record.resolve());cost["launcher_record_sha256"]=sha(args.launcher_record)
        cost["launcher_elapsed_seconds_including_hash_import_load"]=launch.get("elapsed_seconds_including_hash_import_load")
        cost["launcher_conservative_single_gpu_minutes"]=launch.get("conservative_single_gpu_minutes")
        cost["launcher_exit_code"]=launch.get("exit_code");cost["ending_compute_processes_recorded"]=launch.get("ending_compute_processes")
    manual=None
    if args.text_review:
        manual=load(args.text_review)
        for name,value in manual["run_case_json_sha256"].items():
            if input_hashes.get(name)!=value:raise ValueError("Manual review is bound to different run inputs")
        raw_hashes={x["case_id"]+"/"+x["arm"]:x["text_sha256_utf8"] for x in raw_outputs}
        if raw_hashes!=manual["raw_output_sha256_by_case_arm"]:raise ValueError("Manual review raw-output binding mismatch")
    result={"analysis_status":"INDEPENDENT_CPU_PRIMARY_AUDIT_PASS" if not issues else "INDEPENDENT_CPU_AUDIT_HAS_INTEGRITY_ISSUES",
            "scope":"This user-turn five-arm/scaffold protocol only; no cross-old-P0 improvement claim",
            "analysis_source_sha256":sha(__file__),"run_directory":str(run),"input_hashes":input_hashes,
            "protocol_sha256":sha(args.protocol),"case_source_sha256":sha(args.cases),"frozen_parser_sha256":sha(args.extractor),"candidate_catalog_sha256":sha(args.catalog),
            "run_manifest":manifest,"run_summary_recorded":existing_summary,
            "primary_denominator":"All five free outputs complete; unresolved extraction remains incorrect, never dropped. Diagnostic completion is not a primary filter.",
            "planned_cases":len(order),"records_found":len(records),"primary_complete_cases":len(complete),
            "primary_complete_ids":[r["case_id"] for r in complete],
            "diagnostic_complete_ids":[r["case_id"] for r in records if r["diagnostic_complete_recomputed"]],
            "diagnostic_partial_ids":[r["case_id"] for r in records if not r["diagnostic_complete_recomputed"]],
            "unstarted_ids":[cid for cid in order if cid not in {r["case_id"] for r in records}],
            "individual_available_free_counts":{a:sum(a in r["arms"] for r in records) for a in ARMS},
            "primary_accuracy":primary,"paired_repairs_and_harms":pairs,"descriptive_2x2_interaction":interactions,
            "cap_and_format_by_arm":cap_format,"cost_recount":cost,
            "control_bundle_scope":{r["case_id"]:r["control_scope"] for r in records},
            "diagnostic_available_contexts_by_arm_family":{a:{f:sum(p["arm"]==a and p["family"]==f for p in probes) for f in ["z","y"]} for a in ARMS},
            "manual_text_review_no_rescoring":manual,
            "all_raw_free_outputs":raw_outputs,"format_unparsed_outputs":[r for r in raw_outputs if r["extraction"]["value"] is None],
            "all_available_probes":probes,"matched_prefix_conditional_probe_deltas":probe_deltas,
            "probe_scope":"Complete continuation logP sums saved conditionals including newline. First-token marginal is separate. No normalized four-role confidence; aliases are not distinct outcomes. Y is forced y= pre-generation-state query, not natural generated belief.",
            "integrity_issues":issues,"no_model_or_GPU_used_by_analysis":True}
    out.mkdir(parents=True,exist_ok=True)
    json_path=out/"PRIMARY_P05_ANALYSIS.json"
    json_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    write_report(result,out/"PRIMARY_P05_ANALYSIS_ZH.md",json_path)
    print(json.dumps({"analysis_status":result["analysis_status"],"primary_complete_cases":len(complete),
                      "raw_outputs":len(raw_outputs),"available_probe_contexts":len(probes),"issues":len(issues),"output":str(json_path)},ensure_ascii=False))
    return 0 if not issues else 2


def write_report(r,path,json_path):
    lines=["# 本轮 P0.5 五臂独立 primary 分析", "", "状态："+r["analysis_status"],"",
           "只分析本轮新 user-turn / scaffold 协议。与旧 P0 分数的差异不能解释为方法提升；不自动判 induction、内部跳步或旧数字来源。",
           "",f"计划 {r['planned_cases']} 题；实际 case 记录 {r['records_found']}；五臂 primary 配对完整 {r['primary_complete_cases']}；完整诊断 {len(r['diagnostic_complete_ids'])}。",
           "primary 不要求诊断完成；未解析输出在完整 primary 分母内记不正确，不按格式筛样。",
           "", "## 1. Primary 全部配对与 E/C/W", "", "| 臂 | 全部 正确/n（解析） | E | C | W |","|---|---|---|---|---|"]
    for a in ARMS:
        def score(g):
            x=r["primary_accuracy"][a][g];return f"{x['correct']}/{x['n']}（{x['parsed']}）"
        lines.append("|"+a+"|"+"|".join(score(g) for g in ["all","E","C","W"])+"|")
    if r.get("manual_text_review_no_rescoring"):
        lines += ["", "### 逐条读原文后的解释约束（不改主分）", ""]
        lines.extend("- "+s for s in r["manual_text_review_no_rescoring"]["interpretation_constraints"])
    lines += ["", "## 2. 本轮配对修复/伤害", "", "未解析→正确可能包含格式修复，不能自动解读为数学机制修复。", "", "| 对比 | 组 | n | 修复 ID | 伤害 ID | 净变化 |", "|---|---|---:|---|---|---:|"]
    for pair,groups in r["paired_repairs_and_harms"].items():
        for g,x in groups.items():lines.append(f"|{pair}|{g}|{x['n']}|{','.join(x['repair_ids']) or '无'}|{','.join(x['harm_ids']) or '无'}|{x['net_right_minus_left']}|")
    lines += ["", "## 3. WholeEarly×OneLine 描述性交互", "", "对比 = Acc(WholeEarlyOneLine)−Acc(WholeEarlyDirect)−Acc(FullOneLine)+Acc(FullDirect)。它是同一固定病例集上的策略交互，不证明错误来源正交、互补机制或 induction-head。", "", "| 组 | n | 对比和 | 平均准确率对比 |", "|---|---:|---:|---:|"]
    for g,x in r["descriptive_2x2_interaction"].items():lines.append(f"|{g}|{x['n']}|{x['sum_contrast']}|{x['mean_accuracy_contrast']}|")
    lines += ["", "## 4. 原始自由输出：按实际完成量全部列出", "",f"共 {len(r['all_raw_free_outputs'])} 条，不默认已有 80 条。JSON 字符串保留换行/标点；scaffold 单列，冻结 parser 仅接收 free.text。", "", "| case | 组 | 臂 | 固定 scaffold | 原始 free.text（JSON） | 抽取值/方法 | 正确 |", "|---|---|---|---|---|---|---|"]
    for x in r["all_raw_free_outputs"]:
        lines.append(f"|{x['case_id']}|{x['group']}|{x['arm']}|{raw_json(x['fixed_scaffold'])}|{raw_json(x['text'])}|{x['extraction']['value']} / {x['extraction']['method']}|{x['correct']}|")
    lines += ["", "## 5. 格式未解析、部分/未运行", "", "未解析："+str([(x['case_id'],x['arm']) for x in r['format_unparsed_outputs']]),
              "", "仅诊断未完整："+str(r['diagnostic_partial_ids']),"", "未开始："+str(r['unstarted_ids']),
              "", "各臂可用自由输出："+str(r['individual_available_free_counts']),"",
              "| 臂 | 新生成token合计（记录值） | 64-token cap ID | cap且未解析 | cap已解析且不正确 |",
              "|---|---:|---|---|---|"]
    for arm,x in r["cap_and_format_by_arm"].items():
        lines.append(f"|{arm}|{x['generated_new_tokens_recorded_sum']}|{','.join(x['token_budget_ids']) or '无'}|{','.join(x['budget_unparsed_ids']) or '无'}|{','.join(x['budget_parsed_incorrect_ids']) or '无'}|")
    lines += ["", "cap不一律等于未解析：E06式完整末行可以被冻结语法抽取；在部分算式处截断也可能返回一个不正确数字。不能补写后缀、事后增加token或换parser救分。", "",
              "## 6. 条件 probe：全部可用 continuation logP", "",
              "这些 probe 在自由生成前状态上使用独立强制前缀，实际成本另计；不是生成 OneLine 后读出的信念。Z 使用冻结最终答案前缀；Y 使用 `y =`。每个完整 continuation 包含末尾换行，logP 为未作长度归一化的自回归条件和。首 token 列仅是首 token 边际，不能当作完整候选概率。角色别名共用同一候选，不归一化为四类置信度。W 的 revision-consistent 不是 trusted。",
              "", "每个上下文的完整 user 指令、scaffold、prefix token hash/IDs 与绝对位置保存在 JSON 的 all_available_probes.context。", "",
              "| case | 臂 | family / scaffold | context ID前12位 | 角色别名 | continuation JSON | token IDs | 完整 logP | 首token logP |", "|---|---|---|---|---|---|---|---:|---:|"]
    for p in r["all_available_probes"]:
        for c in p["unique_candidates"]:
            lines.append(f"|{p['case_id']}|{p['arm']}|{p['family']} / {raw_json(p['context']['spec'].get('assistant_scaffold'))}|{p['context']['context_id'][:12]}|{','.join(c['role_aliases'])}|{raw_json(c['continuation'])}|{md(c['token_ids'])}|{c['logP']}|{c['first_token_logP']}|")
    lines += ["", "完整/首token role margin、同值别名 NA 与 matched-prefix ΔlogP 全部保存在 JSON；完整 logP 的 CPU 核验为对已保存逐 token conditional 的求和，没有重新生成后续 token logits。",
              "", "## 7. 实际成本与诊断完成边界", "", "诊断各臂 Y/Z 可用上下文数："+str(r['diagnostic_available_contexts_by_arm_family']),
              "", "完整诊断 ID："+str(r['diagnostic_complete_ids']),"", "primary分母仍为全部五臂完整病例，不因后半批诊断超时而减半。",
              "", "实际成本（计时相互包含，不相加）：", "", "```json",json.dumps(r['cost_recount'],ensure_ascii=False,indent=2),"```",
              "", "完整控制bundle仅在记录含checks的病例执行，其余不能宣称完整控制PASS："+str([cid for cid,c in r['control_bundle_scope'].items() if c['full_bundle_present']]),
              "", "## 8. 身份与完整性", "", "冻结 parser SHA256："+r['frozen_parser_sha256'],
              "", "完整性问题："+str(r['integrity_issues']),"", "原 run 保持只读；分析未执行模型/GPU。",
              "", f"完整机器数据：[PRIMARY_P05_ANALYSIS.json]({json_path.as_posix()})"]
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")


def self_test(args):
    extract=frozen_extractor(args.extractor)
    fixtures=[("38。",38),("28*2=56。",56),("y=19\n最终答案：38",38),("2+2=5",5),("28, therefore maybe",None),("最终答案：38 trailing",None)]
    for text,value in fixtures:assert extract(text)["value"]==value
    assert extract("2+2=5")["equation_truth_evaluated"] is False
    print(json.dumps({"self_test":"PASS","parser_hash_verified":True,"fixtures":len(fixtures),"no_run_results_read_or_written":True}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",type=Path,help="Explicit returned GPU run directory; never inferred")
    parser.add_argument("--output-dir",type=Path,default=HERE,help="Must be outside the original run")
    parser.add_argument("--protocol",type=Path,default=HERE/"P05_PROTOCOL_DRAFT_20261105.json")
    parser.add_argument("--cases",type=Path,default=HERE.parent/"direction_selection_20261105/proposed_p0_cases.json")
    parser.add_argument("--catalog",type=Path,default=HERE/"fixed_candidate_roles.json")
    parser.add_argument("--extractor",type=Path,default=HERE.parent/"next_design_20261105/frozen_answer_extractor.py")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--launcher-record",type=Path,help="Optional actual outer cost record; no timing inferred")
    parser.add_argument("--text-review",type=Path,help="Optional human-read notes bound to exact input/output hashes; never rescoring")
    args=parser.parse_args()
    if args.self_test:self_test(args);return 0
    if not args.run_dir:parser.error("--run-dir is required; preparation never creates assumed results")
    return analyze(args)


if __name__=="__main__":sys.exit(main())
