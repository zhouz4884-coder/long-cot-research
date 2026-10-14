"""Freeze a measured M1 comparison from development/selection data only.

Reader-based baselines are independent common-protocol adaptations. Selection
bank timing selects diagnostic thresholds; only the online runs measure speed.
"""
import hashlib
import json
import pickle
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from protocol_guard import validate_formal,sha256
from select_calibrate_policies import load_bank,replay,stats
from risk_policy import eat_update,conformal_dual_update,conformal_discrete_losses


def baseline_replay(row,spec):
    full=row['full'];chosen=full['answer'];point=None;overhead=0.
    mean=variance=0.;count=0
    conformal_ema=None
    selected_route=None
    for p in row['points']:
        if p['offset']<spec['minimum_offset']:continue
        read=p['readouts'][0]
        if spec['kind']=='eat':
            count+=1
            mean,variance,adjusted=eat_update(mean,variance,p['probe']['entropy'],count)
            overhead+=p['probe']['ms']
            accept=count>=spec['minimum_steps'] and adjusted<spec['variance_threshold']
            if accept:overhead+=read['ms']
        elif spec['kind']=='deer':
            overhead+=read['ms']
            accept=read['stop_reason']=='answer_box_complete' and read['maxprob_geomean']>=spec['confidence_threshold']
        elif spec['kind']=='conformal_dual_adaptation':
            overhead+=read['ms']+read['schema']['schema_ms']
            update=conformal_dual_update(conformal_ema,read['maxprob_geomean'],p['offset'],spec)
            conformal_ema=update['smoothed_confidence']
            accept=p['schema_valid'] and update['route'] in ['upper','lower']
        else:raise ValueError(spec['kind'])
        if accept:
            chosen=read;point=p
            if spec['kind']=='conformal_dual_adaptation':selected_route=update['route']
            break
    result={'problem_id':row['problem_id'],'correct':chosen['correct'],'reference_correct':full['correct'],
            'harm':int(full['correct']==1 and chosen['correct']==0),
            'benefit':int(full['correct']==0 and chosen['correct']==1),
            'cost_ms_proxy':(point['elapsed_ms'] if point else full['instrumented_reference_ms'])+overhead,
            'reference_ms_proxy':full['instrumented_reference_ms'],
            'stop_offset':point['offset'] if point else None,'answer_text':chosen['text'],
            'candidate_identity':chosen.get('candidate_identity_sha256')}
    if spec['kind']=='conformal_dual_adaptation':
        eligible=[p for p in row['points'] if p['offset']>=spec['minimum_offset']]
        # Future labels enter only after the confidence-based replay decision.
        y=[p['readouts'][0]['correct'] for p in eligible]+[full['correct']]
        index=next(i for i,p in enumerate(eligible) if p['offset']==point['offset']) if point else len(y)-1
        result['threshold_route']=selected_route or 'fallback'
        result['paper_losses']=conformal_discrete_losses(y,index,result['threshold_route'])
        assert result['paper_losses']['harmful_vs_final']==result['harm']
        result['paper_losses_are_policy_risk_certification']=False
    return result


def choose(candidates):
    eligible=[c for c in candidates if c['statistics']['accuracy_delta']>=-.01]
    if eligible:
        return max(eligible,key=lambda c:c['statistics']['replay_cost_saving_proxy'])
    return min(candidates,key=lambda c:(c['statistics']['harms'],-c['statistics']['accuracy_delta']))


