import hashlib,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from protocol_guard import check_source_map,validate_resume


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


if __name__=='__main__':unittest.main()
