"""Real-token CPU controls for byte-safe text reconstruction."""
import json,sys,time
from pathlib import Path
from transformers import AutoTokenizer

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reason_transition.text_decoder import RollingTextDecoder

tok=AutoTokenizer.from_pretrained('/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/Qwen3-4B',local_files_only=True)
cases=[]
for text in ['16×20 = 320; π≈3.14; √2','中文：计算控制与答案读出。','\\boxed{2\\sqrt{30}}\n</think>']:
    cases.append(tok.encode(text,add_special_tokens=False))
for file in (ROOT/'results').glob('pilot_full_*.jsonl'):
    for line in file.read_text(encoding='utf-8').splitlines():
        try:r=json.loads(line)
        except json.JSONDecodeError:continue
        cases.extend([r['trace']['ids'],r['answer']['ids']])
errors=[];start=time.perf_counter()
for index,ids in enumerate(cases):
    decoder=RollingTextDecoder(tok);stream=''
    for token in ids:stream=decoder.append(token)
    expected=tok.decode(ids,skip_special_tokens=False,clean_up_tokenization_spaces=False)
    if stream!=expected:errors.append(index)
assert not errors,errors
report={'passed':True,'sequences_checked':len(cases),'whole_decode_equality':True,'wall_s':time.perf_counter()-start,
        'scope':'CPU text reconstruction on real token sequences and explicit UTF examples; no GPU performance or correctness claim.'}
(ROOT/'provenance/text_decoder_admission.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
