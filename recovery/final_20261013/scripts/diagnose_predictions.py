"""Question-group uncertainty for rare-event diagnostics."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score
from scripts.analyze_transitions import load
from reason_transition.predictor import targets

rows=load('development');out=Path('results/analysis')
saved=json.loads((out/'oof_predictions.json').read_text(encoding='utf-8'))
assert saved['checkpoint_ids']==[r['checkpoint_id'] for r in rows]
ids=np.array([r['problem_id'] for r in rows]);unique=sorted(set(ids))
group_indices=[np.flatnonzero(ids==key) for key in unique]
y=targets(rows);rng=np.random.default_rng(20261008)
bootstrap=[np.concatenate([group_indices[j] for j in rng.integers(0,len(unique),len(unique))]) for _ in range(500)]
report={'question_n':len(unique),'checkpoint_n':len(rows),'bootstrap_unit':'problem_id','draws':500,'models':{},'ap_differences':{}}
for name,pred in saved['predictions'].items():
    item={}
    for action,key in [('step','step_correct'),('full','end_correct')]:
        predicted=np.array(pred[action+'_fix'])-np.array(pred[action+'_harm'])
        observed=np.array([r[key]-r['stop_correct'] for r in rows])
        q_prediction=np.array([predicted[g].mean() for g in group_indices]);q_observed=np.array([observed[g].mean() for g in group_indices])
        result=spearmanr(q_prediction,q_observed)
        item[action]={'question_mean_spearman':float(result.statistic) if np.isfinite(result.statistic) else None,
            'question_mean_p':float(result.pvalue) if np.isfinite(result.pvalue) else None}
    report['models'][name]=item
for key in ['step_fix','step_harm','full_fix','full_harm']:
    for candidate,baseline in [('all_cheap','length_only'),('all_cheap','confidence_only'),('gbdt_cheap','all_cheap'),
                               ('readout_linear','all_cheap'),('readout_tree','gbdt_cheap')]:
        if y[key].sum()==0:continue
        a=np.array(saved['predictions'][candidate][key]);b=np.array(saved['predictions'][baseline][key]);differences=[]
        for index in bootstrap:
            if y[key][index].sum()==0:continue
            differences.append(average_precision_score(y[key][index],a[index])-average_precision_score(y[key][index],b[index]))
        report['ap_differences'][key+'_'+candidate+'_vs_'+baseline]={'point':float(average_precision_score(y[key],a)-average_precision_score(y[key],b)),
            'cluster_95ci':np.quantile(differences,[0.025,0.975]).tolist(),'valid_draws':len(differences)}
(out/'prediction_cluster_diagnostics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
