"""Deploy only new isolated baseline files and run CPU controls without GPUs.

Credentials remain in the existing local connect() helper, outside this tree.
No primary source, protocol, result or formal .venv is uploaded/installed into.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import posixpath
import re
import shlex
import time

ROOT=Path(__file__).resolve().parents[1]
IMAGE='sha256:5791f8642d1b71d45d832e232250aeca6a9aeb99b89698dff3c1ca5eea7a9655'
GPUS={'GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a','GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28'}
STUDY='/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013'
FILES=['deer_author_bridge.py','deer_author_source.py','deer_trial_score.py','deer_pro.py',
 'scripts/run_deer_author_batch.py','scripts/audit_deer_source_interfaces.py',
 'tests/test_deer_author_bridge.py','tests/test_deer_author_state_machine.py','tests/test_deer_author_guards.py',
 'tests/test_deer_trial_score.py','tests/test_deer_pro.py','vendor/DEER/vllm-deer-qwen3.py',
 'vendor/DEER/vanilla_deer.py','vendor/DEER/LICENSE','provenance/deer_runtime_wheels.json',
 'vendor/runtime_wheels/nltk-3.9.1-py3-none-any.whl','vendor/runtime_wheels/joblib-1.4.2-py3-none-any.whl']


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(client,command,timeout=40):
    _,out,err=client.exec_command(command,timeout=timeout)
    stdout=out.read().decode('utf-8',errors='replace');stderr=err.read().decode('utf-8',errors='replace')
    status=out.channel.recv_exit_status()
    return {'exit_code':status,'stdout':stdout,'stderr':stderr}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--ssh-helper',default=str(ROOT.parents[1]/'.tools/remote.py'))
    p.add_argument('--tag',default='deer_author_20261014_v1')
    args=p.parse_args();assert re.fullmatch('[a-z0-9_]{1,64}',args.tag)
    expected={name:digest(ROOT/name) for name in FILES}
    formal_sha=digest(ROOT/'provenance/formal_protocol.json')
    work=STUDY+'/baseline_workbench/'+args.tag
    attempt={'started_unix':time.time(),'stage':'connect','remote_workbench':work,
             'formal_bound_files_uploaded':False,'gpu_devices_passed_to_container':False}
    output=ROOT/f'provenance/deer_workbench_attempt_{int(time.time())}.json'
    client=None
    try:
        spec=importlib.util.spec_from_file_location('existing_private_ssh_helper',args.ssh_helper)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);client=module.connect()
        attempt['stage']='host_identity'
        check="""import hashlib,json,os,subprocess
