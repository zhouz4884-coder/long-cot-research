"""Bind an independently admitted controlled baseline before online requests."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from protocol_guard import validate_formal,sha256
from evaluate_dtsr_online import SOURCES


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);args=p.parse_args()
    formal,formal_hash=validate_formal(ROOT,args.model)
    admission_path=ROOT/'provenance/dtsr_finite_admission.json';admission=json.loads(admission_path.read_text())
    assert admission['passed'] and admission['model_path']==args.model and len(admission['checks'])==3
    assert admission['package_versions']==formal['package_versions']
    for name,digest in admission['source_sha256'].items():assert sha256(ROOT/name)==digest
    existing=list((ROOT/'results').glob('online_dtsr_*.jsonl'));assert not existing,'Freeze before DTSR generation'
    protocol={'method_scope':'DTSR_controlled_token_level_serial_HF','threshold':100.,'minimum_interval':64,
              'rating_max_tokens':64,'formal_protocol_sha256':formal_hash,
              'data_freeze_sha256':sha256(ROOT/'provenance/data_freeze.json'),
              'source_sha256':{name:sha256(ROOT/name) for name in SOURCES},
              'admission_file':'provenance/dtsr_finite_admission.json','admission_sha256':sha256(admission_path),
              'paper_reference':'https://aclanthology.org/2026.acl-long.1080/',
              'declared_differences':['Qwen3-4B/common FP16 SDPA bounded solver, not paper8/14/32B vLLM',
                                      'Paraphrased third-person rating prompt with thinking disabled',
                                      '64-token bounded auxiliary rating; malformed responses continue',
                                      'Common boxed final readout and fixed per-problem sampling seeds'],
              'risk_guarantee_claimed':False,'actual_dtsr_records_at_freeze':0}
    path=ROOT/'provenance/dtsr_protocol.json';assert not path.exists(),'Do not overwrite a baseline freeze'
    path.write_text(json.dumps(protocol,indent=2)+'\n')
    print(json.dumps({'protocol_sha256':sha256(path),'default_threshold':100,'token_interval':64,
                      'risk_guarantee_claimed':False},indent=2))


if __name__=='__main__':main()
