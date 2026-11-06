"""User-authorized exploratory analysis of the existing incomplete dev bank.

No model calls, new formal candidates, calibration/test reads or risk claims.
Replay timing is explicitly a proxy; bank collection cost is observed worker wall.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from joint_predictor import JointModel,PREFIX_FEATURES,ANSWER_FEATURES
from protocol_guard import validate_formal,sha256


def vote(reads):
    groups=defaultdict(list)
    for i,read in enumerate(reads):
        schema=read['schema']
        if schema['valid']:groups[schema['key']].append(i)
    winners=[indices for indices in groups.values() if len(indices)>=2]
    return reads[winners[0][0]] if winners else reads[0]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output);assert not output.exists()
    formal,fh=validate_formal(ROOT)
    files=[ROOT/f'results/bank_development_{g}.jsonl' for g in [0,1]]
    rows=[]
    for file in files:
        for line in file.read_bytes().splitlines(keepends=True):
            if line.endswith(b'\n'):rows.append(json.loads(line))
    assert rows and len({r['problem_id'] for r in rows})==len(rows)
    assert all(r['formal_protocol_sha256']==fh for r in rows)
    n=len(rows);entries=[];lookup={};weights=[]
    for row in rows:
        for point in row['points']:
            read=point['readouts'][0];features={**point['features'],**point['candidate_features']}
            lookup[(row['problem_id'],point['offset'])]=len(entries)
            entries.append({'problem_id':row['problem_id'],'point':point,'features':features,
                            'current':int(read['correct']),'after':int(row['full']['correct'])})
            weights.append(1/max(1,len(row['points'])))
    groups=np.array([e['problem_id'] for e in entries]);current=np.array([e['current'] for e in entries])
    after=np.array([e['after'] for e in entries]);weights=np.asarray(weights)
    metrics={};predictions={}
    for name,features in {'prefix':PREFIX_FEATURES,'candidate':PREFIX_FEATURES+ANSWER_FEATURES}.items():
        x=np.array([[e['features'][key] for key in features] for e in entries]);pred=np.zeros((len(entries),4))
        for train,test in GroupKFold(5).split(x,current,groups):
            assert not set(groups[train])&set(groups[test])
            model=JointModel(features).fit(x[train],current[train],after[train],weights[train])
            pred[test]=model.probabilities(x[test])
        predictions[name]=pred
        harm=(current==0)&(after==1)
        metrics[name]={'question_disjoint_oof_current_auc':float(roc_auc_score(current,pred[:,2]+pred[:,3],sample_weight=weights)),
                       'question_disjoint_oof_harm_auc':float(roc_auc_score(harm,pred[:,1],sample_weight=weights)),
                       'independent_question_count':len(set(groups))}
    reference_correct=sum(r['full']['correct'] for r in rows)
    reference_ms=sum(r['full']['instrumented_reference_ms'] for r in rows)
    policies={}
    specs=[('candidate_confidence_'+str(t),'raw',t) for t in [.9,.95,.99]]
    specs += [('oof_current_'+str(t),'current',t) for t in [.8,.9,.95]]
    specs += [('oof_joint_harm_001_current09','joint',.01)]
    for name,kind,threshold in specs:
        correct=harm=benefit=commits=0;time_proxy=0.;counts=[]
        for row in rows:
            chosen=None;overhead=0.;checks=0
            for point in row['points']:
                checks+=1;read=point['readouts'][0]
                overhead+=point['probe']['ms']+read['ms']
                idx=lookup[(row['problem_id'],point['offset'])];probs=predictions['candidate'][idx]
                current_p=probs[2]+probs[3]
                accept=read['maxprob_geomean']>=threshold if kind=='raw' else current_p>=threshold if kind=='current' else current_p>=.9 and probs[1]<=threshold
                if point['schema_valid'] and accept:chosen=(point,read);break
            y=row['full']['correct'] if chosen is None else chosen[1]['correct']
            correct+=y;harm+=row['full']['correct']==1 and y==0;benefit+=row['full']['correct']==0 and y==1
            commits+=chosen is not None;counts.append(checks)
            time_proxy+=row['full']['instrumented_reference_ms']+overhead if chosen is None else chosen[0]['elapsed_ms']+overhead
        policies[name]={'correct':correct,'n':n,'accuracy_delta_pp':100*(correct-reference_correct)/n,
            'harmful':int(harm),'beneficial':int(benefit),'commits':commits,'mean_checked_candidates':float(np.mean(counts)),
            'replay_wall_proxy_saving':1-time_proxy/reference_ms,'actual_online_run':False}
    sparse=[];by_question=defaultdict(list)
    for row in rows:
        for point in row['points']:
            reads=point['readouts']
            if len(reads)!=3:continue
            selected=vote(reads);delta=int(selected['correct'])-int(reads[0]['correct'])
            by_question[row['problem_id']].append(delta)
            sparse.append({'problem_id':row['problem_id'],'offset':point['offset'],'first':int(reads[0]['correct']),
                'voted':int(selected['correct']),'extra_read_ms':sum(r['ms'] for r in reads[1:]),
                'any_correct':any(r['correct'] for r in reads),
                'all_same_key':all(r['schema']['valid'] for r in reads) and len({r['schema']['key'] for r in reads})==1})
    all_reads=[read for row in rows for point in row['points'] for read in point['readouts']]
    collection_ms=sum(r['collection_ms'] for r in rows)
    pause_ms=sum(r['full']['trace']['offline_branching_ms'] for r in rows)
    candidate_ms=sum(read['ms'] for read in all_reads)
    direct_tokens=sum(r['full']['trace']['tokens']+r['full']['answer']['tokens'] for r in rows)
    side_tokens=sum(read['tokens'] for read in all_reads)
    oracle={};oracle_offsets=[]
    for row in rows:
        if not row['full']['correct']:continue
        eligible=[p for p in row['points'] if p['offset']<len(row['full']['trace']['ids']) and p['readouts'][0]['correct'] and p['schema_valid']]
        if eligible:oracle_offsets.append(eligible[0]['offset']/max(1,row['full']['trace']['tokens']))
    metadata=[json.loads(line) for line in (ROOT/'data/development.jsonl').read_text(encoding='utf-8').splitlines()]
    present={r['problem_id'] for r in rows}
    coverage={key:{'observed':dict(Counter(str(r.get(key,'missing')) for r in metadata if r['problem_id'] in present)),
                   'all_development':dict(Counter(str(r.get(key,'missing')) for r in metadata))}
                   for key in ['subject','difficulty'] if any(key in r for r in metadata)}
    report={'scope':'Exploratory round 0 on a nonrandom, incomplete development prefix. User requested fast iteration before completing full M1. No certification, blind-test performance or online policy speed claim.',
        'formal_protocol_sha256':fh,'n':n,'checkpoints':len(entries),'all_development_target':530,
        'reference':{'correct':int(reference_correct),'accuracy':reference_correct/n,
                     'think_cap_count':sum(r['full']['trace']['length_censored'] for r in rows),
                     'mean_instrumented_reference_proxy_s':reference_ms/n/1000},
        'collection_cost':{'observed_collection_worker_hours':collection_ms/3600000,'mean_collection_s':collection_ms/n/1000,
            'recorded_offline_branch_wall_fraction':pause_ms/collection_ms,'side_candidate_wall_fraction':candidate_ms/collection_ms,
            'candidate_readouts':len(all_reads),'mean_checkpoints_per_problem':len(entries)/n,
            'direct_generated_tokens':direct_tokens,'side_readout_generated_tokens':side_tokens,
            'side_readout_token_fraction':side_tokens/(direct_tokens+side_tokens)},
        'oof_models':metrics,'policy_replay_diagnostics':policies,
        'reread_three':{'states':len(sparse),'unique_problems':len(by_question),
            'first_correct':sum(r['first'] for r in sparse),'majority_correct':sum(r['voted'] for r in sparse),
            'harmful_changes':sum(r['first']==1 and r['voted']==0 for r in sparse),
            'beneficial_changes':sum(r['first']==0 and r['voted']==1 for r in sparse),
            'question_equal_weight_delta_pp':100*float(np.mean([np.mean(v) for v in by_question.values()])),
            'at_least_one_of_three_correct':sum(r['any_correct'] for r in sparse),
            'all_same_structural_key':sum(r['all_same_key'] for r in sparse),
            'all_same_key_but_wrong':sum(r['all_same_key'] and not r['first'] for r in sparse),
            'mean_two_additional_readout_s':float(np.mean([r['extra_read_ms'] for r in sparse]))/1000,
            'selection_rule':'First member of schema-key majority; otherwise first readout. No Gold choice.'},
        'oracle_diagnostic':{'full_correct_with_schema_valid_earlier_correct_candidate':len(oracle_offsets),
            'full_correct_total':int(reference_correct),'median_first_correct_fraction_of_thought':float(np.median(oracle_offsets)) if oracle_offsets else None,
            'deployable':False,'meaning':'Gold retrospectively locates a correct candidate; token position only, not policy cost.'},
        'coverage':coverage,'input_bank_sha256':{f.name:sha256(f) for f in files},'problem_ids':sorted(present),
        'source_sha256':sha256(Path(__file__)),'formal_training_or_candidate_files_written':False,'model_gpu_calls':0}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['problem_ids','coverage']},indent=2))


if __name__=='__main__':main()
