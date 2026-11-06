"""Reuse read-only Torch packages, override broken HTTP dependencies in a venv."""
import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/data/home/zhoubin/longcot_state_repair_20261105')
base = '/data/home/zhoubin/contractkv_v100/env/contractkv-v100-cu121/bin/python'
venv = root / 'env/longcot-v100'
report = {'started_unix': time.time(), 'base_environment_mutated': False,
          'venv': str(venv), 'steps': []}
path = root / 'provenance/isolated_env_01.json'
try:
    commands = [
        [base, '-m', 'venv', '--system-site-packages', str(venv)],
        [base, '-m', 'pip', '--python', str(venv / 'bin/python'), 'install',
         '--ignore-installed', '--no-deps', 'charset-normalizer==3.4.4', 'chardet==5.2.0'],
        [str(venv / 'bin/python'), '-c',
         'import requests,charset_normalizer,chardet,modelscope; '
         'print(requests.__version__,charset_normalizer.__version__,chardet.__version__,modelscope.__version__)'],
    ]
    for command in commands:
        result = subprocess.run(command, timeout=180, check=False)
        report['steps'].append({'command': command, 'exit': result.returncode})
        assert result.returncode == 0, 'Isolated environment admission failed'
    report['passed'] = True
except BaseException as error:
    report.update(passed=False, exception_type=type(error).__name__)
    raise
finally:
    report['elapsed_seconds'] = time.time() - report['started_unix']
    path.write_text(json.dumps(report, indent=2) + '\n')
