"""Generic scoring-statistics contracts; never reads any study bank/results."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile

import score_readouts as scoring


def main():
    checks=[]
    def ok(name,condition):
        assert condition,name
        checks.append(name)
    for w,l,expected in [(0,0,1.0),(1,0,1.0),(2,0,0.5),(3,0,0.25),(5,0,0.0625),(3,2,1.0)]:
        ok(f'exact_mcnemar_{w}_{l}',scoring.exact_mcnemar_two_sided(w,l)['p_two_sided']==expected)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for status in [None,'RUNNING','ERROR']:
            if status is not None:(root/'launcher.json').write_text(json.dumps({'status':status}),encoding='utf-8')
            try:scoring.require_finished(root)
            except RuntimeError:ok('gate_refuses_'+str(status),True)
            else:ok('gate_refuses_'+str(status),False)
        (root/'launcher.json').write_text(json.dumps({'status':'FINISHED'}),encoding='utf-8')
        ok('gate_finished_without_reading_nonexistent_eval',scoring.require_finished(root)['status']=='FINISHED')
        for study_status,resume_status in [('RUNNING','FINISHED'),('ERROR','FINISHED'),('FINISHED','RUNNING'),('FINISHED','ERROR'),('FINISHED',None)]:
            (root/'STUDY_STATUS.json').write_text(json.dumps({'status':study_status}),encoding='utf-8')
            if resume_status is None:
                if (root/'resume_launcher.json').exists():(root/'resume_launcher.json').unlink()
            else:(root/'resume_launcher.json').write_text(json.dumps({'status':resume_status}),encoding='utf-8')
            try:scoring.require_finished(root)
            except RuntimeError:ok('aggregate_gate_refuses_'+study_status+'_'+str(resume_status),True)
            else:ok('aggregate_gate_refuses_'+study_status+'_'+str(resume_status),False)
        (root/'resume_launcher.json').write_text(json.dumps({'status':'FINISHED'}),encoding='utf-8')
        all_finished=scoring.require_finished(root)
        ok('aggregate_all_three_finished',all_finished['_aggregate_study_status']['status']=='FINISHED' and all_finished['_resume_launcher']['status']=='FINISHED')
        (root/'launcher.json').write_text(json.dumps({'status':'RUNNING'}),encoding='utf-8')
        try:scoring.require_finished(root)
        except RuntimeError:ok('aggregate_does_not_override_original_running',True)
        else:ok('aggregate_does_not_override_original_running',False)
        (root/'launcher.json').write_text(json.dumps({'status':'FINISHED'}),encoding='utf-8')
        (root/'STUDY_STATUS.json').unlink()
        try:scoring.require_finished(root)
        except RuntimeError:ok('orphan_resume_without_study_refused',True)
        else:ok('orphan_resume_without_study_refused',False)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);base=root/'results/worker_0';resume=root/'results/resume_worker_1';duplicate=root/'results/resume_worker_0'
        base.mkdir(parents=True);resume.mkdir(parents=True);duplicate.mkdir(parents=True)
        plan={'01__FullContinue':{'bank_id':'FAKE_ONLY_1','rank':1,'method':'FullContinue'},
              '02__FullContinue':{'bank_id':'FAKE_ONLY_2','rank':2,'method':'FullContinue'}}
        def row(jid):return {'job_id':jid,**plan[jid],'answer_text':'fake_answer','text':'fake_answer','token_ids':[2],'new_tokens':1,'eos_reached':True,'hit_cap':False,'prompt_tokens':7}
        (base/'01__FullContinue.json').write_text(json.dumps(row('01__FullContinue')),encoding='utf-8')
        (resume/'02__FullContinue.json').write_text(json.dumps(row('02__FullContinue')),encoding='utf-8')
        (resume/'summary.json').write_text('not a job; do not parse it',encoding='utf-8')
        merged,files=scoring.collect_readouts(root,plan)
        ok('original_and_resume_collected',len(merged)==2 and len(files)==2 and 'resume_worker_1' in files[0]['path']+files[1]['path'])
        extra=duplicate/'01__FullContinue.json';extra.write_bytes((base/extra.name).read_bytes())
        try:scoring.collect_readouts(root,plan)
        except ValueError:ok('identical_duplicate_refused',True)
        else:ok('identical_duplicate_refused',False)
        changed=row('01__FullContinue');changed['answer_text']='a_different_unjudged_answer';extra.write_text(json.dumps(changed),encoding='utf-8')
        try:scoring.collect_readouts(root,plan)
        except ValueError:ok('different_duplicate_refused_without_effect_selection',True)
        else:ok('different_duplicate_refused_without_effect_selection',False)
        extra.unlink();unknown=resume/'100__Unknown.json';unknown.write_text('{}',encoding='utf-8')
        try:scoring.collect_readouts(root,plan)
        except ValueError:ok('unknown_ID_not_silently_ignored',True)
        else:ok('unknown_ID_not_silently_ignored',False)
        unknown.unlink();bad=row('02__FullContinue');bad['bank_id']='OTHER_FAKE_ID'
        (resume/'02__FullContinue.json').write_text(json.dumps(bad),encoding='utf-8')
        try:scoring.collect_readouts(root,plan)
        except ValueError:ok('resume_bank_mismatch_refused',True)
        else:ok('resume_bank_mismatch_refused',False)
    methods=scoring.REQUIRED_METHODS;ids=[f'TEST_ONLY_{i:03}' for i in range(32)]
    rows=[]
    for i,bank_id in enumerate(ids):
        for method in methods:
            correct=method==scoring.PROJECTED or i<30
            rows.append({'bank_id':bank_id,'method':method,'grade':{'correct':correct,'status':'ok','extraction':{'status':'ok'}},
                         'readout':{'hit_cap':False,'eos_reached':True,'prompt_tokens':17,'new_tokens':3}})
    allgood=scoring.summarize(rows,ids,methods)
    ok('planned224',allgood['planned_outputs']==224)
    ok('complete32',allgood['complete_seven_method_n']==32 and allgood['complete_seven_method_grade_resolved_n']==32)
    ok('aggregate_net2',allgood['continuation_gate']['observed_aggregate_net']==2)
    ok('net2_only_exploratory_continue',allgood['continuation_gate']['decision']=='CONTINUE_TO_INDEPENDENT_CONFIRMATION')
    ok('strongest_baselines_aggregate_all_ties',len(allgood['continuation_gate']['strongest_aggregate_baseline_methods'])==6)
    pair=allgood['projected_vs_each_baseline']['FullContinue']
    ok('winloss_ties',pair['win']==2 and pair['loss']==0 and pair['tie']==30 and pair['resolved_paired_n']==32)
    low=copy.deepcopy(rows)
    next(r for r in low if r['method']==scoring.PROJECTED and r['bank_id']==ids[0])['grade']['correct']=False
    lower=scoring.summarize(low,ids,methods)
    ok('net1_no_go',lower['continuation_gate']['observed_aggregate_net']==1 and lower['continuation_gate']['decision']=='NO_GO_TO_EXPANSION')
    missing=[r for r in rows if not(r['bank_id']==ids[-1] and r['method']=='FullContinue')]
    partial=scoring.summarize(missing,ids,methods)
    m=partial['methods']['FullContinue']
    ok('missing_retains_denominator',m['planned']==32 and m['delivered']==31 and m['missing']==1 and m['confirmed_accuracy_planned']==30/32)
    ok('missing_coverage_not_complete',partial['complete_seven_method_n']==31 and partial['continuation_gate']['decision']=='INCONCLUSIVE_INCOMPLETE_OR_GRADER_UNKNOWN')
    unknown=copy.deepcopy(rows)
    next(r for r in unknown if r['bank_id']==ids[0] and r['method']=='FullContinue')['grade'].update(correct=None,status='grader_timeout')
    unresolved=scoring.summarize(unknown,ids,methods);u=unresolved['methods']['FullContinue']
    ok('unknown_retains_denominator',u['planned']==32 and u['delivered']==32 and u['gradeunknown']==1 and u['confirmed_accuracy_planned']==29/32)
    ok('unknown_bounds',u['accuracy_bounds_from_missing_and_gradeunknown']==[29/32,30/32])
    ok('unknown_explicit_paired_subset',unresolved['projected_vs_each_baseline']['FullContinue']['resolved_paired_n']==31 and unresolved['complete_seven_method_n']==32 and unresolved['complete_seven_method_grade_resolved_n']==31)
    ok('unknown_gate_inconclusive',unresolved['continuation_gate']['decision']=='INCONCLUSIVE_INCOMPLETE_OR_GRADER_UNKNOWN')
    unparsed=copy.deepcopy(rows)
    next(r for r in unparsed if r['bank_id']==ids[0] and r['method']=='FullContinue')['grade'].update(correct=False,status='output_unparsed',extraction={'status':'incomplete'})
    failed=scoring.summarize(unparsed,ids,methods)
    ok('unparsed_not_excluded_from_pairs',failed['methods']['FullContinue']['unparsed']==1 and failed['projected_vs_each_baseline']['FullContinue']['resolved_paired_n']==32)
    try:scoring.summarize(rows+[rows[0]],ids,methods)
    except ValueError:ok('duplicate_rows_rejected',True)
    else:ok('duplicate_rows_rejected',False)
    result={'status':'PASS','checks_passed':len(checks),'checks':checks,
            'scoring_source_sha256':hashlib.sha256(Path(scoring.__file__).read_bytes()).hexdigest(),
            'scope':'Generic fake32/fake224 statistics and finish-gate checks only. No bank/evaluation/actual output read, no Math-Verify or GPU invoked.'}
    path=Path(__file__).with_name('SCORER_CPU_CONTRACT_TEST.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
