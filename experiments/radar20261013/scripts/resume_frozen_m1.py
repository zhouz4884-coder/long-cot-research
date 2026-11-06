"""Resume only frozen development->selection->M1; never replay bound pilots.

Operational recovery script, separate from all frozen inference sources. Holds
the existing flock and preserves live child inference on interruption.
"""
import argparse
import fcntl
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import continue_study as queue
from protocol_guard import validate_formal,sha256


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--recovery-identity',required=True);args=parser.parse_args()
    lock=(ROOT/'logs/continuation.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print('Existing supervisor owns dispatch; leave it untouched',flush=True);return
    try:
        model=queue.MODEL;formal,fh=validate_formal(ROOT,model)
        identity_path=ROOT/args.recovery_identity
        identity=json.loads(identity_path.read_text())
        assert identity['formal_protocol_sha256']==fh and identity['source_packages_and_data_freeze_validated']
        assert identity['model_files_verified'] and identity['model_revision']=='1cfa9a7208912126459214e8b04321603b3df60c'
        # Identity is from this recovery, not the historical frozen admission.
        import datetime
        observed=datetime.datetime.fromisoformat(identity['observed_at_utc'].replace('Z','+00:00')).timestamp()
        assert 0<=time.time()-observed<7200,'Repeat live identity verification before a later recovery'
        review=queue.read_json(ROOT/'provenance/formal_review.json')
        assert review['admitted_for_development'] and review['formal_protocol_sha256']==fh
        for name,digest in review['reviewed_evidence_sha256'].items():assert sha256(ROOT/name)==digest,name
        old_state=ROOT/'results/continuation_state.json'
        archived=ROOT/f'provenance/pre_recovery_state_{int(time.time())}.json'
        archived.write_bytes(old_state.read_bytes())
        queue.write_state('recovery_admission','validated_frozen_identity',recovery_identity_sha256=sha256(identity_path),
                          original_state_archive=str(archived.relative_to(ROOT)),recovery_source_sha256=sha256(Path(__file__)))
        recovery_id=str(int(time.time()))
        canary_files={g:f'provenance/recovery_canary_{recovery_id}_{g}.json' for g in [0,1]}
        queue.run_jobs('recovery_canary',[(g,['scripts/recovery_same_input_canary.py','--shard',str(g),
                       '--output',canary_files[g]]) for g in [0,1]],gpu=True)
        for g in [0,1]:
            canary=queue.read_json(ROOT/canary_files[g])
            assert canary['passed'] and canary['formal_protocol_sha256']==fh
        for split in ['development','selection']:
            queue.run_jobs('bank_'+split,[(g,['scripts/collect_policy_bank.py','--model',model,'--split',split,'--shard',str(g)]) for g in [0,1]],
                           [f'results/bank_{split}_{g}.complete.json' for g in [0,1]])
        training_path=ROOT/'results/risk_training/grouped_cv.json'
        if not training_path.exists():queue.cpu('risk_training','scripts/train_risk_heads.py')
        training=queue.read_json(training_path);assert training['formal_protocol_sha256']==fh
        for name,digest in training['model_sha256'].items():assert sha256(ROOT/f'results/risk_training/{name}.pkl')==digest
        if not (ROOT/'provenance/calibration_candidates.json').exists():
            queue.cpu('candidate_selection','scripts/select_calibrate_policies.py','--phase','selection')
        family=queue.read_json(ROOT/'provenance/calibration_candidates.json');assert family['model_sha256']==training['model_sha256']
        if not (ROOT/'provenance/m1_selection_online.json').exists():queue.cpu('m1_online_plan','scripts/build_m1_online_plan.py')
        queue.run_jobs('m1_selection_online',[(g,['scripts/evaluate_frozen_online.py','--model',model,'--split','selection',
                       '--policy-file','provenance/m1_selection_online.json','--out-tag','m1_selection','--shard',str(g)]) for g in [0,1]],
                       [f'results/online_m1_selection_{g}.complete.json' for g in [0,1]])
        queue.cpu('m1_analysis','scripts/analyze_m1_online.py')
        queue.write_state('m1_review','waiting_for_agent_scientific_gate',evidence=['results/m1_online_analysis.json'],
            remaining='Full objective: conditional core mechanism, strong baselines, calibration, frozen test, transfers, conditional serving and research archive')
    except BaseException as error:
        queue.write_state('recovery_continuation','failed',exception_type=type(error).__name__,error=str(error));raise
    finally:lock.close()


if __name__=='__main__':main()
