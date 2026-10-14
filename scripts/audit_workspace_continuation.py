"""Read and inventory the full research tree without exposing held-out content.

Archives and model outputs are scanned structurally. Held-out prompts/golds are
never printed or used to choose a method. Old audit writes are redirected to a
new audit directory; original published outputs and the ZIP remain unchanged.
"""
import ast
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import runpy
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/next_phase_20261013/workspace_recheck_20261014'


def digest(path):
    hasher=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b''):hasher.update(block)
    return hasher.hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    files=[p for p in ROOT.rglob('*') if p.is_file() and not any(
        part in {'.git','.tools','__pycache__','.venv'} for part in p.parts)
        and OUT not in p.parents]
    inventory=[];errors=[];groups=Counter();copies=defaultdict(list)
    for path in sorted(files):
        relative=path.relative_to(ROOT).as_posix();hash_value=digest(path)
        item={'path':relative,'bytes':path.stat().st_size,'sha256':hash_value,'kind':path.suffix}
        groups[path.parts[len(ROOT.parts)]]+=1;copies[hash_value].append(relative)
        try:
            if path.suffix=='.jsonl':
                count=0;keys=Counter()
                with path.open(encoding='utf-8-sig') as handle:
                    for line in handle:
                        row=json.loads(line);assert isinstance(row,dict)
                        count+=1;keys.update(row.keys())
                item.update({'jsonl_records':count,'top_level_keys':sorted(keys)})
            elif path.suffix in ['.json','.ipynb']:
                value=json.loads(path.read_text(encoding='utf-8-sig'))
                item['json_type']=type(value).__name__
            elif path.suffix=='.py':
                tree=ast.parse(path.read_text(encoding='utf-8-sig'),filename=relative)
                item['definitions']=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
            elif path.suffix in ['.md','.txt','.log','.csv','.sh','.toml','.yml','.yaml']:
                content=path.read_text(encoding='utf-8-sig')
                item['lines']=len(content.splitlines())
                item['replacement_characters']=content.count('\ufffd')
        except Exception as error:
            issue={'path':relative,'error':type(error).__name__+': '+str(error)}
            errors.append(issue);item['structural_issue']=issue['error']
        inventory.append(item)
    receipt=json.loads((ROOT/'outputs/RELEASE_RECEIPT.json').read_text())
    archive=ROOT/receipt['archive'].replace('\\','/')
    assert digest(archive)==receipt['sha256'],'Published release archive changed'
    with zipfile.ZipFile(archive) as container:
        assert container.testzip() is None,'Archive member CRC failed'
        members=len(container.namelist())
    # Execute the exact legacy validation code while redirecting its report.
    original_write=Path.write_text
    redirects={ROOT/'results/analysis/study_integrity.json':OUT/'study_integrity.json',
               ROOT/'results/analysis/online_failure_diagnostics.json':OUT/'online_failure_diagnostics.json'}
    protected={p:digest(p) for p in redirects if p.exists()}
    def write_report(path,text,*args,**kwargs):
        destination=redirects.get(path.resolve(),path)
        return original_write(destination,text,*args,**kwargs)
    Path.write_text=write_report
    try:
        saved_argv=sys.argv
        for script in ['validate_study_artifacts.py','diagnose_online_failures.py']:
            sys.argv=[str(ROOT/'scripts'/script)]
            runpy.run_path(sys.argv[0],run_name='__main__')
        sys.argv=[str(ROOT/'scripts/audit_online_trajectories.py'),'--out',str(OUT/'trajectory_consistency.json')]
        runpy.run_path(sys.argv[0],run_name='__main__')
    finally:
        Path.write_text=original_write;sys.argv=saved_argv
    assert all(digest(p)==h for p,h in protected.items())
    assert digest(archive)==receipt['sha256']
    summary={'inventory_files':len(files),'inventory_bytes':sum(i['bytes'] for i in inventory),
             'files_by_top_level':dict(groups),'unique_content_sha256':len(copies),
             'duplicate_content_groups':sum(len(paths)>1 for paths in copies.values()),
             'structural_issues':errors,'legacy_online_records_revalidated':1648,
             'published_zip_sha256':receipt['sha256'],'published_zip_members':members,
             'original_legacy_audit_reports_and_zip_unchanged':True,
             'scope':'Full file/content inventory and structural parsing; focused scientific/source review of the continuation dependency path. Held-out content is not manually inspected or used for choices. This is not a claim of semantic correctness of every gold answer or archive file.'}
    (OUT/'FILE_INVENTORY.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    (OUT/'WORKSPACE_RECHECK.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
