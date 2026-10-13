"""Executable scope checks against immutable upstream source snapshots."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/ConformalThinking'))
import risk_control_utils as risk
from signal_util import exit_time_lower_threshold

entry={'confidence':np.array([.2,.4]),'intermediate_correct':np.array([False,True]),
       'tokens_used':np.array([100,200])}
try:
    risk.threshold_to_loss_vectorized_lower(entry,{'c':.1},exit_time_lower_threshold)
    lower_result={'exception':None}
except Exception as e:
    lower_result={'exception':type(e).__name__,'message':str(e)}
root=ROOT/'vendor/DEER'
files=[p for p in root.rglob('*.py')]
pro_matches=[]
for p in files:
    text=p.read_text(encoding='utf-8',errors='replace')
    if 'CMAD' in text or 'DEER-PRo' in text or 'mean_absolute_deviation' in text:
        pro_matches.append(str(p.relative_to(root)))
report={'scope':'Code existence/interface checks only, not method efficacy or complete paper reproduction.',
        'source_freeze':json.loads((ROOT/'provenance/baseline_source_freeze.json').read_text(encoding='utf-8')),
        'conformal_lower_utility_smoke':lower_result,
        'conformal_readme_preliminary': 'Preliminary code' in (ROOT/'vendor/ConformalThinking/README.md').read_text(encoding='utf-8'),
        'deer_readme_branch_parallel_coming_soon':'Branch-Parallel Decoding Acceleration' in (root/'README.md').read_text(encoding='utf-8'),
        'deer_pro_name_or_mad_source_matches':pro_matches,
        'not_found_warning':'No token match is not proof that no equivalent algorithm exists; manual implementation audit remains necessary.'}
assert lower_result.get('exception')=='NameError'
out=ROOT/'provenance/baseline_implementation_audit.json'
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
