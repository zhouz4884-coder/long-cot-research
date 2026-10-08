import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reason_transition.core import boundary,digest_ids,last_box,uniform


class ProtocolTests(unittest.TestCase):
    def test_nested_and_revised_answer(self):
        self.assertEqual(last_box(r'\boxed{1} corrected \boxed{\frac{2}{3}}'),r'\frac{2}{3}')
        self.assertIsNone(last_box(r'\boxed{\frac{2}{3}'))

    def test_boundary_does_not_accept_incomplete_math(self):
        self.assertTrue(boundary('We obtain 3.\n\n'))
        self.assertFalse(boundary('A = \\frac{1\n\n'))
        self.assertFalse(boundary('Wait'))
        self.assertFalse(boundary('Unclosed inline math $x + 1\n\n'))
        self.assertFalse(boundary('```python\nx = 1\n\n'))

    def test_counter_pairing_is_phase_separated(self):
        self.assertEqual(uniform(42,'answer',0),uniform(42,'answer',0))
        self.assertNotEqual(uniform(42,'answer',0),uniform(42,'think',0))
        self.assertNotEqual(uniform(42,'answer',0),uniform(42,'answer',1))
        self.assertGreater(uniform(42,'answer',0),0)
        self.assertLess(uniform(42,'answer',0),1)

    def test_hash_is_sequence_sensitive(self):
        self.assertNotEqual(digest_ids([1,23]),digest_ids([12,3]))
        self.assertNotEqual(digest_ids([1,2]),digest_ids([2,1]))


if __name__=='__main__':unittest.main()
