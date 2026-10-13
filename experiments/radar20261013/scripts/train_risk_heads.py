"""Question-disjoint models for actual-candidate risk, fit on development only."""
import json,pickle,sys,hashlib
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from joint_predictor import JointModel,PREFIX_FEATURES,ANSWER_FEATURES


def metric(y,p,w):
    return {'auc':float(roc_auc_score(y,p,sample_weight=w)) if len(set(y))>1 else None,
            'average_precision':float(average_precision_score(y,p,sample_weight=w)) if sum(y)>0 else None,
            'brier':float(brier_score_loss(y,p,sample_weight=w))}


def main():
    files=[ROOT/f'results/bank_development_{g}.jsonl' for g in [0,1]]
    freeze=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    expected=set(freeze['splits']['development']['ids'])
    questions=[]
    for g,file in enumerate(files):
        assert (ROOT/f'results/bank_development_{g}.complete.json').exists()
        questions+=[json.loads(s) for s in file.read_text(encoding='utf-8').splitlines()]
    assert {r['problem_id'] for r in questions}==expected
    assert len(questions)==len(expected)
    entries=[]
    for q in questions:
        count=len(q['points'])
        for p in q['points']:
            read=p['readouts'][0]
            features={**p['features'],**p['candidate_features']}
            if read.get('cue_projection') is not None:
                features.update({f'cue_h_{i}':v for i,v in enumerate(read['cue_projection'])})
                features.update({f'answer_h_{i}':v for i,v in enumerate(read['answer_projection'])})
            entries.append({'problem_id':q['problem_id'],'offset':p['offset'],'features':features,
                            'current':read['correct'],'after':q['full']['correct'],'weight':1/max(1,count),
                            'remaining_ms_proxy':max(0,q['full']['instrumented_reference_ms']-p['elapsed_ms']),
                            'schema_valid':p['schema_valid']})
    assert entries,'No actual development states'
    variants={'prefix':PREFIX_FEATURES,'candidate':PREFIX_FEATURES+ANSWER_FEATURES}
    if all('cue_h_0' in e['features'] for e in entries):
        d=len(questions[0]['points'][0]['readouts'][0]['cue_projection']) if questions[0]['points'] else 64
        variants['candidate_latent']=PREFIX_FEATURES+ANSWER_FEATURES+[f'cue_h_{i}' for i in range(d)]+[f'answer_h_{i}' for i in range(d)]
    groups=np.array([e['problem_id'] for e in entries])
    current=np.array([e['current'] for e in entries]);after=np.array([e['after'] for e in entries])
    harm=(current==0)&(after==1);benefit=(current==1)&(after==0)
    weights=np.array([e['weight'] for e in entries])
    fold_rows=[];reports={};models={}
    for name,features in variants.items():
        x=np.array([[e['features'][k] for k in features] for e in entries],dtype=float)
        pred=np.zeros((len(x),4));foldid=np.full(len(x),-1)
        for fold,(train,test) in enumerate(GroupKFold(5).split(x,current,groups)):
            assert not set(groups[train])&set(groups[test])
            model=JointModel(features).fit(x[train],current[train],after[train],weights[train])
            pred[test]=model.probabilities(x[test]);foldid[test]=fold
            if name=='prefix':fold_rows.append({'fold':fold,'train_problem_ids':sorted(set(groups[train])),
                                               'validation_problem_ids':sorted(set(groups[test]))})
        assert (foldid>=0).all()
        reports[name]={'stop_harm':metric(harm,pred[:,1],weights),'stop_benefit':metric(benefit,pred[:,2],weights),
                       'current_correct':metric(current,pred[:,2]+pred[:,3],weights),
                       'warning':'Checkpoint metrics are descriptive; final policy risk is problem-level and independently calibrated.'}
        models[name]=JointModel(features).fit(x,current,after,weights)
    out=ROOT/'results/risk_training';out.mkdir(exist_ok=True)
    for name,model in models.items():
        with (out/f'{name}.pkl').open('wb') as f:pickle.dump(model,f)
    report={'fit_split':'development_only','unique_problems_with_states':len(set(groups)),
            'development_question_count_including_no_state':len(questions),'checkpoint_rows':len(entries),
            'event_counts':dict(Counter(f"{e['current']}->{e['after']}" for e in entries)),
            'variants':reports,'folds':fold_rows,
            'scaler_and_classifier_version_scope':'Record actual environment with package snapshot; CPU CV does not prove online performance.',
            'model_sha256':{name:hashlib.sha256((out/f'{name}.pkl').read_bytes()).hexdigest() for name in models}}
    (out/'grouped_cv.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='folds'},indent=2))


if __name__=='__main__':main()
