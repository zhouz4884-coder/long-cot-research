"""Read-only, CPU-only raw audit of Phase5-A quality_round_01.

Uses the pre-frozen parser without modification. Does not launch any model,
retry incomplete work, rescue JSON answers into the primary score, or compare
scores across the earlier P0/P0.5 protocols.
"""

import ast
import collections
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

BASE=Path(__file__).parent
RUN=BASE/"results/quality_round_01"
PARSER=BASE.parent/"next_design_20261105/frozen_answer_extractor.py"
PARSER_SHA="c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed"


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def digest(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()
def md(value):return str(value).replace("|","\\|").replace("`","\\u0060").replace("\n","\\n")
def raw(value):return md(json.dumps(value,ensure_ascii=False))


def arithmetic(expression,environment):
    def visit(n):
        if isinstance(n,ast.Constant) and type(n.value) is int:return n.value
        if isinstance(n,ast.Name):return environment[n.id]
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.USub):return -visit(n.operand)
        if isinstance(n,ast.BinOp):
            a,b=visit(n.left),visit(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.Mult):return a*b
            if isinstance(n.op,ast.FloorDiv) and b and a%b==0:return a//b
        raise ValueError("Unsupported independent integer-oracle syntax")
    return visit(ast.parse(expression,mode="eval").body)


def question_oracle(question):
    definitions=re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,，;；。\n]+)",question)
    if len(definitions)!=4:raise ValueError("Expected four visible definitions")
    values={}
    for variable,expression in definitions:values[variable]=arithmetic(expression.strip(),values)
    goal=re.search(r"求\s*([A-Za-z_][A-Za-z0-9_]*)",question)
    if not goal:raise ValueError("Missing visible goal")
    return definitions,values,goal[1]


def first_json(text):
    start=text.find("{")
    if start<0:raise ValueError("Missing shared evidence JSON")
    return json.JSONDecoder().raw_decode(text[start:])[0]


def stats(rows):
    n=len(rows)
    return {"n":n,"correct":sum(r["correct"] for r in rows),
            "eos_correct":sum(r["eos_correct"] for r in rows),"eos":sum(r["eos"] for r in rows),
            "cap":sum(r["cap"] for r in rows),"unparsed":sum(r["extraction"]["value"] is None for r in rows),
            "accuracy":sum(r["correct"] for r in rows)/n if n else None,
            "generated_tokens":sum(r["new_tokens"] for r in rows),"prompt_tokens":sum(r["prompt_tokens"] for r in rows),
            "request_seconds_inclusive":math.fsum(r["request_seconds_inclusive"] for r in rows),
            "G_seconds_already_in_request":math.fsum(r["G_cpu_seconds"] for r in rows),
            "compile_seconds_already_in_request":math.fsum(r["compile_seconds"] for r in rows)}


