"""Execute original author's entire main() on CPU scripted backend responses.

These verify orchestration and repairs only, never model task performance.
"""
import argparse
from collections import deque
import contextlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from nltk import ngrams
import torch
from deer_author_bridge import AuthorBridge
from deer_author_source import load_original_functions_for_cpu_controls, invoke_author_batch


class Tokenizer:
    eos_token='<eos>'
    eos_token_id=2
    pad_token='<eos>'
    def encode(self,text,**kwargs):
        return [1] if text=='</think>' else [3]*len(text)
    def apply_chat_template(self,messages,**kwargs):
        return messages[0]['content']+'\n'+messages[1]['content']+'<think>'


class Progress:
    def __init__(self,**kwargs):pass
    def update(self,*args):pass
    def close(self):pass


def sampling(**kwargs):
    return SimpleNamespace(**{'temperature':1.,'top_p':1.,'seed':None,'max_tokens':20,
                              'logprobs':None,'include_stop_str_in_output':False,**kwargs})


def completion(text,ids,probability=None):
    if probability is None:
        logprobs=None
    else:
        logprobs=[{token:SimpleNamespace(logprob=math.log(probability),decoded_token='</think>' if token==1 else 'token',rank=1)} for token in ids]
    return SimpleNamespace(text=text,token_ids=ids,logprobs=logprobs,finish_reason='stop',stop_reason=None)


