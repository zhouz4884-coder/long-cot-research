"""Prevent a partial numeric match from certifying a whole answer family."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stem_quality import numeric_gold_issues,stem_issues


class InputEligibility(unittest.TestCase):
    def test_non_scalar_family_and_prose_rejected(self):
        self.assertTrue(numeric_gold_issues(r'(2, 6), (2^k - 1, 2), (1, n) \text{ for any } n \ge 1'))
        self.assertTrue(numeric_gold_issues("Integers with no $0$'s in their base 10 expansion."))

    def test_valid_constant_formulas_preserved(self):
        for text in [r'14849-\frac{9999}{200}\binom{200}{99}',r'\frac{\pi}{4}',r'2\sqrt{30}','-120','2^3']:
            self.assertFalse(numeric_gold_issues(text),text)

    def test_undefined_point_is_not_a_sufficient_numeric_problem(self):
        q=r'If $\triangle PQR$ is right-angled at $P$ with $PR=12$, $SQ=11$, and $SR=13$, what is the perimeter of $\triangle QRS$?'
        self.assertTrue(stem_issues(q,'Geometry'))


if __name__=='__main__':unittest.main()
