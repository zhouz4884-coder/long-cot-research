"""Replay stored old decisions without retraining or generating new answers."""
import argparse,hashlib,json,pickle,sys
from importlib.metadata import version
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser();parser.add_argument('--legacy-root',default=str(ROOT.parents[1]))
args=parser.parse_args();legacy=Path(args.legacy_root)
metadata=json.loads((ROOT/'provenance/legacy/frozen_controller.json').read_text())
weight=ROOT/metadata['predictor_metadata']['path']
assert hashlib.sha256(weight.read_bytes()).hexdigest()==metadata['predictor_metadata']['sha256']
with weight.open('rb') as f:predictor=pickle.load(f)
spec=metadata['method_spec'];checked=0;errors=[];sources={}
for file in (legacy/'results/online').glob('qwen3_4b_[01].jsonl'):
    sources[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
    for line in file.read_text(encoding='utf-8').splitlines():
        r=json.loads(line)
        if r['method']!='transition':continue
        points={p['offset']:p for p in r['trace']['checkpoints']}
        for decision in r['decisions']:
            if decision['action'] not in ['STOP','STEP','FULL']:continue
            features=dict(points[decision['offset']]['features']);saved=decision['detail']
            if 'readout_entropy' in predictor.features:features['readout_entropy']=saved['readout_probe']['entropy']
            action,actual=predictor.choose(features,spec['cost_lambda'],spec['margin'],mode=spec['prediction_mode'])
            checked+=1
            if action!=decision['action'] or any(abs(actual[k]-saved[k])>1e-10 for k in predictor.fast_names):
                errors.append({'problem_id':r['problem_id'],'offset':decision['offset']})
assert checked and not errors,errors[:10]
out={'passed':True,'actual_saved_decisions_replayed':checked,
 'predictor_sha256':metadata['predictor_metadata']['sha256'],'source_sha256':sources,
 'package_versions':{n:version(n) for n in ['numpy','scikit-learn']},'tolerance':1e-10,
 'scope':'CPU reconstruction on saved original features; no new GPU transfer efficacy.'}
(ROOT/'provenance/legacy/decision_replay_admission.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