class StateMachineControls(unittest.TestCase):
    def execute(self,mode,scripted,no_thinking=0):
        with tempfile.TemporaryDirectory() as folder:
            state={'queue':deque(scripted),'calls':[]}
            class Backend:
                def __init__(self,**kwargs):pass
                def get_tokenizer(self):return Tokenizer()
                def generate(self,prompts,parameters,**kwargs):
                    params=parameters if isinstance(parameters,list) else [parameters]*len(prompts)
                    result=[]
                    for prompt,param in zip(prompts,params):
                        state['calls'].append({'prompt':prompt,'trial':param.logprobs==1,'temperature':param.temperature})
                        if prompt=='Hello, world!':actual=completion('warmup',[3])
                        else:
                            expected,actual=state['queue'].popleft()
                            assert expected==('trial' if param.logprobs==1 else 'generation')
                        result.append(SimpleNamespace(request_id=str(len(state['calls'])),prompt_token_ids=Tokenizer().encode(prompt),outputs=[actual]))
                    return result
            author=load_original_functions_for_cpu_controls({'os':os,'json':json,'time':time,'torch':torch,'math':math,'np':np,
                    'ngrams':ngrams,'LLM':Backend,'SamplingParams':sampling,'tqdm':Progress,
                    'AutoTokenizer':SimpleNamespace(from_pretrained=lambda *a,**k:Tokenizer())})
            bridge=AuthorBridge(mode,Path(folder)/'calls.jsonl',1)
            bridge.attach(author)
            args=SimpleNamespace(model_name_or_path='CPU-scripted-backend',dataset_dir=folder,dataset='math',output_path=folder,
                 max_len=128,think_ratio=.8,batch_size=1,threshold=.95,prob_check_max_tokens=20,
                 max_judge_steps=10,points=1,policy='avg2',temperature=0.,top_p=1.,dtype='float16',
                 gpu_memory_utilization=.9,trust_remote_code=False,run_time=1,no_thinking=no_thinking,rep=0,af=0)
            with patch.dict(os.environ,{'CUDA_VISIBLE_DEVICES':'0'}),contextlib.redirect_stdout(io.StringIO()):
                rows=invoke_author_batch(author,[{'problem_id':'cpu-only','question':'fixture question'}],args)
            self.assertFalse(state['queue'])
            records=[json.loads(x) for x in (Path(folder)/'calls.jsonl').read_text().splitlines()]
            return rows,state['calls'],records

    def test_original_rejects_then_restores_wait_then_accepts_and_regenerates_final(self):
        rows,calls,records=self.execute('raw_source',[
            ('generation',completion('thought',[3])),('trial',completion('trial-2',[4,1],.5)),
            ('generation',completion('further thought',[3])),('trial',completion('trial-2',[4,1],.99)),
            ('generation',completion('\\boxed{7}',[5,2]))])
        self.assertEqual(rows[0]['high_prob'],1)
        self.assertEqual(rows[0]['thinking_steps'],2)
        self.assertTrue(calls[3]['prompt'].endswith('Wait'))
        self.assertIn('\\boxed{7}',rows[0]['generated_responses'][0])
        self.assertNotIn('trial-2',rows[0]['generated_responses'][0])
        self.assertEqual(rows[0]['gold_answer'],'<withheld>')
        self.assertEqual([x['temperature'] for x in calls if x['trial']],[1.,1.])

    def test_natural_end_think_skips_trial_and_preserves_source_final(self):
        rows,calls,_=self.execute('raw_source',[
            ('generation',completion('thought',[3,1])),('generation',completion('\\boxed{7}',[5,2]))])
        self.assertEqual(rows[0]['regular_end'],1)
        self.assertFalse(any(x['trial'] for x in calls))

    def test_raw_one_token_trial_error_is_preserved(self):
        rows,_,records=self.execute('raw_source',[
            ('generation',completion('thought',[3])),('trial',completion('',[1],.99))])
        self.assertIn('division by zero',rows[0]['generated_responses'][0])
        self.assertEqual(sum(x['kind']=='source_trial_score_failed' for x in records),1)

    def test_declared_short_trial_repair_continues_instead_of_silent_acceptance(self):
        rows,calls,_=self.execute('declared_greedy_identity_repair',[
            ('generation',completion('thought',[3])),('trial',completion('',[1],.99)),
            ('generation',completion('further thought',[3,1])),('generation',completion('\\boxed{7}',[5,2]))])
        self.assertEqual(rows[0]['high_prob'],0)
        self.assertEqual(rows[0]['regular_end'],1)
        self.assertTrue(calls[3]['prompt'].endswith('Wait'))
        self.assertEqual([x['temperature'] for x in calls if x['trial']],[0.])

    def test_full_pro_state_machine_rejects_noisy_first_four_and_accepts_second_four(self):
        script=[('generation',completion('thought',[3]))]
        script += [('trial',completion('trial-2',[4,1],p)) for p in [.99,.99,.99,.2]]
        script += [('generation',completion('further thought',[3]))]
        script += [('trial',completion('trial-2',[4,1],.99)) for _ in range(4)]
        script += [('generation',completion('\\boxed{7}',[5,2]))]
        rows,calls,records=self.execute('paper_pro_declared_greedy',script)
        self.assertEqual(rows[0]['thinking_steps'],2)
        self.assertEqual(rows[0]['high_prob'],1)
        self.assertEqual(sum(x['trial'] for x in calls),8)
        scores=[x['calibration']['score'] for x in records if x['kind']=='paper_pro_confidence']
        self.assertAlmostEqual(scores[0],.49625)
        self.assertAlmostEqual(scores[1],.99)
        self.assertIn('\\boxed{7}',rows[0]['generated_responses'][0])

    def test_gold_field_rejected_before_author_main(self):
        author=SimpleNamespace(parse_args=lambda:None,read_jsonl=lambda path:None,write_jsonl=lambda rows,path:None)
        with self.assertRaises(AssertionError):
            invoke_author_batch(author,[{'problem_id':'cpu-only','question':'fixture','answer':'leaked'}],None)

    def test_admission_forces_four_real_trial_calls_before_any_thinking(self):
        script=[('trial',completion('trial-2',[4,1],.99)) for _ in range(4)]
        script += [('generation',completion('\\boxed{7}',[5,2]))]
        rows,calls,_=self.execute('paper_pro_declared_greedy',script,no_thinking=1)
        self.assertEqual(rows[0]['high_prob'],1)
        self.assertEqual(rows[0]['thinking_steps'],0)
        self.assertEqual(sum(x['trial'] for x in calls),4)

    def test_duplicate_text_and_source_reordering_keep_every_frozen_id(self):
        questions=[{'problem_id':'first','question':'duplicate'}, {'problem_id':'middle','question':'other'},
                   {'problem_id':'last','question':'duplicate'}]
        author=SimpleNamespace(parse_args=lambda:None,read_jsonl=lambda path:None,write_jsonl=lambda rows,path:None)
        def fake_source_main():
            data=author.read_jsonl('unused')
            # Mimic source's question-text sorting, which places the first
            # duplicate behind the middle item; bind identity through markers.
            order=[1,0,2]
            author.write_jsonl([{'question':data[i]['problem'],'gold_answer':data[i]['answer'],
                                 'generated_responses':['result-'+str(i)]} for i in order],'unused')
        author.main=fake_source_main
        rows=invoke_author_batch(author,questions,None)
        self.assertEqual([x['problem_id'] for x in rows],['first','middle','last'])
        self.assertEqual([x['generated_responses'][0] for x in rows],['result-0','result-1','result-2'])
        self.assertTrue(all(x['gold_answer']=='<withheld>' for x in rows))


if __name__=='__main__':unittest.main()
