"""Adversarial answer surfaces must not become admissible numeric fragments."""
import importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from candidate_schema import scalar_schema
from reason_transition.core import grade


@unittest.skipUnless(importlib.util.find_spec('math_verify'),'Requires frozen experiment environment')
class CandidateSchema(unittest.TestCase):
    def test_observed_exact_factorial_form_and_invalid_suffixes(self):
        self.assertTrue(scalar_schema(r'\boxed{1/7!}')['valid'])
        # Grouping is intentionally structural; unequal keys cannot disprove
        # equality. Do not add unbounded online simplification to force a key.
        self.assertEqual(grade(r'\boxed{1/7!}','1/5040')['correct'],1)
        self.assertTrue(scalar_schema(r'\boxed{(3+1)!}')['valid'])
        self.assertEqual(grade(r'\boxed{(3+1)!}','24')['correct'],1)
        self.assertTrue(scalar_schema(r'\boxed{16\times4!\times4!}')['valid'])
        for text in [r'\boxed{7!!!}',r'\boxed{!7}',r'\boxed{7!2}',r'\boxed{7! or14}',r'\boxed{(-1)!}']:
            self.assertFalse(scalar_schema(text)['valid'],text)
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
