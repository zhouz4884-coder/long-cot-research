"""Actual upstream interface counterexamples; no GPU efficacy conclusions."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
vendor=ROOT/'vendor/ConformalThinking'
sys.path.insert(0,str(vendor))
spec=importlib.util.spec_from_file_location('frozen_conformal_utils',vendor/'risk_control_utils.py')
upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)
from signal_util import exit_time_first_geq


def main():
    controls=[]
    # The notebook aggregates its two-dimensional per-problem losses first,
    # then passes a length-K mean vector into find_threshold. Its shape[0] is K.
    n_problems=2;delta=.1
    for k in [5,5000]:
        per_problem=np.zeros((n_problems,k))
        averaged=per_problem.mean(0)
        chosen,losses=upstream.find_threshold(np.arange(k),averaged,np.linspace(0,1,k),
                                             epsilon=.1,method='UCB',delta=delta)
        controls.append({'independent_problem_count':n_problems,'candidate_grid_size':k,
                         'selected_threshold_or_minus1':int(chosen),
                         'radius_used_by_snapshot':math.sqrt(math.log(1/delta)/(2*k)),
                         'radius_for_actual_problem_n_without_family_correction':math.sqrt(math.log(1/delta)/(2*n_problems)),
                         'example_is_synthetic_api_control':True})
    assert controls[0]['selected_threshold_or_minus1']==-1 and controls[1]['selected_threshold_or_minus1']>=0
    entry={'confidence':np.array([.2,.4]),'intermediate_correct':np.array([False,False]),'tokens_used':np.array([100,200])}
    loss,eff=upstream.threshold_to_loss_vectorized_upper(entry,np.array([.9]),exit_time_first_geq,signal_transform_fn=None)
    assert loss.tolist()==[1.]
    result={'scope':'Frozen-source/notebook API defects and formula-interface differences. Synthetic CPU controls, not model performance or evidence against the paper method.',
            'source_revision':'6551e3000dcda3d76491f30cc687d64618807c5b',
            'source_sha256':{name:hashlib.sha256((vendor/name).read_bytes()).hexdigest()
                             for name in ['risk_control_utils.py','signal_util.py','end2end.ipynb']},
            'ucb_sample_size_controls':controls,
            'upper_no_cross_control':{'signal':[.2,.4],'threshold':.9,'correctness':[0,0],
                                      'snapshot_loss':loss.tolist(),'threshold_crossed':False,
                                      'paper_eq8_triggered_upper_error':0},
            'interpretation':'Notebook passes an averaged length-K vector; utility uses K as sample size, so denser grids incorrectly shrink its finite-sample correction. Upper fallback error also differs from the threshold-triggered Eq8 loss. Keep author snapshot immutable and declare an independent adaptation with explicit per-problem loss matrices.',
            'numpy_version':np.__version__}
    path=ROOT/'provenance/conformal_interface_audit_20261014.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':main()
