"""Independent REFRAIN adaptation: published default discriminator and SW-UCB.

Author repository had no executable implementation at the archived commit.
Functional trigger terms below are Table5's default terms, excluding underlined
expansions and the bold new-category ablation. Common solver/readout settings,
CPU encoder placement, cue normalization and prior-mean reward are declared
adaptations, not an exact author benchmark reproduction.
"""
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re
import time

from reason_transition.core import digest_ids, brace_balance, last_box
from reason_transition.text_decoder import RollingTextDecoder

TRIGGERS = {
    'check': ('wait', 'let me check', 'hold on', 'have made a mistake'),
    'shift': ('alternatively', 'let me try', 'think of it as', 'let me consider', 'what if we try'),
    'uncertainty': ('not sure', 'looks like', 'that seems', 'hmm', 'perhaps', 'maybe i'),
    'retrospective': ('earlier we saw', 'from before', 'so now we have', 'recall that', 'let me go back'),
}
PROVISIONAL_CUE = re.compile(r'answer\s+(?:is|should\s+be)', re.I)
DEFAULT_ARMS = (.60, .65, .70, .75, .80)


class MiniLMEncoder:
    """Existing Transformers on CPU; no sentence-transformers installation."""
    def __init__(self, path, manifest):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.path = Path(path)
        spec = json.loads(Path(manifest).read_text(encoding='utf-8'))
        assert spec['repository'] == 'sentence-transformers/all-MiniLM-L6-v2'
        for row in spec['files']:
            digest = hashlib.sha256((self.path / row['file']).read_bytes()).hexdigest()
            assert digest == row['sha256'], f"Encoder checksum mismatch: {row['file']}"
        assert spec['sentence_config']['max_seq_length'] == 256
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model, loading = AutoModel.from_pretrained(path, local_files_only=True,
                                                   torch_dtype=torch.float32, output_loading_info=True)
        assert not loading.get('missing_keys') and not loading.get('mismatched_keys') and not loading.get('error_msgs'), loading
        unexpected = set(loading.get('unexpected_keys', []))
        assert unexpected <= {'embeddings.position_ids'}, loading
        # Old snapshots persist this deterministic buffer; newer Transformers
        # regenerates it. Verify that it is precisely the standard position tape.
        if unexpected:
            from safetensors import safe_open
            with safe_open(str(self.path / 'model.safetensors'), framework='pt', device='cpu') as snapshot:
                positions = snapshot.get_tensor('embeddings.position_ids')
            assert torch.equal(positions, torch.arange(model.config.max_position_embeddings).unsqueeze(0))
        self.loading_info = {'missing_keys': [], 'mismatched_keys': [], 'error_msgs': [],
                             'unexpected_keys': sorted(unexpected),
                             'unexpected_positions_buffer_verified': bool(unexpected)}
        self.model = model.cpu().eval()
        assert self.model.config.hidden_size == 384
        self.revision = spec['revision']

    def encode(self, texts):
        torch = self.torch
        batch = self.tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors='pt')
        with torch.inference_mode():
            states = self.model(**batch).last_hidden_state
            mask = batch['attention_mask'].unsqueeze(-1).to(states.dtype)
            vectors = (states * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
        assert vectors.shape == (len(texts), 384) and torch.isfinite(vectors).all()
        return vectors.numpy()


class Discriminator:
    def __init__(self, encoder, threshold):
        assert 0 <= threshold <= 1
        self.encoder = encoder
        self.threshold = float(threshold)
        self.embeddings = []
        self.prior_answer = False

    def observe(self, step):
        started = time.perf_counter()
        # Match substrings as Eq2; do not silently add a word-boundary filter.
        normalized = step.lower().replace('\u2019', "'")
        terms = [v for group in TRIGGERS.values() for v in group if v in normalized]
        vector = self.encoder.encode([step])[0]
        similarity = max((float(vector @ prior) for prior in self.embeddings), default=0.)
        eligible = self.prior_answer and bool(terms)
        stop = eligible and similarity >= self.threshold
        result = {'step_index': len(self.embeddings) + 1, 'prior_provisional_answer': self.prior_answer,
                  'reflection_terms': terms, 'max_prior_cosine': similarity,
                  'threshold': self.threshold, 'action': 'STOP' if stop else 'CONTINUE',
                  'encoder_and_discriminator_wall_ms': 1000 * (time.perf_counter() - started)}
        self.embeddings.append(vector)
        # Current-step cue only enables subsequent steps, per Eq3/5.
        self.prior_answer |= bool(PROVISIONAL_CUE.search(normalized))
        return result


class SlidingWindowUCB:
    """Per-arm recent W rewards, Eq7-9. One serial ordered problem stream."""
    def __init__(self, arms=DEFAULT_ARMS, window=100, exploration=1., length_penalty=.2):
        assert window > 0 and exploration > 0 and length_penalty >= 0
        assert len(set(arms)) == len(arms) and all(0 <= t <= 1 for t in arms)
        self.arms = tuple(float(t) for t in arms)
        self.window = int(window)
        self.exploration = float(exploration)
        self.length_penalty = float(length_penalty)
        self.buffers = {t: deque(maxlen=self.window) for t in self.arms}
        self.completed = 0
        self.total_length = 0

    def choose(self):
        for arm in self.arms:
            if not self.buffers[arm]:
                return arm
        effective_time = min(self.completed + 1, self.window * len(self.arms))
        def ucb(arm):
            values = self.buffers[arm]
            return sum(values) / len(values) + self.exploration * math.sqrt(2 * math.log(effective_time) / len(values))
        return max(self.arms, key=ucb)  # First configured arm resolves ties.

    def update(self, arm, answer_score, output_length):
        assert arm in self.buffers and 0 <= answer_score <= 1 and math.isfinite(answer_score)
        assert isinstance(output_length, int) and output_length > 0
        prior_mean = self.total_length / self.completed if self.completed else None
        penalty = .0001 * output_length if prior_mean is None else self.length_penalty * output_length / prior_mean
        reward = answer_score - penalty
        self.buffers[arm].append(reward)
        self.completed += 1
        self.total_length += output_length
        return {'reward': reward, 'answer_score': answer_score, 'penalty': penalty,
                'prior_mean_output_tokens': prior_mean, 'gold_used': False}

    def snapshot(self):
        return {'completed': self.completed, 'total_length': self.total_length,
                'buffers': {str(t): list(self.buffers[t]) for t in self.arms}}


def decode_refrain(engine, encoder, prefix, max_think_tokens, seed, threshold):
    """Check every completed blank-line step, without a token interval floor."""
    assert max_think_tokens > 0
    engine.torch.cuda.synchronize()
    started = time.perf_counter()
    before = engine.model_ms
    cache, logits = engine.forward(prefix)
    prefill_ms = engine.model_ms - before
    decoder = RollingTextDecoder(engine.tok)
    discriminator = Discriminator(encoder, threshold)
    ids = []
    text = ''
    consumed = 0
    checks = []
    reason = 'limit'
    for index in range(max_think_tokens):
        token, _ = engine.sample(logits, seed, 'think', index, stats=False)
        ids.append(token)
        text = decoder.append(token)
        cache, logits = engine.forward([token], cache)
        if token in engine.eos:
            reason = 'eos'
            break
        if token == engine.endthink:
            reason = 'natural_end'
            break
        # A token can contain a delimiter and the next paragraph's first bytes.
        while True:
            boundary = text.find('\n\n', consumed)
            if boundary < 0:
                break
            step = text[consumed:boundary]
            consumed = boundary + 2
            if not step.strip():
                continue
            check = discriminator.observe(step)
            check.update({'offset': index + 1, 'step_text': step,
                          'prefix_sha256': digest_ids(prefix + ids),
                          'generated_tail_after_step': text[consumed:]})
            checks.append(check)
            if check['action'] == 'STOP':
                reason = 'policy_stop'
                break
        if reason == 'policy_stop':
            break
    engine.torch.cuda.synchronize()
    return {'ids': ids, 'text': text, 'tokens': len(ids), 'stop_reason': reason,
            'length_censored': reason == 'limit', 'ms': 1000 * (time.perf_counter() - started),
            'model_ms': engine.model_ms - before, 'prefill_model_ms': prefill_ms,
            'decisions': checks, 'cache': cache, 'logits': logits,
            'encoder_wall_ms': sum(c['encoder_and_discriminator_wall_ms'] for c in checks),
            'quality_labels_available_during_decisions': False,
            'scope': 'Controlled independent REFRAIN; actual step-encoder work is inside request timing.'}


def answer_refrain(engine, prefix, seed, natural_closed=False, initial=None):
    """Common boxed finalizer with raw chosen-token answer likelihood.

No additional scoring forward pass. A token overlapping the answer/closing-brace
boundary is indivisible; include that token and explicitly record this numerical
adaptation. Brace-only tokens outside the boxed content are excluded.
"""
    engine.torch.cuda.synchronize()
    started = time.perf_counter()
    before = engine.model_ms
    if natural_closed:
        suffix = engine.tok.encode('\n\n' + engine.answer_cue, add_special_tokens=False)
    else:
        suffix = engine.suffix
        if engine.tok.convert_tokens_to_ids('<think>') not in prefix:
            suffix = engine.tok.encode('<think>\n', add_special_tokens=False) + suffix
    context = prefix + suffix
    cache, logits = engine.forward(suffix, initial[0]) if initial is not None else engine.forward(context)
    prefill_ms = engine.model_ms - before
    ids, logprobs = [], []
    decoder = RollingTextDecoder(engine.tok)
    text = ''
    reason = 'limit'
    for index in range(192):
        token, _ = engine.sample(logits, seed, 'answer', index, stats=False)
        probability = float(logits.float().log_softmax(-1)[token].item())
        assert math.isfinite(probability)
        ids.append(token)
        logprobs.append(probability)
        text = decoder.append(token)
        cache, logits = engine.forward([token], cache)
        if 1 + brace_balance(text) <= 0:
            reason = 'answer_box_complete'
            break
        if token in engine.eos:
            reason = 'eos'
            break
    boxed = last_box(r'\boxed{' + text)
    selected, boundary_overlaps = [], []
    if boxed is not None and boxed.strip():
        endpoint = len(boxed)
        previous = ''
        for index, token in enumerate(ids):
            current = engine.tok.decode(ids[:index + 1], skip_special_tokens=False,
                                        clean_up_tokenization_spaces=False)
            # Delay incomplete UTF8 byte prefixes; assign the completed unit's
            # sampled tokens together, rather than treating replacement chars as content.
            if current.endswith('\ufffd'):
                continue
            if len(previous) < endpoint and len(current) > len(previous):
                last_included = selected[-1] if selected else -1
                selected.extend(range(last_included + 1, index + 1))
                if len(current) > endpoint:
                    boundary_overlaps.append(index)
            previous = current
    likelihood = math.exp(sum(logprobs[i] for i in selected) / len(selected)) if selected else 0.
    engine.torch.cuda.synchronize()
    return {'ids': ids, 'tokens': len(ids), 'text': r'\boxed{' + text, 'generated_text': text,
            'stop_reason': reason, 'length_censored': reason == 'limit',
            'ms': 1000 * (time.perf_counter() - started), 'model_ms': engine.model_ms - before,
            'prefill_model_ms': prefill_ms, 'cached_prefix': initial is not None,
            'control_prefix_input_tokens': len(suffix), 'answer_prefix_hash': digest_ids(context),
            'answer_score': likelihood, 'answer_score_token_indices': selected,
            'answer_raw_token_logprobs': logprobs, 'answer_boundary_overlap_indices': boundary_overlaps,
            'score_scope': 'Raw geometric chosen-token likelihood on nonempty boxed content; boundary-overlap token included; invalid/missing box gets zero.',
            'cache': cache, 'logits': logits}
