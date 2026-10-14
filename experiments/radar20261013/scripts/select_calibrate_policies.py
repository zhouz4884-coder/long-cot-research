"""Finite candidate selection and independent terminal-policy risk audit.

Bank-selected answers are observed GPU actions under a shared prefix/seed
protocol. Their cost remains a replay proxy. Deployment validity additionally
requires a recorded real online/replay equivalence audit on selection data.
"""
import argparse,hashlib,json,pickle,sys
from pathlib import Path
import numpy as np
from scipy.stats import beta

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from risk_policy import quality_decision,features_at
from protocol_guard import validate_formal
from design_risk import strata_from_frozen_data,finite_test_risk_audit


def load_bank(split,model_path):
    _,formal_hash=validate_formal(ROOT,model_path)
    df=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    rows=[]
    for g in [0,1]:
        assert (ROOT/f'results/bank_{split}_{g}.complete.json').exists()
        rows += [json.loads(s) for s in (ROOT/f'results/bank_{split}_{g}.jsonl').read_text(encoding='utf-8').splitlines()]
    expected=set(df['splits'][split]['ids'])
    assert len(rows)==len(expected) and {r['problem_id'] for r in rows}==expected
    assert all(r['formal_protocol_sha256']==formal_hash for r in rows)
    assert {r['model_path'] for r in rows}=={model_path}
    if split=='calibration':
        family_hash=hashlib.sha256((ROOT/'provenance/calibration_candidates.json').read_bytes()).hexdigest()
        assert all(r['candidate_family_sha256']==family_hash for r in rows),'Calibration does not match the frozen candidate family'
    return sorted(rows,key=lambda r:r['problem_id'])


def replay(row,spec,learner):
    reference=row['full'];chosen=reference['answer'];point=None;overhead=0.
    for p in row['points']:
        if p['offset']<spec.get('minimum_offset',256):continue
        read=p['readouts'][0]
        pred=learner.predict_one(features_at(p,read))
        overhead += read['ms']+read['schema']['schema_ms']
        action=quality_decision(spec,pred,p['schema_valid'])
        if action=='COMMIT':chosen=read;point=p;break
        if action=='FALLBACK':break
    correct=chosen['correct']
    ref_correct=reference['correct']
    cost_proxy=(point['elapsed_ms'] if point else reference['instrumented_reference_ms'])+overhead
    return {'problem_id':row['problem_id'],'correct':correct,'reference_correct':ref_correct,
            'harm':int(ref_correct==1 and correct==0),'benefit':int(ref_correct==0 and correct==1),
            'stop_offset':point['offset'] if point else None,'cost_ms_proxy':cost_proxy,
            'reference_ms_proxy':reference['instrumented_reference_ms'],
            'candidate_identity':chosen.get('candidate_identity_sha256'),
            'answer_text':chosen['text'],'latency_is_measured_new_online_policy':False}


def stats(rows,alpha=.05):
    n=len(rows);h=sum(r['harm'] for r in rows);b=sum(r['benefit'] for r in rows)
    return {'n':n,'correct':sum(r['correct'] for r in rows),'accuracy_delta':(b-h)/n,
            'harms':h,'benefits':b,'harm_upper':float(beta.ppf(1-alpha,h+1,n-h)) if h<n else 1.,
            'replay_cost_saving_proxy':1-sum(r['cost_ms_proxy'] for r in rows)/sum(r['reference_ms_proxy'] for r in rows),
            'online_performance_proven':False}


