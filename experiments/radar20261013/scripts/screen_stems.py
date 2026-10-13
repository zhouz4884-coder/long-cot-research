"""Version the untouched formal splits after pilot exposed missing context."""
import collections,hashlib,json,math,random,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stem_quality import stem_issues

assert not list((ROOT/'results').glob('bank_*.jsonl'))
assert not list((ROOT/'results').glob('online_*.jsonl'))
data=ROOT/'data';old=json.loads((ROOT/'provenance/data_freeze.json').read_text())
assert old.get('version',1)==1,'Version2 is already frozen; do not resplit or overwrite its predecessor'
archive=data/'v1';archive.mkdir(exist_ok=True)
names=['development','selection','calibration','test']
pool=[];exclusions=[]
for name in names:
    p=data/f'{name}.jsonl'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==old['splits'][name]['sha256']
    rows=[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()]
    shutil.copy2(p,archive/p.name)
    for r in rows:
        issues=stem_issues(r['question'],r['subject'])
        if issues:exclusions.append({'problem_id':r['problem_id'],'issues':issues})
        else:pool.append(r)
shutil.copy2(ROOT/'provenance/data_freeze.json',ROOT/'provenance/data_freeze_v1.json')
groups=collections.defaultdict(list)
for r in pool:groups[(r['subject'],int(r['difficulty'])//2)].append(r)
rng=random.Random(20261013)
for v in groups.values():rng.shuffle(v)
n=len(pool);sizes={'development':int(n*.2),'selection':int(n*.1),'calibration':int(n*.3)}
sizes['test']=n-sum(sizes.values())
splits={}
for name,size in sizes.items():
    total=sum(map(len,groups.values()));ideal={k:size*len(v)/total for k,v in groups.items()}
    quota={k:math.floor(v) for k,v in ideal.items()}
    for k in sorted(ideal,key=lambda k:(-(ideal[k]-quota[k]),k))[:size-sum(quota.values())]:quota[k]+=1
    rows=[]
    for k,count in quota.items():rows+=groups[k][:count];del groups[k][:count]
    rng.shuffle(rows);splits[name]=rows
    (data/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
updated={**old,'version':2,'initial_numeric_eligible_n':old['eligible_n'],'formal_pool_n':n,'formal_input_quality_exclusions':len(exclusions),
         'source_problem_coverage_formal_pool_excluding_pilot':n/old['source_n'],
         'eligibility_update':'Gold-free visual-reference and explicit-geometry-label screen, uniformly applied before formal generation',
         'formal_generation_records_at_refreeze':0,
         'splits':{**{'pilot':old['splits']['pilot']},**{name:{'n':len(rows),'ids':[r['problem_id'] for r in rows],
                    'subject_counts':dict(collections.Counter(r['subject'] for r in rows)),
                    'sha256':hashlib.sha256((data/f'{name}.jsonl').read_bytes()).hexdigest()} for name,rows in splits.items()}}}
assert len(set(r['problem_id'] for rows in splits.values() for r in rows))==n
(ROOT/'provenance/data_freeze.json').write_text(json.dumps(updated,indent=2)+'\n')
(data/'stem_exclusions_v2.json').write_text(json.dumps(exclusions,indent=2)+'\n')
pilot=[json.loads(s) for s in (data/'pilot.jsonl').read_text(encoding='utf-8').splitlines()]
pilot_issues=[{'problem_id':r['problem_id'],'issues':stem_issues(r['question'],r['subject'])} for r in pilot if stem_issues(r['question'],r['subject'])]
(ROOT/'provenance/pilot_stem_issues.json').write_text(json.dumps(pilot_issues,indent=2)+'\n')
print(json.dumps({'formal_pool':n,'split_counts':sizes,'excluded_formal':len(exclusions),
                  'pilot_stem_issue_count':len(pilot_issues),'all_solver_outcomes_unused':True},indent=2))
