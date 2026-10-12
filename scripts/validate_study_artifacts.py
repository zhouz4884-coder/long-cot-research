"""Artifact counts, frozen policies, source identities and finite cost audit."""
import hashlib,json,math
from collections import defaultdict
from pathlib import Path

split={name:{json.loads(line)['problem_id'] for line in Path(f'data/{name}.jsonl').read_text(encoding='utf-8').splitlines()} for name in ['development','engineering','test']}
assert [len(split[k]) for k in ['development','engineering','test']]==[150,50,300]
assert len(set.union(*split.values()))==500
cal_path=Path('results/analysis/policy_calibration.json')
freeze=json.loads(Path('provenance/ABLATION_POLICY_FREEZE_20261012.json').read_text())
assert hashlib.sha256(cal_path.read_bytes()).hexdigest()==freeze['policy_sha256']
assert freeze['online_records_at_freeze']==0
generation=json.loads(Path('provenance/ONLINE_GENERATION_FILES_20261012.json').read_text())['sha256']
for name in ['reason_transition/core.py','reason_transition/predictor.py','scripts/evaluate_online.py']:
 assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==generation[name],name
cal=json.loads(cal_path.read_text());rows=[];counts=defaultdict(set)
for p in Path('results/online').glob('*.jsonl'):
 for line in p.read_text(encoding='utf-8').splitlines():
  r=json.loads(line);rows.append(r);assert r['problem_id'] in split['test']
  model=r['model_path'].split('/')[-1];key=(model,r['method'])
  assert r['problem_id'] not in counts[key];counts[key].add(r['problem_id'])
  assert r['quality_labels_available_during_decisions'] is False
  assert r['total_tokens']==r['think_tokens']+r['answer_tokens']
  assert all(math.isfinite(r[k]) and r[k]>=0 for k in ['wall_ms','detector_ms','feature_gpu_ms'])
  assert r['wall_ms']>0 and r['total_tokens']>0
  assert r['dtype']=='float16'
  if r['method'] in cal['selected_empirical']:assert r['policy_spec']==cal['selected_empirical'][r['method']]
  assert (r['grade'].get('scorer_version')=='math_verify_0.9_surface_vector_v3' or
          (r['grade']['correct']==0 and r['grade']['parse_status'] in ['parse_failed','grader_error']))
expected=json.loads(Path('provenance/FINAL_EVALUATION_FREEZE_20261012.json').read_text())
assert len(rows)==expected['expected_online_records']
test_order=[json.loads(line)['problem_id'] for line in Path('data/test.jsonl').read_text(encoding='utf-8').splitlines()]
for method in expected['primary_methods']:assert counts[(expected['primary_model'],method)]==split['test']
for method in expected['additional_controls']:assert counts[(expected['primary_model'],method)]==set(test_order[:50])
for method in expected['second_model_methods']:assert counts[(expected['second_model'],method)]==set(test_order[50:74])
payload={'passed':True,'online_records':len(rows),'problem_splits_disjoint':True,'all_expected_problem_ids_match':True,
 'policy_unchanged_from_zero_test_record_freeze':True,'all_costs_finite_and_nonnegative':True,'common_fp16_and_scorer':True,
 'generating_source_hashes_unchanged':True,
 'claim_scope':'This is provenance/count audit. It is not proof of absence of MATH-500 pretraining contamination or external validity.'}
Path('results/analysis/study_integrity.json').write_text(json.dumps(payload,indent=2));print(json.dumps(payload))
