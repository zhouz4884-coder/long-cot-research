import json,os,hashlib,shutil,subprocess,time,sys
from pathlib import Path
root=Path.cwd();py=str(root/'.venv/bin/python')
sys.path.insert(0,str(root))
env=os.environ.copy();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
assert not list(Path('results/online').glob('*.jsonl')),'Repair must precede held-out evaluation'
old=Path('results/scoring_v2_backup');old.mkdir(exist_ok=True)
for name in ['bank','analysis']:
 if not (old/name).exists():shutil.copytree(Path('results')/name,old/name)
for text,gold,want in [(r'\boxed{(-2)(3) + (0)(4) + (7)(-5)}','-41',1),(r'\boxed{(-2)(3) + (0)(4) + (7)(-5)}','-36',0),(r'\boxed{log_2 8}','3',1),(r'\boxed{log_2 8}','8',0)]:
 from reason_transition.core import grade
 assert grade(text,gold)['correct']==want,(text,gold)
print('V3_SCORER_POSITIVE_AND_NEGATIVE_CONTROLS_PASS',flush=True)
for script in ['scripts/regrade_bank.py','scripts/analyze_transitions.py','scripts/diagnose_predictions.py','scripts/calibrate_policies.py']:
 subprocess.run([py,script],env=env,check=True)
for name in ['grouped_prediction','calibration']:
 Path(f'results/{name}.complete.json').write_text(json.dumps({'scorer_version':'surface_vector_v3','completed_unix':time.time()}))
subprocess.run([py,'scripts/validate_cache_clone.py'],env={**env,'CUDA_VISIBLE_DEVICES':'1'},check=True)
lock=Path('provenance/FINAL_POLICY_LOCK_20261012.json')
shutil.copy2(lock,lock.with_name('FINAL_POLICY_LOCK_PRE_SCORER_REPAIR_20261012.json'))
payload={'policy_sha256':hashlib.sha256(Path('results/analysis/policy_calibration.json').read_bytes()).hexdigest(),'core_sha256':hashlib.sha256(Path('reason_transition/core.py').read_bytes()).hexdigest(),'scorer_version':'surface_vector_v3','online_records_at_extension':0,'reason':'Confirmed scoring defects corrected uniformly before any test generation'}
lock.write_text(json.dumps(payload,indent=2));print('REFROZEN',json.dumps(payload),flush=True)
# An old repeat child is allowed to finish; do not create concurrent writers.
while True:
 rows=[json.loads(x) for x in Path('results/controls/repeat_branches.jsonl').read_text().splitlines()]
 if len(rows)>=32:break
 time.sleep(10)
log=Path('logs/pipeline_after_scoring_v3.log').open('a')
process=subprocess.Popen([py,'-u','scripts/run_pipeline.py'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
Path('logs/pipeline.pid').write_text(str(process.pid));print('RESTARTED_MASTER',process.pid,flush=True)