def main():
    formal,formal_hash=validate_formal(ROOT)
    training=json.loads((ROOT/'results/risk_training/grouped_cv.json').read_text())
    assert training['formal_protocol_sha256']==formal_hash
    rows=load_bank('selection',training['model_path'])
    frozen=json.loads((ROOT/'provenance/calibration_candidates.json').read_text())
    assert frozen['model_sha256']==training['model_sha256']
    models={}
    for name,digest in training['model_sha256'].items():
        path=ROOT/f'results/risk_training/{name}.pkl';assert sha256(path)==digest
        with path.open('rb') as handle:models[name]=pickle.load(handle)
    current=[]
    for name,model in models.items():
        for threshold in [.8,.9,.95,.98,.995,1.]:
            spec={'kind':'current_correctness','predictor':name,'correctness_threshold':threshold,'minimum_offset':256}
            current.append({'spec':spec,'statistics':stats([replay(r,spec,model) for r in rows])})
    selected_current=choose(current)
    comparisons={}
    for kind in ['eat','deer','conformal_dual_adaptation']:
        candidates=[]
        grid=([{'minimum_steps':steps,'variance_threshold':threshold}
               for steps in [2,3,4] for threshold in [.0001,.001,.01,.05,.1,.2,.5,1.]] if kind=='eat'
              else [{'confidence_threshold':threshold} for threshold in [.7,.8,.85,.9,.95,.98,.995,1.]] if kind=='deer'
              else [{'upper_threshold':upper,'lower_base':0.,'slope_times_budget':slope,'shift_fraction':shift,
                     'reference_budget':formal['max_think_tokens'],'ema_alpha':alpha}
                    for upper in [.9,.95,.98,.995,.999,1.] for slope in [1.,4.,8.,16.]
                    for shift in [.5,1.] for alpha in [.2,.95]])
        for parameters in grid:
            spec={'kind':kind,'minimum_offset':256,**parameters}
            replays=[baseline_replay(r,spec) for r in rows]
            summary=stats(replays)
            if kind=='conformal_dual_adaptation':
                summary['paper_loss_means']={name:sum(r['paper_losses'][name] for r in replays)/len(replays)
                                             for name in replays[0]['paper_losses']}
                summary['threshold_route_counts']={route:sum(r['threshold_route']==route for r in replays)
                                                    for route in ['upper','lower','fallback']}
                summary['paper_loss_certification_performed']=False
            candidates.append({'spec':spec,'statistics':summary})
        comparisons[kind]={'selected':choose(candidates),'all_candidates':candidates}
    legacy=json.loads((ROOT/'provenance/legacy/frozen_controller.json').read_text())
    assert sha256(ROOT/legacy['predictor_metadata']['path'])==legacy['predictor_metadata']['sha256']
    matched_legacy={**legacy['method_spec'],'budget':formal['max_think_tokens']}
    calibration_records=sum(len(p.read_text(encoding='utf-8').splitlines()) for p in (ROOT/'results').glob('bank_calibration_*.jsonl'))
    assert calibration_records==0,'Build the comparison plan before observing calibration outputs'
    methods={'full':{'kind':'full'},**{f'fixed_{b}':{'kind':'fixed_budget','budget':b} for b in [1024,2048,4096,8192]},
             'risk_primary':frozen['candidates'][frozen['primary_candidate_index']],
             'current_correctness':selected_current['spec'],
             'eat_adaptation':comparisons['eat']['selected']['spec'],
             'deer_confidence_proxy':comparisons['deer']['selected']['spec'],
             'conformal_dual_adaptation':comparisons['conformal_dual_adaptation']['selected']['spec'],
             'legacy_original_cap':legacy['method_spec'],'legacy_matched_cap':matched_legacy}
    payload={'scope':'Selection-only M1 online comparison, not final test or risk certification.',
             'formal_protocol_sha256':formal_hash,'methods':methods,
             'models':{**{name:{'path':f'results/risk_training/{name}.pkl','sha256':digest}
                         for name,digest in training['model_sha256'].items()},
                       'legacy_readout_linear':legacy['predictor_metadata']},
             'selection_problems':len(rows),'calibration_generation_records_at_plan':calibration_records,
             'baseline_scope':'EAT is an independent boxed-reader adaptation. deer_confidence_proxy uses geometric mean of maximum probabilities along a sampled shared-reader trial; it omits upstream greedy trials, injected Wait/Alternatively continuation and the documented Qwen trial thinking-close condition. It is a DEER-inspired confidence proxy, not author DEER or DEER-PRo reproduction. Author-full strong baselines remain W10-12 work. Original legacy cap8192 and matched-cap transfer are separate methods.',
             'conformal_adaptation_scope':'Paper dual-threshold/logistic rule, explicit EMA and current-candidate schema admission on the common sampled boxed reader. Operating point selected on selection by paired quality and measured-action cost proxy. No author utility/full-assets reproduction, UCB theorem or independent certification claimed at M1. Paper Eq8-11 losses and harmful-vs-FULL differ and are reported separately.',
             'candidate_family_sha256':sha256(ROOT/'provenance/calibration_candidates.json'),
             'builder_sha256':sha256(Path(__file__)),
             'measured_m1_gate':{'primary_accuracy_delta_min':-.01,'primary_wall_saving_min':.15,
                                 'cost_scope':'Measured end-to-end requests including rejected candidates; selection is exploratory.'}}
    path=ROOT/'provenance/m1_selection_online.json'
    serialized=json.dumps(payload,indent=2)+'\n'
    if path.exists():assert path.read_text()==serialized,'Do not replace an existing online plan; review run/version first'
    else:path.write_text(serialized)
    (ROOT/'results/policy_selection/m1_baseline_selection.json').write_text(json.dumps(
        {'current_correctness':{'selected':selected_current,'all_candidates':current},**comparisons},indent=2)+'\n')
    print(json.dumps({'n':len(rows),'methods':list(methods),'actual_online_requests_expected':len(rows)*len(methods),
                      'plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
