"""CPU fake-backend controls for faithful author-state-machine instrumentation."""
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from deer_author_bridge import AuthorBridge, IdentityLogprobs


def params(**kwargs):
    return SimpleNamespace(**{'temperature': 1., 'seed': None, 'top_p': 1., 'max_tokens': 16,
                              'logprobs': None, 'include_stop_str_in_output': False, **kwargs})


class BridgeControls(unittest.TestCase):
    def test_raw_defaults_preserved_and_repair_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = AuthorBridge('raw_source', Path(folder)/'raw.jsonl', 1)
            fixed = AuthorBridge('declared_greedy_identity_repair', Path(folder)/'fixed.jsonl', 1)
            self.assertEqual(raw.sampling_constructor(params)(logprobs=1).temperature, 1.)
            actual = fixed.sampling_constructor(params)(logprobs=1)
            self.assertEqual(actual.temperature, 0.)
            self.assertEqual(actual.seed, 42)
            self.assertEqual(fixed.sampling_constructor(params)(temperature=.6).temperature, .6)

    def test_repair_requires_actual_identity_and_raw_calls_original(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = AuthorBridge('raw_source', Path(folder)/'raw.jsonl', 1)
            fixed = AuthorBridge('declared_greedy_identity_repair', Path(folder)/'fixed.jsonl', 1)
            original = lambda values, policy: .33
            self.assertEqual(raw.score_function(original)([], 'avg2'), .33)
            with self.assertRaises(AssertionError): fixed.score_function(original)([], 'avg2')
            values = IdentityLogprobs([{2: math.log(.5)}, {1: math.log(.9), 7: math.log(.05)}], [2, 1])
            self.assertAlmostEqual(fixed.score_function(original)(values), .9)

    def test_all_batch_tokens_and_errors_are_recorded(self):
        class Backend:
            def get_tokenizer(self): return SimpleNamespace(encode=lambda text, **kwargs: [11, 12])
            def generate(self, prompts, sampling, **kwargs):
                if prompts == ['error']: raise RuntimeError('fixture')
                lp = SimpleNamespace(logprob=math.log(.9), decoded_token='</think>', rank=1)
                return [SimpleNamespace(request_id='q', prompt_token_ids=[11, 13], outputs=[SimpleNamespace(text='', token_ids=[1], logprobs=[{1:lp}],
                                                                           finish_reason='stop', stop_reason='</think>')])]
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'calls.jsonl'
            bridge = AuthorBridge('raw_source', file, 1)
            engine = bridge.engine_constructor(Backend)()
            outputs = engine.generate(['input'], params())
            self.assertIsInstance(outputs[0].outputs[0].logprobs, IdentityLogprobs)
            self.assertEqual(outputs[0].outputs[0].logprobs.emitted_ids, (1,))
            with self.assertRaises(RuntimeError): engine.generate(['error'], params())
            records = [json.loads(line) for line in file.read_text().splitlines()]
            self.assertEqual(records[0]['actual_generated_tokens'], 1)
            self.assertEqual(records[0]['reencoded_input_token_ids'], [[11, 12]])
            self.assertEqual(records[0]['outputs'][0]['actual_prompt_token_ids'], [11, 13])
            self.assertEqual(records[1]['kind'], 'batch_generation_failed')

    def test_pro_expands_only_trials_and_charges_every_branch(self):
        class Backend:
            def get_tokenizer(self): return SimpleNamespace(encode=lambda text, **kwargs: [11, 12])
            def generate(self, prompts, sampling, **kwargs):
                results = []
                trial = 0
                for i, (prompt, params) in enumerate(zip(prompts, sampling)):
                    if params.logprobs == 1:
                        probability = [.99, .99, .99, .2][trial]; trial += 1
                        lp = SimpleNamespace(logprob=math.log(probability), decoded_token='</think>', rank=1)
                        ids, values = [7, 1], [{7: lp}, {1: lp}]
                    else:
                        ids, values = [8], None
                    results.append(SimpleNamespace(request_id=str(i), prompt_token_ids=[i], outputs=[SimpleNamespace(
                        text='fixture', token_ids=ids, logprobs=values, finish_reason='stop', stop_reason=None)]))
                self.actual_prompts = prompts
                return results
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'pro.jsonl'
            bridge = AuthorBridge('paper_pro_declared_greedy', file, 1)
            engine = bridge.engine_constructor(Backend)()
            outputs = engine.generate(['ordinary', 'prefix\n**Final Answer**\n\\boxed'], [params(), params(logprobs=1)])
            self.assertEqual(len(outputs), 2)
            self.assertEqual(engine.actual.actual_prompts[0], 'ordinary')
            self.assertEqual(len(engine.actual.actual_prompts), 5)
            score = bridge.score_function(lambda values, policy: 1.)(outputs[1].outputs[0].logprobs)
            self.assertAlmostEqual(score, .49625)
            record = json.loads(file.read_text().splitlines()[0])
            self.assertEqual(record['actual_generated_tokens'], 9)
            self.assertEqual(record['actual_input_count'], 5)
            self.assertEqual(record['original_input_count'], 2)

    def test_nonfinite_backend_probability_is_preserved_in_json(self):
        class Backend:
            def get_tokenizer(self): return SimpleNamespace(encode=lambda text, **kwargs: [11])
            def generate(self, prompts, sampling, **kwargs):
                lp = SimpleNamespace(logprob=-math.inf, decoded_token='token', rank=1)
                return [SimpleNamespace(request_id='q', prompt_token_ids=[11], outputs=[SimpleNamespace(
                    text='fixture', token_ids=[1], logprobs=[{1:lp}], finish_reason='length', stop_reason=None)])]
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'nonfinite.jsonl'
            engine=AuthorBridge('raw_source',file,1).engine_constructor(Backend)()
            engine.generate(['input'],params())
            row=json.loads(file.read_text())
            self.assertEqual(row['outputs'][0]['completions'][0]['logprobs'][0]['1']['logprob'], '-inf')


if __name__ == '__main__':
    unittest.main()
