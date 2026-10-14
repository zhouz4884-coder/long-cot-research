"""Validate complete raw pilot scopes; never use marker existence as evidence."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stem_quality import stem_issues,numeric_gold_issues


def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def main():
    questions=read(ROOT/'data/pilot.jsonl')
    raw=[r for g in [0,1] for r in read(ROOT/f'results/pilot_full_{g}.jsonl')]
    ids={q['problem_id'] for q in questions}
    assert len(raw)==len(questions)==100 and {r['problem_id'] for r in raw}==ids
    by_id={r['problem_id']:r for r in raw}
    noise=json.loads((ROOT/'provenance/noise_protocol.json').read_text())
    expected=set()
    for q in questions[:noise['problem_count']]:
        if stem_issues(q['question'],q['subject']) or numeric_gold_issues(q['gold']):continue
        trace=by_id[q['problem_id']]['trace'];used=set()
        for target in noise['checkpoint_minimum_offsets']:
            points=[c for c in trace['checkpoints'] if target<=c['offset']<len(trace['ids'])]
            if not points or points[0]['offset'] in used:continue
            used.add(points[0]['offset']);expected.add(q['problem_id']+':'+str(points[0]['offset']))
    states=[r for g in [0,1] for r in read(ROOT/f'results/noise_bank_{g}.jsonl')]
    assert len(states)==len(expected) and {s['state_id'] for s in states}==expected
    noise_hash=hashlib.sha256((ROOT/'provenance/noise_protocol.json').read_bytes()).hexdigest()
    for state in states:
        assert state['protocol_sha256']==noise_hash and state['same_input_continuation_controls_passed']
        assert state['gold_used_online'] is False
        assert len(state['stop_readouts'])==noise['answer_repeats']
        for action in ['DEFER_1','DEFER_4','FULL']:
            branches=[b for b in state['branches'] if b['action']==action]
            assert sorted(b['reasoning_index'] for b in branches)==list(range(noise['reasoning_repeats']))
            assert all(len(b['readouts'])==noise['answer_repeats'] for b in branches)
    eligible={q['problem_id'] for q in questions[:32]
              if not stem_issues(q['question'],q['subject']) and not numeric_gold_issues(q['gold'])}
    budget=[r for g in [0,1] for r in read(ROOT/f'results/budget_pilot_{g}.jsonl')]
    assert len(budget)==len(eligible)*4
    assert {(r['problem_id'],r['budget']) for r in budget}=={(pid,b) for pid in eligible for b in [1024,2048,4096,16384]}
    native=[r for g in [0,1] for r in read(ROOT/f'results/native_pilot_{g}.jsonl')]
    assert len(native)==len(eligible)*2
    assert {(r['problem_id'],r['nominal_budget']) for r in native}=={(pid,b) for pid in eligible for b in [8192,16384]}
    assert all(r['same_thinking_prefix_control'] for r in native)
    assert all(r['quality_labels_available_during_generation'] is False for r in native)
    analysis=json.loads((ROOT/'results/budget_pilot_analysis.json').read_text())
    assert analysis['integrity_controls_passed']
    sources=[ROOT/f'results/{name}_{g}.jsonl' for name in ['pilot_full','budget_pilot','noise_bank','native_pilot'] for g in [0,1]]
    result={'passed':True,'pilot_problems':len(raw),'budget_problems':len(eligible),'budget_requests':len(budget),
            'noise_states':len(states),'noise_problems':len({s['problem_id'] for s in states}),
            'native_requests':len(native),'actual_test_generation_records':0,
            'raw_source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            'scope':'Complete finite pilot scopes and recorded continuation controls; not semantic gold correctness, policy efficacy, or independent risk certification.'}
    # Test files are inspected only for existence and split tags, never prompts.
    test_records=0
    for file in (ROOT/'results').glob('online_*.jsonl'):
        test_records+=sum(r.get('split')=='test' for r in read(file))
    result['actual_test_generation_records']=test_records
    assert test_records==0,'Formal review must predate any test generation'
    (ROOT/'results/pilot_evidence_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='raw_source_sha256'},indent=2))


if __name__=='__main__':main()
