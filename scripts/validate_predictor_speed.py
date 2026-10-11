"""Validate exact algebraic fusion on real pilot rows, not synthetic accuracy."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from reason_transition.predictor import Predictor,matrix

rows=[]
for p in Path('results/bank').glob('engineering_branches_*.jsonl'):
    if '_orphan_' not in p.name:rows.extend(json.loads(x) for x in p.read_text(encoding='utf-8').splitlines())
assert rows
predictor=Predictor().fit(rows);reference=predictor.predict(rows)
fast=[predictor.fast_one(row['features']) for row in rows]
error=max(float(np.max(np.abs(reference[k]-np.array([r[0][k] for r in fast])))) for k in reference)
cost_error=0.0
for action,model in predictor.cost_heads.items():
    raw=np.expm1(np.clip(model.predict(matrix(rows)),0,12))
    cost_error=max(cost_error,float(np.max(np.abs(raw-np.array([r[1][action] for r in fast])))))
assert error<1e-10 and cost_error<1e-5,(error,cost_error)
feature=rows[0]['features'];n=5000
start=time.perf_counter()
for _ in range(n):predictor.choose(feature)
us=(time.perf_counter()-start)*1e6/n
report={'real_pilot_rows':len(rows),'max_probability_error':error,'max_cost_prediction_error':cost_error,
    'fused_decision_mean_us':us,'iterations':n,'scope':'CPU predictor implementation equivalence and cost; not model accuracy or GPU speedup'}
Path('results/analysis').mkdir(parents=True,exist_ok=True)
Path('results/analysis/predictor_implementation_qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
