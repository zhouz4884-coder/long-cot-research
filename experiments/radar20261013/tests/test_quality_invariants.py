"""Prevent the observed low-quality cost-induced stop from recurring by design."""
import json,sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from risk_policy import quality_decision


class QualityAdmission(unittest.TestCase):
    def test_actual_legacy_harm_is_not_cost_admissible(self):
        # This is a rule invariant using a saved actual decision, not a GPU rerun.
        path=ROOT.parents[1]/'results/audit/online_reversals.json'
        if not path.exists():self.skipTest('Legacy raw decision not present on this host')
        rows=json.loads(path.read_text(encoding='utf-8'))
        case=next(r for r in rows if r['model']=='Qwen3-4B' and r['problem_id']=='test/algebra/2176.json')
        d=case['last_decision']['detail']
        pred={'outside_length_support':False,'stop_harm_vs_action':d['full_fix'],'candidate_correct':d['stop_correct']}
        self.assertEqual(case['last_decision']['action'],'STOP')
        self.assertEqual(quality_decision({'kind':'risk_gate','risk_threshold':.01,'minimum_correctness':.9},pred,True),'DEFER')

    def test_invalid_and_unsupported_states_do_not_commit(self):
        spec={'kind':'risk_gate','risk_threshold':.01,'minimum_correctness':.9}
        pred={'outside_length_support':False,'stop_harm_vs_action':0.,'candidate_correct':1.}
        self.assertEqual(quality_decision(spec,pred,False),'DEFER')
        self.assertEqual(quality_decision(spec,{**pred,'outside_length_support':True},True),'FALLBACK')


if __name__=='__main__':unittest.main()
