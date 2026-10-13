"""Methodological regression tests, not GPU benchmark evidence."""
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crossed_variance import crossed_components


class SeedDesign(unittest.TestCase):
    def test_readout_only_does_not_create_reasoning_variance(self):
        # Identical reasoning states, answer changes with the common answer seed.
        x=crossed_components([[0,1,0],[0,1,0],[0,1,0]])
        self.assertAlmostEqual(x['reasoning_unclipped'],0.,places=12)
        self.assertAlmostEqual(x['within_readout'],1/3)
        self.assertAlmostEqual(x['answer_seed_unclipped'],1/3)

    def test_reasoning_only_is_preserved(self):
        x=crossed_components([[0,0,0],[1,1,1],[0,0,0]])
        self.assertEqual(x['within_readout'],0.)
        self.assertAlmostEqual(x['reasoning_unclipped'],1/3)

    def test_finite_sample_negative_components_remain_visible(self):
        x=crossed_components([[0,1],[1,0]])
        self.assertLess(x['reasoning_unclipped'],0.)
        self.assertLess(x['answer_seed_unclipped'],0.)
        self.assertGreater(x['interaction'],0.)


if __name__=='__main__':unittest.main()
