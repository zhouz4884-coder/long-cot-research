"""Package auditable final artifacts and verify every ZIP member checksum."""
import argparse,hashlib,json,subprocess,zipfile
from datetime import datetime,timezone
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--raw-batch',required=True);p.add_argument('--out',default='outputs/reason-transition-final-20261013.zip');args=p.parse_args()
root=Path.cwd().resolve();raw=Path(args.raw_batch).resolve();target=Path(args.out).resolve()
assert raw.is_file() and target.is_relative_to(root)
assert hashlib.sha256(raw.read_bytes()).hexdigest()=='6bb24ab4abe21e86cdb55bffdb8eacba58eb0a62512e9b8307ec3c4ad560a0e9'
assert json.loads(Path('provenance/COMPLETION_AUDIT.json').read_text(encoding='utf-8'))['finite_programme_requirements_verified']
assert json.loads(Path('results/analysis/study_integrity.json').read_text(encoding='utf-8'))['online_records']==1648
qa=json.loads(Path('provenance/FIGURE_QA.json').read_text(encoding='utf-8'))
for figure in qa['figures']:
 for suffix,expected in figure['sha256'].items():assert hashlib.sha256(Path('figures',figure['base']+suffix).read_bytes()).hexdigest()==expected
paths={}
for folder in ['data','configs','scripts','reason_transition','tests','docs','provenance','results','figures','logs']:
 for file in Path(folder).rglob('*'):
  if file.is_file() and '__pycache__' not in file.parts and file.suffix!='.pyc':
   assert file.resolve().is_relative_to(root);paths[file.as_posix()]=file
for name in ['README.md','requirements-experiment.txt','.gitattributes','.gitignore']:
 paths[name]=Path(name)
paths['raw_batch/final_experiment_snapshot.tar.gz']=raw
checksums={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sorted(paths.items())}
manifest={'created_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
 'git_base_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'scope':'Final source/data/raw results and QA-reviewed derived artifacts; original remote batch retained separately. The manifest excludes itself.',
 'frozen_online_records':1648,'scientific_outcome':'NO-GO','sha256':checksums}
target.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
 for name,path in sorted(paths.items()):archive.write(path,name)
 archive.writestr('RELEASE_FILES_MANIFEST.json',json.dumps(manifest,indent=2))
with zipfile.ZipFile(target) as archive:
 assert archive.testzip() is None
 assert set(archive.namelist())==set(paths)|{'RELEASE_FILES_MANIFEST.json'}
 for name,expected in checksums.items():assert hashlib.sha256(archive.read(name)).hexdigest()==expected,name
receipt={'archive':str(target.relative_to(root)),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
         'verified_file_count':len(paths),'all_member_checksums_verified':True,'git_base_revision':manifest['git_base_revision']}
Path('outputs/RELEASE_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8',newline='\n')
print(json.dumps(receipt))
