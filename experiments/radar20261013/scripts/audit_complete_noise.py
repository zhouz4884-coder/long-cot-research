"""Complete intervention matrix, saved-prefix controls and scoring recheck."""
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.core import Engine,grade,digest_ids
from candidate_schema import scalar_schema
from stem_quality import stem_issues,numeric_gold_issues
from transformers import AutoTokenizer


def read(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def main():
    spec=json.loads((ROOT/'provenance/noise_protocol.json').read_text())
    spec_hash=hashlib.sha256((ROOT/'provenance/noise_protocol.json').read_bytes()).hexdigest()
    questions=read(ROOT/'data/pilot.jsonl');qmap={q['problem_id']:q for q in questions}
    raw={r['problem_id']:r for g in [0,1] for r in read(ROOT/f'results/pilot_full_{g}.jsonl')}
    expected=set()
    for q in questions[:spec['problem_count']]:
        if stem_issues(q['question'],q['subject']) or numeric_gold_issues(q['gold']):continue
        trace=raw[q['problem_id']]['trace'];seen=set()
        for target in spec['checkpoint_minimum_offsets']:
            available=[c for c in trace['checkpoints'] if target<=c['offset']<len(trace['ids'])]
            if available and available[0]['offset'] not in seen:
                offset=available[0]['offset'];seen.add(offset);expected.add(q['problem_id']+':'+str(offset))
    states=[s for g in [0,1] for s in read(ROOT/f'results/noise_bank_{g}.jsonl')]
    assert len(states)==len(expected)==39 and {s['state_id'] for s in states}==expected
    model=states[0]['model_path'];assert {s['model_path'] for s in states}=={model}
    tok=AutoTokenizer.from_pretrained(model,local_files_only=True)
    model_stub=SimpleNamespace(tok=tok)
    suffix=tok.encode('</think>\n\nFinal answer: \\boxed{',add_special_tokens=False)
    readouts_n=branches_n=censored_full=0;schema_issues=[];regrade_errors=[]
    details=[]
    for s in states:
        assert s['protocol_sha256']==spec_hash and s['gold_used_online'] is False
        q=qmap[s['problem_id']]
        prefix=Engine.prompt(model_stub,q['question'])+raw[s['problem_id']]['trace']['ids'][:s['offset']]
        assert hashlib.sha256(json.dumps(prefix).encode()).hexdigest()==s['parent_prefix_hash']
        assert s['parent_seq_len_after']==len(prefix)
        seeds=[r['sample_seed'] for r in s['stop_readouts']];assert len(set(seeds))==3
        outcomes={'STOP':[r['correct'] for r in s['stop_readouts']]}
        checks=[('STOP',s['stop_readouts'],prefix,False)]
        for r_index in range(3):
            indexed={b['action']:b for b in s['branches'] if b['reasoning_index']==r_index}
            assert set(indexed)=={'DEFER_1','DEFER_4','FULL'}
            full=indexed['FULL']['trajectory']['ids']
            for action,b in indexed.items():
                branches_n+=1;trajectory=b['trajectory']
                assert trajectory['ids']==full[:len(trajectory['ids'])]
                assert len(b['readouts'])==3 and [r['sample_seed'] for r in b['readouts']]==seeds
                assert trajectory['ms']>0 and math.isfinite(trajectory['ms'])
                checks.append((action,b['readouts'],prefix+trajectory['ids'],trajectory['stop_reason']=='natural_end'))
                outcomes.setdefault(action,[]).extend(r['correct'] for r in b['readouts'])
                if action=='FULL':censored_full+=trajectory['length_censored']
        for action,reads,parent,closed in checks:
            cue=tok.encode(('\n\n' if closed else '</think>\n\n')+'Final answer: \\boxed{',add_special_tokens=False)
            for r in reads:
                readouts_n+=1
                assert r['answer_prefix_hash']==digest_ids(parent+cue)
                assert r['candidate_sha256']==hashlib.sha256(json.dumps(r['ids'],separators=(',',':')).encode()).hexdigest()
                assert r['candidate_text_sha256']==hashlib.sha256(r['text'].encode()).hexdigest()
                assert 0<r['tokens']<=192 and r['tokens']==len(r['ids'])
                score=grade(r['text'],q['gold'])
                if score['correct']!=r['correct'] or score['parse_status']!=r['grade']['parse_status']:
                    regrade_errors.append({'state_id':s['state_id'],'action':action,'seed':r['sample_seed'],'saved':r['grade'],'recomputed':score})
                schema=scalar_schema(r['text'])
                if not schema['valid']:
                    schema_issues.append({'state_id':s['state_id'],'action':action,'seed':r['sample_seed'],
                                          'correct_under_frozen_scorer':r['correct'],'reason':schema['reason'],'text':r['text']})
        details.append({'state_id':s['state_id'],'problem_id':s['problem_id'],'outcomes':outcomes,
                        'full_all_nine_correct_stop_all_three_wrong':not any(outcomes['STOP']) and all(outcomes['FULL']),
                        'all_actions_and_seeds_wrong':not any(value for values in outcomes.values() for value in values)})
    assert branches_n==351 and readouts_n==1170
    assert not regrade_errors,'Frozen regrading changed; investigate before interpreting gains'
    report={'passed':True,'problems':len({s['problem_id'] for s in states}),'states':len(states),
            'real_continuation_branches':branches_n,'real_readouts':readouts_n,
            'all_prefix_candidate_identity_and_continuation_controls_passed':True,
            'frozen_regrade_disagreements':regrade_errors,'censored_full_branches':int(censored_full),
            'full_branches':117,'candidate_schema_issue_count':len(schema_issues),
            'schema_invalid_but_frozen_scorer_correct':sum(r['correct_under_frozen_scorer'] for r in schema_issues),
            'schema_issues':schema_issues,'details':details,
            'zero_variance_does_not_imply_no_action_mean_effect':True,
            'scope':'Complete pilot-prefix operational interventions, frozen-score and structural eligibility audit. No latent cognition claim, test performance, new online policy latency or certification.',
            'source_sha256':{f'results/noise_bank_{g}.jsonl':hashlib.sha256((ROOT/f'results/noise_bank_{g}.jsonl').read_bytes()).hexdigest() for g in [0,1]}}
    (ROOT/'results/noise_complete_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['details','schema_issues','source_sha256']},indent=2))


if __name__=='__main__':main()
