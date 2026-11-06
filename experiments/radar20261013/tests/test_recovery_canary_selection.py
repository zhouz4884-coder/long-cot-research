import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/recovery_same_input_canary.py'
spec=importlib.util.spec_from_file_location('recovery_canary',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CanarySelectionControls(unittest.TestCase):
    def test_length_and_identity_selection_ignores_correctness(self):
        rows=[{'problem_id':'b','points':[{}],'full':{'trace':{'ids':[1]*8},'correct':1}},
              {'problem_id':'a','points':[{}],'full':{'trace':{'ids':[1]*8},'correct':0}},
              {'problem_id':'c','points':[{}],'full':{'trace':{'ids':[1]*12},'correct':1}}]
        self.assertEqual(module.select_canary(rows)['problem_id'],'a')
        for row in rows:row['full']['correct']=1-row['full']['correct']
        self.assertEqual(module.select_canary(rows)['problem_id'],'a')

    def test_missing_points_or_too_long_cannot_weaken_canary(self):
        rows=[{'problem_id':'a','points':[],'full':{'trace':{'ids':[1]*4}}},
              {'problem_id':'b','points':[{}],'full':{'trace':{'ids':[1]*9}}}]
        with self.assertRaises(AssertionError):module.select_canary(rows,max_tokens=8)


if __name__=='__main__':unittest.main()
