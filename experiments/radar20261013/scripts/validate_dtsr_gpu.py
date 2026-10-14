"""Finite auxiliary-rating/cache admission; run only after measured workers stop."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from reason_transition.core import Engine,stable_seed
from dtsr_adapter import evaluate_sufficiency
from run_native_pilot import verify_live_model
from protocol_guard import package_snapshot


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);args=p.parse_args()
    native=json.loads((ROOT/'provenance/native_pilot_protocol.json').read_text())
    hashes=verify_live_model(args.model,native)
    questions=[json.loads(s) for s in (ROOT/'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:3]
    engine=Engine(args.model);checks=[]
    for q,limit in zip(questions,[128,512,2048]):
        seed=stable_seed('dtsr-admission',q['problem_id']);prompt=engine.prompt(q['question'])
        state=engine.decode(prompt,limit,seed,until='eos');prefix=prompt+state['ids']
        parent=copy.deepcopy(state['cache'])
        rating=evaluate_sufficiency(engine,q['question'],state['text'],stable_seed(seed,'rating'))
        same=all(engine.torch.equal(a.keys,b.keys) and engine.torch.equal(a.values,b.values)
                 for a,b in zip(parent.layers,state['cache'].layers))
        a=engine.decode(prefix,16,seed,offset=state['tokens'],until='eos',initial=(state['cache'],state['logits']))
        b=engine.decode(prefix,16,seed,offset=state['tokens'],until='eos',initial=(parent,state['logits']))
        check={'problem_id':q['problem_id'],'actual_prefix_tokens':state['tokens'],
               'rating':rating['rating'],'rating_text':rating['rating_text'],
               'rating_input_tokens':rating['input_tokens'],'rating_generated_tokens':rating['tokens'],
               'auxiliary_wall_ms':rating['auxiliary_wall_ms'],'all_parent_kv_unchanged':same,
               'same16_token_continuation':a['ids']==b['ids']}
        assert same and check['same16_token_continuation'];checks.append(check)
        print(json.dumps(check),flush=True);del state,parent,a,b,rating
    valid=sum(c['rating'] is not None for c in checks)
    report={'passed':valid>0,'valid_rating_responses':valid,'model_path':args.model,
            'model_revision':native['model_revision'],'live_model_file_sha256':hashes,
            'package_versions':package_snapshot(),'checks':checks,
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                             for name in ['dtsr_adapter.py','scripts/validate_dtsr_gpu.py','reason_transition/core.py','reason_transition/text_decoder.py']},
            'scope':'Three finite rating/cache/continuation controls only. No task accuracy, calibration, timing benefit or author reproduction proven.'}
    (ROOT/'provenance/dtsr_finite_admission.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['passed'],'No parsed score; investigate rating protocol rather than declaring a useful baseline'


if __name__=='__main__':main()
