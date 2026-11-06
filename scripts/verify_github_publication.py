"""Read-only GitHub delivery verification using existing noninteractive GCM.

Credential material lives only in this process. It is never written, printed,
passed as a command argument, or placed in a URL. No API mutation is performed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', default='zhouz4884-coder/long-cot-research')
    parser.add_argument('--expected-visibility', choices=['private', 'public'],
                        help='Require this explicitly selected visibility; never mutate visibility.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository)
    process_env = dict(os.environ)
    process_env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    credential = subprocess.run(['git', '-c', 'credential.helper=manager', 'credential', 'fill'],
        cwd=ROOT, input='protocol=https\nhost=github.com\n\n', capture_output=True,
        text=True, env=process_env, check=True, timeout=45)
    fields = dict(row.split('=', 1) for row in credential.stdout.splitlines() if '=' in row)
    access_material = fields['password']
    headers = {'Authorization': 'Bearer ' + access_material,
               'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'ACL-research-read-only-verification'}

    def api(path):
        request = urllib.request.Request('https://api.github.com' + path, headers=headers)
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)

    identity = api('/user')
    assert identity['login'] == args.repository.split('/')[0], 'Do not verify under an unintended account'
    prefix = '/repos/' + args.repository
    repo = api(prefix)
    assert repo['default_branch'] == 'main'
    actual_visibility = 'private' if repo['private'] else 'public'
    if args.expected_visibility is not None:
        assert actual_visibility == args.expected_visibility, 'Repository visibility differs from explicit expectation'
    local_head = git('rev-parse', 'HEAD').decode().strip()
    local_tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    ref = api(prefix + '/git/ref/heads/main')
    assert ref['object']['sha'] == local_head, 'Remote head differs'
    commit = api(prefix + '/git/commits/' + local_head)
    assert commit['tree']['sha'] == local_tree
    tree = api(prefix + '/git/trees/' + local_tree + '?recursive=1')
    assert not tree.get('truncated'), 'Cannot call a truncated inventory complete'
    remote = {row['path']: row['sha'] for row in tree['tree'] if row['type'] == 'blob'}
    local = {}
    for item in git('ls-tree', '-r', '-z', 'HEAD').split(b'\0'):
        if not item: continue
        info, path = item.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        assert kind == 'blob', 'Submodule requires its own scope'
        local[path.decode('utf-8')] = oid
    assert local == remote, 'GitHub recursive tree differs from local complete tree'

    ancestors = set(git('rev-list', 'HEAD').decode().splitlines())
    remote_ancestors, page = set(), 1
    while True:
        records = api(prefix + '/commits?sha=main&per_page=100&page=' + str(page))
        remote_ancestors.update(row['sha'] for row in records)
        if len(records) < 100: break
        page += 1
    assert ancestors == remote_ancestors
    representative = [
        'README.md', 'docs/phases/INDEX_ZH.md',
        'docs/phases/Phase5_候选算法与公平基线_计划_ZH.md',
        'research/p05_design_review_20261105/p05_five_arm.py',
        'research/p05_design_review_20261105/prelaunch_freeze_01.json',
        'research/p05_design_review_20261105/p05_five_arm_01/E02_logits.npz',
    ]
    phase5_samples = [
        'research/phase5_prototype_20261106/phase5_quality_runner.py',
        'research/phase5_prototype_20261106/prelaunch_freeze_01.json',
        'research/phase5_prototype_20261106/RUN_STATUS_ZH.md',
        'research/phase5_prototype_20261106/results/quality_round_01/summary.json',
        'research/phase5_prototype_20261106/results/quality_round_01/T1_support_before_fault_E__VersionFrame.json',
    ]
    representative.extend(path for path in phase5_samples if path in local)
    phase5b_samples = [
        'research/phase5b_boundary_20261106/boundary_core.py',
        'research/phase5b_boundary_20261106/prelaunch_freeze.json',
        'research/phase5b_boundary_20261106/RUN_STATUS_ZH.md',
        'research/phase5b_boundary_20261106/NATURAL_DIAGNOSIS_ZH.md',
        'research/phase5b_boundary_20261106/results/round_01/summary.json',
        'research/phase5b_boundary_20261106/results/round_01/LongR_E__SharedGFull.json',
    ]
    representative.extend(path for path in phase5b_samples if path in local)
    phase5c_samples = [
        'docs/phases/Phase5C_单模型自然轨迹验证与收尾_ZH.md',
        'research/phase5c_goal_contract_20261106/PHASE_CLOSEOUT_ZH.md',
        'research/phase5c_goal_contract_20261106/prelaunch_freeze.json',
        'research/phase5c_goal_contract_20261106/scoring/summary.json',
        'research/phase5c_goal_contract_20261106/results/resume_worker_1/32__ProjectedContractEvidence.json',
    ]
    representative.extend(path for path in phase5c_samples if path in local)
    phase5d_samples = [
        'docs/phases/Phase5D_方法重构与原生接口准入_ZH.md',
        'research/phase5d_scope_rebase_20261106/STAGE1_CLOSEOUT_ZH.md',
        'research/phase5d_scope_rebase_20261106/D1_NATIVE_INTERFACE_PASS.json',
        'research/phase5d_scope_rebase_20261106/native_results/worker_0/D1_01/checkpoint_logits.npz',
        'research/phase5d_scope_rebase_20261106/d0_scoring/D0_RESULTS.json',
    ]
    representative.extend(path for path in phase5d_samples if path in local)
    samples = []
    for path in representative:
        blob = api(prefix + '/git/blobs/' + local[path])
        assert blob['encoding'] == 'base64'
        data = base64.b64decode(blob['content'])
        expected = (ROOT / path).read_bytes()
        assert data == expected, path
        samples.append({'path': path, 'blob_oid': local[path], 'bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest(), 'returned_bytes_match': True})

    anonymous_status = None
    request = urllib.request.Request('https://api.github.com' + prefix,
                                     headers={'User-Agent': 'ACL-repository-visibility-check'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            anonymous_status = response.status
    except urllib.error.HTTPError as error:
        anonymous_status = error.code
    # The authenticated private flag is authoritative; an anonymous rate limit is not a privacy proof.
    report = {'status': 'PASS', 'repository': args.repository, 'url': repo['html_url'],
        'private': repo['private'], 'visibility': actual_visibility,
        'expected_visibility': args.expected_visibility, 'visibility_mutated': False,
        'account': identity['login'], 'default_branch': 'main',
        'head': local_head, 'tree': local_tree, 'files_in_complete_tree': len(local),
        'all_tree_blob_ids_match': True, 'all_ancestor_commit_ids_match': True,
        'ancestor_count': len(ancestors), 'representative_content': samples,
        'anonymous_api_status': anonymous_status, 'credential_material_saved_or_printed': False,
        'mutation_performed': False,
        'returned_file_count': len(samples),
        'scope': 'Whole tree/ancestry via Git IDs plus representative actual returned files, including a binary logits NPZ and available Phase5 evidence; not every byte fetched independently'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'representative_content'}, ensure_ascii=True))


if __name__ == '__main__': main()
