"""User-authorized ModelScope acquisition, independently checked against HF."""
import hashlib
import json
from pathlib import Path
import urllib.request

from modelscope import snapshot_download

ROOT=Path(__file__).resolve().parents[1]
metadata=json.loads((ROOT/'provenance/deepseek_hf_source_metadata.json').read_text())
repo='deepseek-ai/DeepSeek-R1-Distill-Llama-8B'
model_root=Path('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models')
target=model_root/'DeepSeek-R1-Distill-Llama-8B'
snapshot_download(repo,local_dir=str(target),cache_dir=str(model_root.parent/'cache/modelscope-radar'),
                  ignore_file_pattern=['*.jpg','*.png'])
checks=[]
for item in metadata['siblings']:
    name=item['rfilename']
    if not (name.endswith('.json') or name.endswith('.safetensors')):
        continue
    path=target/name
    assert path.is_file(), name
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            h.update(block)
    observed=h.hexdigest()
    if item.get('lfs'):
        expected=item['lfs']['sha256']
    else:
        url=f"https://huggingface.co/{repo}/resolve/{metadata['sha']}/{name}"
        with urllib.request.urlopen(url,timeout=40) as r:
            expected=hashlib.sha256(r.read()).hexdigest()
    assert observed==expected,'Mirror bytes do not match frozen HF revision: '+name
    checks.append({'name':name,'sha256':observed,'bytes':path.stat().st_size,'matches_revision':True})
    print('VERIFIED_MODEL_FILE',name,flush=True)
payload={'model_id':repo,'revision':metadata['sha'],'path':str(target),'files':checks,'all_match':True,
         'acquired_from':'ModelScope','identity_checked_against':'frozen Hugging Face snapshot'}
(ROOT/'provenance/deepseek_verified.json').write_text(json.dumps(payload,indent=2)+'\n')
print('CROSS_FAMILY_MODEL_DOWNLOAD_VERIFIED',flush=True)
