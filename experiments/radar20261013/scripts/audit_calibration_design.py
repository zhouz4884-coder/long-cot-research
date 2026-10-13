"""Risk-design feasibility before any calibration outcome, never certification."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_risk import strata_from_frozen_data,finite_test_risk_audit

assert not list((ROOT/'results').glob('bank_calibration_*.jsonl'))
strata=strata_from_frozen_data(ROOT)
report={'scope':'Prospective design feasibility with hypothetical zero calibration harms; no model outcomes or certification.',
 'strata_count':len(strata),'calibration_n':sum(n for N,n in strata),'test_n':sum(N-n for N,n in strata),
 'test_questions_in_unsampled_strata':sum(N for N,n in strata if n==0),
 'data_freeze_sha256':hashlib.sha256((ROOT/'provenance/data_freeze.json').read_bytes()).hexdigest(),
 'strata_N_and_calibration_n':strata,
 'hypothetical_zero_harm_feasibility':{str(k):{str(e):finite_test_risk_audit(strata,0,e,.05/k) for e in [.01,.02]} for k in [1,8]}}
(ROOT/'provenance/calibration_design_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='strata_N_and_calibration_n'},indent=2))
