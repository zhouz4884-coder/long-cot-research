"""Prospective v3: a numeric extraction is not whole-answer numeric eligibility."""
import collections,hashlib,json,math,random,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stem_quality import numeric_gold_issues,stem_issues

assert not list((ROOT/'results').glob('bank_*.jsonl'))
assert not list((ROOT/'results').glob('online_*.jsonl'))
data=ROOT/'data';old=json.loads((ROOT/'provenance/data_freeze.json').read_text())
assert old.get('version')==2,'Only refreeze the still-unobserved v2 formal pool once'
archive=data/'v2';archive.mkdir(exist_ok=True)
names=['development','selection','calibration','test'];pool=[];exclusions=[]
for name in names:
    p=data/f'{name}.jsonl';assert hashlib.sha256(p.read_bytes()).hexdigest()==old['splits'][name]['sha256']
    shutil.copy2(p,archive/p.name)
    for r in (json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()):
        issues=numeric_gold_issues(r['gold'])
        if issues:exclusions.append({'problem_id':r['problem_id'],'issues':issues})
        else:pool.append(r)
shutil.copy2(ROOT/'provenance/data_freeze.json',ROOT/'provenance/data_freeze_v2.json')
groups=collections.defaultdict(list)
for r in pool:groups[(r['subject'],int(r['difficulty'])//2)].append(r)
rng=random.Random(20261013)
for v in groups.values():rng.shuffle(v)
n=len(pool);sizes={'development':int(n*.2),'selection':int(n*.1),'calibration':int(n*.3)};sizes['test']=n-sum(sizes.values())
splits={}
for name,size in sizes.items():
    total=sum(map(len,groups.values()));ideal={k:size*len(v)/total for k,v in groups.items()};quota={k:math.floor(v) for k,v in ideal.items()}
    for k in sorted(ideal,key=lambda k:(-(ideal[k]-quota[k]),k))[:size-sum(quota.values())]:quota[k]+=1
    rows=[]
    for k,count in quota.items():rows+=groups[k][:count];del groups[k][:count]
    rng.shuffle(rows);splits[name]=rows
    (data/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
updated={**old,'version':3,'formal_pool_n':n,'gold_surface_exclusions':len(exclusions),
         'source_problem_coverage_formal_pool_excluding_pilot':n/old['source_n'],
         'eligibility_update':'Uniform gold-pure numeric-expression whitelist after partial extraction discovered in pilot; no formal solver output used',
         'formal_generation_records_at_refreeze':0,
         'splits':{'pilot':old['splits']['pilot'],**{name:{'n':len(rows),'ids':[r['problem_id'] for r in rows],
                  'subject_counts':dict(collections.Counter(r['subject'] for r in rows)),
                  'sha256':hashlib.sha256((data/f'{name}.jsonl').read_bytes()).hexdigest()} for name,rows in splits.items()}}}
assert len(set(r['problem_id'] for rows in splits.values() for r in rows))==n
(ROOT/'provenance/data_freeze.json').write_text(json.dumps(updated,indent=2)+'\n')
(data/'gold_surface_exclusions_v3.json').write_text(json.dumps(exclusions,indent=2)+'\n')
pilot=[json.loads(s) for s in (data/'pilot.jsonl').read_text(encoding='utf-8').splitlines()]
issues=[{'problem_id':r['problem_id'],'issues':stem_issues(r['question'],r['subject'])+numeric_gold_issues(r['gold'])} for r in pilot if stem_issues(r['question'],r['subject']) or numeric_gold_issues(r['gold'])]
(ROOT/'provenance/pilot_input_issues_v3.json').write_text(json.dumps(issues,indent=2)+'\n')
print(json.dumps({'formal_pool':n,'split_counts':sizes,'gold_surface_exclusions':len(exclusions),
                  'pilot_input_issue_count':len(issues),'all_formal_solver_outcomes_unused':True},indent=2))
