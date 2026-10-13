import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from code_sandbox import execute_cases

checks=[]
for label,code,cases,fn,expected in [
 ('stdio','import sys\na,b=map(int,sys.stdin.read().split())\nprint(a+b)\n',
  [{'input':'2 3\n','output':'5\n'},{'input':'-7 5\n','output':'-2\n'}],None,True),
 ('callable','class Solution:\n def add(self,a,b):\n  return a+b\n',
  [{'input':'2\n3','output':'5'},{'input':'-7\n5','output':'-2'}],'add',True),
 ('wrong','print(6)',[{'input':'2 3','output':'5'}],None,False)]:
    result=execute_cases(code,cases,fn,require_admission=False)
    assert result['all_passed']==expected
    checks.append({'label':label,'expected_pass':expected,'result':result})
payload={'passed':True,'checks':checks,
 'worker_sha256':hashlib.sha256((ROOT/'scripts/code_sandbox_worker_v2.py').read_bytes()).hexdigest(),
 'prelude_sha256':hashlib.sha256((ROOT/'provenance/lcb/callable_import_prelude.json').read_bytes()).hexdigest(),
 'scope':'Actual execution/interface checks, no model code-generation quality claim.'}
(ROOT/'provenance/code_sandbox_v2_admission.json').write_text(json.dumps(payload,indent=2)+'\n')
print('CODE_SANDBOX_V2_ADMITTED',len(checks),flush=True)
