"""LCB data decoding and output comparison; never executes candidate code."""
import base64,io,json,pickle,zlib
from decimal import Decimal,InvalidOperation


class DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        raise pickle.UnpicklingError('Executable/global pickle value forbidden')
    def persistent_load(self,pid):
        raise pickle.UnpicklingError('Persistent pickle reference forbidden')


def decode_private(value,max_bytes=128*1024*1024):
    try:decoded=json.loads(value)
    except json.JSONDecodeError:
        raw=base64.b64decode(value,validate=True)
        decompressor=zlib.decompressobj()
        payload=decompressor.decompress(raw,max_bytes+1)
        if len(payload)>max_bytes or decompressor.unconsumed_tail or not decompressor.eof:
            raise ValueError('Private cases exceed frozen decoded-size limit')
        decoded=DataOnlyUnpickler(io.BytesIO(payload)).load()
        if isinstance(decoded,str):decoded=json.loads(decoded)
    if not isinstance(decoded,list):raise ValueError('Cases must be a list')
    for case in decoded:
        if not isinstance(case,dict) or not {'input','output','testtype'}<=case.keys():
            raise ValueError('Malformed case')
        if not isinstance(case['input'],str) or not isinstance(case['output'],str):
            raise ValueError('Expected serialized input/output strings')
        if case['testtype'] not in ['stdin','functional']:raise ValueError('Unknown test interface')
    return decoded


def cases_for_row(row):
    cases=json.loads(row['public_test_cases'])+decode_private(row['private_test_cases'])
    if not cases:raise ValueError('Empty evaluation cases')
    styles={c['testtype'] for c in cases}
    if len(styles)!=1:raise ValueError('Mixed case interfaces')
    metadata=json.loads(row['metadata'])
    if styles=={'functional'} and not isinstance(metadata.get('func_name'),str):
        raise ValueError('Missing callable name')
    return cases,metadata.get('func_name')


def stdio_equal(prediction,expected):
    # Official testing_util.py strips each line and accepts exact Decimal token
    # equality, avoiding np.isclose on large integers. No numeric tolerance.
    a=[s.strip() for s in prediction.strip().split('\n')]
    b=[s.strip() for s in expected.strip().split('\n')]
    if len(a)!=len(b):return False
    for x,y in zip(a,b):
        if x==y:continue
        try:
            px=[Decimal(v) for v in x.split()];py=[Decimal(v) for v in y.split()]
            if not px or len(px)!=len(py) or any(not v.is_finite() for v in px+py) or px!=py:return False
        except InvalidOperation:return False
    return True
