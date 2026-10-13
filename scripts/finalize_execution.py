"""Run analysis only when all frozen GPU evaluation stages actually complete."""
import hashlib,json,os,subprocess,tarfile,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];os.chdir(root);py=str(root/'.venv/bin/python')
while not Path('results/heldout_300.complete.json').exists():
 if Path('results/holdout_state.json').exists() and json.loads(Path('results/holdout_state.json').read_text()).get('status')=='failed':raise RuntimeError('Held-out generation failed')
 time.sleep(20)
for script in ['scripts/analyze_controls.py','scripts/audit_bank.py','scripts/validate_study_artifacts.py','scripts/audit_online_trajectories.py','scripts/final_stats.py','scripts/export_online_cases.py','scripts/representation_sensitivity.py','scripts/diagnose_online_failures.py','scripts/plot_research_results.py','scripts/write_final_report.py']:
 subprocess.run([py,script],check=True)
files=[p for folder in ['results','logs','provenance','figures','docs','scripts','reason_transition','configs','data','tests'] for p in Path(folder).rglob('*') if p.is_file() and p.suffix not in ['.pending','.pyc']]
files.extend(Path(name) for name in ['README.md','requirements-experiment.txt','.gitattributes'] if Path(name).is_file())
manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
mp=Path('FINAL_REMOTE_FILES_MANIFEST.json');mp.write_text(json.dumps(manifest,indent=2))
with tarfile.open('final_experiment_snapshot.tar.gz','w:gz') as tf:
 for p in files+[mp]:tf.add(p,arcname=str(p))
payload={'status':'complete','files':len(files),'snapshot_sha256':hashlib.sha256(Path('final_experiment_snapshot.tar.gz').read_bytes()).hexdigest(),'completed_unix':time.time()}
Path('results/FINAL_EXECUTION.json').write_text(json.dumps(payload,indent=2));print(json.dumps(payload),flush=True)
