"""Isolated real case execution. This is a controlled LCB runtime adapter."""
import hashlib,json,platform,subprocess,time,uuid
from pathlib import Path
from lcb_cases import stdio_equal

ROOT=Path(__file__).resolve().parent


def execute_cases(code,cases,fn_name=None,batch_size=16,require_admission=True):
    assert platform.system()=='Linux','Only execute on the verified Linux Docker host'
    worker=ROOT/'scripts/code_sandbox_worker_v2.py'
    prelude=ROOT/'provenance/lcb/callable_import_prelude.json'
    original=json.loads((ROOT/'provenance/code_sandbox_admission.json').read_text())
    if require_admission:
        admission=json.loads((ROOT/'provenance/code_sandbox_v2_admission.json').read_text())
        assert admission['passed'] and admission['worker_sha256']==hashlib.sha256(worker.read_bytes()).hexdigest()
        assert admission['prelude_sha256']==hashlib.sha256(prelude.read_bytes()).hexdigest()
    command=['docker','run','--rm','-i','--runtime','runc','--network','none','--read-only',
      '--user','65534:65534','--cap-drop','ALL','--security-opt','no-new-privileges',
      '--memory','512m','--cpus','1','--pids-limit','64',
      '--tmpfs','/tmp:rw,noexec,nosuid,size=64m,mode=1777',
      '--mount',f'type=bind,src={worker},dst=/worker.py,readonly',
      '--mount',f'type=bind,src={prelude},dst=/prelude.json,readonly',
      '--entrypoint','python3',original['image_id'],'/worker.py']
    details=[];start=time.perf_counter()
    for first in range(0,len(cases),batch_size):
        batch=cases[first:first+batch_size]
        job={'style':'functional' if fn_name else 'stdio','code':code,
             'inputs':[c['input'] for c in batch],'func_name':fn_name,'timeout_seconds':5}
        # No expected outputs or correctness labels are passed to this container.
        container_name='radar-eval-'+uuid.uuid4().hex
        named_command=command[:2]+['--name',container_name]+command[2:]
        try:
            process=subprocess.run(named_command,input=json.dumps(job),text=True,capture_output=True,
                                   timeout=30+6*len(batch))
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',container_name],capture_output=True,timeout=30)
            details.append({'case_index':first,'correct':False,'reason':'container_timeout'});break
        if process.returncode==125:
            raise RuntimeError('Docker infrastructure/startup failed: '+process.stderr[-1000:])
        if process.returncode:
            details.append({'case_index':first,'correct':False,'reason':'container_exit',
                            'returncode':process.returncode});break
        marked=[s for s in process.stdout.splitlines() if s.startswith('SANDBOX_RESULTS_JSON=')]
        if len(marked)!=1:raise RuntimeError('Malformed trusted worker response')
        outputs=json.loads(marked[0].split('=',1)[1]);assert len(outputs)==len(batch)
        failed=False
        for i,(case,output) in enumerate(zip(batch,outputs)):
            correct=False;reason='runtime_or_timeout'
            if output['returncode']==0 and not output['timeout']:
                if fn_name:
                    values=[s for s in output['stdout'].splitlines() if s.startswith('CALLABLE_RESULT_JSON=')]
                    if len(values)==1:
                        try:correct=json.loads(values[0].split('=',1)[1])==json.loads(case['output'])
                        except json.JSONDecodeError:pass
                else:correct=stdio_equal(output['stdout'],case['output'])
                reason='pass' if correct else 'wrong_or_malformed_output'
            details.append({'case_index':first+i,'correct':bool(correct),'reason':reason,
                            'timeout':output['timeout'],'returncode':output['returncode']})
            failed|=not correct
        if failed:break
    return {'all_passed':len(details)==len(cases) and all(x['correct'] for x in details),
            'expected_cases':len(cases),'executed_cases':len(details),'case_details':details,
            'evaluation_wall_s':time.perf_counter()-start,'hidden_expected_outputs_exposed_to_candidate':False,
            'scope':'Controlled Docker protocol: fresh interpreter per test, 3s CPU/384MiB child limit; not identical to official shared-instance runtime.'}
