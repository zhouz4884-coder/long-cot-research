"""Malformed ratings are unknown, and triggers need an observed full marker."""
from pathlib import Path
import sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dtsr_adapter import parse_rating,MARKER,rating_prompt,decode_dtsr


class TapeEngine:
    def __init__(self,tape):
        self.tape=list(map(ord,tape));self.model_ms=0.;self.endthink=ord('~');self.eos={0}
        self.torch=SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda:None))
        self.tok=SimpleNamespace(decode=lambda ids,**kwargs:''.join(map(chr,ids)))
    def forward(self,ids,cache=None):
        length=(cache.length if cache else 0)+len(ids)
        return SimpleNamespace(length=length,get_seq_length=lambda:length),None
    def sample(self,logits,seed,phase,position,stats=False):return self.tape[position],None


class DTSRProtocol(unittest.TestCase):
    def test_rating_requires_a_single_bounded_numeric_response(self):
        for text,value in [('Confidence:100',100.),('99.5',99.5),('1e2',100.),('0',0.)]:
            self.assertEqual(parse_rating(text),value)
        for text in ['I think80 but maybe100','Confidence:101','100 and0','nan','Confidence:-1','']:
            self.assertIsNone(parse_rating(text))

    def test_trigger_cannot_precede_observed_word(self):
        self.assertFalse(MARKER.search('Wai'))
        self.assertTrue(MARKER.search('Wait,'))
        self.assertFalse(MARKER.search('Awaiting'))
        self.assertTrue(MARKER.search('But let me check'))
        prompt=rating_prompt('q','observed prefix')
        self.assertIn('q',prompt);self.assertIn('observed prefix',prompt)

    def test_full_tape_is_preserved_for_unknown_and_low_ratings(self):
        tape='x'*59+' '+'Wait'+' continue to the end~'
        for value in [None,99.]:
            rating={'rating':value,'tokens':3,'input_tokens':200,'auxiliary_wall_ms':2.}
            with patch('dtsr_adapter.evaluate_sufficiency',return_value=rating):
                result=decode_dtsr(TapeEngine(tape),'q',[1,2],len(tape),7)
            self.assertEqual(result['ids'],list(map(ord,tape)))
            self.assertEqual(result['stop_reason'],'natural_end')
            self.assertEqual(result['rating_generated_tokens'],3)
            self.assertEqual(result['decisions'][0]['offset'],64)

    def test_stop_at64_is_not_delayed_to_paragraph_or128(self):
        tape='x'*59+' '+'Wait'+' unreached future~'
        rating={'rating':100.,'tokens':1,'input_tokens':200,'auxiliary_wall_ms':2.}
        with patch('dtsr_adapter.evaluate_sufficiency',return_value=rating):
            result=decode_dtsr(TapeEngine(tape),'q',[1,2],len(tape),7)
        self.assertEqual(result['text'],'x'*59+' '+'Wait')
        self.assertEqual(result['stop_reason'],'policy_stop')
        self.assertEqual(result['tokens'],64)


if __name__=='__main__':unittest.main()
