import argparse
from collections import Counter
import json
from pathlib import Path
import pickle
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from sklearn.model_selection import GroupKFold
from scipy.stats import spearmanr
from reason_transition.predictor import Predictor,TreePredictor,FEATURES,READOUT_FEATURES,with_readout,targets


def load(split):
    rows=[]
    for f in sorted(Path('results/bank').glob(f'{split}_branches_*.jsonl')):
        if '_orphan_' in f.name:continue
        rows.extend(json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip())
    ids=[r['checkpoint_id'] for r in rows]
    assert len(ids)==len(set(ids)),'Duplicate checkpoints across shards'
    return rows


def metrics(y,p):
    classes=len(np.unique(y))
    return {'events':int(sum(y)),'n':len(y),'prevalence':float(np.mean(y)),
        'pr_auc':float(average_precision_score(y,p)) if sum(y)>0 else None,
        'roc_auc':float(roc_auc_score(y,p)) if classes==2 else None,'brier':float(brier_score_loss(y,p))}


def summary(rows):
    result={}
    for group in ['all','natural','reflective']:
        subset=rows if group=='all' else [r for r in rows if r['checkpoint_kind']==group]
        result[group]={'n':len(subset),'problems':len({r['problem_id'] for r in subset}),
            'step_transition':dict(Counter(f"{r['stop_correct']}->{r['step_correct']}" for r in subset)),
            'full_transition':dict(Counter(f"{r['stop_correct']}->{r['end_correct']}" for r in subset)),
            'censored':sum(r['length_censored'] for r in subset),'step_overflow':sum(r['step_overflow'] for r in subset),
            'stop_parse_failed':sum(r['stop_grade']['parse_status']!='ok' for r in subset),
            'step_parse_failed':sum(r['step_grade']['parse_status']!='ok' for r in subset)}
        clean=[r for r in subset if not r['step_overflow'] and r['stop_grade']['parse_status']=='ok' and r['step_grade']['parse_status']=='ok']
        result[group]['natural_step_clean_n']=len(clean)
        result[group]['natural_step_clean_transitions']=dict(Counter(f"{r['stop_correct']}->{r['step_correct']}" for r in clean))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',action='store_true');args=p.parse_args()
    out=Path('results/analysis');out.mkdir(parents=True,exist_ok=True)
    split='engineering' if args.pilot else 'development'
    rows=load(split);assert rows,'No real branch data'
    report={'split':split,'transitions':summary(rows),'inference_unit':'problem_id','claims':'diagnostic; not online speed evidence'}
    if args.pilot:
        (out/'pilot.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return
    groups=np.array([r['problem_id'] for r in rows]);y=targets(rows)
    fold=GroupKFold(n_splits=5,shuffle=True,random_state=20261008)
    sets={'all_cheap':FEATURES,'length_only':['length','log_length'],'confidence_only':['logprob'],
          'entropy_only':['entropy'],'text_only':['length','reflection_count','repeat4','steps','reflective'],'gbdt_cheap':FEATURES,
          'readout_linear':READOUT_FEATURES,'readout_tree':READOUT_FEATURES}
    report['models']={};oof={};fold_ids=[]
    splits=list(fold.split(rows,groups=groups))
    for train,test in splits:
        assert not set(groups[train])&set(groups[test])
        fold_ids.append({'train':sorted(set(groups[train])),'test':sorted(set(groups[test]))})
    for name,features in sets.items():
        model_rows=with_readout(rows) if name.startswith('readout_') else rows
        predictions={k:np.zeros(len(rows)) for k in y}
        for train,test in splits:
            predictor=(TreePredictor if name in ['gbdt_cheap','readout_tree'] else Predictor)(features).fit([model_rows[i] for i in train])
            preds=predictor.predict([model_rows[i] for i in test])
            for key in y:predictions[key][test]=preds[key]
        model_metrics={k:metrics(y[k],predictions[k]) for k in y}
        net=predictions['step_fix']-predictions['step_harm']
        observed=np.array([r['step_correct']-r['stop_correct'] for r in rows])
        rho=spearmanr(net,observed).statistic
        model_metrics['net_spearman']=float(rho) if np.isfinite(rho) else None
        report['models'][name]=model_metrics;oof[name]={k:v.tolist() for k,v in predictions.items()}
        print(name,json.dumps(model_metrics),flush=True)
    predictor=Predictor().fit(rows)
    with (out/'predictor.pkl').open('wb') as f:pickle.dump(predictor,f)
    with (out/'predictor_linear.pkl').open('wb') as f:pickle.dump(predictor,f)
    tree=TreePredictor().fit(rows)
    with (out/'predictor_tree.pkl').open('wb') as f:pickle.dump(tree,f)
    for name,cls in [('readout_linear',Predictor),('readout_tree',TreePredictor)]:
        model=cls(READOUT_FEATURES).fit(with_readout(rows))
        with (out/f'predictor_{name}.pkl').open('wb') as f:pickle.dump(model,f)
    (out/'grouped_cv.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'oof_predictions.json').write_text(json.dumps({'checkpoint_ids':[r['checkpoint_id'] for r in rows],'folds':fold_ids,'predictions':oof}),encoding='utf-8')


if __name__=='__main__':main()
