"""Brute finite populations, rather than using the same PMF as an oracle."""
import itertools,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_risk import lower_tail_bound,finite_test_risk_audit


def observed_counts(strata,harms):
    draws=[]
    for (N,n),K in zip(strata,harms):
        draws.append([sum(i<K for i in sample) for sample in itertools.combinations(range(N),n)])
    return [sum(x) for x in itertools.product(*draws)]


class FiniteDesignRisk(unittest.TestCase):
    def test_upper_tail_bound_covers_every_small_population_allocation(self):
        strata=[(5,2),(4,1)]
        for a in range(6):
            for b in range(5):
                observed=observed_counts(strata,[a,b])
                for h in range(4):
                    actual=sum(x<=h for x in observed)/len(observed)
                    bound=lower_tail_bound(strata,a+b,h)
                    self.assertGreaterEqual(bound+1e-10,actual)

    def test_unsampled_stratum_can_hide_harm(self):
        self.assertEqual(lower_tail_bound([(2,0),(10,5)],2,0),1.)

    def test_false_certification_probability_is_bounded(self):
        strata=[(5,2),(4,1)];alpha=.6;target=.2
        for a in range(6):
            for b in range(5):
                draws=observed_counts(strata,[a,b]);bad=0
                for h in draws:
                    verdict=finite_test_risk_audit(strata,h,target,alpha)
                    bad+=verdict['risk_bound_passed'] and (a+b-h)>verdict['maximum_allowed_test_harms']
                self.assertLessEqual(bad/len(draws),alpha+1e-12)


if __name__=='__main__':unittest.main()
