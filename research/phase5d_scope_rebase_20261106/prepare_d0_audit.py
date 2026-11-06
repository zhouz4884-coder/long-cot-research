"""Freeze generic D0 contracts, then apply them to old text without loading Gold."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

import d0_answer_extract as extractor

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'phase5c_goal_contract_20261106'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):
    text=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text(encoding='utf-8')!=text:raise ValueError('Refuse overwrite of different frozen bytes: '+str(path))
    path.write_text(text,encoding='utf-8')


def freeze(remote_test):
    test=json.loads(remote_test.read_text(encoding='utf-8'))
    if test['status']!='PASS' or test['math_executed']!=test['math_planned']:raise ValueError('Complete non-bank semantic smoke is required')
    if test['extractor_sha256']!=sha(ROOT/'d0_answer_extract.py') or test['semantic_grader_sha256']!=sha(ROOT/'d0_math_grade.py'):raise ValueError('Source/test binding mismatch')
    result={'schema_version':'phase5d_D0_frozen_contract_v1','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'FROZEN_BEFORE_NEW_SELECTIONS_AND_SCORES','extractor_sha256':sha(ROOT/'d0_answer_extract.py'),
        'semantic_grader_sha256':sha(ROOT/'d0_math_grade.py'),'generic_test_source_sha256':sha(ROOT/'test_d0_answer_extract.py'),
        'generic_backend_test_sha256':sha(remote_test),'policies':list(extractor.POLICIES),
        'selection_inputs':'Text and fixed policy only; never Gold, correctness, level or quality labels.',
        'fixed_last_policy':'Last complete object of the declared kind; later incomplete object abstains. No arbitrary last number.',
        'surface_disagreement':'Flagged only; conservative policy abstains. Not a proof of logical contradiction.',
        'LastBox_not_oracle_upper_bound':True,'candidate_hit_oracle_computed':False,
        'old_score_policy':'Phase5-C main scores/bytes unchanged. D0 results are separate retrospective diagnostics.',
        'offline_only':'All old text is available here. Never use future final markers to trigger an earlier online checkpoint.',
        'scope':'32 thinking texts plus224 generated answer_text records, four fixed policies each; correlated observations, not1024 independent problems.'}
    path=ROOT/'D0_parser_contract.json'
    if path.exists():raise ValueError('Contract already frozen; do not reset its timestamp')
    write(path,result);print(json.dumps({k:v for k,v in result.items() if k in ['status','extractor_sha256','semantic_grader_sha256','policies']},indent=2))


def prepare():
    contract=json.loads((ROOT/'D0_parser_contract.json').read_text(encoding='utf-8'))
    if contract['extractor_sha256']!=sha(ROOT/'d0_answer_extract.py'):raise ValueError('Frozen extractor changed')
    manifest=json.loads((OLD/'DELIVERY_MANIFEST.json').read_text(encoding='utf-8'))
    expected={r['path']:r for r in manifest['files']}
    sourcefiles={};bankpath=OLD/'bank_visible.jsonl'
    if sha(bankpath)!=expected['bank_visible.jsonl']['sha256']:raise ValueError('Old visible bank changed')
    sourcefiles['bank_visible.jsonl']=sha(bankpath)
    bank=[json.loads(v) for v in bankpath.read_text(encoding='utf-8').splitlines()]
    inputs=[]
    for rank,row in enumerate(bank,1):
        inputs.append({'source_id':'thinking:'+row['bank_id'],'bank_id':row['bank_id'],'rank':rank,'source_kind':'thinking',
            'method':'HistoricalThinking','text':row['trace_text'],'text_sha256':extractor.digest(row['trace_text']),
            'source_relative_path':'bank_visible.jsonl','source_line_1based':rank})
    seen=set()
    for directory in sorted((OLD/'results').glob('*worker*')):
        if not directory.is_dir():continue
        for path in sorted(directory.glob('*__*.json')):
            rel=path.relative_to(OLD).as_posix()
            if rel not in expected or sha(path)!=expected[rel]['sha256']:raise ValueError('Old raw changed '+rel)
            row=json.loads(path.read_text(encoding='utf-8'));jid=row['job_id']
            if jid in seen:raise ValueError('Duplicate old job '+jid)
            seen.add(jid);sourcefiles[rel]=sha(path)
            inputs.append({'source_id':'readout:'+jid,'bank_id':row['bank_id'],'rank':row['rank'],'source_kind':'generated',
                'method':row['method'],'text':row['answer_text'],'text_sha256':extractor.digest(row['answer_text']),
                'source_relative_path':rel,'eos_reached':row['eos_reached'],'hit_cap':row['hit_cap']})
    if len(bank)!=32 or len(seen)!=224 or len(inputs)!=256:raise ValueError('Expected32+224 old text inputs')
    selections=[]
    for item in inputs:
        for policy in extractor.POLICIES:
            selected=extractor.extract_policy(item['text'],policy)
            selections.append({k:v for k,v in item.items() if k!='text'}|{'selection_id':item['source_id']+'::'+policy,'policy':policy,'selection':selected})
    inputs_text=''.join(json.dumps(v,ensure_ascii=False,separators=(',',':'))+'\n' for v in inputs)
    selections_text=''.join(json.dumps(v,ensure_ascii=False,separators=(',',':'))+'\n' for v in selections)
    for name,text in [('D0_VISIBLE_INPUTS.jsonl',inputs_text),('D0_SELECTIONS.jsonl',selections_text)]:
        path=ROOT/name
        if path.exists() and path.read_text(encoding='utf-8')!=text:raise ValueError('Refuse different selections')
        path.write_text(text,encoding='utf-8')
    coverage={}
    for kind in ['HistoricalThinking',*sorted({r['method'] for r in inputs if r['source_kind']=='generated'})]:
        coverage[kind]={}
        for policy in extractor.POLICIES:
            rr=[r for r in selections if r['method']==kind and r['policy']==policy]
            coverage[kind][policy]={'n':len(rr),'selected':sum(r['selection']['status']=='ok' for r in rr),
                'selection_statuses':{s:sum(r['selection']['status']==s for r in rr) for s in sorted({r['selection']['status'] for r in rr})}}
    result={'status':'PREPARED_GOLD_BLIND','contract_sha256':sha(ROOT/'D0_parser_contract.json'),'sources_verified':sourcefiles,
        'text_inputs':256,'thinking_n':32,'generated_n':224,'selections':len(selections),'policies':list(extractor.POLICIES),
        'visible_inputs_sha256':sha(ROOT/'D0_VISIBLE_INPUTS.jsonl'),'selections_sha256':sha(ROOT/'D0_SELECTIONS.jsonl'),
        'quality_or_Gold_loaded':False,'coverage_not_correctness':coverage}
    write(ROOT/'D0_PREPARATION.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ['sources_verified','coverage_not_correctness']},indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--freeze-contract',type=Path);args=ap.parse_args()
    if args.freeze_contract:freeze(args.freeze_contract)
    else:prepare()
