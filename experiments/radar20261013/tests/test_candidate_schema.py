"""Adversarial answer surfaces must not become admissible numeric fragments."""
import importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from candidate_schema import scalar_schema


@unittest.skipUnless(importlib.util.find_spec('math_verify'),'Requires frozen experiment environment')
class CandidateSchema(unittest.TestCase):
    def test_family_and_yes_no_reject_partial_number(self):
        for value in [r'\text{all integers } n\geq1',r'\text{Yes for }2017',r'5^{2013}\text{ OR }125^{671}']:
            self.assertFalse(scalar_schema(r'\boxed{'+value+'}')['valid'])

    def test_numeric_values_have_consistent_structural_keys(self):
        a=scalar_schema(r'\boxed{\frac{2}{4}}')
        b=scalar_schema(r'\boxed{\frac{1}{2}}')
        self.assertTrue(a['valid'] and b['valid'])
        self.assertEqual(a['key'],b['key'])
        self.assertFalse(scalar_schema(r'\boxed{x+1}')['valid'])


if __name__=='__main__':unittest.main()
