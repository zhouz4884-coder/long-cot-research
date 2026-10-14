"""Freeze formal runtime after an actual agent review and fresh GPU admission.

This command cannot infer a scientific review. It consumes a written review
whose evidence hashes bind the investigator's decision to complete pilot data.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from protocol_guard import source_snapshot,package_snapshot,sha256,validate_formal


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--review-file',required=True)
    parser.add_argument('--max-think-tokens',type=int,choices=[8192,12288,16384],required=True)
    parser.add_argument('--candidate-admission',required=True)
    parser.add_argument('--capture-hidden',action='store_true')
    args=parser.parse_args()
    review_path=Path(args.review_file);review=json.loads(review_path.read_text(encoding='utf-8'))
    assert review['pilot_interpretation'] and review['reference_choice_reason'] and review['noise_interpretation']
    assert review['native_readout_interpretation'] and review['proceed_to_development'] is True
    required=['results/budget_pilot_analysis.json','results/noise_analysis.json',
              'results/native_pilot_analysis.json','results/pilot_evidence_audit.json','results/budget_repair_audit.json']
    assert all(name in review['reviewed_evidence_sha256'] for name in required)
    for name,digest in review['reviewed_evidence_sha256'].items():
        assert sha256(ROOT/name)==digest,'Review refers to changed evidence: '+name
    audit=json.loads((ROOT/'results/pilot_evidence_audit.json').read_text())
    assert audit['passed'] and audit['actual_test_generation_records']==0
    assert not list((ROOT/'results').glob('bank_*.jsonl')),'Cannot redefine the reference after formal bank generation'
    assert not list((ROOT/'results').glob('online_*.jsonl')),'Cannot redefine the reference after online generation'
    model='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
    admission_file='provenance/'+args.candidate_admission
    assert Path(args.candidate_admission).name==args.candidate_admission
    admission=json.loads((ROOT/admission_file).read_text())
    assert admission['passed'] and admission['model_path']==model
    assert admission['package_versions']==package_snapshot()
    assert len(admission['checks'])==3
    for name,digest in admission['source_sha256'].items():assert sha256(ROOT/name)==digest
    live=json.loads((ROOT/'provenance/live_protocol_admission.json').read_text())
    assert live['passed'] and live['core_sha256']==sha256(ROOT/'reason_transition/core.py')
    assert review['fresh_live_admission_sha256']==sha256(ROOT/'provenance/live_protocol_admission.json')
    payload={'seed':20261013,'max_think_tokens':args.max_think_tokens,'max_answer_tokens':192,
             'gpu_shards':2,'gpu_assignment':'problem_id_sha256_independent_of_split_membership',
             'reference_protocol':'Bounded FULL with shared boxed reader; native uninterrupted protocol reported separately.',
             'dtype':'float16','attention':'sdpa','temperature':.6,'top_p':.95,'top_k':20,
             'extra_readout_offsets':[512,2048],'capture_candidate_hidden':args.capture_hidden,
             'source_sha256':source_snapshot(ROOT),'package_versions':package_snapshot(),
             'data_freeze_sha256':sha256(ROOT/'provenance/data_freeze.json'),
             'admitted_model_paths':[model],'candidate_admission_files':{model:admission_file},
             'review_source_sha256':sha256(review_path),
             'quality_claim_scope':'No new policy efficacy or risk certification at formal freeze. Test1062 remains ungenerated.'}
    path=ROOT/'provenance/formal_protocol.json'
    assert not path.exists(),'Do not overwrite an existing formal freeze'
    path.write_text(json.dumps(payload,indent=2)+'\n')
    formal,formal_hash=validate_formal(ROOT,model)
    release={'admitted_for_development':True,'formal_protocol_sha256':formal_hash,
             'reviewed_evidence_sha256':review['reviewed_evidence_sha256'],
             'scientific_review_source_sha256':sha256(review_path)}
    (ROOT/'provenance/formal_review.json').write_text(json.dumps(release,indent=2)+'\n')
    print(json.dumps({'formal_protocol_sha256':formal_hash,'max_think_tokens':formal['max_think_tokens'],
                      'development_admitted':True,'test_generation_admitted':False},indent=2))


if __name__=='__main__':main()
