"""Read-only D0 recount. No semantic regrading or source/old-score mutation."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import d0_answer_extract as extractor

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'phase5c_goal_contract_20261106'


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def jsonl(path):return [json.loads(v) for v in path.read_text(encoding='utf-8').splitlines() if v.strip()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    oldmanifest=load(OLD/'DELIVERY_MANIFEST.json')
    for row in oldmanifest['files']:check('old_frozen_'+row['path'],sha(OLD/row['path'])==row['sha256'])
    contract=load(ROOT/'D0_parser_contract.json');prep=load(ROOT/'D0_PREPARATION.json');result=load(ROOT/'d0_scoring/D0_RESULTS.json')
    for filename,key in [('d0_answer_extract.py','extractor_sha256'),('d0_math_grade.py','semantic_grader_sha256')]:check('frozen_'+filename,sha(ROOT/filename)==contract[key])
    check('generic_test_binding',sha(ROOT/'test_d0_answer_extract.py')==contract['generic_test_source_sha256'])
    check('generic_backend_test_binding',sha(ROOT/'D0_REMOTE_CPU_TEST.json')==contract['generic_backend_test_sha256'])
    smoke=load(ROOT/'D0_REMOTE_CPU_TEST.json');check('CPU39plus18',smoke['status']=='PASS' and smoke['structural_passed']==39 and smoke['math_executed']==18)
    check('selection_bytes',sha(ROOT/'D0_SELECTIONS.jsonl')==prep['selections_sha256']==result['selection_sha256'])
    check('input_bytes',sha(ROOT/'D0_VISIBLE_INPUTS.jsonl')==prep['visible_inputs_sha256'])
    check('score_bytes',sha(ROOT/'d0_scoring/D0_scores.jsonl')==result['scores_sha256'])
    check('score_source',sha(ROOT/'score_d0_audit.py')==result['source_sha256'])
    check('eval_original',sha(OLD/'bank_evaluation_only.jsonl')==result['evaluation_sha256']==load(ROOT/'D0_EVALUATION_BINDING.json')['evaluation_sha256'])
    inputs=jsonl(ROOT/'D0_VISIBLE_INPUTS.jsonl');selected=jsonl(ROOT/'D0_SELECTIONS.jsonl');scores=jsonl(ROOT/'d0_scoring/D0_scores.jsonl')
    imap={r['source_id']:r for r in inputs};smap={r['selection_id']:r for r in selected}
    check('inputs256unique',len(imap)==len(inputs)==256)
    check('thinking32_generated224',sum(r['source_kind']=='thinking' for r in inputs)==32 and sum(r['source_kind']=='generated' for r in inputs)==224)
    check('selections1024unique',len(smap)==len(selected)==1024)
    check('scores1024unique',len({r['selection_id'] for r in scores})==len(scores)==1024)
    for row in inputs:check('input_text_'+row['source_id'],extractor.digest(row['text'])==row['text_sha256'])
    for row in selected:
        source=imap[row['source_id']]
        check('replay_'+row['selection_id'],extractor.extract_policy(source['text'],row['policy'])==row['selection'])
        check('selection_metadata_'+row['selection_id'],all(row[k]==source[k] for k in source if k!='text'))
    gold={r['bank_id']:r['gold'] for r in jsonl(OLD/'bank_evaluation_only.jsonl')};cache={};counts=defaultdict(lambda:defaultdict(list))
    for row in scores:
        prior=smap[row['selection_id']]
        check('score_selection_'+row['selection_id'],all(row[k]==prior[k] for k in prior))
        if row['selection']['status']=='ok':
            payload={'surface':row['selection']['surface'],'gold':str(gold[row['bank_id']])}
            key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            check('cache_key_'+row['selection_id'],row['semantic_cache_key']==key)
            if key in cache:check('same_query_same_grade_'+row['selection_id'],cache[key]==row['grade'])
            else:cache[key]=row['grade']
        else:check('abstain_not_mathfalse_'+row['selection_id'],row['grade']['status']=='selection_abstained' and row['grade']['mathematical_correctness'] is None)
        counts[row['method']][row['policy']].append(row)
    check('semantic_dedup43',len(cache)==result['semantic_queries_deduplicated']==43)
    groups={}
    for method,policies in counts.items():
        groups[method]={}
        for policy,rr in policies.items():
            data={'n':len(rr),'selected':sum(r['selection']['status']=='ok' for r in rr),'abstained':sum(r['selection']['status']!='ok' for r in rr),
                'selected_correct':sum(r['grade']['correct'] is True for r in rr),
                'selected_wrong':sum(r['selection']['status']=='ok' and r['grade']['correct'] is False for r in rr),
                'backend_unknown':sum(r['grade']['correct'] is None for r in rr),
                'policy_success_over32':sum(r['grade']['correct'] is True for r in rr)/32,
                'surface_disagreement_flagged':sum(r['selection']['signals']['distinct_surface_count']>1 for r in rr)}
            check('group_'+method+'_'+policy,len(rr)==32 and len({r['bank_id'] for r in rr})==32 and data==result['groups'][method][policy])
            groups[method][policy]=data
    check('all8conditions4policies',len(groups)==8 and all(set(v)==set(extractor.POLICIES) for v in groups.values()))
    check('no_backend_unknown',all(r['grade'].get('correct') is not None for r in scores))
    oldgrades={r['job_id']:r for r in jsonl(OLD/'scoring/grades.jsonl')};delta={}
    for method in oldgrades.values():
        name=method['method']
        if name in delta:continue
        wins=[];loss=[]
        for row in counts[name]['LastBox']:
            jid=row['source_id'].split(':',1)[1];before=oldgrades[jid]['grade']['correct'];after=row['grade']['correct']
            if after is True and before is not True:wins.append(row['bank_id'])
            if before is True and after is not True:loss.append(row['bank_id'])
        delta[name]={'retrospective_LastBox_recovered_vs_oldStrict':wins,'lost':loss,'old_main_correct':sum(r['grade']['correct'] is True for r in oldgrades.values() if r['method']==name)}
    audit={'status':'PASS','checks_passed':len(checks),'checks_total':len(checks),'checks':checks,'issues':[],
        'old_frozen_members_verified':len(oldmanifest['files']),'text_inputs':len(inputs),'selection_and_score_rows':len(scores),
        'semantic_queries':len(cache),'groups':groups,'old_strict_vs_new_LastBox_diagnostic':delta,
        'new_GPU_model_calls':0,'new_semantic_regrading_calls_by_this_audit':0,
        'scope':'Fixed-policy extraction replay, recorded semantic-result/cache consistency and independent recount; not a new mathematical proof of every backend judgement.',
        'observations':['HistoricalThinking LastBox28/32 is a deterministic policy observation, not a Gold-best oracle or universal upper bound.',
            'Thinking FirstComplete C013 abstains on an oversize earlier label capture; conservative surface disagreement can include parser noise, not a true reasoning conflict.',
            'LastFinalAnswer coverage is16/32 in thinking and0/32 inForcedBoxCue; absence of this textual marker does not prove absence of mathematical answer.',
            'Seven generated LastBox results each recover one prior strict failure, on different IDs; old main scores remain untouched.',
            'Full historical text may include tokens future to an earlier checkpoint; this audit cannot choose online trigger or first-correct point.']}
    (ROOT/'D0_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k not in ['checks','groups','observations','old_strict_vs_new_LastBox_diagnostic']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