from pathlib import Path
p=Path('provenance/formal_protocol.json')
g=subprocess.run(['nvidia-smi','--query-gpu=uuid','--format=csv,noheader'],capture_output=True,text=True,check=True)
print(json.dumps({'formal_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'gpu_uuids':g.stdout.splitlines(),'uid':os.getuid(),'gid':os.getgid()}))
"""
        result=run(client,'cd '+shlex.quote(STUDY)+' && .venv/bin/python -c '+shlex.quote(check))
        assert result['exit_code']==0,result
        identity=json.loads(result['stdout'])
        assert identity['formal_sha256']==formal_sha and set(identity['gpu_uuids'])==GPUS,'Do not deploy to an unverified host/study'
        attempt['stage']='new_workbench_transfer'
        sftp=client.open_sftp()
        def mkdir(path):
            assert path==STUDY or path.startswith(STUDY+'/')
            try:sftp.stat(path)
            except FileNotFoundError:mkdir(posixpath.dirname(path));sftp.mkdir(path)
        mkdir(work)
        for name in FILES:
            target=work+'/'+name;mkdir(posixpath.dirname(target))
            try:
                with sftp.open(target,'rb') as stream:present=hashlib.sha256(stream.read()).hexdigest()
            except FileNotFoundError:present=None
            assert present is None or present==expected[name],'Preserve existing different workbench; choose a new version: '+name
            if present is None:sftp.put(str(ROOT/name),target)
        mkdir(work+'/runtime_deps');sftp.close()
        verify="""import hashlib,json
from pathlib import Path
root=Path("""+repr(work)+""")
expected="""+repr(expected)+"""
for name,sha in expected.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,name
print(json.dumps({'verified_files':len(expected)}))
"""
        result=run(client,'cd '+shlex.quote(STUDY)+' && .venv/bin/python -c '+shlex.quote(verify))
        assert result['exit_code']==0,result
        attempt['source_sha256']=expected;attempt['host_identity']=identity
        attempt['stage']='offline_dependency_install'
        base=['docker','run','--rm','--runtime','runc','--network','none','--read-only','--cpus','1','--memory','2g',
              '--user',str(identity['uid'])+':'+str(identity['gid']),'--tmpfs','/tmp:rw,nosuid,nodev,size=256m']
        command=base+['-v',work+'/vendor/runtime_wheels:/wheels:ro','-v',work+'/runtime_deps:/deps:rw',
                '--entrypoint','python3',IMAGE,'-m','pip','install','--disable-pip-version-check','--no-cache-dir',
                '--no-index','--no-deps','--target','/deps','/wheels/nltk-3.9.1-py3-none-any.whl','/wheels/joblib-1.4.2-py3-none-any.whl']
        install=run(client,shlex.join(command),timeout=55);attempt['dependency_install']=install
        assert install['exit_code']==0,install
        attempt['stage']='real_image_cpu_controls'
        control="""import hashlib,importlib.metadata,io,json,pathlib,sys,torch,unittest,zipfile
root=pathlib.Path('/workbench');deps=pathlib.Path('/deps')
manifest=json.loads((root/'provenance/deer_runtime_wheels.json').read_text())
checked=0
for item in manifest['wheels']:
 wheel=root/'vendor/runtime_wheels'/item['filename']
 assert hashlib.sha256(wheel.read_bytes()).hexdigest()==item['sha256']
 with zipfile.ZipFile(wheel) as z:
  for name in z.namelist():
   if name.startswith(item['name']+'/') and not name.endswith('/'):
    assert (deps/name).read_bytes()==z.read(name),name;checked+=1
assert not torch.cuda.is_available(),'CPU controls must receive no GPU devices'
suite=unittest.defaultTestLoader.discover('/workbench/tests',pattern='test_deer*.py')
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
print(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,'cpu_only':not torch.cuda.is_available(),
 'installed_wheel_payload_files_verified':checked,'versions':{n:importlib.metadata.version(n) for n in ['torch','transformers','vllm','numpy','nltk','joblib','regex']},'test_output':stream.getvalue()}))
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
        command=base+['-v',work+':/workbench:ro','-v',work+'/runtime_deps:/deps:ro','-e','PYTHONPATH=/deps:/workbench',
                      '--entrypoint','python3',IMAGE,'-c',control]
        controls=run(client,shlex.join(command),timeout=55);attempt['cpu_controls']=controls
        assert controls['exit_code']==0,controls
        parsed=json.loads(controls['stdout']);assert parsed['passed'] and parsed['tests_run']>=22
        attempt['stage']='completed_cpu_preparation';attempt['completed_unix']=time.time()
        attempt['scope']='New isolated baseline deployment and genuine CPU controls in pinned image; no GPU or task quality/wall results'
        (ROOT/'provenance/deer_workbench_deployment.json').write_text(json.dumps(attempt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'stage':attempt['stage'],'tests_run':parsed['tests_run'],'cpu_only':parsed['cpu_only'],'remote_workbench':work}))
    except BaseException as error:
        attempt['failed_unix']=time.time();attempt['exception_type']=type(error).__name__;attempt['message']=str(error)
        print(json.dumps({'stage':attempt['stage'],'exception_type':type(error).__name__,'message':str(error)}))
        raise
    finally:
        output.write_text(json.dumps(attempt,indent=2)+'\n',encoding='utf-8')
        if client:client.close()


if __name__=='__main__':main()
