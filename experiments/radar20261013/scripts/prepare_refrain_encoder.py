"""Download a pinned public MiniLM snapshot, preserving source checksums.

No package installation or GPU operation. The model weights are ignored by Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REPOSITORY = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
FILES = ['config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
         'special_tokens_map.json', 'vocab.txt', 'sentence_bert_config.json',
         '1_Pooling/config.json', 'modules.json', 'config_sentence_transformers.json', 'README.md']


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    api = f'https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}?blobs=true'
    with urllib.request.urlopen(api, timeout=60) as response:
        metadata = json.load(response)
    assert metadata['sha'] == REVISION
    siblings = {x['rfilename']: x for x in metadata['siblings']}
    records = []
    for name in FILES:
        entry = siblings[name]
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = entry.get('lfs', {}).get('sha256')
        url = f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}'
        if not target.exists() or (expected and sha256(target) != expected):
            temporary = target.with_name(target.name + '.download')
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    output.write(chunk)
            digest = sha256(temporary)
            assert expected is None or digest == expected, f'LFS checksum mismatch: {name}'
            os.replace(temporary, target)
        digest = sha256(target)
        size = target.stat().st_size
        if 'size' in entry:
            assert size == entry['size']
        blob_verified = False
        if not expected and entry.get('blobId'):
            content = target.read_bytes()
            git_blob = hashlib.sha1(f'blob {len(content)}\0'.encode() + content).hexdigest()
            assert git_blob == entry['blobId'], f'Git object checksum mismatch: {name}'
            blob_verified = True
        records.append({'file': name, 'bytes': size, 'sha256': digest,
                        'source_lfs_sha256': expected, 'source_git_blob_oid': entry.get('blobId'),
                        'source_checksum_verified': bool(expected) or blob_verified,
                        'source_url': url})
        print(json.dumps({'file': name, 'bytes': size, 'checksum_verified': bool(expected) or blob_verified}), flush=True)
    sentence_config = json.loads((destination / 'sentence_bert_config.json').read_text())
    pooling = json.loads((destination / '1_Pooling/config.json').read_text())
    assert sentence_config['max_seq_length'] == 256
    assert pooling['word_embedding_dimension'] == 384
    assert pooling['pooling_mode_mean_tokens'] and not pooling['pooling_mode_cls_token']
    manifest = {'repository': REPOSITORY, 'revision': REVISION, 'metadata_url': api,
                'model_path': str(destination), 'files': records, 'sentence_config': sentence_config,
                'pooling_config': pooling, 'implementation': 'CPU FP32 masked mean pooling and L2 normalization',
                'scope': 'Pinned encoder dependency only; no stopping-policy accuracy or runtime gain proven.'}
    path = Path(args.manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
