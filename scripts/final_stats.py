"""Question-paired statistics; absent GPU results stay absent."""
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from scipy.stats import beta


def cluster_comparison(reference,candidate,draws=2000):
    ids=sorted(set(reference)&set(candidate));n=len(ids)
    if not n:return {'n':0,'status':'no_paired_results'}
    a=np.array([[reference[k]['correct'],reference[k]['total_tokens'],reference[k]['wall_ms']] for k in ids],dtype=float)
    b=np.array([[candidate[k]['correct'],candidate[k]['total_tokens'],candidate[k]['wall_ms']] for k in ids],dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all() or np.any(a[:,1:]<=0) or np.any(b[:,1:]<=0):
        raise ValueError('Missing, nonfinite or nonpositive measured cost; do not manufacture a speedup')
    rng=np.random.default_rng(20261008);bootstrap=[]
    for _ in range(draws):
        index=rng.integers(0,n,n);aa=a[index];bb=b[index]
        bootstrap.append([np.mean(bb[:,0]-aa[:,0]),1-bb[:,1].sum()/aa[:,1].sum(),1-bb[:,2].sum()/aa[:,2].sum()])
    ci=np.quantile(np.array(bootstrap),[0.025,0.975],axis=0)
    harms=int(np.sum((a[:,0]==1)&(b[:,0]==0)));fixes=int(np.sum((a[:,0]==0)&(b[:,0]==1)))
    harm_upper=float(beta.ppf(0.95,harms+1,n-harms)) if harms<n else 1.0
    return {'n':n,'problem_ids':ids,'accuracy_delta':float(np.mean(b[:,0]-a[:,0])),
        'token_saving':float(1-b[:,1].sum()/a[:,1].sum()),'wall_saving':float(1-b[:,2].sum()/a[:,2].sum()),
        'bootstrap_95ci':{key:[float(ci[0,j]),float(ci[1,j])] for j,key in enumerate(['accuracy_delta','token_saving','wall_saving'])},
        'harmful_pairs':harms,'beneficial_pairs':fixes,'one_sided_95_harm_upper':harm_upper,
        'conservative_one_pp_noninferiority_certified':harm_upper<=0.01,
        'warning':'A zero-width bootstrap interval with zero observed errors does not certify absence of rare harms; exact harm bound is separate.'}


def main():
    out=Path('results/analysis');out.mkdir(parents=True,exist_ok=True)
    models=defaultdict(lambda:defaultdict(dict))
    for f in Path('results/online').glob('*.jsonl'):
        for line in f.read_text(encoding="utf-8").splitlines():
            row=json.loads(line);model=row['model_path'].split('/')[-1]
            assert row['quality_labels_available_during_decisions'] is False
            key=row['problem_id'];method=row['method']
            assert key not in models[model][method],'Duplicated online evaluation'
            models[model][method][key]=row
    report={'models':{},'inference_unit':'problem_id','bootstrap_draws':2000,'status':'complete' if models else 'no_online_results'}
    freeze=json.loads(Path('provenance/FINAL_EVALUATION_FREEZE_20261012.json').read_text(encoding='utf-8'))
    expected={freeze['primary_model']:{m:freeze['primary_n'] for m in freeze['primary_methods']},
              freeze['second_model']:{m:freeze['second_model_n'] for m in freeze['second_model_methods']}}
    expected[freeze['primary_model']].update({m:freeze['additional_controls_n'] for m in freeze['additional_controls']})
    for model,methods in expected.items():
        for method,n in methods.items():
            actual=len(models.get(model,{}).get(method,{}))
            if actual!=n:raise ValueError(f'Incomplete frozen evaluation: {model}/{method}: {actual}/{n}')
    report['expected_counts_verified']=True
    report['total_online_records']=sum(len(rows) for methods in models.values() for rows in methods.values())
    for model,methods in models.items():
        item={'methods':{},'comparisons':{}}
        for method,by_id in methods.items():
            rows=list(by_id.values());item['methods'][method]={'n':len(rows),'correct':sum(r['correct'] for r in rows),
                'accuracy':float(np.mean([r['correct'] for r in rows])),
                'mean_tokens':float(np.mean([r['total_tokens'] for r in rows])),
                'mean_wall_ms':float(np.mean([r['wall_ms'] for r in rows])),
                'p95_wall_ms':float(np.quantile([r['wall_ms'] for r in rows],0.95)),
                'mean_detector_ms':float(np.mean([r['detector_ms'] for r in rows])),
                'length_censored':sum(r['length_censored'] for r in rows),'parse_failed':sum(r['grade']['parse_status']!='ok' for r in rows)}
        for method in methods:
            if method!='full' and 'full' in methods:item['comparisons'][method+'_vs_full']=cluster_comparison(methods['full'],methods[method])
        if 'transition' in methods:
            for baseline in ['learned_stop','eat','conformal_thinking','fixed0','fixed1024','random','value_outcome','value_frequency','value_cheap','matched_stop']:
                if baseline in methods:item['comparisons']['transition_vs_'+baseline]=cluster_comparison(methods[baseline],methods['transition'])
        report['models'][model]=item
    (out/'online_statistics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
