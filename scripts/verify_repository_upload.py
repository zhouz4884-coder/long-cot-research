"""Read the staged blobs, compare bytes/frozen manifests, and scan changed text.

No credentials are read from a store or printed. This uses the versioned redacted
scanner and emits only rule counts and paths. It never pushes or modifies Git.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = {
    'docs/repository/PRE_PUSH_VALIDATION.json',
    'docs/repository/GITHUB_DELIVERY_20261106_ZH.md',
}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('publication_rules', ROOT / 'research/repository_phase_plan_20261106/audit_publication_inventory.py')
    rules = importlib.util.module_from_spec(spec); spec.loader.exec_module(rules)
    indexed = {}
    for item in git('ls-files', '--stage', '-z').split(b'\0'):
        if not item: continue
        metadata, path = item.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        assert stage == '0', 'Unmerged index entry'
        indexed[path.decode('utf-8')] = {'mode': mode, 'oid': oid}
    forbidden = [p for p in indexed if p.startswith(('.tools/', 'models/', 'vendor/')) or '/runtime4552/' in p or p.endswith(('.zip', '.pyc')) or p.endswith('v100_platform_inventory_02.json')]
    blob_sha, rows, mismatches, oversize = {}, [], [], []
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for path, entry in indexed.items():
            if entry['mode'] == '160000': raise RuntimeError('Submodule requires separate publication scope: ' + path)
            oid = entry['oid']
            if oid not in blob_sha:
                process.stdin.write((oid + '\n').encode()); process.stdin.flush()
                header = process.stdout.readline().decode().split()
                assert len(header) == 3 and header[1] == 'blob'
                remaining = size = int(header[2]); h = hashlib.sha256()
                while remaining:
                    data = process.stdout.read(min(1024 * 1024, remaining)); assert data
                    h.update(data); remaining -= len(data)
                assert process.stdout.read(1) == b'\n'
                blob_sha[oid] = (h.hexdigest(), size)
            staged_sha, size = blob_sha[oid]
            actual = ROOT / path
            actual_sha = digest(actual)
            if staged_sha != actual_sha: mismatches.append(path)
            if size > 100 * 1024 * 1024: oversize.append({'path': path, 'bytes': size})
            if path not in RECEIPTS:
                rows.append({'path': path, 'blob_oid': oid, 'bytes': size, 'sha256': staged_sha})
    finally:
        process.stdin.close(); process.wait()

    frozen = []
    for folder, name in [('direction_selection_20261105', 'DELIVERY_MANIFEST.json'), ('next_design_20261105', 'DESIGN_DELIVERY_MANIFEST.json'),
                         ('algorithm_mechanism_20261105', 'DELIVERY_MANIFEST.json'), ('p05_design_review_20261105', 'DELIVERY_MANIFEST.json'),
                         ('phase5_prototype_20261106', 'DELIVERY_MANIFEST.json'),
                         ('phase5b_boundary_20261106', 'DELIVERY_MANIFEST.json'),
                         ('phase5c_goal_contract_20261106', 'DELIVERY_MANIFEST.json')]:
        base = ROOT / 'research' / folder
        manifest = json.loads((base / name).read_text(encoding='utf-8'))
        for item in manifest['files']:
            path = 'research/' + folder + '/' + item['path']
            assert path in indexed, 'Frozen evidence absent from index: ' + path
            assert blob_sha[indexed[path]['oid']][0] == item['sha256'], 'Frozen blob differs: ' + path
            frozen.append(path)

    changed = [p.decode('utf-8') for p in git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z', 'HEAD').split(b'\0') if p]
    credentials, scan_states = [], {}
    for path in changed:
        state, findings = rules.scan_chunks(rules.read_file_chunks(ROOT / path), path)
        scan_states[state] = scan_states.get(state, 0) + 1
        hits = [f for f in findings if f['kind'] == 'credential']
        if hits: credentials.append({'path': rules.path_display(path), 'findings': hits})
    missing_links = []
    for path in ['README.md', *[str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'docs/phases').glob('*.md')],
                 'docs/repository/PUBLISH_SCOPE_ZH.md', 'docs/repository/GITHUB_DELIVERY_20261106_ZH.md']:
        for target in re.findall(r'\]\(([^)]+)\)', (ROOT / path).read_text(encoding='utf-8')):
            target = target.strip('<>')
            if '://' in target or re.match(r'^[A-Za-z]:[/\\]', target): continue
            resolved = ((ROOT / path).parent / target.split('#')[0]).resolve()
            try: relative = str(resolved.relative_to(ROOT)).replace('\\', '/')
            except ValueError: continue
            if relative not in indexed: missing_links.append({'source': path, 'target': target})
    report = {
        'status': 'PASS' if not (forbidden or mismatches or oversize or credentials or missing_links) else 'FAIL',
        'scope': 'All staged blobs byte-compared; 224 prior frozen members plus Phase5-A/B/C delivery manifests; changed text credential rules; navigation links. Not universal secret-free proof.',
        'source_head': git('rev-parse', 'HEAD').decode().strip(),
        'indexed_files': len(indexed), 'indexed_bytes': sum(blob_sha[e['oid']][1] for e in indexed.values()),
        'unique_blobs': len(blob_sha), 'frozen_members_verified': len(frozen),
        'prior_frozen_members_verified': sum(not p.startswith(('research/phase5_prototype_20261106/', 'research/phase5b_boundary_20261106/', 'research/phase5c_goal_contract_20261106/')) for p in frozen),
        'phase5_manifest_members_verified': sum(p.startswith('research/phase5_prototype_20261106/') for p in frozen),
        'phase5b_manifest_members_verified': sum(p.startswith('research/phase5b_boundary_20261106/') for p in frozen),
        'phase5c_manifest_members_verified': sum(p.startswith('research/phase5c_goal_contract_20261106/') for p in frozen),
        'forbidden_paths': forbidden, 'byte_mismatches': mismatches, 'oversize': oversize,
        'changed_files_scanned': len(changed), 'scan_states': scan_states, 'credential_candidates': credentials,
        'missing_navigation_links': missing_links,
        'payload_excludes_receipts': sorted(RECEIPTS),
        'payload_manifest_sha256': hashlib.sha256(json.dumps(sorted(rows, key=lambda r: r['path']), sort_keys=True).encode()).hexdigest(),
        'payload_files': sorted(rows, key=lambda r: r['path']),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'payload_files'}, ensure_ascii=True))
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__': raise SystemExit(main())
