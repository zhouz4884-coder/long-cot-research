"""Audit a completed/partial P0.5 saved run on CPU; never invoke its model.

Prepared before the real run directory is available. NumPy metrics are independent
of the experimental runner. Use --run-dir after artifacts arrive; no result is
created by --help. Partial diagnostics never become primary exclusions.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

import numpy as np

BASE=Path(__file__).resolve().parent
EXPECTED={"source_sha256":"91b6ed7c584bf7561073964f5dc08510ab10f7a92f35e9fa89d2efe669442742",
 "base_source_sha256":"246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b",
 "input_sha256":"6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27",
 "answer_extractor_sha256":"c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed",
 "model_manifest_sha256":"37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"}
ARMS=["FullDirect","FullOneLine","WholeEarlyDirect","WholeEarlyOneLine","WholeLateOneLine"]
CONTROL_IDS={"E01","C01","W01"}


def read(p): return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def log_probs(a):
    a=np.asarray(a,dtype=np.float64)
    return a-(a.max()+np.log(np.exp(a-a.max()).sum(dtype=np.float64)))


def metrics(a,b):
    a,b=np.asarray(a,dtype=np.float64),np.asarray(b,dtype=np.float64)
    assert a.shape==b.shape and np.isfinite(a).all() and np.isfinite(b).all()
    la,lb=log_probs(a),log_probs(b); p,q=np.exp(la),np.exp(lb)
    lm=np.log(np.maximum((p+q)/2,1e-300))
    return {"logit_max_abs":float(np.abs(a-b).max()),
       "logit_relative_l2":float(np.linalg.norm(a-b)/max(np.linalg.norm(a),1e-30)),
       "TV":float(np.abs(p-q).sum()/2),
       "JS_nats":max(0.0,float(np.sum(p*(la-lm))/2+np.sum(q*(lb-lm))/2)),
       "argmax_equal":bool(a.argmax()==b.argmax()),"exact_equal":bool(np.array_equal(a,b))}


def ev(expression,env):
    def f(n):
        if isinstance(n,ast.Constant) and type(n.value) is int: return n.value
        if isinstance(n,ast.Name): return env[n.id]
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.USub): return -f(n.operand)
        if isinstance(n,ast.BinOp):
            a,b=f(n.left),f(n.right)
            if isinstance(n.op,ast.Add): return a+b
            if isinstance(n.op,ast.Sub): return a-b
            if isinstance(n.op,ast.Mult): return a*b
            if isinstance(n.op,ast.FloorDiv) and b and a%b==0: return a//b
        raise ValueError(ast.dump(n))
    return f(ast.parse(expression,mode="eval").body)


def roles(case,family):
    rules={x["variable"]:x["expression"] for x in case["definitions"]}
    nx,ox=case["revision_root_value"],case["old_root_value"]
    ny,oy=ev(rules["y"],{"x":nx}),ev(rules["y"],{"x":ox})
    if family=="y":
        return {"trusted_y":case["oracle_values"]["y"],"old_y":oy,"revision_consistent_y":ny,"root_misbind":nx}
    return {"trusted_final":case["required_final_value"],"old_final":case["old_branch_final_value"],
      "revision_consistent_final":ev(rules["z"],{"x":nx,"y":ny}),
      "skip_signature":ev(rules["z"],{"x":nx,"y":nx})}


def max_kv(rows):
    return max((v["max_abs"] for row in rows for tensors in row["groups"].values()
                for v in tensors.values() if v is not None),default=0.0)


def recompute_control_checks(c):
    tol=c["tolerance_logit_and_KV_max_abs"]
    attn=[c["attention_check_early"],c["attention_check_late"]]
    prefill=[c["target_prefill_attention"],c["random_prefill_attention"]]
    return {"same_mask_no_delete":c["same_mask_no_delete"]["logit_max_abs"]<=tol,
      "same_mask_no_delete_KV":max_kv(c["same_mask_no_delete"]["KV"])<=tol,
      "same_mask_early_rebuild":c["same_mask_early_rebuild"]["logit_max_abs"]<=tol,
      "same_mask_early_rebuild_KV":max_kv(c["same_mask_early_rebuild"]["KV"])<=tol,
      "prefix_invariance":c["prefix_invariance_max_abs"]<=tol,
      "first_layer_invariance":c["first_layer_invariance_max_abs"]<=tol,
      "masked_sentinel":c["masked_value_sentinel_8"]["logit_max_abs"]<=tol,
      "masked_and_future_attention_zero":all(i["all_finite"] and max(i["masked_key_mass_max_per_layer"]+i["future_key_mass_max_per_layer"])==0.0 for i in attn),
      "early_prefill_target_and_random_forbidden_mass_zero":all(i["all_finite"] and max(i["masked_key_mass_max_per_layer"]+i["surviving_query_masked_key_mass_max_per_layer"]+i["future_key_mass_max_per_layer"])==0.0 for i in prefill)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--output-prefix",type=Path,default=BASE/"independent_p05_release_audit")
    parser.add_argument("--prelaunch-freeze",type=Path,default=BASE/"prelaunch_freeze_01.json")
    parser.add_argument("--rendered-inputs",type=Path,default=BASE/"rendered_inputs_01.json")
    args=parser.parse_args(); run=args.run_dir.resolve(strict=True)
    manifest=read(run/"manifest.json"); summary=read(run/"summary.json")
    assertions,partial_notes,numeric_deltas=[],[],[]
    def check(condition,message):
        if not condition: assertions.append(message)
    def compare(computed,saved,context):
        for k,v in computed.items():
            if isinstance(v,bool): check(v==saved[k],context+"/"+k)
            else:
                delta=abs(v-saved[k]); numeric_deltas.append(delta)
                check(delta<=1e-10,context+"/"+k+" diff="+str(delta))
    for k,v in EXPECTED.items(): check(manifest.get(k)==v,"manifest binding: "+k)
    freeze=read(args.prelaunch_freeze); frozen_render=read(args.rendered_inputs)
    check(sha(args.prelaunch_freeze)=="a70ff643f4f513b90bb18b0943e5595ae6c0eb4b2a842dee9abb61bcfd5029df","prelaunch freeze external anchor")
    check(sha(args.rendered_inputs)=="6ccef1ab340e99ae01172cf8e687892b9f94dd06147590f3ceb3a51e7ba6c973","rendered-input external anchor")
    remote_freeze={x["path"]:x for x in freeze["remote_files"]}
    check(remote_freeze["provenance/rendered_inputs_01.json"]["sha256"]==sha(args.rendered_inputs),"rendered-input binding in prelaunch")
    frozen_rows={r["case_id"]:r for r in frozen_render["rows"]}
    render_checks=0; json_pair_count=0
    local_files={"source_sha256":BASE/"p05_five_arm.py",
      "base_source_sha256":BASE.parent/"direction_selection_20261105"/"real_model_p0.py",
      "input_sha256":BASE.parent/"direction_selection_20261105"/"proposed_p0_cases.json",
      "answer_extractor_sha256":BASE.parent/"next_design_20261105"/"frozen_answer_extractor.py"}
    for k,p in local_files.items(): check(sha(p)==EXPECTED[k],"local binding: "+k)
    files=manifest["model_files"]["files"]
    model_digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    check(model_digest==EXPECTED["model_manifest_sha256"],"model file-list digest")
    check(not manifest.get("interface_only"),"not a real-model run")
    cases={c["case_id"]:c for c in read(local_files["input_sha256"])["cases"]}
    namespace={"__name__":"frozen_parser_audit"}
    exec(compile(local_files["answer_extractor_sha256"].read_text(encoding="utf-8"),str(local_files["answer_extractor_sha256"]),"exec"),namespace)
    extract=namespace["extract_answer"]
    order=manifest["executed_order"]; records=[]; raw_outputs=[]; all_pairs=[]
    first_logP_deltas=[]; candidate_count=probe_count=array_count=0
    control_summary=[]; expected_ledger={}
    for cid in order:
        p=run/(cid+".json")
        if not p.exists(): partial_notes.append(cid+": case not started/saved"); continue
        r=read(p); records.append(r); case=cases[cid]; core=r["rendering_core"]
        check(core==frozen_rows[cid]["core"],cid+" core equals prelaunch token freeze")
        for k,v in EXPECTED.items(): check(r.get(k)==v,cid+" binding "+k)
        check(core["visible_fields"]=={k:case[k] for k in ["question","old_branch","revision"]},cid+" visible whitelist")
        check(case["independent_conclusion"] not in "".join(core["rendered_pieces"].values()),cid+" oracle verifier rendered")
        check(core["close_assistant_text"]=="<|im_end|>\n",cid+" assistant closure")
        check(core["prefix_position_ids"]==list(range(len(core["prefix_ids"]))),cid+" prefix positions")
        check(core["target_columns"]==list(range(*core["segments"]["B"])),cid+" target B addresses")
        bank={}; npz=run/(cid+"_logits.npz")
        if npz.exists():
            try:
                with np.load(npz,allow_pickle=False) as z: bank={k:z[k].copy() for k in z.files}
            except Exception as exc: partial_notes.append(cid+": unreadable NPZ: "+str(exc))
        else: partial_notes.append(cid+": no NPZ saved")
        for k,a in bank.items():
            check(a.shape==(manifest["model_config"]["vocab_size"],),cid+"/"+k+" shape")
            check(a.dtype==np.float32 and bool(np.isfinite(a).all()),cid+"/"+k+" finite float32")
            array_count+=1
        control=r.get("controls")
        if cid in CONTROL_IDS:
            if control is None: control_summary.append({"case_id":cid,"state":"NOT_FINISHED"})
            else:
                independent_checks=recompute_control_checks(control)
                check(control.get("checks")==independent_checks,cid+" independent control reduction")
                check(bool(control.get("passed"))==all(independent_checks.values()),cid+" control passed reduction")
                control_summary.append({"case_id":cid,"state":"PASS" if control.get("passed") else "FAIL","checks":control.get("checks")})
        else:
            check(control is None or control.get("passed") is None,cid+" falsely claimed full controls")
            control_summary.append({"case_id":cid,"state":"NOT_RUN_AS_PREDECLARED"})
        completed=all(a in r.get("arms",{}) and "free" in r["arms"][a] for a in ARMS)
        check(bool(r["primary_complete"])==completed,cid+" primary flag")
        diagnostics=[]
        for arm,ac in r.get("arms",{}).items():
            masked=arm.startswith("Whole"); expected_columns=core["target_columns"] if masked else []
            check(ac["mask_columns"]==expected_columns,cid+"/"+arm+" mask")
            spec,fr=ac["free_rendering"]["spec"],ac["free_rendering"]
            frozen_free=frozen_rows[cid]["renders"][arm]["free"]
            check(fr["ids"]==frozen_free["readout_ids"] and spec==frozen_free["readout_spec"],cid+"/"+arm+" free token/text freeze")
            check(fr["position_ids"]==frozen_free["position_ids"][len(core["prefix_ids"]):],cid+" free frozen positions")
            render_checks+=1
            check(spec["family"]=="free" and not any(k in spec["text"] for k in ["required_final_value","oracle_values"]),cid+" free spec")
            check(fr["position_ids"]==list(range(len(core["prefix_ids"]),len(core["prefix_ids"])+len(fr["ids"]))),cid+" free positions")
            parsed=extract(ac["free"]["text"])
            check(parsed==ac["extraction"],cid+"/"+arm+" frozen extraction")
            check(ac["evaluation"]["correct"]==(parsed["value"]==case["required_final_value"] if parsed["value"] is not None else False),cid+"/"+arm+" accuracy")
            raw_outputs.append({"case_id":cid,"arm":arm,"text":ac["free"]["text"],"extraction":parsed})
            if arm+"__free" not in bank: partial_notes.append(cid+": missing saved "+arm+"__free")
            expected_ledger[(cid,arm+"_free_readout")]=(1,len(fr["ids"]))
            expected_ledger[(cid,arm+"_free_greedy")]=(ac["free"]["additional_forward_tokens"],ac["free"]["additional_forward_tokens"])
            for family,probe in ac.get("probes",{}).items():
                probe_count+=1; s=probe["scores"]; expected_roles=roles(case,family)
                frozen_probe=frozen_rows[cid]["renders"][arm][family]
                check(probe["rendering"]["ids"]==frozen_probe["readout_ids"] and probe["rendering"]["spec"]==frozen_probe["readout_spec"],cid+"/"+arm+"/"+family+" probe freeze")
                check(probe["rendering"]["position_ids"]==frozen_probe["position_ids"][len(core["prefix_ids"]):],cid+" probe frozen positions")
                render_checks+=1
                check(s["roles_evaluator_only"]==expected_roles,cid+"/"+arm+family+" roles")
                check(s["used_to_choose_free_output"] is False,cid+" candidate output selection")
                cache_len=len(core["prefix_ids"])+len(probe["rendering"]["ids"])
                check(s["readout_cache_length_before_after"]==[cache_len,cache_len],cid+" candidate cache mutation")
                lookup={}; forward_calls=forward_tokens=0
                key=arm+"__"+family
                if key not in bank: partial_notes.append(cid+": missing saved "+key)
                for candidate in s["unique_candidates"]:
                    candidate_count+=1; ids=candidate["token_ids"]
                    check(abs(math.fsum(candidate["token_logP"])-candidate["logP"])<=1e-10,cid+" candidate full sum")
                    check(candidate["continuation"].endswith("\n") and candidate["length_normalization"]=="none",cid+" candidate canonical form")
                    check(candidate["teacher_forced_input_tokens"]==len(ids)-1,cid+" candidate token accounting")
                    check(candidate["candidate_forward_calls"]==int(len(ids)>1),cid+" candidate call accounting")
                    forward_calls+=int(len(ids)>1); forward_tokens+=len(ids)-1
                    for alias in candidate["role_aliases"]:
                        check(alias not in lookup,cid+" duplicated role alias")
                        check(candidate["continuation"]==str(expected_roles[alias])+"\n",cid+" alias value")
                        lookup[alias]=candidate
                    if key in bank:
                        lp=float(log_probs(bank[key])[ids[0]])
                        delta=abs(lp-candidate["token_logP"][0]); first_logP_deltas.append(delta)
                        check(delta<=5e-5+4*np.finfo(np.float32).eps*abs(lp),cid+" first-token logP precision")
                check(set(lookup)==set(expected_roles),cid+" incomplete role aliases")
                for pair in s["pairwise_role_margins"]:
                    a,b=lookup[pair["left"]],lookup[pair["right"]]
                    alias=a["token_ids"]==b["token_ids"]; samefirst=a["token_ids"][0]==b["token_ids"][0]
                    check(pair["same_full_candidate"]==alias and pair["same_first_token"]==samefirst,cid+" pair collision flags")
                    check((pair["full_log_odds_left_minus_right"] is None)==alias,cid+" alias full NA")
                    if not alias: check(abs(pair["full_log_odds_left_minus_right"]-(a["logP"]-b["logP"]))<=1e-10,cid+" full margin")
                    check((pair["first_token_log_odds_interpretable"] is None)==samefirst,cid+" first NA")
                reuse=family=="z" and arm in ["FullDirect","WholeEarlyDirect"]
                check(probe["readout_additional_forward_calls"]==int(not reuse),cid+" probe call reuse")
                if reuse: check(probe["rendering"]["ids"]==fr["ids"],cid+" exact Direct/Z reuse")
                expected_ledger[(cid,arm+"_"+family+"_candidate_scoring")]=(forward_calls,forward_tokens)
                if not reuse: expected_ledger[(cid,arm+"_"+family+"_probe_readout")]=(1,len(probe["rendering"]["ids"]))
            done=set(ac.get("probes",{}))=={"z","y"}
            if ac["diagnostics_complete"]:
                check(done,cid+"/"+arm+" true diagnostic flag without both families")
            elif done:
                partial_notes.append(cid+"/"+arm+": both probes saved before conservative completion flag was committed")
            diagnostics.append(done)
        if r["diagnostic_complete"]:
            check(completed and all(diagnostics),cid+" true full diagnostic flag without complete data")
        for family in ["free","z","y"]:
            a,b="WholeLateOneLine__"+family,"WholeEarlyOneLine__"+family
            if a in bank and b in bank:
                result=metrics(bank[a],bank[b]); context=family+"__WholeLateOneLine__WholeEarlyOneLine"
                recorded=r.get("pairwise_probe_logits",{}).get(context)
                all_pairs.append({"case_id":cid,"family":family,"metrics":result,"JSON_comparison_available":recorded is not None})
        for context,saved in r.get("pairwise_probe_logits",{}).items():
            family,left,right=context.split("__")
            a,b=left+"__"+family,right+"__"+family
            if a in bank and b in bank:
                compare(metrics(bank[a],bank[b]),saved,cid+"/"+context)
                json_pair_count+=1
            else: partial_notes.append(cid+": recorded comparison lacks NPZ arrays "+context)
        if completed:
            arms=r["arms"]
            check(arms["FullOneLine"]["free_rendering"]["ids"]==arms["WholeEarlyOneLine"]["free_rendering"]["ids"]==arms["WholeLateOneLine"]["free_rendering"]["ids"],cid+" same OneLine suffix")
    ledger_paths=[p for p in [run/"forward_ledger.json",run/"forward_ledger_at_deadline.json"] if p.exists()]
    ledger=max((read(p) for p in ledger_paths),key=len) if ledger_paths else []
    for (cid,stage),(count,tokens) in expected_ledger.items():
        actual=[x for x in ledger if x["case_id"]==cid and x["stage"]==stage]
        check(len(actual)==count and sum(x["input_tokens"] for x in actual)==tokens,cid+" ledger "+stage)
    lastfree=max((i for i,x in enumerate(ledger) if str(x["stage"]).endswith("_free_greedy")),default=-1)
    firstscore=min((i for i,x in enumerate(ledger) if str(x["stage"]).endswith("_candidate_scoring")),default=len(ledger))
    check(lastfree<firstscore,"candidate scoring before primary generation ended")
    cost={"forward_calls":len(ledger),"input_tokens":sum(x["input_tokens"] for x in ledger),"synchronized_forward_seconds":sum(x["seconds"] for x in ledger)}
    oldcost=summary.get("actual_forward_cost",{})
    for key,value in cost.items():
        if abs(value-oldcost.get(key,float("nan")))>1e-8:
            if (run/"deadline.json").exists(): partial_notes.append("summary cost predates deadline ledger: "+key)
            else: check(False,"summary cost "+key)
    primary=[r["case_id"] for r in records if r["primary_complete"]]
    diagnostic=[r["case_id"] for r in records if r["diagnostic_complete"]]
    if (run/"deadline.json").exists():
        if summary["primary_complete_ids"]!=primary: partial_notes.append("summary primary IDs predate deadline case packets")
        if summary["diagnostic_complete_ids"]!=diagnostic: partial_notes.append("summary diagnostic IDs predate deadline case packets")
    else:
        check(summary["primary_complete_ids"]==primary,"primary denominator/IDs")
        check(summary["diagnostic_complete_ids"]==diagnostic,"diagnostic denominator/IDs")
    paired=[r for r in records if r["case_id"] in summary["primary_complete_ids"]]
    for arm in ARMS:
        for group,saved in summary["primary_accuracy"][arm].items():
            selected=[r for r in paired if group=="all" or r["evaluation_metadata"]["group"]==group]
            expected={"n":len(selected),"correct":sum(r["arms"][arm]["evaluation"]["correct"] for r in selected),
                      "parsed":sum(r["arms"][arm]["evaluation"]["parsed_value"] is not None for r in selected)}
            check(saved==expected,arm+" summary primary accuracy "+group)
    complete=len(primary)==len(order) and len(diagnostic)==len(order) and not partial_notes
    result={"status":"FAIL_AUDIT" if assertions else "PASS_COMPLETE_ARTIFACT_AUDIT" if complete else "PASS_AVAILABLE_ARTIFACT_AUDIT_PARTIAL_RUN",
      "run_dir":str(run),"audit_source_sha256":sha(__file__),"expected_bindings":EXPECTED,
      "binding_scope":"Local source/input/parser and recorded remote model hash list; remote model bytes are not re-read.",
      "prelaunch_binding":{"freeze_sha256":sha(args.prelaunch_freeze),"rendered_inputs_sha256":sha(args.rendered_inputs),
        "core_records_matched":len(records),"free_and_probe_renderings_matched":render_checks,
        "time_scope":"Hash/render bindings independently checked; BEFORE_NEW_GPU_OUTPUTS ordering uses the prelaunch record and parent execution evidence."},
      "errors":assertions,"partial_notes":partial_notes,"run_status":summary["status"],
      "primary_complete_ids":primary,"diagnostic_complete_ids":diagnostic,"planned_ids":order,
      "validated_primary_accuracy":summary["primary_accuracy"],
      "free_generated_tokens":sum(a["free"]["new_tokens"] for r in records for a in r.get("arms",{}).values()),
      "arrays_checked":array_count,"probes_checked":probe_count,"unique_candidates_checked":candidate_count,
      "all_saved_JSON_pair_comparisons_recomputed":json_pair_count,"numeric_metric_comparisons":len(numeric_deltas),
      "independent_numpy_metric_max_abs_difference":max(numeric_deltas,default=None),
      "first_token_numpy_float64_vs_original_float32_max_abs_logP_difference":max(first_logP_deltas,default=None),
      "candidate_scope":"Complete logP sums and initial-logit probability checked; later teacher-forced raw logits not saved, not independently re-forwarded.",
      "controls":control_summary,"late_vs_early_pairs":all_pairs,"all_free_outputs":raw_outputs,
      "actual_forward_cost":cost,"last_free_ledger_index":lastfree,"first_candidate_ledger_index":firstscore,
      "recorded_total_wall_seconds":summary["elapsed_seconds"],"recorded_load_hash_seconds":manifest.get("load_and_hash_seconds"),
      "artifact_snapshot_hashes":[{"file":p.name,"sha256":sha(p),"bytes":p.stat().st_size}
        for p in sorted(run.iterdir()) if p.is_file()],
      "no_GPU_or_remote_calls":True,"no_algorithm_conclusion_generated":True}
    args.output_prefix.parent.mkdir(parents=True,exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["status","errors","partial_notes","arrays_checked","probes_checked","unique_candidates_checked","primary_complete_ids","diagnostic_complete_ids","actual_forward_cost"]},ensure_ascii=False,indent=2))
    return int(bool(assertions))


if __name__=="__main__": raise SystemExit(main())
