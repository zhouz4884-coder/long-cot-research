"""Read-only final integrity/count audit across original and completion waves.

No evaluator/Gold, grading, model or remote access. Run after final retrieval.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
MODEL_SHA = "37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"
GPUS = ["GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a", "GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28"]
METHODS = ["ForcedBoxCue","FullContinue","FullContract","FullContractEvidence","TailContract","ProjectedContractEvidence","RestartP"]

def read(path): return json.loads(path.read_text(encoding="utf-8"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    checks=[];issues=[];observations=[]
    def check(name, condition):
        checks.append({"name":name,"pass":bool(condition)})
        if not condition:issues.append(name)
    freeze_counts={}
    for filename in ("prelaunch_freeze.json","resume_freeze.json"):
        f=read(ROOT/filename);freeze_counts[filename]=len(f["files"])
        for row in f["files"]:
            path=ROOT/row["path"]
            if row["path"]=="p0_base_frozen.py":path=ROOT.parent/"direction_selection_20261105/real_model_p0.py"
            check(filename+":"+row["path"],path.exists() and sha(path)==row["sha256"] and path.stat().st_size==row["bytes"])
    retrieval_counts={}
    for filename in ("ORIGINAL_WAVE_RETRIEVAL.json","RETRIEVAL_MANIFEST.json"):
        m=read(ROOT/filename);retrieval_counts[filename]=len(m["files"])
        for row in m["files"]:
            path=ROOT/row["path"]
            check(filename+":"+row["path"],path.exists() and sha(path)==row["sha256"] and path.stat().st_size==row["bytes"])
    jobs=read(ROOT/"jobs.json");compiled=read(ROOT/"rendered_prelaunch.json");expected={r["job_id"]:r for r in compiled}
    bank=[json.loads(x) for x in (ROOT/"bank_visible.jsonl").read_text(encoding="utf-8").splitlines()]
    check("224_unique_frozen_jobs",len(jobs)==len(compiled)==len(expected)==224)
    check("32_distinct_questions",len(bank)==len({r["problem_id"] for r in bank})==32)
    bank_manifest=read(ROOT/"NATURAL_BANK_MANIFEST.json")
    bank_origins={r["problem_id"]:r for r in bank_manifest["cases"]}
    q_groups={};t_groups={};q_normalized={}
    for record in bank:
        qsha=hashlib.sha256(record["question"].encode("utf-8")).hexdigest()
        tsha=hashlib.sha256(record["trace_text"].encode("utf-8")).hexdigest()
        nsha=hashlib.sha256(re.sub(r"\s+"," ",record["question"]).strip().encode("utf-8")).hexdigest()
        q_groups.setdefault(qsha,[]).append(record["problem_id"])
        t_groups.setdefault(tsha,[]).append(record["problem_id"])
        q_normalized.setdefault(nsha,[]).append(record["problem_id"])
        origin=bank_origins[record["problem_id"]]
        check("bank_source_hashes:"+record["bank_id"],qsha==origin["question_utf8_sha256"] and tsha==origin["trace_text_sha256_utf8"])
    exact_q_dupes=[v for v in q_groups.values() if len(v)>1]
    normalized_q_dupes=[v for v in q_normalized.values() if len(v)>1]
    trace_dupes=[v for v in t_groups.values() if len(v)>1]
    if exact_q_dupes or normalized_q_dupes:observations.append("Duplicate question text across IDs; do not call all32 independent semantic questions.")
    check("render_jobs_fields",all({k:r[k] for k in j}==j for r,j in zip(compiled,jobs)))
    check("render_total595893_max9528",sum(r["prompt_tokens"] for r in compiled)==595893 and max(r["prompt_tokens"] for r in compiled)==9528)
    for row in compiled:check("promptIDs:"+row["job_id"],row["prompt_tokens"]==len(row["prompt_ids"]))
    spec=importlib.util.spec_from_file_location("p5c_integrity_inputs",ROOT/"paired_readout.py")
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    rebuilt,packets=original.prepare(ROOT)
    check("rebuilt_inputs_no_eval",rebuilt==jobs and packets==read(ROOT/"evidence_packets.json"))
    for rank in range(1,33):
        check(f"rank{rank}:7methods",{r["method"] for r in jobs if r["rank"]==rank}==set(METHODS))
        a,b=expected[f"{rank:02}__FullContractEvidence"],expected[f"{rank:02}__ProjectedContractEvidence"]
        check(f"rank{rank}:same_packet_contract",a["shared_packet_sha256"]==b["shared_packet_sha256"] and a["contract_hash"]==b["contract_hash"])
    cpu=read(ROOT/"CPU_BATCH_INTERFACE.json");helper=read(ROOT/"CPU_CONTRACT_CHECKS.json");resume_cpu=read(ROOT/"CPU_RESUME_PLANNER.json")
    check("batchCPU49",cpu["status"]=="PASS" and cpu["passed"]==49 and cpu["paired_readout_source_sha256"]==sha(ROOT/"paired_readout.py"))
    check("helperCPU46",helper["status"]=="PASS" and helper["passed"]==46 and helper["source_sha256"]==sha(ROOT/"goal_evidence.py"))
    check("resumeCPU33",resume_cpu["status"]=="PASS" and resume_cpu["passed"]==33 and resume_cpu["planner_sha256"]==sha(ROOT/"resume_planner.py"))
    from resume_planner import plan_resume
    previous=read(ROOT.parent/"phase5b_boundary_20261106/results/round_01/manifest.json")
    check("EOS_reference_same_assets",previous["model_files"]["manifest_sha256"]==MODEL_SHA)
    eos=set(previous["eos_ids"]);eos_source="Prior exact37ff-asset manifest"
    generation_candidates=list(ROOT.rglob("observed_model_generation_config.json"))+list(ROOT.rglob("generation_config.json"))+list(ROOT.rglob("model_generation_config.json"))
    generation_file=generation_candidates[0] if generation_candidates else None
    if generation_file:
        config=read(generation_file);value=config["eos_token_id"];fresh=set(value if isinstance(value,list) else [value])
        check("current_generation_config_EOS_matches",fresh==eos);eos=fresh;eos_source=str(generation_file.relative_to(ROOT))
    else:observations.append("Current generation_config absent; EOS check uses earlier same-asset manifest, not a remote reread.")
    def validate_row(row,label,worker):
        jid=row["job_id"];check(label+":known",jid in expected)
        if jid not in expected:return
        p=expected[jid]
        check(label+":identity",row["rank"]==p["rank"] and row["bank_id"]==p["bank_id"] and row["method"]==p["method"] and (row["rank"]-1)%2==worker)
        check(label+":input_metadata",row["prompt_tokens"]==p["prompt_tokens"] and row["contract_hash"]==p["contract_hash"] and row["shared_packet_sha256"]==p["shared_packet_sha256"])
        ids=row["token_ids"];first=next((i for i,v in enumerate(ids) if v in eos),None)
        check(label+":token_count",row["new_tokens"]==len(ids) and 1<=len(ids)<=384)
        check(label+":EOS_cap",(row["eos_reached"] and not row["hit_cap"] and first==len(ids)-1) or (not row["eos_reached"] and row["hit_cap"] and first is None and len(ids)==384))
        check(label+":scoreprefix",row["answer_text"]==p["scoring_prefix"]+row["text"])
    authoritative={};all_batches=[];all_discard=[];wave_info=[]
    for wave in ("worker","resume_worker"):
        for worker in (0,1):
            name=f"{wave}_{worker}";folder=ROOT/"results"/name
            rows=[]
            for path in sorted(folder.glob("*.json")):
                if re.fullmatch(r"\d{2}__[A-Za-z]+\.json",path.name):
                    row=read(path);validate_row(row,name+":"+path.stem,worker)
                    check(name+":"+path.stem+":filename",path.stem==row["job_id"]);rows.append(row)
            current={r["job_id"]:r for r in rows};check(name+":unique_rows",len(current)==len(rows))
            summary=read(folder/"summary.json") if (folder/"summary.json").exists() else None
            manifest=read(folder/"manifest.json") if (folder/"manifest.json").exists() else None
            if manifest:
                files=manifest["model_files"];aggregate=hashlib.sha256(json.dumps(files["files"],sort_keys=True).encode()).hexdigest()
                check(name+":model",files["manifest_sha256"]==aggregate==MODEL_SHA)
                check(name+":binding",manifest["GPU"]==GPUS[worker] and manifest["worker"]==worker)
                check(name+":runtime",manifest["torch"]=="2.8.0+cu128" and manifest["transformers"]=="4.55.2" and manifest["backend"]=="sdpa" and manifest["guard"]==384)
                check(name+":source",manifest["source_sha256"]==sha(ROOT/("paired_readout.py" if wave=="worker" else "resume_worker.py")))
                if wave=="resume_worker":
                    check(name+":same_generator",manifest["original_generator_sha256"]==sha(ROOT/"paired_readout.py") and manifest["resume_planner_sha256"]==sha(ROOT/"resume_planner.py") and manifest["same_generate_batch_function"] and manifest["seed"]==20261106)
                else:check(name+":dtype",manifest["dtype"]=="FP16" and manifest["batch_size_max"]==2 and manifest["greedy"])
                if generation_file:
                    gf=[f for f in files["files"] if f["name"]=="generation_config.json"]
                    check(name+":generation_asset",len(gf)==1 and gf[0]["sha256"]==sha(generation_file))
            else:check(name+":no_unattested_output",not rows)
            discarded=read(folder/"discarded_recomputations.json") if (folder/"discarded_recomputations.json").exists() else []
            discard_map={r["job_id"]:r for r in discarded};check(name+":discard_unique",len(discard_map)==len(discarded))
            for row in discarded:
                validate_row(row,name+":discard:"+row["job_id"],worker)
                check(name+":discard_prior_exists:"+row["job_id"],row["job_id"] in authoritative and row["job_id"] not in current)
            plan=None
            if wave=="resume_worker":
                prior=[r for r in authoritative.values() if (r["rank"]-1)%2==worker]
                plan=plan_resume(compiled,worker,prior)
                check(name+":plan_rebuilt_by_existence",plan==read(folder/"resume_plan.json"))
                check(name+":writes_only_missing",set(current)<=set(plan["missing_job_ids"]))
            batches=read(folder/"batches.json") if (folder/"batches.json").exists() else []
            touched=[];physical_generated=0
            for i,batch in enumerate(batches):
                label=name+":batch"+str(i);ids=batch["rows"];touched.extend(ids)
                check(label+":available",all(j in current or j in discard_map for j in ids))
                if not all(j in current or j in discard_map for j in ids):continue
                group=[current[j] if j in current else discard_map[j] for j in ids];width=max(expected[j]["prompt_tokens"] for j in ids);B=len(ids);n=max(r["new_tokens"] for r in group);calls=batch["forward_calls"]
                check(label+":forward_shapes",len(calls)==n and calls[0]["batch"]==B and calls[0]["sequence"]==width and all(c["batch"]==B and c["sequence"]==1 for c in calls[1:]))
                check(label+":physical",batch["physical_forward_input_tokens"]==sum(c["physical_input_tokens"] for c in calls)==B*(width+n-1) and all(c["physical_input_tokens"]==c["batch"]*c["sequence"] for c in calls))
                check(label+":logical",batch["logical_generated_tokens"]==sum(r["new_tokens"] for r in group))
                check(label+":padding",batch["padded_prefill_tokens"]==B*width and batch["unpadded_prompt_tokens"]==sum(expected[j]["prompt_tokens"] for j in ids))
                physical_generated+=sum(r["new_tokens"] for r in group)
                if plan:
                    planned={b["batch_id"]:b for b in plan["batches"]};pb=planned.get(batch.get("batch_id"))
                    check(label+":original_pair_shape",pb is not None and pb["job_ids"]==ids and pb["discard_job_ids"]==batch["discard_existing_ids"])
            check(name+":rows_and_batches",sorted(touched)==sorted(list(current)+list(discard_map)))
            if summary:
                check(name+":summary_outputs",summary["outputs"]==len(current))
                if wave=="worker":
                    complete=[r for r in sorted({v["rank"] for v in rows}) if sum(v["rank"]==r for v in rows)==7]
                    check(name+":summary_counts",summary["planned"]==112 and summary["complete_cases"]==complete and summary["EOS"]==sum(r["eos_reached"] for r in rows) and summary["caps"]==sum(r["hit_cap"] for r in rows))
                    check(name+":summary_tokens",summary["logical_generated_tokens"]==sum(r["new_tokens"] for r in rows) and summary["physical_forward_input_tokens"]==sum(b["physical_forward_input_tokens"] for b in batches))
                else:
                    check(name+":summary_missing",summary["planned_missing"]==len(plan["missing_job_ids"]) and summary["job_ids"]==[j for b in plan["batches"] for j in b["missing_job_ids"]])
                    check(name+":complete_missing",summary["status"]=="COMPLETE" and set(current)==set(plan["missing_job_ids"]))
                    if "discarded_recomputed_rows" in summary:check(name+":summary_discard",summary["discarded_recomputed_rows"]==len(discarded))
            else:observations.append(name+": final summary absent; partial scope only")
            check(name+":no_cross_wave_duplicate",not(set(authoritative)&set(current)))
            authoritative.update(current);all_batches.extend(batches);all_discard.extend(discarded)
            wave_info.append({"directory":name,"authoritative_outputs":len(current),"discarded_recomputations":len(discarded),"batches":len(batches),"summary_status":None if summary is None else summary["status"],"actual_generation_including_discard":physical_generated})
    launchers=[]
    for filename in ("launcher.json","resume_launcher.json"):
        l=read(ROOT/filename);actual=sum(r["elapsed_seconds"] for r in l["workers"].values())
        check(filename+":finished",l["status"]=="FINISHED")
        check(filename+":worker_UUIDs",all(l["workers"][str(w)]["gpu"]==GPUS[w] for w in (0,1)))
        check(filename+":sum_GPU_seconds",abs(actual-l["conservative_aggregate_GPU_seconds"])<1e-6)
        check(filename+":GPU_minutes",abs(actual/60-l["conservative_GPU_minutes"])<1e-6)
        if filename=="resume_launcher.json":check(filename+":exit0",all(r.get("exit_code")==0 for r in l["workers"].values()))
        if l.get("ending_compute_processes","").strip():observations.append(filename+": nonempty endcompute snapshot; needs PID ownership check, not automatic evidence of leftover model")
        launchers.append({"filename":filename,"GPU_seconds":actual,"workers":l["workers"]})
    study=read(ROOT/"STUDY_STATUS.json")
    check("final224authoritative",len(authoritative)==224 and set(authoritative)==set(expected))
    complete7=[rank for rank in range(1,33) if all(f"{rank:02}__{m}" in authoritative for m in METHODS)]
    check("final32complete7",len(complete7)==32)
    check("STUDY_STATUS_agrees",study["status"]=="FINISHED" and study["completed_unique"]==224 and study["duplicates"]==0 and not study["missing_ids"])
    check("STUDY_GPU_waves_agree",abs(study["original_GPU_minutes"]-launchers[0]["GPU_seconds"]/60)<1e-6 and abs(study["resume_GPU_minutes"]-launchers[1]["GPU_seconds"]/60)<1e-6)
    rows=list(authoritative.values());generated=sum(r["new_tokens"] for r in rows);discard_tokens=sum(r["new_tokens"] for r in all_discard)
    check("generation_discard_accounted",sum(b["logical_generated_tokens"] for b in all_batches)==generated+discard_tokens)
    report={"status":"PASS" if not issues else "FAIL","issues":issues,"observations":observations,"checks_passed":sum(c["pass"] for c in checks),"checks_total":len(checks),"checks":checks,
            "planned_distinct_questions":32,"planned_outputs":224,"authoritative_outputs":len(rows),"complete7_ranks":complete7,"missing_jobs":sorted(set(expected)-set(authoritative)),"wave_details":wave_info,
            "bank_distinctness":{"unique_problem_IDs":len({r["problem_id"] for r in bank}),"exact_question_SHA_unique":len(q_groups),"whitespace_normalized_question_SHA_unique":len(q_normalized),"exact_trace_SHA_unique":len(t_groups),"exact_question_duplicate_ID_groups":exact_q_dupes,"whitespace_normalized_question_duplicate_ID_groups":normalized_q_dupes,"exact_trace_duplicate_ID_groups":trace_dupes,"semantic_note":"Exact/whitespace identity audit only; different wording is not a proof of semantic or statistical independence."},
            "discarded_recomputed_rows":len(all_discard),"discarded_generated_tokens":discard_tokens,"authoritative_generated_tokens":generated,"all_computed_generated_tokens":generated+discard_tokens,
            "physical_forward_input_tokens":sum(b["physical_forward_input_tokens"] for b in all_batches),"batch_count":len(all_batches),
            "condition_counts":{m:{"n":sum(r["method"]==m for r in rows),"EOS":sum(r["method"]==m and r["eos_reached"] for r in rows),"cap":sum(r["method"]==m and r["hit_cap"] for r in rows),"generated_tokens":sum(r["new_tokens"] for r in rows if r["method"]==m)} for m in METHODS},
            "freeze_files_verified":freeze_counts,"retrieval_files_verified":retrieval_counts,"EOS_ids":sorted(eos),"EOS_config_source":eos_source,
            "all_waves_GPU_seconds":sum(l["GPU_seconds"] for l in launchers),"launcher_details":launchers,"original30GPUmin_is_not_current_gate":True,
            "scope":"Only saved-byte/source/input/coverage/EOS/cap/physical-count integrity. No Gold/correctness grading, no independent output-text decoding or remote weights reread. User-authorized resumption counts all waves/discard costs."}
    (ROOT/"RESULT_INTEGRITY.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    text=f'''# Phase5-C 两wave结果完整性独立核对\n\n2026-11-06。审计状态 **{report['status']}**。只读本地取回数据，不读Gold/评价文件、不打正确率分、不运行模型/远程/GPU。\n\n- 预定32个不同ID、7条件、224输出；authoritative {len(rows)}，七条件完整{len(complete7)}题。\n- 原wave与续wave共{len(all_batches)}批；弃用重复计算{len(all_discard)}行，不作为第二份答案。\n- authoritative生成{generated} tokens，弃用生成{discard_tokens}，全部实际生成合计{generated+discard_tokens}；physical forward输入{report['physical_forward_input_tokens']}，含padding及已EOS行后续批处理。\n- 两wave外层GPU时间合计{report['all_waves_GPU_seconds']:.6f}秒={report['all_waves_GPU_seconds']/60:.6f}单卡分钟。用户已撤销原30分钟停止线，旧protocol保留历史，不用旧上限判本轮失败。\n- source/CPU/freeze、原wave下载SHA保持、最终取回SHA、224预渲染输入与case/job映射、同packet对照、逐批形状/物理计账、resumption存在性计划及STUDY_STATUS已逐项核对。\n- 通过{report['checks_passed']}/{report['checks_total']}项；issues={issues}；observations={observations}。\n\n逐wave范围、各条件EOS/cap和所有机器核查见RESULT_INTEGRITY.json。本审计不替代最终数学评分或因果/泛化结论；raw仅保存长度/指纹并由冻结源码校验输入重建，未另追踪GPU张量的每个实参。\n'''
    (ROOT/"RESULT_INTEGRITY_ZH.md").write_text(text,encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("checks","launcher_details")},ensure_ascii=False,indent=2))
    if issues:raise SystemExit(2)

if __name__=="__main__":main()