def candidate_spec_hash(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def candidate_consistency_admitted(consistency,spec,formal_hash,model_path):
    return (consistency.get('passed') is True
            and consistency.get('formal_protocol_sha256')==formal_hash
            and consistency.get('model_path')==model_path
            and candidate_spec_hash(spec) in consistency.get('verified_candidate_spec_sha256',[]))


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['selection','calibration'],required=True)
    args=p.parse_args();train=ROOT/'results/risk_training'
    metadata=json.loads((train/'grouped_cv.json').read_text());models={}
    _,formal_hash=validate_formal(ROOT,metadata['model_path'])
    assert metadata['formal_protocol_sha256']==formal_hash,'Predictor was trained under another formal protocol'
    for name,h in metadata['model_sha256'].items():
        path=train/f'{name}.pkl';assert hashlib.sha256(path.read_bytes()).hexdigest()==h
        with path.open('rb') as f:models[name]=pickle.load(f)
    out=ROOT/'results/policy_selection';out.mkdir(exist_ok=True)
    if args.phase=='selection':
        rows=load_bank('selection',metadata['model_path']);results=[]
        for name,learner in models.items():
            for risk in [.005,.01,.02,.04,.08,.12]:
                for minimum in [0.,.9]:
                    spec={'kind':'risk_gate','predictor':name,'risk_threshold':risk,
                          'minimum_correctness':minimum,'minimum_offset':256}
                    selected=[replay(r,spec,learner) for r in rows]
                    results.append({'spec':spec,'statistics':stats(selected)})
        eligible=[r for r in results if r['statistics']['accuracy_delta']>=-.02]
        ranked=sorted(eligible,key=lambda r:(-r['statistics']['replay_cost_saving_proxy'],r['statistics']['harms']))
        assert ranked,'No selection policy meets the diagnostic quality tolerance; report the gate failure'
        # At most eight concrete candidates, fixed before any calibration outcome.
        primary_options=[r for r in ranked if r['spec']['minimum_correctness']>=.9]
        assert primary_options,'No quality-first primary candidate; do not promote a no-correctness-floor ablation'
        primary_pool=[r for r in primary_options if r['statistics']['harms']/len(rows)<=.01 and r['statistics']['accuracy_delta']>=-.01]
        primary=(primary_pool[0] if primary_pool else min(primary_options,key=lambda r:(r['statistics']['harms'],-r['statistics']['accuracy_delta'],-r['statistics']['replay_cost_saving_proxy'])))
        priority=[primary]
        # Keep cost/quality tradeoffs and conservative endpoints represented;
        # eight nearly identical aggressive policies would waste calibration.
        for tolerance in [0.,-.005,-.01,-.02]:
            subset=[r for r in ranked if r['statistics']['accuracy_delta']>=tolerance]
            if subset:priority.append(subset[0])
        for name in models:
            subset=[r for r in ranked if r['spec']['predictor']==name]
            if subset:priority.append(min(subset,key=lambda r:(r['statistics']['harms'],-r['statistics']['accuracy_delta'],-r['statistics']['replay_cost_saving_proxy'])))
        priority+=ranked
        chosen=[];used=set()
        for r in priority:
            key=json.dumps(r['spec'],sort_keys=True)
            if key in used:continue
            chosen.append(r['spec']);used.add(key)
            if len(chosen)==8:break
        assert chosen,'No eligible candidate; report the gate failure rather than invent a policy'
        assert not list((ROOT/'results').glob('bank_calibration_*.jsonl')),'Candidate set must predate calibration generation'
        # The finite stratified design cannot certify a 1pp held-out target with
        # eight equal alpha shares even under hypothetical zero harms. Allocate
        # error to a primary chosen before calibration; the entire fixed family
        # still has total error budget .05. Never swap primary after calibration.
        alphas=[.05] if len(chosen)==1 else [.04]+[.01/(len(chosen)-1)]*(len(chosen)-1)
        payload={'candidates':chosen,'candidate_count':len(chosen),'familywise_alpha':.05,'target_harm_risk':.01,
                 'candidate_alphas':alphas,'primary_candidate_index':0,
                 'primary_selection_rule':'Selection only: correctness floor >=.9, best replay cost among <=1 percent harmful and >=-1pp accuracy candidates; otherwise least-harm quality-first diagnostic fallback. No primary swap after calibration.',
                 'primary_selection_quality_gate_passed':bool(primary_pool),
                 'fit_scope':'development; candidate selection uses selection only',
                 'calibration_records_at_freeze':0,'model_sha256':metadata['model_sha256'],
                 'data_freeze_sha256':hashlib.sha256((ROOT/'provenance/data_freeze.json').read_bytes()).hexdigest()}
        (ROOT/'provenance/calibration_candidates.json').write_text(json.dumps(payload,indent=2)+'\n')
        (out/'all_selection_replays.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(payload,indent=2))
    else:
        frozen=json.loads((ROOT/'provenance/calibration_candidates.json').read_text())
        assert frozen['calibration_records_at_freeze']==0
        assert frozen['model_sha256']==metadata['model_sha256']
        assert frozen['data_freeze_sha256']==hashlib.sha256((ROOT/'provenance/data_freeze.json').read_bytes()).hexdigest()
        rows=load_bank('calibration',metadata['model_path']);k=frozen['candidate_count'];report=[]
        strata=strata_from_frozen_data(ROOT)
        alphas=frozen['candidate_alphas'];assert len(alphas)==k and sum(alphas)<=frozen['familywise_alpha']+1e-12
        audit=ROOT/'provenance/selection_online_equivalence.json'
        consistency=json.loads(audit.read_text()) if audit.exists() else {}
        for index,spec in enumerate(frozen['candidates']):
            selected=[replay(r,spec,models[spec['predictor']]) for r in rows]
            summary=stats(selected,alpha=alphas[index])
            finite=finite_test_risk_audit(strata,summary['harms'],frozen['target_harm_risk'],alphas[index])
            secondary=finite_test_risk_audit(strata,summary['harms'],.02,alphas[index])
            report.append({'spec':spec,'statistics':summary,
                           'is_prespecified_primary':index==frozen['primary_candidate_index'],'allocated_alpha':alphas[index],
                           'online_action_consistency_admitted':candidate_consistency_admitted(consistency,spec,formal_hash,metadata['model_path']),
                           'iid_binomial_bound_passed_conditional_on_iid':summary['harm_upper']<=frozen['target_harm_risk'],
                           'iid_assumption_established_by_current_split_design':False,
                           'finite_test_design_audit':finite,'finite_test_2pp_design_audit':secondary,
                           'risk_bound_passed':finite['risk_bound_passed'],
                           'terminal_replays':selected})
        payload={'scope':'Independent calibration of the fixed candidate family under the logged action bank protocol.',
                 'candidate_family_count':k,'familywise_alpha':frozen['familywise_alpha'],
                 'candidate_alphas':alphas,'primary_candidate_index':frozen['primary_candidate_index'],
                 'risk_target':frozen['target_harm_risk'],'candidates':report,
                 'online_action_consistency_admitted':consistency.get('passed') is True,
                 'finite_test_pool_certification_admitted_under_stated_assumptions':any(r['online_action_consistency_admitted'] and r['risk_bound_passed'] for r in report),
                 'deployment_certification_admitted':False,
                 'warning':'The frozen split is stratified without replacement. Binomial bounds are conditional IID sensitivity, not an unconditional guarantee. Design-aware bounds concern the fixed finite test pool under fixed potential outcomes and the logged action protocol; they do not certify another backend, seed protocol or deployment distribution.'}
        (out/'independent_calibration.json').write_text(json.dumps(payload,indent=2)+'\n')
        print(json.dumps({k:v for k,v in payload.items() if k!='candidates'},indent=2))


if __name__=='__main__':main()
