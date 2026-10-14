"""Complete problem-paired M1 runtime and bank/online consistency audit."""
import hashlib
import json
import pickle
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from protocol_guard import validate_formal,sha256
from select_calibrate_policies import replay,load_bank


def spec_hash(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    formal,formal_hash=validate_formal(ROOT)
    path=ROOT/'provenance/m1_selection_online.json';policy=json.loads(path.read_text())
    policy_hash=sha256(path);freeze=json.loads((ROOT/'provenance/data_freeze.json').read_text())
    ids=sorted(freeze['splits']['selection']['ids']);methods={m:{} for m in policy['methods']}
    files=[ROOT/f'results/online_m1_selection_{g}.jsonl' for g in [0,1]]
    for g,file in enumerate(files):
        assert (ROOT/f'results/online_m1_selection_{g}.complete.json').exists()
        for line in file.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            assert row['split']=='selection' and row['policy_file_sha256']==policy_hash
            assert row['formal_protocol_sha256']==formal_hash and row['method'] in methods
            assert row['problem_id'] in ids and row['problem_id'] not in methods[row['method']]
            assert row['wall_ms']>0 and np.isfinite(row['wall_ms'])
            methods[row['method']][row['problem_id']]=row
    assert all(set(rows)==set(ids) for rows in methods.values())
    model_paths={r['model_path'] for rows in methods.values() for r in rows.values()};assert len(model_paths)==1
    model_path=next(iter(model_paths));bank=load_bank('selection',model_path)
    bank_by_id={r['problem_id']:r for r in bank}
    controls=[];equivalence={};admitted=[]
    for name,rows in methods.items():
        for pid,row in rows.items():
            full=methods['full'][pid]
            shared=min(len(row['trace']['ids']),len(full['trace']['ids']))
            if row['seed']!=full['seed'] or row['trace']['ids'][:shared]!=full['trace']['ids'][:shared]:
                controls.append({'method':name,'problem_id':pid,'reason':'thinking_prefix_control_failed'})
    for pid,reference in methods['full'].items():
        original=bank_by_id[pid]['full']
        if reference['trace']['ids']!=original['trace']['ids'] or reference['answer']['text']!=original['answer']['text'] or reference['correct']!=original['correct']:
            controls.append({'method':'full','problem_id':pid,'reason':'bank_online_reference_diverged'})
    for name in ['risk_primary','current_correctness']:
        spec=policy['methods'][name];metadata=policy['models'][spec['predictor']]
        model_file=ROOT/metadata['path'];assert sha256(model_file)==metadata['sha256']
        with model_file.open('rb') as handle:learner=pickle.load(handle)
        failed=[]
        for original in bank:
            expected=replay(original,spec,learner);actual=methods[name][original['problem_id']]
            same=(expected['answer_text']==actual['answer']['text'] and expected['correct']==actual['correct'])
            offset=len(actual['trace']['ids']) if actual['committed_checked_candidate'] else None
            same=same and offset==expected['stop_offset']
            if offset is not None:
                same=same and actual['answer']['candidate_identity_sha256']==expected['candidate_identity']
            if not same:failed.append(original['problem_id'])
        passed=not failed and not controls
        equivalence[name]={'passed':passed,'n':len(bank),'failed_problem_ids':failed,'candidate_spec_sha256':spec_hash(spec)}
        if passed:admitted.append(spec_hash(spec))
    consistency={'passed':bool(admitted) and not controls,'model_path':model_path,'formal_protocol_sha256':formal_hash,
                 'policy_file_sha256':policy_hash,'verified_candidate_spec_sha256':admitted,
                 'per_method':equivalence,'controls':controls,
                 'scope':'Finite complete selection sample only; other candidate specs, seeds, models and backends are not admitted by this audit.'}
    (ROOT/'provenance/selection_online_equivalence.json').write_text(json.dumps(consistency,indent=2)+'\n')
    full=methods['full'];ref_y=np.array([full[i]['correct'] for i in ids]);ref_t=np.array([full[i]['wall_ms'] for i in ids])
    rng=np.random.default_rng(20261014);indices=rng.integers(0,len(ids),(4000,len(ids)))
    statistics={}
    for name,rows in methods.items():
        y=np.array([rows[i]['correct'] for i in ids]);t=np.array([rows[i]['wall_ms'] for i in ids]);delta=y-ref_y
        saving=1-t.sum()/ref_t.sum();draw_saving=1-t[indices].sum(axis=1)/ref_t[indices].sum(axis=1)
        statistics[name]={'n':len(ids),'correct':int(y.sum()),'accuracy':float(y.mean()),
                          'accuracy_delta':float(delta.mean()),'accuracy_delta_95ci':np.quantile(delta[indices].mean(axis=1),[.025,.975]).tolist(),
                          'harmful':int(((ref_y==1)&(y==0)).sum()),'beneficial':int(((ref_y==0)&(y==1)).sum()),
                          'mean_wall_s':float(t.mean()/1000),'wall_saving':float(saving),
                          'wall_saving_95ci':np.quantile(draw_saving,[.025,.975]).tolist(),
                          'wall_s_quantiles':dict(zip(['p50','p95','p99'],np.quantile(t/1000,[.5,.95,.99]).tolist())),
                          'mean_compute_tokens':float(np.mean([r['compute_generated_tokens'] for r in rows.values()])),
                          'parse_non_success':sum(r['grade']['parse_status']!='ok' for r in rows.values()),
                          'censored':sum(r['length_censored'] for r in rows.values()),
                          'natural_end':sum(r['trace']['stop_reason']=='natural_end' for r in rows.values()),
                          'committed_checked_candidate':sum(r['committed_checked_candidate'] for r in rows.values()),
                          'wall_saving_on_reference_correct':float(1-t[ref_y==1].sum()/ref_t[ref_y==1].sum()) if (ref_y==1).any() else None,
                          'peak_allocated_bytes':max(r['peak_allocated_bytes'] for r in rows.values())}
    primary=statistics['risk_primary'];gate=policy['measured_m1_gate']
    empirical=(primary['accuracy_delta']>=gate['primary_accuracy_delta_min'] and primary['wall_saving']>=gate['primary_wall_saving_min'])
    same_quality=[(name,s) for name,s in statistics.items() if name!='risk_primary' and s['accuracy_delta']>=-.01]
    best=min(same_quality,key=lambda x:x[1]['mean_wall_s']) if same_quality else None
    report={'scope':'Complete measured selection-stage comparison. Thresholds were selected using these question IDs, so this is exploratory and not blind-test or independent certification.',
            'model_path':model_path,'formal_protocol_sha256':formal_hash,'statistics':statistics,
            'integrity_controls_passed':not controls,'prefix_or_reference_failures':controls,
            'primary_bank_online_equivalence_passed':equivalence['risk_primary']['passed'],
            'primary_empirical_m1_gate_passed':bool(empirical and not controls and equivalence['risk_primary']['passed']),
            'primary_gate_thresholds':gate,'best_same_quality_baseline':best[0] if best else None,
            'primary_saving_vs_best_same_quality_baseline':float(1-primary['mean_wall_s']/best[1]['mean_wall_s']) if best else None,
            'independent_risk_certification_performed':False,'serving_performance_proven':False,
            'raw_source_sha256':{str(f.relative_to(ROOT)):sha256(f) for f in files}}
    (ROOT/'results/m1_online_analysis.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['raw_source_sha256','prefix_or_reference_failures']},indent=2))


if __name__=='__main__':main()
