"""Public ModelScope download into the isolated long-CoT project; no GPU work."""
import argparse
import hashlib
import json
from pathlib import Path
import time

ROOT = Path('/data/home/zhoubin/longcot_state_repair_20261105')
parser = argparse.ArgumentParser()
parser.add_argument('--attempt', default='01')
args = parser.parse_args()
report = {'model_id': 'Qwen/Qwen3-1.7B', 'requested_revision': 'master',
          'started_unix': time.time(), 'weights_source': 'ModelScope',
          'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'cache_dir': '/tmp/zhoubin/longcot_state_repair_20261105/modelscope-cache',
          'gpu_used': False, 'status': 'STARTED'}
out = ROOT / ('provenance/modelscope_download_' + args.attempt + '.json')
assert not out.exists(), 'Keep previous attempt evidence'


def save():
    out.write_text(json.dumps(report, indent=2) + '\n')


save()
try:
    print('Importing official ModelScope SDK', flush=True)
    from modelscope import snapshot_download
    report['sdk_import_seconds'] = time.time() - report['started_unix']
    save()
    print('Downloading public Qwen3-1.7B snapshot', flush=True)
    dest = snapshot_download(
        report['model_id'], revision='master',
        cache_dir='/tmp/zhoubin/longcot_state_repair_20261105/modelscope-cache',
        local_dir=str(ROOT / 'models/Qwen3-1.7B'), max_workers=4,
        ignore_patterns=['*.bin', '*.pt', '*.pth', '*.onnx', '*.gguf'],
    )
    files = []
    for path in sorted(Path(dest).iterdir()):
        if not path.is_file() or path.name.startswith('.'):
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        files.append({'name': path.name, 'size_bytes': path.stat().st_size,
                      'sha256': digest.hexdigest()})
    assert any(f['name'].endswith('.safetensors') for f in files)
    assert any(f['name'] == 'config.json' for f in files)
    report.update(status='DOWNLOADED_HASHED_NOT_YET_ADMITTED', files=files,
                  local_dir=dest,
                  revision_limitation='master is mutable; local file SHA256 is authoritative. Cross-hub identity and load admission remain required.')
except BaseException as error:
    # Exception strings may contain signed download URLs; retain only their type.
    report.update(status='FAILED', exception_type=type(error).__name__)
    raise
finally:
    report['elapsed_seconds'] = time.time() - report['started_unix']
    save()
    print(json.dumps({k: report[k] for k in ('status', 'elapsed_seconds')}), flush=True)
