"""Choose all ablation operating points from the same engineering candidates."""
import hashlib
import json
from pathlib import Path
import time

path=Path('results/analysis/policy_calibration.json');cal=json.loads(path.read_text())
assert sum(len(p.read_text().splitlines()) for p in Path('results/online').glob('*.jsonl'))==0
old_hash=hashlib.sha256(path.read_bytes()).hexdigest()
selected_type=cal['selected_empirical']['transition'].get('predictor_type','linear')
selected_control=cal['selected_empirical']['transition'].get('control_mode','one_shot')
alternate_control='sequential_adaptive' if selected_control=='sequential' else 'sequential'
cheap_type=selected_type.removeprefix('readout_')
queries={
 'value_outcome':{'method':'transition','predictor_type':selected_type,'prediction_mode':'outcome','control_mode':selected_control},
 'value_frequency':{'method':'transition','predictor_type':selected_type,'prediction_mode':'transition','control_mode':alternate_control},
 'value_cheap':{'method':'transition','predictor_type':cheap_type,'prediction_mode':'transition','control_mode':selected_control},
 'matched_stop':{'method':'learned_stop','predictor_type':selected_type}}
cal['selected_empirical'].pop('tree_stop',None)
cal['selected_empirical'].pop('value_dense',None)
for method,query in queries.items():
 candidates=[r for r in cal['candidates'] if all(r.get(k)==v for k,v in query.items()) and r['delta_accuracy']>=-0.01]
 cal['selected_empirical'][method]=min(candidates,key=lambda r:r['estimated_compute_units']) if candidates else {'method':'full','reason':'No engineering point meets shared quality tolerance'}
path.write_text(json.dumps(cal,indent=2),encoding='utf-8')
payload={'admitted':True,'frozen_unix':time.time(),'prior_policy_sha256':old_hash,'policy_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'online_records_at_freeze':0,'ablation_queries':queries,'primary_specs_unchanged':True,'selected_ablation_specs':{m:cal['selected_empirical'][m] for m in queries}}
Path('provenance/ABLATION_POLICY_FREEZE_20261012.json').write_text(json.dumps(payload,indent=2))
print(json.dumps(payload,indent=2))
