import hashlib,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from protocol_guard import check_source_map,validate_resume
from risk_policy import problem_shard


class FormalRecordGuard(unittest.TestCase):
    def test_runtime_mutation_cannot_reuse_a_source_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'engine.py';path.write_bytes(b'old')
            expected={'engine.py':hashlib.sha256(b'old').hexdigest()}
            check_source_map(directory,expected,required=['engine.py'])
            path.write_bytes(b'new')
            with self.assertRaises(AssertionError):check_source_map(directory,expected,required=['engine.py'])

    def test_resume_rejects_wrong_protocol_model_and_duplicates(self):
        row={'problem_id':'q1','formal_protocol_sha256':'v1','model_path':'m1'}
        self.assertEqual(validate_resume([row],'v1','m1',{'q1'}),{'q1'})
        for rows,protocol,model in [([row],'v2','m1'),([row],'v1','m2'),([row,row],'v1','m1')]:
            with self.assertRaises(AssertionError):validate_resume(rows,protocol,model,{'q1'})

    def test_worker_identity_is_independent_of_partition_and_order(self):
        questions=['q'+str(i) for i in range(100)]
        assigned={q:problem_shard(q,2) for q in questions}
        # Candidate/calibration/test membership changes cannot move the physical
        # worker and hence cannot define a different potential response path.
        split_order=questions[::3]+questions[1::3]+questions[2::3]
        self.assertEqual(assigned,{q:problem_shard(q,2) for q in reversed(split_order)})
        self.assertEqual(set(assigned.values()),{0,1})


if __name__=='__main__':unittest.main()
