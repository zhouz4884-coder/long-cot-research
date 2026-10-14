"""A verified policy cannot lend its action consistency to a different policy."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from select_calibrate_policies import candidate_spec_hash,candidate_consistency_admitted


class CandidateSpecificCertification(unittest.TestCase):
    def test_admission_stays_with_one_policy_model_and_protocol(self):
        admitted={'kind':'risk_gate','risk_threshold':.01,'minimum_correctness':.9}
        different={**admitted,'risk_threshold':.02}
        audit={'passed':True,'model_path':'m1','formal_protocol_sha256':'f1',
               'verified_candidate_spec_sha256':[candidate_spec_hash(admitted)]}
        self.assertTrue(candidate_consistency_admitted(audit,admitted,'f1','m1'))
        self.assertFalse(candidate_consistency_admitted(audit,different,'f1','m1'))
        self.assertFalse(candidate_consistency_admitted(audit,admitted,'f2','m1'))
        self.assertFalse(candidate_consistency_admitted(audit,admitted,'f1','m2'))
        self.assertFalse(candidate_consistency_admitted({'passed':True},admitted,'f1','m1'))


if __name__=='__main__':unittest.main()