def main():
    issues=[]
    def check(ok,message):
        if not ok:issues.append(message)
    retrieval=load(BASE/"RESULT_RETRIEVAL_MANIFEST.json")
    retrieval_before={}
    for item in retrieval["files"]:
        p=BASE/item["path"]
        check(p.exists(),"Missing retrieved file: "+item["path"])
        if p.exists():
            check(p.stat().st_size==item["bytes"],"Retrieved byte count mismatch: "+item["path"])
            actual=sha(p);check(actual==item["sha256"],"Retrieved SHA mismatch: "+item["path"])
            retrieval_before[item["path"]]=actual
    protocol=load(BASE/"QUALITY_PROTOCOL_V1.json");freeze=load(BASE/"prelaunch_freeze_01.json")
    manifest=load(RUN/"manifest.json");summary=load(RUN/"summary.json");prepared=load(RUN/"prepared_dataset.json")
    launcher=load(BASE/"provenance/launcher_01.json")
    check(launcher["freeze_sha256"]==sha(BASE/"prelaunch_freeze_01.json"),"Launcher/prelaunch binding mismatch")
    check(manifest["parser_sha256"]==PARSER_SHA==sha(PARSER),"Frozen parser binding mismatch")
    source_map={"source/phase5_quality_runner.py":BASE/"phase5_quality_runner.py",
                "source/prepare_cpu_input_adapter.py":BASE/"prepare_cpu_input_adapter.py",
                "source/launch_quality.py":BASE/"launch_quality.py",
                "source/p0_base_frozen.py":BASE.parent/"direction_selection_20261105/real_model_p0.py",
                "source/frozen_answer_extractor.py":PARSER,
                "data/topology_v2.json":BASE.parent/"next_design_20261105/P05_topology_cases_v2.json",
                "provenance/quality_protocol.json":BASE/"QUALITY_PROTOCOL_V1.json",
                "provenance/rendered_inputs_01.json":BASE/"rendered_inputs_01.json"}
    frozen_local=[]
    for item in freeze["remote_files"]:
        p=source_map[item["path"]];ok=p.exists() and sha(p)==item["sha256"]
        check(ok,"Frozen local source/input reference mismatch: "+item["path"])
        frozen_local.append({"reference":item["path"],"local_path":str(p),"sha256":item["sha256"],"matched":ok})
    check(not manifest["interface_only"],"Interface-only data cannot be called a real run")
    check(manifest["quality_guard"]==protocol["quality_policy"]["max_new_tokens"]==512,"Guard mismatch")
    check(manifest["source_sha256"]==sha(BASE/"phase5_quality_runner.py"),"Runner source binding mismatch")
    check(manifest["adapter_source_sha256"]==protocol["input"]["adapter_sha256"],"Adapter binding mismatch")
    check(manifest["input_sha256"]==protocol["input"]["sha256"],"Input binding mismatch")
    check(manifest["model_manifest_sha256"]==protocol["model"]["manifest_sha256"],"Model manifest binding mismatch")
    check(manifest["rendered_jobs_sha256"]==sha(RUN/"rendered_jobs.json"),"Rendered jobs file binding mismatch")
    payload={"selected_ids":prepared["selected_order"],"methods":prepared["methods"],"source_sha256":prepared["source_sha256"],
             "main_messages":{c["case_id"]:{m:c["model_inputs"][m]["messages_sha256"] for m in prepared["methods"]} for c in prepared["cases"]},
             "basis_messages":{b["basis_id"]:b["provenance"]["messages_sha256"] for b in prepared["basis"]},
             "dedupe_map":prepared["dedupe_map"],"generation_policy":prepared["generation_policy_draft"]}
    check(digest(payload)==prepared["hash"]==protocol["input"]["prepared_dataset_hash"]==manifest["prepared_dataset_hash"],"Prepared-message dataset hash mismatch")
    spec=importlib.util.spec_from_file_location("phase5_pre_frozen_parser",PARSER)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    methods=protocol["methods"];order=protocol["order"]
    cases={c["case_id"]:c for c in prepared["cases"]};basis={b["basis_id"]:b for b in prepared["basis"]}
    frozen_render=load(BASE/"rendered_inputs_01.json")["rows"]
    render_key=lambda r:(r["kind"],r.get("case_id"),r.get("basis_id"),r.get("method"))
    frozen_by={render_key(r):r for r in frozen_render}
    jobs=load(RUN/"rendered_jobs.json");job_by={r["job_id"]:r for r in jobs}
    check(len(jobs)==len(frozen_by)==30,"Planned render count is not 30")
    for job in jobs:
        pre=frozen_by[render_key(job)]
        check(job["messages"]==pre["messages"] and job["prompt_text"]==pre["text"] and job["prompt_token_ids"]==pre["input_ids"],"Prelaunch render mismatch: "+job["job_id"])
        check(job["position_ids"]==list(range(len(job["prompt_token_ids"]))),"Prompt positions mismatch: "+job["job_id"])
    all_rows=[];leaf_records={};common_by_case={};state_rows={}
    for job in jobs:
        path=RUN/(job["job_id"]+".json")
        if not path.exists():continue
        record=load(path);leaf_records[job["job_id"]]=record
        check(record["job_id"]==job["job_id"],"Job identity mismatch")
        check(record["rendering"]==job,"Actual request render drift: "+job["job_id"])
        for a,b in [("source_sha256","source_sha256"),("adapter_sha256","adapter_source_sha256"),("data_sha256","input_sha256"),("model_manifest_sha256","model_manifest_sha256")]:
            check(record[a]==manifest[b],"Per-request identity mismatch: "+job["job_id"]+"/"+a)
        if "free" not in record:continue
        check(record.get("complete") is True,"A saved graded output is not marked complete: "+job["job_id"])
        if job["kind"]=="main":
            item=cases[job["case_id"]];question=item["visible"]["question"];hidden=item["hidden_evaluation"]
        else:
            item=basis[job["basis_id"]];question=item["visible"]["question"];hidden=item["hidden_evaluation"]
        definitions,values,goal=question_oracle(question);target=values[goal]
        check(target==hidden["required_final_value"]==record["hidden_evaluation_not_prompted"]["required_final_value"],"Visible-question integer oracle mismatch: "+job["job_id"])
        free=record["free"];extraction=module.extract_answer(free["text"])
        correct=extraction["value"] is not None and extraction["value"]==target
        eos=free["stop_reason"]=="eos";cap=free["hit_safety_cap"]
        check(record["grade"]["frozen_extraction"]==extraction,"Stored extraction mismatch: "+job["job_id"])
        check(record["grade"]["numeric_correct"]==correct and record["grade"]["eos_and_correct"]==(eos and correct),"Stored grade mismatch: "+job["job_id"])
        check(free["new_tokens"]==len(free["token_ids"]),"Generated-token count mismatch")
        check(free["guard"]==512 and free["no_dynamic_grader_stop"] is True,"Free generation guard/stopping flag mismatch")
        check(free["eos_reached"]==eos,"EOS metadata mismatch")
        if eos:check(bool(free["token_ids"]) and free["token_ids"][-1] in manifest["eos_token_ids"],"EOS token evidence mismatch")
        check(free["input_checkpoint_cache_length_before_after"][0]==free["input_checkpoint_cache_length_before_after"][1],"Original request checkpoint mutated")
        r={"job_id":job["job_id"],"kind":job["kind"],"case_id":job["case_id"],"basis_id":job["basis_id"],"method":job["method"],
           "program_id":hidden["program_id"],"group":hidden["group"],"target_from_visible_question":target,"visible_integer_values":values,
           "complete_recorded":record["complete"],"text":free["text"],"text_sha256_utf8":hashlib.sha256(free["text"].encode()).hexdigest(),
           "extraction":extraction,"correct":correct,"eos_correct":eos and correct,"eos":eos,"cap":cap,"stop_reason":free["stop_reason"],
           "new_tokens":free["new_tokens"],"prompt_tokens":job["prompt_tokens"],"G_cpu_seconds":record["G_cpu_seconds"],
           "compile_seconds":record["prompt_compile_and_tokenize_seconds"],"request_seconds_inclusive":record["request_seconds_before_posthoc_grader"],
           "posthoc_grader_seconds":record["posthoc_grader_seconds"],"actual_forward_cost":record["actual_forward_cost"]}
        all_rows.append(r)
        if job["kind"]=="main":
            gate=record["G_and_bookkeeping"];shared=first_json(job["messages"][-1]["content"])
            check(shared==item["shared_evidence"],"Shared evidence differs from prepared input: "+job["job_id"])
            if job["case_id"] in common_by_case:check(shared==common_by_case[job["case_id"]],"Method-specific shared information drift")
            common_by_case[job["case_id"]]=shared
            check(gate["derived_arithmetic_evaluations"]==0 and gate["final_commit"]["allowed"] is False,"Unauthorized derived checker/final commit")
            check(all(v["certification_status"]=="UNVERIFIED" for v in gate["old_derived_statuses"].values()),"Old derived result auto-certified")
            check(set(gate["roots"])=={"x","r"} and all(v["value"]==values[k] for k,v in gate["roots"].items()),"Root-only G values differ from visible definitions")
            state_rows.setdefault(job["case_id"],{})[job["method"]]=r
    actual_order=[r["job_id"] for r in all_rows]
    check(actual_order==[r["job_id"] for r in jobs[:len(actual_order)]],"Actual outputs are not the frozen fixed-order prefix")
    main_rows=[r for r in all_rows if r["kind"]=="main"];basis_rows=[r for r in all_rows if r["kind"]=="basis"]
    complete_ids=[cid for cid in order if set(state_rows.get(cid,{}))==set(methods) and all(x["complete_recorded"] for x in state_rows[cid].values())]
    partial_ids=[cid for cid in order if cid in state_rows and cid not in complete_ids]
    unstarted_ids=[cid for cid in order if cid not in state_rows]
    for cid in state_rows:
        aggregate=load(RUN/(cid+".json"));check(aggregate["primary_complete"]==(cid in complete_ids),"Aggregate completion mismatch: "+cid)
        for method,r in state_rows[cid].items():check(aggregate["methods"][method]==leaf_records[r["job_id"]],"Aggregate duplicate differs from leaf request")
    paired_rows=[r for r in main_rows if r["case_id"] in complete_ids]
    grouped={m:{g:stats([r for r in paired_rows if r["method"]==m and (g=="all" or r["group"]==g)]) for g in ["all","E","C","W"]} for m in methods}
    program_counts={m:{p:stats([r for r in paired_rows if r["method"]==m and r["program_id"]==p]) for p in ["T1","T2"]} for m in methods}
    for method in methods:
        for group in ["all","E","C","W"]:
            stored=summary["methods"][method] if group=="all" else summary["methods"][method]["by_group"][group]
            audited=grouped[method][group]
            for key_a,key_s in [("n","n"),("correct","numeric_correct"),("eos_correct","eos_and_correct"),("eos","eos"),("cap","hit_cap"),("unparsed","unparsed"),("generated_tokens","generated_tokens")]:
                check(audited[key_a]==stored[key_s],"Summary recount mismatch: "+method+"/"+group+"/"+key_a)
    check(summary["complete_main_ids"]==complete_ids and summary["main_started"]==len(state_rows) and summary["basis_complete"]==len(basis_rows),"Summary completion mismatch")
    pairwise={}
    for left in methods:
        for right in methods:
            if methods.index(right)<=methods.index(left):continue
            gain=[cid for cid in complete_ids if not state_rows[cid][left]["correct"] and state_rows[cid][right]["correct"]]
            harm=[cid for cid in complete_ids if state_rows[cid][left]["correct"] and not state_rows[cid][right]["correct"]]
            pairwise[left+"__to__"+right]={"n_related_states":len(complete_ids),"independent_programs_at_most":2,"repair_ids":gain,"harm_ids":harm}
    ledger=load(RUN/"forward_ledger.json")
    recount={"forward_calls":len(ledger),"input_tokens":sum(x["input_tokens"] for x in ledger),"synchronized_forward_seconds":math.fsum(x["seconds"] for x in ledger)}
    check(all(abs(recount[k]-summary["actual_forward_cost"][k])<1e-6 for k in recount),"Forward cost recount mismatch")
    check(sum(r["actual_forward_cost"]["forward_calls"] for r in all_rows)==len(ledger),"Per-request forward calls do not reconcile")
    check(sum(r["actual_forward_cost"]["input_tokens"] for r in all_rows)==recount["input_tokens"],"Per-request forward input tokens do not reconcile")
    json_failures=[]
    for r in main_rows:
        if r["extraction"]["value"] is None:
            try:content=json.loads(r["text"])
            except (ValueError,TypeError):content=None
            json_failures.append({"job_id":r["job_id"],"normal_eos":r["eos"],"cap":r["cap"],
                                  "visible_JSON_final_answer":content.get("final_answer") if isinstance(content,dict) else None,
                                  "scope":"Raw layout observation only. Never converted into an alternative primary score."})
    costs={"study_launcher_seconds":launcher["elapsed_seconds_including_imports_hash_load"],"single_gpu_minutes":launcher["conservative_single_gpu_minutes"],
           "runner_seconds":summary["elapsed_seconds"],"load_hash_seconds_already_in_study":manifest["load_and_hash_seconds"],
           "shared_preparation_seconds_already_in_study":manifest["shared_preparation_seconds"],
           "request_seconds_sum_includes_G_compile_prefill_decode":math.fsum(r["request_seconds_inclusive"] for r in all_rows),
           "G_seconds_component_do_not_add":math.fsum(r["G_cpu_seconds"] for r in all_rows),
           "compile_seconds_component_do_not_add":math.fsum(r["compile_seconds"] for r in all_rows),
           "generated_tokens_all":sum(r["new_tokens"] for r in all_rows),"prompt_tokens_all":sum(r["prompt_tokens"] for r in all_rows),
           "basis_actual_cost":stats(basis_rows),"main_available_cost_including_partial_state":stats(main_rows),
           "paired_method_cost":{m:grouped[m]["all"] for m in methods},"forward_recount":recount,
           "postload_peak_allocated_bytes_recorded":summary["observed_postload_peak_allocated_bytes"],
           "ending_compute_processes_recorded":launcher["ending_compute_processes"],
           "accounting":"Request elapsed already includes G + compile + prefill + decode; components are not added again. Launcher/runner/load/request/forward are nested. Basis, the incomplete main block and failures remain study cost."}
    for path,value in retrieval_before.items():check(sha(BASE/path)==value,"Input changed during audit: "+path)
    result={"audit_status":"PASS" if not issues else "INTEGRITY_ISSUES","execution_status":summary["status"],
            "analysis_source_sha256":sha(__file__),"frozen_parser_sha256":PARSER_SHA,
            "retrieval_manifest_sha256":sha(BASE/"RESULT_RETRIEVAL_MANIFEST.json"),"retrieved_files_verified":len(retrieval_before),
            "retrieved_files_unchanged_during_audit":True,"prelaunch_local_bindings":frozen_local,"planned_renderings_checked":len(jobs),
            "independent_question_oracle":"Parse/evaluate the four original visible integer definitions; no model, no adapter import, no gold-selection",
            "planned_outputs":len(jobs),"available_complete_output_count":len(all_rows),"basis_outputs":len(basis_rows),
            "unstarted_job_ids":[j["job_id"] for j in jobs if j["job_id"] not in leaf_records],
            "incomplete_started_job_ids":[jid for jid,rec in leaf_records.items() if not rec.get("complete")],
            "main_outputs":len(main_rows),"planned_main_states":len(order),"started_main_states":len(state_rows),
            "complete_four_method_ids":complete_ids,"partial_main_ids":partial_ids,"unstarted_main_ids":unstarted_ids,
            "independent_program_count":len({c["hidden_evaluation"]["program_id"] for c in prepared["cases"]}),
            "primary_unit_caution":"Six planned related states from two independent arithmetic programs, not six IID natural questions; no significance/independence claim",
            "primary_counts_complete_pairs":grouped,"per_program_complete_pairs":program_counts,
            "individual_available_counts_not_primary_comparison":{m:stats([r for r in main_rows if r["method"]==m]) for m in methods},
            "partial_state_outputs":[r for r in main_rows if r["case_id"] in partial_ids],
            "basis_counts_separate":{kind:stats([r for r in basis_rows if basis[r["basis_id"]]["kind"]==kind]) for kind in ["P_only","P_plus_R"]},
            "paired_changes":pairwise,"all_actual_raw_outputs":all_rows,"unparsed_raw_layout_observations_not_rescoring":json_failures,
            "cost":costs,"issues":issues,"no_GPU_remote_or_rescoring":True,
            "scope":"Single-shot shared-root-G prompt/frame test only. No full runtime node verification, no KV operation, no natural graph, no W main comparison, no cross-P05 improvement claim."}
    (BASE/"INDEPENDENT_RESULT_AUDIT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report(result,methods)
    print(json.dumps({"audit_status":result["audit_status"],"execution_status":result["execution_status"],"retrieved_files_verified":len(retrieval_before),
                      "planned_outputs":len(jobs),"actual_outputs":len(all_rows),"complete_four_method_states":len(complete_ids),"independent_programs":2,
                      "frozen_primary_correct":{m:grouped[m]["all"]["correct"] for m in methods},"issues":issues},ensure_ascii=False))
    if issues:raise SystemExit(2)


def report(r,methods):
    lines=["# Phase 5-A 独立结果审计", "", "审计状态：**"+r["audit_status"]+"**；执行状态：**"+r["execution_status"]+"**。",
           "", "结论：本轮只有3个四方法完整配对状态，来自2个算术程序。三个共享G基线各3/3，VersionFrame按预冻结解析器为1/3；未显示其独立正确率增量。两个未解析VersionFrame输出为自然EOS结束的JSON格式，不是512-token截断。本轮主比较没有W输出，不能给W安全性结论。",
           "", "## 1. 完成范围：exit0不等于30个计划输出完成", "",
           f"计划{r['planned_outputs']}输出，实际{r['available_complete_output_count']}：basis {r['basis_outputs']}，主请求{r['main_outputs']}。主状态计划6、已开始{r['started_main_states']}、四方法完整{len(r['complete_four_method_ids'])}。",
           "", "完整配对："+str(r['complete_four_method_ids']),"", "部分状态："+str(r['partial_main_ids']),"", "未开始："+str(r['unstarted_main_ids']),
           "", "T2-C只有SharedGDirect输出，虽已正确交付，但不并入四方法primary配对。两种W主状态均未运行。6个计划状态是2程序×E/C/W，不能视为6个独立题；当前3个完整状态也不是3个独立程序，不给小样本IID显著性或普适正确率保证。",
           "", "## 2. 冻结primary重数", "", "| 方法 | 完整配对正确/n | E | C | W | EOS | cap | 未解析 |", "|---|---:|---:|---:|---|---:|---:|---:|"]
    for m in methods:
        g=r['primary_counts_complete_pairs'][m];a=g['all']
        score=lambda x:f"{x['correct']}/{x['n']}" if x['n'] else "未运行 / NA"
        lines.append(f"|{m}|{score(a)}|{score(g['E'])}|{score(g['C'])}|{score(g['W'])}|{a['eos']}/{a['n']}|{a['cap']}|{a['unparsed']}|")
    lines += ["", "上述所有正确输出也均为EOS且正确；没有因未解析或cap删除完整配对中的状态。逐程序：T1有E/C两个相关完整状态，三个基线各2/2、VersionFrame0/2；T2仅E完整，四方法各1/1。不能把同一程序的多个状态或basis副本增加为独立样本。",
              "", "冻结parser SHA256：`"+r['frozen_parser_sha256']+"`。逐条raw重新应用parser后与保存extraction/correct一致；目标值由原始可见question中的四个整数定义独立求得T1=80、T2=63，未用Gold选择生成或补写答案。这里的生成后评分不等于生成后改解析器。",
              "", "## 3. Basis单列及配对变化", "", "P-only的2个唯一输入均正确且EOS；P+实际R的4个唯一输入均正确且EOS，均无cap/未解析。它们来自相同两个程序且有输入去重，不计入主比较分母，也不证明任意读出或自然修订能力。PR中的W记录含错误R，不称为正确修订；这不替代带B/G/工作帧的W主条件。",
              "", "同期完整状态上，SharedGDirect/Compact/Stepwise彼此无修复/伤害；每个基线→VersionFrame均损失T1-E与T1-C，未获得修复。原因须结合原文区分交付格式与算术，不按1/3直接宣称模型有两次算术错误。",
              "", "## 4. 原文解释：不改主分", "",
              "- T1-E与T1-C的VersionFrame在EOS前完整输出JSON，含候选y=56、z=80及 `\"final_answer\":80`，但没有满足冻结解析器的终结答案格式。保留未解析/错误主分，不临时添加JSON救分；原文说明这两条不应被叙述为已证实算术不会。",
              "- T2-E的VersionFrame先复述大量工作帧，再给候选y=81、z=63和可解析的最终答案，419新token后EOS。它没有触512 guard，但明显比精简基线长。",
              "- 四方法共享的system均要求最终答案格式；VersionFrame用户消息中额外的JSON状态帧可能影响输出模仿，这是待检验的格式/提示猜想，当前没有隔离它的因果实验。不能用此猜想抹掉实际交付失败，也不能改称完整版本算法已失败。",
              "- 当前共享G及明确原题规则已足以让这些简单同期基线答对，独立版本机制增量没有得到支持；只有两个程序且W未跑，不能据此推广其有用或无用范围。",
              "", "## 5. 公平性、停止条件与manifest复核", "",
              f"取回清单{r['retrieved_files_verified']}个文件的bytes/SHA256通过，审计前后均未改；全部30个计划render的messages/text/token IDs与调用前冻结一致，实际19个请求与对应render一致。prelaunch、launcher、runner、adapter、原始输入、prepared消息hash、冻结parser和model manifest绑定通过。这里只核对本地证据，不重新读取远端权重。",
              "", "主请求的共享证据逐项一致；G只认证原题常数根x/r，derived_arithmetic_evaluations=0，旧y/z均UNVERIFIED，deterministic final commit禁止。没有因C组直接提交旧z。该行为仍是一轮prompt/frame，非逐节点提案check/commit。",
              "", "实际19条均正常EOS，末token属于配置EOS集合，无cap，input checkpoint长度未变；无parser停止、整数换行停止、强制尾提交或KV mask/crop的实现声明与冻结来源一致。结果只支持这些本地接口观察，不认证所有内部运行行为或自然场景。",
              "", "## 6. 成本：请求已含G/compile/prefill/decode，不重复相加", "",
              f"launcher {r['cost']['study_launcher_seconds']:.6f}秒 = {r['cost']['single_gpu_minutes']:.6f}单卡分钟；worker {r['cost']['runner_seconds']:.6f}秒。加载/哈希{r['cost']['load_hash_seconds_already_in_study']:.6f}秒已含于研究总时长。退出0表示正常停止，不改变PARTIAL范围。",
              "", "| 方法：仅同一3状态 | prompt token合计 | 生成token合计 | 请求秒合计（已含各组件） |", "|---|---:|---:|---:|"]
    for m in methods:
        c=r['cost']['paired_method_cost'][m]
        lines.append(f"|{m}|{c['prompt_tokens']}|{c['generated_tokens']}|{c['request_seconds_inclusive']:.6f}|")
    c=r['cost']
    lines += ["",f"所有19输出共{c['generated_tokens_all']}生成token、{c['prompt_tokens_all']}prompt token；{c['forward_recount']['forward_calls']}次实际forward、{c['forward_recount']['input_tokens']}累计输入token、同步forward {c['forward_recount']['synchronized_forward_seconds']:.6f}秒。逐请求forward/call与ledger、summary核对一致。",
              "",f"所有19请求的request_seconds合计{c['request_seconds_sum_includes_G_compile_prefill_decode']:.6f}秒，已经包含G {c['G_seconds_component_do_not_add']:.6f}秒与compile {c['compile_seconds_component_do_not_add']:.6f}秒等；不能再次加G/compile/prefill/decode。basis、T2-C部分块和共享准备/加载都保留为研究成本；完整配对的每方法成本不冒充完整6状态平均或独立生产加速。",
              "", "同步forward、request、worker、launcher是嵌套计时，不相加。peak为加载后观察的allocated阶段峰值，原始结束记录compute为空；本审计未连接远端重新观察。",
              "", "## 7. 全部实际raw输出", "", "下表仅列实际19条，未运行11条不生成假记录。原换行/标点保留为JSON字符串。", "", "| job | kind | 程序/组 | target | 抽取/正确 | EOS/cap | 新token | raw.text JSON |", "|---|---|---|---:|---|---|---:|---|"]
    for x in r['all_actual_raw_outputs']:
        lines.append(f"|{x['job_id']}|{x['kind']}|{x['program_id']}/{x['group'] if x['kind']=='main' else 'basis非独立组样本'}|{x['target_from_visible_question']}|{x['extraction']['value']} / {x['correct']}|{x['eos']}/{x['cap']}|{x['new_tokens']}|{raw(x['text'])}|")
    lines += ["", "## 8. 决策与下一门槛", "",
              "本轮最窄结论是：在已完成的两程序/三个相关状态上，简单共享G基线自然结束且交付正确；更长的VersionFrame没有独立质量优势，并出现两个正常EOS的格式未交付。下一步若研究格式约束或更短工作帧，须新协议、同期基线和同信息条件，不补跑本轮、不重算旧分。W/C安全性、一般合流、多布局、自然依赖、完整运行时验证及正式多数据集收益仍未建立。",
              "", "不跨P0.5作准确率提升叙事，不根据PARTIAL结果选更容易状态，不把当前两个程序变成统计功效结论。原始run未变；本独立复核无GPU、远程、训练或额外生成。",
              "", "完整机器审计：[INDEPENDENT_RESULT_AUDIT.json](D:/ACL/research/phase5_prototype_20261106/INDEPENDENT_RESULT_AUDIT.json)；源码：[independent_quality_result_audit.py](D:/ACL/research/phase5_prototype_20261106/independent_quality_result_audit.py)。",
              "", "完整性问题："+str(r['issues'])]
    (BASE/"INDEPENDENT_RESULT_AUDIT_ZH.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":main()
