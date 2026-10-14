"""Live weight identities and cache/probe invariants on fresh pilot prefixes."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reason_transition.core import Engine, stable_seed
from protocol_guard import package_snapshot

model = '/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B'
identity = json.loads((ROOT / 'provenance/qwen3_4b_verified.json').read_text())
checks = []
for item in identity['files']:
    path = Path(model) / item['name']
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    assert h.hexdigest() == item['sha256'], item['name']
    checks.append({'name':item['name'], 'sha256':h.hexdigest(), 'passed':True})
print('LIVE_MODEL_HASHES_PASSED', len(checks), flush=True)
e = Engine(model)
rows = [json.loads(s) for s in (ROOT / 'data/pilot.jsonl').read_text(encoding='utf-8').splitlines()][:3]
cache_checks = []
for row, length in zip(rows, [128,512,2048]):
    seed = stable_seed('radar-live-cache', row['problem_id'])
    prompt = e.prompt(row['question'])
    state = e.decode(prompt, length, seed, until='eos')
    prefix = prompt + state['ids']
    cache, logits = state['cache'], state['logits']
    parent = copy.deepcopy(cache)
    child = copy.deepcopy(cache)
    _, answer_logits = e.forward(e.suffix, child)
    lp = answer_logits.float().log_softmax(-1)
    expected_entropy = float(-(lp.exp() * lp).sum().item())
    observed = e.entropy_probe(cache, logits)
    same_kv = all(e.torch.equal(a.keys,b.keys) and e.torch.equal(a.values,b.values) for a,b in zip(cache.layers,parent.layers))
    a = e.decode(prefix,16,seed,offset=state['tokens'],until='eos',initial=(cache,logits))
    b = e.decode(prefix,16,seed,offset=state['tokens'],until='eos',initial=(parent,logits))
    result = {'problem_id':row['problem_id'],'requested_max_tokens':length,
              'actual_prefix_tokens':state['tokens'],'actual_total_prefix_tokens':len(prefix),
              'prefix_generation_stop_reason':state['stop_reason'],
              'continuation_randomness_offset':state['tokens'],'same_kv':same_kv,
              'entropy_error':abs(expected_entropy-observed['entropy']),
              'same_16_token_continuation':a['ids']==b['ids']}
    assert same_kv and result['entropy_error'] < 1e-8 and result['same_16_token_continuation']
    cache_checks.append(result)
    print(json.dumps(result),flush=True)
    del state, parent, child, a, b
payload = {'passed':True,'live_weight_checks':checks,'cache_checks':cache_checks,
           'core_sha256':hashlib.sha256((ROOT/'reason_transition/core.py').read_bytes()).hexdigest(),
           'package_versions':package_snapshot(),
           'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                            ['scripts/validate_new_protocol.py','reason_transition/core.py','reason_transition/text_decoder.py','protocol_guard.py']},
           'scope':'Three finite prefixes, this model and runtime only; not a universal numeric invariance theorem.'}
(ROOT / 'provenance/live_protocol_admission.json').write_text(json.dumps(payload,indent=2)+'\n')
print('LIVE_PROTOCOL_ADMITTED',flush=True)
