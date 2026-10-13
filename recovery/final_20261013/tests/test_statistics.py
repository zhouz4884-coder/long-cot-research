import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('final_stats',Path(__file__).resolve().parents[1]/'scripts/final_stats.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class StatisticsTests(unittest.TestCase):
    def test_zero_observed_harms_does_not_prove_one_pp_with_fifty_questions(self):
        reference={str(i):{'correct':1,'total_tokens':100,'wall_ms':100} for i in range(50)}
        candidate={str(i):{'correct':1,'total_tokens':80,'wall_ms':80} for i in range(50)}
        result=module.cluster_comparison(reference,candidate,draws=100)
        self.assertFalse(result['conservative_one_pp_noninferiority_certified'])
        self.assertAlmostEqual(result['one_sided_95_harm_upper'],1-0.05**(1/50),places=10)

    def test_question_pairing_uses_intersection_and_rejects_missing_costs(self):
        a={'a':{'correct':1,'total_tokens':100,'wall_ms':100},'b':{'correct':1,'total_tokens':100,'wall_ms':100}}
        b={'a':{'correct':0,'total_tokens':80,'wall_ms':80},'c':{'correct':1,'total_tokens':80,'wall_ms':80}}
        result=module.cluster_comparison(a,b,draws=100)
        self.assertEqual(result['n'],1);self.assertEqual(result['harmful_pairs'],1)
        b['a']['wall_ms']=0
        with self.assertRaises(ValueError):module.cluster_comparison(a,b,draws=10)


if __name__=='__main__':unittest.main()
