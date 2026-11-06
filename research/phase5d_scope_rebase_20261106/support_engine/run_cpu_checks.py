import hashlib
import json
from pathlib import Path
import time
import unittest
import test_support_engine

ROOT=Path(__file__).resolve().parent
started=time.monotonic()
suite=unittest.defaultTestLoader.loadTestsFromTestCase(test_support_engine.SupportEngineTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={"status":"PASS" if result.wasSuccessful() else "FAIL","unit_tests_run":result.testsRun,
        "independent_random_closure_comparisons":test_support_engine.PROPERTY_COMPARISONS,
        "failed":[[str(t),trace] for t,trace in result.failures+result.errors],"seconds":time.monotonic()-started,
        "scope":"CPU trusted-input/restricted-rational support semantics only. No GPU, natural verifier or model/task benefit.",
        "source_sha256":hashlib.sha256((ROOT/'scope_rebase_hardened.py').read_bytes()).hexdigest(),
        "test_sha256":hashlib.sha256((ROOT/'test_support_engine.py').read_bytes()).hexdigest()}
(ROOT/'CPU_SUPPORT_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
