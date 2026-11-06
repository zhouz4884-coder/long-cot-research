"""CPU-only post-generation scoring and exploratory paired analysis.

The launcher FINISHED gate is checked before any bank/Gold/result read. No
generation, online checking, sample replacement or grader mutation occurs here.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

PROJECTED = "ProjectedContractEvidence"
REQUIRED_METHODS = ["ForcedBoxCue", "FullContinue", "FullContract", "FullContractEvidence",
                    "TailContract", PROJECTED, "RestartP"]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,obj):
    path=Path(path);tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    os.replace(tmp,path)


def require_finished(root):
    path=Path(root)/"launcher.json"
    if not path.is_file(): raise RuntimeError("Generation gate: launcher.json absent; evaluation is forbidden")
    launcher=json.loads(path.read_text(encoding="utf-8"))
    if launcher.get("status")!="FINISHED":
        raise RuntimeError("Generation gate: launcher.status must be FINISHED before reading any Gold or outputs")
    return launcher


def exact_mcnemar_two_sided(wins,losses):
    if type(wins) is not int or type(losses) is not int or min(wins,losses)<0:raise ValueError("Nonnegative integer discordances required")
    n=wins+losses
    if n==0:p=1.0
    else:p=min(1.0,2*sum(math.comb(n,k) for k in range(min(wins,losses)+1))/2**n)
    return {"p_two_sided":p,"discordant_n":n,"definition":"min(1, 2*BinomialCDF(min(wins,losses); wins+losses, .5))",
            "scope":"Exploratory exact paired McNemar/binomial, no multiplicity correction or generalization proof"}


def paired(rows,left,right,case_ids):
    available=[];resolved=[];unknown=[];missing=[];w=[];l=[];tt=[];ff=[]
    for bank_id in case_ids:
        a,b=rows.get((bank_id,left)),rows.get((bank_id,right))
        if a is None or b is None:missing.append(bank_id);continue
        available.append(bank_id);ca,cb=a["grade"].get("correct"),b["grade"].get("correct")
        if type(ca) is not bool or type(cb) is not bool:unknown.append(bank_id);continue
        resolved.append(bank_id)
        if ca and not cb:w.append(bank_id)
        elif cb and not ca:l.append(bank_id)
        elif ca:tt.append(bank_id)
        else:ff.append(bank_id)
    return {"left":left,"right":right,"planned_n":len(case_ids),"both_delivered_n":len(available),
            "resolved_paired_n":len(resolved),"paired_case_ids":resolved,"unknown_pair_case_ids":unknown,"missing_pair_case_ids":missing,
            "win":len(w),"loss":len(l),"tie":len(tt)+len(ff),"tie_both_correct":len(tt),"tie_both_incorrect_or_unparsed":len(ff),
            "net_wins":len(w)-len(l),"win_case_ids":w,"loss_case_ids":l,"mcnemar":exact_mcnemar_two_sided(len(w),len(l)),
            "denominator_note":"Pairs exclude only explicitly missing/grade-unknown rows; no correctness-based inclusion. Unparsed False remains a scored delivery failure."}


def summarize(grades,case_ids,methods):
    rows={(r["bank_id"],r["method"]):r for r in grades}
    if len(rows)!=len(grades):raise ValueError("Duplicate scored bank/method row")
    n=len(case_ids);out={"planned_questions":n,"planned_outputs":n*len(methods),"scored_delivered_outputs":len(grades),"methods":{}}
    for method in methods:
        rr=[rows[(c,method)] for c in case_ids if (c,method) in rows]
        unknown=sum(type(r["grade"].get("correct")) is not bool for r in rr)
        correct=sum(r["grade"].get("correct") is True for r in rr)
        unparsed=sum(r["grade"].get("extraction",{}).get("status")!="ok" or r["grade"].get("status")=="math_parse_failed" for r in rr)
        missing=n-len(rr)
        out["methods"][method]={"planned":n,"delivered":len(rr),"missing":missing,"gradeunknown":unknown,
            "unparsed":unparsed,"cap":sum(r["readout"]["hit_cap"] for r in rr),"EOS":sum(r["readout"]["eos_reached"] for r in rr),
            "correct":correct,"EOS_and_correct":sum(r["readout"]["eos_reached"] and r["grade"].get("correct") is True for r in rr),
            "confirmed_accuracy_planned":correct/n if n else None,
            "accuracy_bounds_from_missing_and_gradeunknown":[correct/n,(correct+missing+unknown)/n] if n else None,
            "confirmed_accuracy_among_resolved":correct/(len(rr)-unknown) if len(rr)>unknown else None,
            "prompt_tokens":sum(r["readout"]["prompt_tokens"] for r in rr),"generated_tokens":sum(r["readout"]["new_tokens"] for r in rr),
            "denominator_note":"All planned questions remain. Missing/unknown are unresolved, not claims of mathematical wrongness; cap/unparsed not removed."}
    complete=[c for c in case_ids if all((c,m) in rows for m in methods)]
    complete_resolved=[c for c in complete if all(type(rows[c,m]["grade"].get("correct")) is bool for m in methods)]
    out.update(complete_seven_method_case_ids=complete,complete_seven_method_n=len(complete),
               complete_seven_method_grade_resolved_case_ids=complete_resolved,complete_seven_method_grade_resolved_n=len(complete_resolved),
               incomplete_case_ids=[c for c in case_ids if c not in complete])
    baselines=[m for m in methods if m!=PROJECTED]
    out["projected_vs_each_baseline"]={m:paired(rows,PROJECTED,m,case_ids) for m in baselines}
    out["projected_vs_baselines_on_common_complete_resolved_subset"]={m:paired(rows,PROJECTED,m,complete_resolved) for m in baselines}
    baseline_max=max((out["methods"][m]["correct"] for m in baselines),default=0)
    strongest=[m for m in baselines if out["methods"][m]["correct"]==baseline_max]
    projected_correct=out["methods"][PROJECTED]["correct"];net=projected_correct-baseline_max
    interpretable=len(complete_resolved)==n and n>0
    out["continuation_gate"]={"threshold_net_correct_vs_strongest_baseline":2,"strongest_aggregate_baseline_methods":strongest,
        "strongest_baseline_confirmed_correct":baseline_max,"projected_confirmed_correct":projected_correct,
        "observed_aggregate_net":net,"point_threshold_met":net>=2,"complete_and_resolved":interpretable,
        "decision":"CONTINUE_TO_INDEPENDENT_CONFIRMATION" if interpretable and net>=2 else "NO_GO_TO_EXPANSION" if interpretable else "INCONCLUSIVE_INCOMPLETE_OR_GRADER_UNKNOWN",
        "meaning":"Prespecified exploratory >=2/32 line; aggregate best baseline, never per-case oracle. Passing is not significance, publication readiness or natural end-to-end proof."}
    return out


def child_cpu_usage():
    try:
        import resource
        info=resource.getrusage(resource.RUSAGE_CHILDREN)
        return info.ru_utime+info.ru_stime
    except (ImportError,AttributeError):return None


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    ap.add_argument('--output',type=Path);args=ap.parse_args();root=args.root.resolve()
    launcher=require_finished(root)  # MUST precede every evaluation/bank/output read.
    os.environ["CUDA_VISIBLE_DEVICES"]=""
    import goal_math_grader as grader
    started=time.monotonic();parent_cpu=time.process_time();child_start=child_cpu_usage()
    protocol=json.loads((root/'PROTOCOL.json').read_text(encoding='utf-8'))
    if protocol['methods']!=REQUIRED_METHODS or protocol['n_distinct_questions']!=32:raise ValueError("Unexpected planned protocol")
    if sha(Path(grader.__file__))!=protocol['grader_sha256']:raise ValueError("Frozen grader source mismatch")
    manifest=json.loads((root/'NATURAL_BANK_MANIFEST.json').read_text(encoding='utf-8'))
    eval_path=root/'bank_evaluation_only.jsonl'
    if sha(eval_path)!=manifest['files']['bank_evaluation_only.jsonl']['sha256']:raise ValueError("Frozen evaluation file hash mismatch")
    evaluation=[json.loads(line) for line in eval_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    emap={r['bank_id']:r for r in evaluation}
    cases=manifest['cases'];cmap={r['bank_id']:r for r in cases}
    if len(emap)!=32 or len(cmap)!=32 or len(evaluation)!=32 or set(emap)!=set(cmap):raise ValueError("Evaluation bank IDs not unique/matched")
    ordered=sorted(cases,key=lambda r:r['sample_rank_1based']);case_ids=[r['bank_id'] for r in ordered]
    planned={f"{c['sample_rank_1based']:02}__{m}":{'bank_id':c['bank_id'],'rank':c['sample_rank_1based'],'method':m} for c in cases for m in REQUIRED_METHODS}
    readouts={};raw_files=[]
    for path in sorted((root/'results').glob('worker_*/??__*.json')):
        row=json.loads(path.read_text(encoding='utf-8'));jid=row.get('job_id');expected=planned.get(jid)
        if not expected or path.stem!=jid:raise ValueError("Unplanned/misnamed readout: "+str(path))
        if any(row.get(k)!=v for k,v in expected.items()):raise ValueError("Bank/rank/method mismatch: "+jid)
        if jid in readouts:raise ValueError("Duplicate readout: "+jid)
        if type(row.get('answer_text')) is not str or type(row.get('text')) is not str:raise ValueError("Missing delivered answer text")
        if not isinstance(row.get('token_ids'),list) or row.get('new_tokens')!=len(row['token_ids']):raise ValueError("Token-count mismatch")
        if type(row.get('eos_reached')) is not bool or type(row.get('hit_cap')) is not bool:raise ValueError("Missing stop flags")
        if row['eos_reached'] and row['hit_cap']:raise ValueError("Mutually exclusive stop flags")
        worker=int(path.parent.name.split('_')[-1])
        if worker!=(row['rank']-1)%2:raise ValueError("Worker partition mismatch")
        readouts[jid]=(row,path);raw_files.append({'path':path.relative_to(root).as_posix(),'sha256':sha(path)})
    output=args.output.resolve() if args.output else root/'scoring'
    output.mkdir(parents=True,exist_ok=False)  # Never overwrite a prior scoring pass.
    def score(item):
        jid,(row,path)=item;begin=time.monotonic()
        try:grade=grader.grade_final(row['answer_text'],emap[row['bank_id']]['gold'])
        except Exception as exc:grade={'status':'scoring_caller_error','correct':None,'error_type':type(exc).__name__,
                                      'extraction':grader.extract_final(row['answer_text'])}
        return {'job_id':jid,'bank_id':row['bank_id'],'rank':row['rank'],'method':row['method'],
                'raw_path':path.relative_to(root).as_posix(),'raw_sha256':sha(path),
                'answer_text_sha256':hashlib.sha256(row['answer_text'].encode()).hexdigest(),
                'readout':{k:row[k] for k in ('prompt_tokens','new_tokens','eos_reached','hit_cap')},
                'grade':grade,'grade_call_wall_seconds':time.monotonic()-begin}
    grades=[]
    with (output/'grades.jsonl').open('x',encoding='utf-8') as handle, ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(score,item):item[0] for item in sorted(readouts.items())}
        for future in as_completed(futures):
            rec=future.result();grades.append(rec);handle.write(json.dumps(rec,ensure_ascii=False,allow_nan=False)+'\n');handle.flush()
            if len(grades)%16==0:write(output/'progress.json',{'scored_delivered':len(grades),'planned':224,'scoring_wall_seconds':time.monotonic()-started})
    grades.sort(key=lambda r:(r['rank'],REQUIRED_METHODS.index(r['method'])))
    result=summarize(grades,case_ids,REQUIRED_METHODS);child_end=child_cpu_usage()
    result.update(status='SCORING_COMPLETE',scoring_source_sha256=sha(__file__),grader_source_sha256=sha(Path(grader.__file__)),
        protocol_sha256=sha(root/'PROTOCOL.json'),bank_manifest_sha256=sha(root/'NATURAL_BANK_MANIFEST.json'),
        evaluation_sha256=sha(eval_path),launcher_sha256=sha(root/'launcher.json'),raw_files=raw_files,
        grade_jsonl_sha256=sha(output/'grades.jsonl'),thread_workers=4,
        scoring_wall_seconds=time.monotonic()-started,scoring_parent_process_CPU_seconds=time.process_time()-parent_cpu,
        scoring_child_process_CPU_seconds=child_end-child_start if child_end is not None and child_start is not None else None,
        grade_call_wall_seconds_sum_overlapping=sum(r['grade_call_wall_seconds'] for r in grades),
        generation_launcher={'status':launcher['status'],'elapsed_seconds':launcher.get('elapsed_seconds'),
            'aggregate_GPU_seconds':launcher.get('conservative_aggregate_GPU_seconds'),'GPU_minutes':launcher.get('conservative_GPU_minutes'),
            'workers':{k:{field:v.get(field) for field in ('status','exit_code','elapsed_seconds')} for k,v in launcher.get('workers',{}).items()}},
        cost_boundary='Physical paired-batch wall/forward work is never divided into per-method latency. Scoring wall/CPU are offline evaluation, not online method compute.',
        scope='Single-model frozen historical-prefix terminal-readout exploration, new common grader; not natural end-to-end RawFull or a formal multi-dataset result.',
        true_G_implemented=protocol.get('true_G_implemented'),certified_boundary_implemented=protocol.get('certified_boundary_implemented'))
    write(output/'summary.json',result)
    print(json.dumps({k:result[k] for k in ('status','planned_outputs','scored_delivered_outputs','methods','complete_seven_method_n','continuation_gate','scoring_wall_seconds','scoring_parent_process_CPU_seconds','scoring_child_process_CPU_seconds')},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
