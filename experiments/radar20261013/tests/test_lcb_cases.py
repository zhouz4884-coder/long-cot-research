import base64,json,pickle,sys,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lcb_cases import decode_private,stdio_equal


class LCBCaseProtocol(unittest.TestCase):
    def test_data_only_compressed_cases(self):
        cases=[{'input':'2 3\n','output':'5\n','testtype':'stdin'}]
        encoded=base64.b64encode(zlib.compress(pickle.dumps(json.dumps(cases)))).decode()
        self.assertEqual(decode_private(encoded),cases)
        with self.assertRaises(ValueError):decode_private(encoded,max_bytes=4)

    def test_global_pickle_is_rejected_without_execution(self):
        encoded=base64.b64encode(zlib.compress(pickle.dumps(eval))).decode()
        with self.assertRaises(pickle.UnpicklingError):decode_private(encoded)

    def test_no_large_integer_float_tolerance(self):
        self.assertFalse(stdio_equal('50000000000000000','50000000000000001'))
        self.assertTrue(stdio_equal('1.00  2\n','1 2.0'))
        self.assertFalse(stdio_equal('1\n2','1 2'))


if __name__=='__main__':unittest.main()
