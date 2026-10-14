"""Complete native sensitivity results; censoring and reader scope separated."""
import hashlib,json,math,sys
from pathlib import Path
import numpy as np
from scipy.stats import binomtest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stem_quality import stem_issues,numeric_gold_issues
spec=json.loads((ROOT/'provenance/native_pilot_protocol.json').read_text())
qs=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:spec['n']]
ids={q['problem_id'] for q in qs if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])}
rows=[]
for g in [0,1]:
    assert (ROOT/f'results/native_pilot_{g}.complete.json').exists()
    rows += [json.loads(s) for s in (ROOT/f'results/native_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines()]
expected={(pid,b) for pid in ids for b in spec['nominal_thought_budgets']}
assert {(r['problem_id'],r['nominal_budget']) for r in rows}==expected and len(rows)==len(expected)
protocol_hash=hashlib.sha256((ROOT/'provenance/native_pilot_protocol.json').read_bytes()).hexdigest()
data_hash=hashlib.sha256((ROOT/'data/pilot.jsonl').read_bytes()).hexdigest()
identity=json.loads((ROOT/spec['model_identity_file']).read_text())
assert hashlib.sha256((ROOT/spec['model_identity_file']).read_bytes()).hexdigest()==spec['model_identity_manifest_sha256']
expected_files={item['name']:item['sha256'] for item in identity['files']}
for row in rows:
    assert row['protocol_sha256']==protocol_hash and row['data_sha256']==data_hash
    assert row['model_revision']==spec['model_revision']
    assert row['model_identity_manifest_sha256']==spec['model_identity_manifest_sha256']
    assert row['live_model_file_sha256']==expected_files
    assert row['quality_labels_available_during_generation'] is False
    assert math.isfinite(row['wall_ms']) and row['wall_ms']>0
    assert row['total_tokens']==len(row['trace']['ids'])<=row['total_budget']
    assert row['thinking_tokens']+row['native_answer_tokens']==row['total_tokens']
methods={budget:{r['problem_id']:r for r in rows if r['nominal_budget']==budget}
         for budget in spec['nominal_thought_budgets']}
forced={budget:{} for budget in spec['nominal_thought_budgets']}
for g in [0,1]:
    for line in (ROOT/f'results/pilot_full_{g}.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['problem_id'] in ids:forced[8192][row['problem_id']]=row
    for line in (ROOT/f'results/budget_pilot_{g}.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['budget']==16384:forced[16384][row['problem_id']]=row
assert all(set(group)==ids for group in forced.values())


def paired_quality(candidate,reference):
    order=sorted(ids);delta=np.array([candidate[i]['correct']-reference[i]['correct'] for i in order])
    harms=sum(reference[i]['correct']==1 and candidate[i]['correct']==0 for i in order)
    benefits=sum(reference[i]['correct']==0 and candidate[i]['correct']==1 for i in order)
    discordant=harms+benefits;rng=np.random.default_rng(20261014)
    draws=delta[rng.integers(0,len(order),(4000,len(order)))].mean(axis=1)
    return {'n':len(order),'candidate_correct':sum(r['correct'] for r in candidate.values()),
            'reference_correct':sum(r['correct'] for r in reference.values()),
            'accuracy_delta':float(delta.mean()),'problem_bootstrap95ci':np.quantile(draws,[.025,.975]).tolist(),
            'harmful':int(harms),'beneficial':int(benefits),
            'conditional_exact_mcnemar_two_sided_p':float(binomtest(benefits,discordant,.5).pvalue) if discordant else 1.,
            'independent_policy_certification':False}


statistics={}
for b in spec['nominal_thought_budgets']:
    group=[r for r in rows if r['nominal_budget']==b];finished=[r for r in group if r['eos_completed']]
    statistics[str(b)]={'n':len(group),'correct':sum(r['correct'] for r in group),
        'thinking_closed':sum(r['thinking_closed'] for r in group),'length_censored':sum(r['length_censored'] for r in group),
        'eos_completed':len(finished),'correct_among_eos_completed':sum(r['correct'] for r in finished),
        'censored_complete_answer_correct':sum(r['correct'] and r['length_censored'] for r in group),
        'parse_non_success':sum(r['grade']['parse_status']!='ok' for r in group),
        'mean_wall_s':float(np.mean([r['wall_ms']/1000 for r in group])),
        'mean_tokens':float(np.mean([r['total_tokens'] for r in group])),
        'wall_s_quantiles':dict(zip(['p50','p95','p99'],np.quantile([r['wall_ms']/1000 for r in group],[.5,.95,.99]).tolist())),
        'thinking_unclosed':sum(not r['thinking_closed'] for r in group),
        'closed_but_missing_or_unparsed_final':sum(r['thinking_closed'] and r['grade']['parse_status']!='ok' for r in group),
        'parsed_wrong':sum(r['grade']['parse_status']=='ok' and not r['correct'] for r in group),
        'thinking_exceeded_nominal_cap':sum(r['thinking_tokens']>b for r in group),
        'thinking_prefix_control_failures':sum(not r['same_thinking_prefix_control'] for r in group)}
paired={};controls=[];cases=[]
for budget in spec['nominal_thought_budgets']:
    candidate=methods[budget];reference=forced[budget]
    paired[str(budget)]=paired_quality(candidate,reference)
    for pid,row in candidate.items():
        ref=reference[pid];thought=row['trace']['ids'][:row['thinking_tokens']]
        shared=min(len(thought),len(ref['trace']['ids']))
        same=row['seed']==ref['seed'] and row['model_path']==ref['model_path'] and thought[:shared]==ref['trace']['ids'][:shared]
        if not same:controls.append({'problem_id':pid,'budget':budget,'reason':'matched_thinking_prefix_diverged'})
        if row['correct']!=ref['correct'] or row['grade']['parse_status']!='ok':
            cases.append({'problem_id':pid,'nominal_budget':budget,'native_correct':row['correct'],
                          'forced_correct':ref['correct'],'native_thinking_closed':row['thinking_closed'],
                          'native_censored':row['length_censored'],'native_parse_status':row['grade']['parse_status'],
                          'native_answer':row['native_answer_text'],'forced_answer':ref['answer']['text'],
                          'cause':'unknown','is_cue_only_intervention':False})
assert not controls,'Investigate actual matched-prefix failures before interpreting readout differences'
report={'scope':'Pilot readout sensitivity, distinct total-budget native protocol; no blind-test or learned-policy performance.',
        'no_injected_answer_cue':True,'statistics':statistics,'source_problem_ids':sorted(ids),
        'native_vs_forced_reader_paired':paired,
        'native16384_vs_native8192':paired_quality(methods[16384],methods[8192]),
        'matched_thinking_prefix_controls_passed':True,'control_failures':controls,
        'interpretation_warning':'Protocol sensitivity jointly changes injected cue, post-close sampling coupling and allocation between thinking/final answer. Native total cap=nominal+192; native thinking may exceed nominal. Original forced8192 also captures features. Do not attribute all quality/time differences to the cue or pool protocols.',
        'small_sample_warning':'Only29 matched diagnostic questions. Exact paired test accompanies percentile bootstrap; no risk certification or final strategy choice follows automatically.',
        'review_cases':cases,
        'analysis_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'native_protocol_sha256':protocol_hash,
        'raw_source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                             for name in ['native_pilot','pilot_full','budget_pilot']
                             for p in sorted((ROOT/'results').glob(name+'_[01].jsonl'))}}
(ROOT/'results/native_pilot_analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='source_problem_ids'},indent=2))
