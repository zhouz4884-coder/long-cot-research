"""Independent finite-path oracles and operational lower-curve controls."""
import itertools
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from risk_policy import conformal_dual_update,conformal_discrete_losses,bounded_family_ucb


class DualThresholdAdaptation(unittest.TestCase):
    def test_bounded_curve_and_explicit_routes(self):
        spec={'ema_alpha':1.,'upper_threshold':.9,'lower_base':0.,'slope_times_budget':8.,
              'reference_budget':1000,'shift_fraction':.5}
        self.assertEqual(conformal_dual_update(None,.95,200,spec)['route'],'upper')
        self.assertEqual(conformal_dual_update(None,.1,900,spec)['route'],'lower')
        self.assertEqual(conformal_dual_update(None,.6,100,spec)['route'],'continue')
        old=-1.
        for length in [0,200,500,1000,1000000]:
            result=conformal_dual_update(None,.5,length,spec)
            self.assertLess(result['lower_threshold'],result['upper_threshold'])
            self.assertGreaterEqual(result['lower_threshold'],old);old=result['lower_threshold']
        smoothed=conformal_dual_update(.2,.8,500,{**spec,'ema_alpha':.25})['smoothed_confidence']
        self.assertAlmostEqual(smoothed,.35)

    def test_all_short_binary_paths_against_counting_oracle(self):
        for n in range(1,6):
            for path in itertools.product([0,1],repeat=n):
                for index in range(n):
                    for route in ['upper','lower','fallback']:
                        actual=conformal_discrete_losses(path,index,route)
                        future=[j for j in range(index,n) if path[j]==1]
                        past_bad=[j for j in range(index+1) if path[j]==0]
                        oracle=0. if route!='lower' else len(future)/(n-index)
                        self.assertEqual(actual['lower_future_correctness'],oracle)
                        self.assertEqual(actual['lower_past_incorrect_fraction'],0. if route!='lower' else len(past_bad)/n)
                        self.assertEqual(actual['upper_error'],float(route=='upper' and path[index]==0))
                        if route=='fallback':self.assertEqual(actual['harmful_vs_final'],0)
        # A correct STOP can coexist with future solvability loss; this is
        # exactly why paper loss and paired harmful STOP must remain separate.
        row=conformal_discrete_losses([1,0,1],0,'lower')
        self.assertEqual(row['harmful_vs_final'],0)
        self.assertEqual(row['lower_future_correctness'],2/3)
        self.assertEqual(conformal_discrete_losses([0,0],1,'fallback')['upper_error'],0.)

    def test_grid_density_does_not_create_independent_calibration_samples(self):
        small=bounded_family_ucb([[0.]*5 for _ in range(2)],.1)
        dense=bounded_family_ucb([[0.]*5000 for _ in range(2)],.1)
        self.assertEqual(dense['independent_problem_rows'],2)
        self.assertGreater(dense['finite_sample_radius'],small['finite_sample_radius'])
        self.assertTrue(all(bound>.1 for bound in small['upper_bounds']))
        self.assertTrue(all(bound>.1 for bound in dense['upper_bounds']))


if __name__=='__main__':unittest.main()
