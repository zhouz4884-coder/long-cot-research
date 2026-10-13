"""Keep formal requests and resumed banks bound to one admitted runtime."""
import hashlib,json,platform
from importlib.metadata import version
from pathlib import Path

RUNTIME_SOURCES=[
 'protocol_guard.py','reason_transition/core.py','reason_transition/text_decoder.py','reason_transition/predictor.py',
 'radar_engine.py','candidate_schema.py','stem_quality.py','probe_engine.py',
 'model_adapter.py','joint_predictor.py','risk_policy.py','design_risk.py',
 'scripts/collect_policy_bank.py','scripts/evaluate_frozen_online.py',
 'scripts/train_risk_heads.py','scripts/select_calibrate_policies.py']
PACKAGES=['torch','transformers','numpy','scipy','scikit-learn','math-verify']


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_snapshot(root):
    return {name:sha256(Path(root)/name) for name in RUNTIME_SOURCES}


def package_snapshot():
    return {'python':platform.python_version(),**{name:version(name) for name in PACKAGES}}


def check_source_map(root,expected,required=RUNTIME_SOURCES):
    assert set(expected)==set(required),'Formal source manifest is incomplete or includes unexpected entries'
    for name,digest in expected.items():
        assert sha256(Path(root)/name)==digest,'Runtime changed after formal freeze: '+name


def validate_formal(root,model_path=None):
    root=Path(root);path=root/'provenance/formal_protocol.json'
    formal=json.loads(path.read_text(encoding='utf-8'))
    check_source_map(root,formal['source_sha256'])
    assert formal['package_versions']==package_snapshot(),'Use the frozen formal runtime environment'
    assert formal['data_freeze_sha256']==sha256(root/'provenance/data_freeze.json')
    if model_path is not None:
        assert model_path in formal['admitted_model_paths'],'Model has not passed this formal protocol admission'
    paths=[model_path] if model_path is not None else formal['admitted_model_paths']
    for admitted_path in paths:
        filename=formal['candidate_admission_files'][admitted_path]
        admission=json.loads((root/filename).read_text())
        assert admission['passed'] and admission['model_path']==admitted_path
        assert len(admission['checks'])>=3,'Finite admission requires the configured three prefix checks'
        for name,digest in admission['source_sha256'].items():
            assert sha256(root/name)==digest,'Candidate admission predates source change: '+name
    return formal,sha256(path)


def validate_resume(rows,formal_hash,model_path,expected_ids):
    seen=set()
    for row in rows:
        assert row['formal_protocol_sha256']==formal_hash,'Do not mix formal versions in one bank'
        assert row['model_path']==model_path,'Do not mix models in one bank'
        assert row['problem_id'] in expected_ids,'Unexpected or stale split ID'
        assert row['problem_id'] not in seen,'Duplicate completed problem in bank'
        seen.add(row['problem_id'])
    return seen
