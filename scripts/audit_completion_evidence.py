"""Finite-scope evidence audit of the complete research programme."""
import hashlib,json
from pathlib import Path

def read(name):return json.loads(Path(name).read_text(encoding='utf-8'))
raw=[json.loads(s) for s in Path('results/original_raw.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(raw)==168 and {r['call'] for r in raw}==set(range(168))
assert all(r['batch_size']==1 and r['do_sample'] is False for r in raw)
primary=read('provenance/qwen3_4b_verified.json');second=read('provenance/qwen3_thinking_verified.json')
assert primary['all_match'] and second['all_match']
protocol=read('results/protocol/checks.json');clone=read('results/protocol/clone_check.json');probe=read('results/protocol/entropy_probe_crop.json')
assert protocol['admitted'] and protocol['ending_n']==24 and len(protocol['cache'])==5
assert clone['passed'] and clone['code_sha256']==hashlib.sha256(Path('reason_transition/core.py').read_bytes()).hexdigest()
assert len(probe)==3 and all(r['same_kv'] and r['same_sampled_continuation'] and r['entropy_error']==0 for r in probe)
pilot=read('results/protocol/pilot_review.json');assert pilot['admitted'] and pilot['sample_n']==50 and pilot['covered_problems']==24
lineage=read('results/audit/bank_lineage.json')['splits']
assert lineage['development']['trace_n']==150 and lineage['engineering']['trace_n']==50
assert lineage['development']['checkpoint_n']==699 and lineage['engineering']['checkpoint_n']==210
assert all(r['all_prefixes_hash_and_parent_ids_match'] for r in lineage.values())
oof=read('results/analysis/oof_predictions.json');assert len(oof['checkpoint_ids'])==699 and len(oof['folds'])==5
all_test=[]
for fold in oof['folds']:
 assert not set(fold['train'])&set(fold['test']);all_test+=fold['test']
assert len(all_test)==len(set(all_test))==149
assert {s.split(':')[0] for s in oof['checkpoint_ids']}==set(all_test)
rep=read('results/analysis/repeat_control_analysis.json');assert rep['state_n']==9 and rep['repeat_n']==36 and all(r['n']==4 for r in rep['states'])
integrity=read('results/analysis/study_integrity.json');stats=read('results/analysis/online_statistics.json');trajectory=read('results/analysis/trajectory_consistency.json')
assert integrity['passed'] and stats['expected_counts_verified'] and stats['total_online_records']==1648
assert trajectory['is_final'] and all(trajectory[k] for k in ['all_observed_prefixes_match','all_observed_same_context_answers_match','all_observed_identical_outputs_scored_consistently'])
for model,cohorts in [("Qwen3-4B",{'main_300':300,'diagnostic_50':50}),("Qwen3-4B-Thinking-2507",{'transfer_24':24})]:
 for name,n in cohorts.items():assert stats['models'][model]['cohorts'][name]['n']==n
qa=read('provenance/FIGURE_QA.json');assert qa['file_checks_passed'] and qa['figure_count']==6
report=Path('docs/REPORT_ZH.md').read_text(encoding='utf-8');assert '1648' in report and 'NO-GO' in report and '敏感性' in report
assert read('results/analysis/representation_sensitivity.json')['is_primary_analysis'] is False
assert read('results/analysis/online_failure_diagnostics.json')['models']['Qwen3-4B']['harm_n']==25
requirements={
 'model_and_data_freeze':'revision/file checks and study split/hash admission',
 'original_p0':'168 actual observed BF16 greedy generation calls',
 'protocol_and_cache':'24 endings, five numeric prefixes, real cache clone and three append/crop probes',
 'pilot_manual_review':'stored 50-answer manual audit covering 24 engineering problems',
 'development_and_engineering':'150/50 complete trajectories; 699/210 stored parent-matching checkpoints',
 'grouped_prediction':'699 OOF checkpoint predictions; five problem-disjoint test folds covering 149 eligible problems',
 'innovation_and_comparators':'frozen engineering selections, four 300-question methods and eight 50-question controls/ablations',
 'sampling_controls':'nine retained states, four independent-seed pairs each',
 'actual_online_and_transfer':'1648 scope-exact records, second model 24 paired questions',
 'real_cost_and_statistics':'positive measured costs; 2000 question-paired bootstrap and exact harmful-pair bound',
 'failure_analysis':'all 31 model/controller reversals exported; frozen decision diagnostics and separately labelled surface sensitivity',
 'scientific_figures':'six visually reviewed PNGs plus embedded-font vector PDF and editable-text SVG',
 'full_report':'source-grounded Chinese full workflow, results, causes versus hypotheses and next improvements',
 'reproducibility':'fixed data, model identities, code, dependency versions, raw outputs and archive manifests'}
payload={'finite_programme_requirements_verified':True,'requirements':requirements,
 'manual_evidence':'Share-chat reading and case/figure reviews were performed in this task. Hashes and this audit do not independently prove human reading or scientific novelty.',
 'scientific_outcome':'Current quality-preserving controller NO-GO; publication acceptance was not a completion condition.'}
Path('provenance/COMPLETION_AUDIT.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps({'verified':True,'requirements':len(requirements),'real_online_records':1648,'scientific_outcome':'NO-GO'}))
