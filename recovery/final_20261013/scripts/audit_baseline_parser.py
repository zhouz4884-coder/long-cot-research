import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upstream_budget',root/'vendor/llm-think-stop/scripts/reason_budget_probe.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
cases=[{'text':r'\boxed{\frac{1}{2}}','expected':r'\frac{1}{2}'},
    {'text':r'\boxed{3} corrected final: \boxed{4}','expected':'4'},
    {'text':r'\boxed{\sqrt{2}}','expected':r'\sqrt{2}'}]
for row in cases:
    row['upstream_extraction']=module.extract_answer(row['text'])
    row['correct_extraction']=row['upstream_extraction']==row['expected']
report={'kind':'deterministic CPU parser audit; not task accuracy','upstream_commit':'21efe411bcaf34de884c1120ab7fb0573c193a62','cases':cases}
(root/'provenance/baseline_parser_audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
