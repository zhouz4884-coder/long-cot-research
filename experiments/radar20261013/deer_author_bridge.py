"""Instrumentation bridge for the pinned author Qwen-vLLM state machine.

Does not implement an early-stop proxy. The future runner must load the actual
author module and call its main(). No model/GPU engine is imported here.
Raw-source and declared greedy/identity-repair modes remain separate.
"""
import json
import math
from pathlib import Path
import time
from deer_trial_score import qwen_trial_score
from deer_pro import pro_prompts, calibrated_confidence


class IdentityLogprobs(list):
    def __init__(self, values, emitted_ids):
        super().__init__(values)
        self.emitted_ids = tuple(emitted_ids)


class ProLogprobs(IdentityLogprobs):
    def __init__(self, values, emitted_ids, trials):
        super().__init__(values, emitted_ids)
        self.trials = trials
        self.calibration = calibrated_confidence([x['score'] for x in trials])


def json_float(value):
    value = float(value)
    return value if math.isfinite(value) else str(value)


class AuthorBridge:
    def __init__(self, mode, log_path, endthink_id, seed=42):
        assert mode in ['raw_source', 'declared_greedy_identity_repair', 'paper_pro_declared_greedy']
        self.mode = mode
        self.log_path = Path(log_path)
        self.endthink_id = endthink_id
        self.seed = seed
        self.calls = 0

    def record(self, value):
        with self.log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()

    def sampling_constructor(self, original):
        def constructor(*args, **kwargs):
            requested = dict(kwargs)
            is_trial = kwargs.get('logprobs') == 1
            if is_trial and self.mode != 'raw_source':
                kwargs = {**kwargs, 'temperature': 0., 'seed': self.seed}
            params = original(*args, **kwargs)
            self.record({'kind': 'sampling_parameters', 'mode': self.mode, 'trial': is_trial,
                         'requested_explicit_keys': sorted(requested),
                         'effective': {key: getattr(params, key, None) for key in
                         ['temperature', 'top_p', 'seed', 'max_tokens', 'logprobs', 'include_stop_str_in_output']}})
            return params
        return constructor

    def score_function(self, original):
        def calculate(logprobs, policy='avg2'):
            if self.mode == 'raw_source':
                try:
                    score = original(logprobs, policy)
                except Exception as error:
                    self.record({'kind': 'source_trial_score_failed', 'exception_type': type(error).__name__})
                    raise
                self.record({'kind': 'source_trial_score', 'score': json_float(score)})
                return score
            if self.mode == 'paper_pro_declared_greedy':
                assert policy == 'avg2', 'Paper PRo setting uses geometric per-trial score'
                assert isinstance(logprobs, ProLogprobs), 'All four actual trial identities required'
                self.record({'kind': 'paper_pro_confidence', 'trials': logprobs.trials,
                             'calibration': logprobs.calibration})
                return logprobs.calibration['score']
            assert isinstance(logprobs, IdentityLogprobs), 'Actual emitted IDs must accompany trial logprobs'
            result = qwen_trial_score(logprobs.emitted_ids, logprobs, self.endthink_id, policy)
            self.record({'kind': 'declared_score_repair', 'details': result})
            return result['score']
        return calculate

    def engine_constructor(self, original):
        bridge = self
        class RecordedEngine:
            def __init__(self, *args, **kwargs):
                self.actual = original(*args, **kwargs)
                self.tokenizer = self.actual.get_tokenizer()
            def __getattr__(self, key):
                return getattr(self.actual, key)
            def generate(self, prompts, sampling_params, *args, **kwargs):
                bridge.calls += 1
                call = bridge.calls
                params = sampling_params if isinstance(sampling_params, list) else [sampling_params] * len(prompts)
                assert len(prompts) == len(params)
                expanded_prompts, expanded_params, groups = [], [], []
                for prompt, sampling in zip(prompts, params):
                    is_pro = bridge.mode == 'paper_pro_declared_greedy' and sampling.logprobs == 1
                    group_prompts = pro_prompts(prompt) if is_pro else [prompt]
                    groups.append((len(expanded_prompts), len(group_prompts), is_pro))
                    expanded_prompts.extend(group_prompts)
                    expanded_params.extend([sampling] * len(group_prompts))
                actual_params = expanded_params if isinstance(sampling_params, list) or len(expanded_prompts) != len(prompts) else sampling_params
                started = time.perf_counter()
                try:
                    outputs = self.actual.generate(expanded_prompts, actual_params, *args, **kwargs)
                except Exception as error:
                    bridge.record({'kind': 'batch_generation_failed', 'call': call, 'exception_type': type(error).__name__,
                                   'elapsed_ms': 1000 * (time.perf_counter() - started)})
                    raise
                elapsed = 1000 * (time.perf_counter() - started)
                records = []
                for output in outputs:
                    completions = []
                    for completion in output.outputs:
                        ids = list(completion.token_ids)
                        logprobs = completion.logprobs
                        if logprobs is not None:
                            completion.logprobs = IdentityLogprobs(logprobs, ids)
                        completions.append({'token_ids': ids, 'text': completion.text,
                                            'finish_reason': completion.finish_reason,
                                            'stop_reason': completion.stop_reason,
                                            'logprobs': None if logprobs is None else [
                                                {str(token): {'logprob': json_float(value.logprob),
                                                              'decoded_token': value.decoded_token,
                                                              'rank': value.rank}
                                                 for token, value in values.items()} if values else {}
                                                for values in logprobs]})
                    records.append({'request_id': str(output.request_id),
                                    'actual_prompt_token_ids': list(output.prompt_token_ids) if output.prompt_token_ids is not None else None,
                                    'completions': completions})
                prompt_ids = [self.tokenizer.encode(text, add_special_tokens=False) for text in expanded_prompts]
                bridge.record({'kind': 'actual_batch_generation', 'call': call, 'mode': bridge.mode,
                               'reencoded_input_token_ids': prompt_ids, 'outputs': records,
                               'original_input_count': len(prompts), 'actual_input_count': len(expanded_prompts),
                               'actual_generated_tokens': sum(len(c['token_ids']) for r in records for c in r['completions']),
                               'batch_wall_ms': elapsed,
                               'scope': 'Actual batch call including all emitted trial tokens. Batch time is not per-request latency or goodput.'})
                assert len(outputs) == len(expanded_prompts), 'Preserve/log partial returned output; do not silently drop missing trials'
                collapsed = []
                for start, count, is_pro in groups:
                    canonical = outputs[start]
                    if is_pro:
                        trials = []
                        for output in outputs[start:start + count]:
                            assert len(output.outputs) == 1, 'PRo setting is one completion per inducing prompt'
                            completion = output.outputs[0]
                            trial = qwen_trial_score(list(completion.token_ids), completion.logprobs or [], bridge.endthink_id)
                            trials.append(trial)
                        completion = canonical.outputs[0]
                        completion.logprobs = ProLogprobs(completion.logprobs or [], completion.token_ids, trials)
                    collapsed.append(canonical)
                return collapsed
        return RecordedEngine

    def attach(self, author_module):
        # Mutates only the loaded module namespace, never the pinned vendor file.
        author_module.SamplingParams = self.sampling_constructor(author_module.SamplingParams)
        author_module.LLM = self.engine_constructor(author_module.LLM)
        author_module.calculate_average_max_prob_from_logprobs = self.score_function(
            author_module.calculate_average_max_prob_from_logprobs)
