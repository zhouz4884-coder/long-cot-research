"""Ensure preparation cannot start inference in an idle gap or on another GPU."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('deer_author_batch_runner',Path(__file__).resolve().parents[1]/'scripts/run_deer_author_batch.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class AuthorGuards(unittest.TestCase):
    def test_admission_refuses_while_m1_not_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'provenance').mkdir()
            freeze=root/'provenance/data_freeze.json';freeze.write_text('{}')
            (root/'provenance/formal_protocol.json').write_text(json.dumps({'admitted_model_paths':['model'],
                'source_sha256':{},'data_freeze_sha256':runner.digest(freeze)}))
            with self.assertRaisesRegex(AssertionError,'M1 actual selection not complete'):
                runner.prepare_inputs(root,'model','admission')

    def test_gpu_uuid_must_match_executing_index(self):
        with patch.dict(os.environ,{'CUDA_VISIBLE_DEVICES':'1'}),patch.object(runner.subprocess,'run',return_value=SimpleNamespace(stdout='GPU-other\n')):
            with self.assertRaisesRegex(AssertionError,'GPU index/UUID mismatch'):
                runner.require_idle_gpu('GPU-requested')

    def test_matching_uuid_with_live_process_refused(self):
        answers=[SimpleNamespace(stdout='GPU-requested\n'),SimpleNamespace(stdout='GPU-requested, 123\n')]
        with patch.dict(os.environ,{'CUDA_VISIBLE_DEVICES':'1'}),patch.object(runner.subprocess,'run',side_effect=answers):
            with self.assertRaisesRegex(AssertionError,'live compute processes'):
                runner.require_idle_gpu('GPU-requested')


if __name__=='__main__':unittest.main()
