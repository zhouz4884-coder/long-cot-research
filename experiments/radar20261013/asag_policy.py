"""Pure four-action state logic for the declared ASAG controlled adaptation.

No generation implementation or author reproduction is claimed by this file.
The eventual runner must pay for each probe, measure a scratch attention window,
retain all interventions, and declare the normalized answer-vector aggregation.
"""
import math


class ASAGState:
    def __init__(self, confidence_threshold=.95, entropy_change_threshold=-.1, maximum_jumps=1):
        assert 0 <= confidence_threshold <= 1 and math.isfinite(entropy_change_threshold)
        assert isinstance(maximum_jumps, int) and maximum_jumps >= 0
        self.confidence_threshold = confidence_threshold
        self.entropy_change_threshold = entropy_change_threshold
        self.maximum_jumps = maximum_jumps
        self.first_entropy = None
        self.jumps = 0

    def decide(self, confidence, entropy, trap):
        valid = (confidence is not None and entropy is not None and math.isfinite(confidence)
                 and math.isfinite(entropy) and 0 <= confidence <= 1 and entropy >= 0)
        if not valid:
            return {'action': 'CONTINUE', 'reason': 'unavailable_or_invalid_probe', 'delta_entropy': None}
        first = self.first_entropy is None
        if first:
            self.first_entropy = entropy
        delta = None if first or self.first_entropy == 0 else (entropy - self.first_entropy) / self.first_entropy
        high = confidence > self.confidence_threshold
        converged = delta is not None and delta < self.entropy_change_threshold
        if high and (first or converged):
            action, reason = 'STOP', 'first_high_confidence' if first else 'high_confidence_and_entropy_drop'
        elif confidence < self.confidence_threshold and converged:
            action, reason = 'INJECT', 'low_confidence_and_entropy_drop'
        elif delta is not None and delta > self.entropy_change_threshold and trap:
            if self.jumps < self.maximum_jumps:
                self.jumps += 1
                action, reason = 'JUMP', 'nonconverged_and_previous_action_has_more_mean_attention'
            else:
                action, reason = 'STOP', 'jump_budget_exhausted'
        else:
            action, reason = 'CONTINUE', ('undefined_ratio_zero_first_entropy' if not first and self.first_entropy == 0
                                           else 'no_published_strict_inequality_branch')
        return {'action': action, 'reason': reason, 'delta_entropy': delta,
                'first_entropy': self.first_entropy, 'jumps_used': self.jumps,
                'confidence_threshold': self.confidence_threshold,
                'entropy_change_threshold': self.entropy_change_threshold,
                'quality_labels_used': False}


def injected_probabilities(model_probabilities, answer_distribution, answer_weight=.05):
    """Eq7 convex probability mixture, returned as log-probabilities for sampling.

Do not add normalized probabilities directly to unnormalized model logits.
The mean-over-answer-step distribution must be declared by the future runner.
"""
    import torch
    assert 0 <= answer_weight <= 1 and model_probabilities.ndim == answer_distribution.ndim == 1
    assert model_probabilities.shape == answer_distribution.shape
    assert torch.isfinite(model_probabilities).all() and torch.isfinite(answer_distribution).all()
    assert (model_probabilities >= 0).all() and (answer_distribution >= 0).all()
    assert torch.isclose(model_probabilities.sum(), model_probabilities.new_tensor(1.), atol=1e-5, rtol=0)
    assert torch.isclose(answer_distribution.sum(), answer_distribution.new_tensor(1.), atol=1e-5, rtol=0)
    mixture = (1 - answer_weight) * model_probabilities + answer_weight * answer_distribution
    return mixture.clamp_min(torch.finfo(mixture.dtype).tiny).log()
