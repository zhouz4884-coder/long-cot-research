"""CPU demonstration of inspected uploaded-reference limitations, not an exploit.

Only the reviewed stdlib-only core member is imported from a temporary directory.
No model, credentials, shell command, or expensive unbounded power is executed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import zipfile


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--zip-path',type=Path,default=Path('E:/Downloads/longcot_phase5d_codex_kit.zip'))
    args=parser.parse_args();out=Path(__file__).resolve().parent
    with zipfile.ZipFile(args.zip_path) as archive:
        data=archive.read('phase5d_codex_kit/scope_rebase_core.py')
    with tempfile.TemporaryDirectory(prefix='phase5d_reference_core_') as directory:
        source=Path(directory)/'reference_core.py';source.write_bytes(data)
        name='_reviewed_phase5d_reference';spec=importlib.util.spec_from_file_location(name,source)
        ref=importlib.util.module_from_spec(spec);sys.modules[name]=ref;spec.loader.exec_module(ref)
        claim=ref.Claim('x','x=999 without authenticated source','S',0,1)
        proof=ref.Justification('p','x',(),'S','PASS','trusted_root','arbitrary nonempty string')
        g=ref.EvidenceLedger([claim],[proof])
        arbitrary_root_accepted='x' in g.supported()
        d=g.revoke_by_challenge(ref.Challenge('p','PASS','S','arbitrary alleged refutation'))
        arbitrary_challenge_revoked=bool(d.lost_support)
        claims=[ref.Claim('x','x=2','S',0,10),ref.Claim('r','r=11','S',80,90),ref.Claim('z','z=11','S',110,120)]
        proofs=[ref.Justification('px','x',(),'S','PASS','trusted_root','a'),
                ref.Justification('pr','r',(),'S','PASS','trusted_root','b'),
                ref.Justification('pz1','z',('x',),'S','PASS','verified_rule','c'),
                ref.Justification('pz2','z',('r',),'S','PASS','verified_rule','d')]
        multi=ref.EvidenceLedger(claims,proofs);delta=multi.revoke_by_challenge(ref.Challenge('pz1','PASS','S','receipt'))
        lost_empty_crop_none=not delta.lost_support and delta.crop_at_token is None
        cyclic=ref.EvidenceLedger([ref.Claim('a','a','S',0,1),ref.Claim('b','b','S',1,2)],
            [ref.Justification('pa','a',('b',),'S','PASS','verified_rule','e'),ref.Justification('pb','b',('a',),'S','PASS','verified_rule','f')])
        cycles_not_grounded=not cyclic.supported()
    result={'scope':'Actual CPU demonstrations of known documented-reference gaps; not model/algorithm gain.',
            'reference_core_sha256':hashlib.sha256(data).hexdigest(),
            'arbitrary_nonempty_certificate_root_accepted':arbitrary_root_accepted,
            'arbitrary_PASS_challenge_string_revokes_supported_proof':arbitrary_challenge_revoked,
            'alternative_support_keeps_claim_but_no_reconstruction_trigger':lost_empty_crop_none,
            'reference_least_fixed_point_correctly_blocks_ungrounded_cycles':cycles_not_grounded,
            'static_only_not_executed':['Nested powers have per-exponent bound but no aggregate AST/bit bound.',
                'Claim canonical text is reserialized without an authenticated semantic/canonical checker.',
                'Proof-span retirement is not represented; crop derived only from lost claims.'],
            'interpretation':'The kit explicitly calls its certificates externally prevalidated. These are integration gaps, not evidence that its AND/OR fixed point is wrong.'}
    assert all((arbitrary_root_accepted,arbitrary_challenge_revoked,lost_empty_crop_none,cycles_not_grounded))
    (out/'UPSTREAM_GAPS_REPRODUCED.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
