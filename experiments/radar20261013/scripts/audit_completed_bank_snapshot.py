"""Capture immutable bank bytes then reuse the original read-only prefix audit.

No quality statistics, GPU inference or live-bank mutation. Frozen source/data
links form a read-only audit root; captured raw files and report are preserved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
os.environ['CUDA_VISIBLE_DEVICES']=''
from protocol_guard import validate_formal
import audit_running_bank


def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['development','selection'],required=True);p.add_argument('--tag',required=True)
    args=p.parse_args();assert re.fullmatch('[a-zA-Z0-9_]{1,64}',args.tag)
    formal,sha=validate_formal(ROOT)
    snapshot=ROOT/'results/bank_snapshots'/args.tag
    assert not snapshot.exists(),'Preserve earlier snapshot; choose a new tag'
    snapshot.mkdir(parents=True);(snapshot/'results').mkdir()
    top_names={Path(name).parts[0] for name in formal['source_sha256']}
    top_names.update(['provenance','data'])
    for name in top_names:(snapshot/name).symlink_to(ROOT/name,target_is_directory=(ROOT/name).is_dir())
    captures=[]
    for shard in range(formal['gpu_shards']):
        name=f'bank_{args.split}_{shard}.jsonl';path=ROOT/'results'/name
        started=time.time();raw=path.read_bytes() if path.exists() else b''
        (snapshot/'results'/name).write_bytes(raw)
        captures.append({'shard':shard,'capture_started_unix':started,'capture_completed_unix':time.time(),
                         'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    meta={'formal_protocol_sha256':sha,'split':args.split,'captures':captures,
          'source_and_data_links_are_read_only_inputs':True,'wrapper_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'live_bank_changed':False,'scope':'Sequential per-shard immutable byte captures. No synchronized whole-bank completion or partial quality claim.'}
    (snapshot/'capture.json').write_text(json.dumps(meta,indent=2)+'\n')
    audit_running_bank.ROOT=snapshot
    sys.argv=[str(Path(audit_running_bank.__file__)),'--split',args.split,'--output',str(snapshot/'audit.json')]
    audit_running_bank.main()


if __name__=='__main__':main()
