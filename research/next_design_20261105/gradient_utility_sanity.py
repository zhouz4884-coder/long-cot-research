"""CPU float64 mathematical control; random shared-parameter causal RNN, no LLM claim.

Checks directional token utility against exact parameter-gradient inner products,
and separates causal activation gradients from shared-parameter gradient utility.
The independent data splits and seed are fixed, not selected for positive results.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.utils import parameters_to_vector, vector_to_parameters


class CausalRNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(4, 7)
        self.recurrent = nn.Linear(7, 7, bias=False)
        self.output = nn.Linear(7, 5)

    def forward(self, inputs, labels):
        hidden = torch.zeros(7, dtype=inputs.dtype)
        states, losses = [], []
        for x, target in zip(inputs, labels):
            hidden = torch.tanh(self.input(x) + self.recurrent(hidden))
            states.append(hidden)
            losses.append(F.cross_entropy(self.output(hidden).unsqueeze(0), target.unsqueeze(0)))
        return torch.stack(losses), states


def flat_grad(loss, model, retain_graph=False):
    return torch.cat([x.flatten() for x in torch.autograd.grad(loss, model.parameters(), retain_graph=retain_graph)])


def kl_matched_weights(scores, delta=0.05):
    n = len(scores)
    def at(beta):
        logq = (beta * scores).log_softmax(0)
        q = logq.exp()
        return q, (q * (logq + torch.log(torch.tensor(float(n))))).sum().item()
    lo, hi = 0.0, 1.0
    while at(hi)[1] < delta and hi < 1e12:
        hi *= 2
    for _ in range(90):
        mid = (lo + hi) / 2
        if at(mid)[1] < delta:
            lo = mid
        else:
            hi = mid
    q, kl = at((lo + hi) / 2)
    return q.detach(), kl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Preserve previous evidence'
    started = time.perf_counter()
    torch.set_default_dtype(torch.float64)
    torch.set_num_threads(1)
    torch.manual_seed(20261105)
    model = CausalRNN().double()
    generator = torch.Generator().manual_seed(20261106)
    datasets = [(torch.randn((8, 4), generator=generator), torch.randint(0, 5, (8,), generator=generator)) for _ in range(3)]
    base_parameters = parameters_to_vector(model.parameters()).detach().clone()
    anchor_position = 3

    # One shared reference forward, but two distinct gradient queries.
    reference, states = model(*datasets[1])
    g_uniform = flat_grad(reference.mean(), model, retain_graph=True).detach()
    g_anchor = flat_grad(reference[anchor_position], model, retain_graph=True).detach()
    later_activation = torch.autograd.grad(reference[anchor_position], states[anchor_position + 1:], allow_unused=True)
    assert all(x is None or torch.count_nonzero(x) == 0 for x in later_activation)

    main_losses, _ = model(*datasets[0])
    token_gradients = torch.stack([flat_grad(loss, model, retain_graph=True).detach() for loss in main_losses])
    exact = {'uniform_reference': token_gradients @ g_uniform, 'answer_like_anchor': token_gradients @ g_anchor}
    base_losses = main_losses.detach()
    estimates, errors = {}, {}
    epsilon = 1e-6
    for name, direction in [('uniform_reference', g_uniform), ('answer_like_anchor', g_anchor)]:
        with torch.no_grad():
            vector_to_parameters(base_parameters - epsilon * direction, model.parameters())
            probe, _ = model(*datasets[0])
            estimate = (base_losses - probe) / epsilon
            vector_to_parameters(base_parameters.clone(), model.parameters())
        estimates[name] = estimate
        errors[name] = float((estimate - exact[name]).abs().max())
        assert errors[name] < 1e-5

    # Later parameter losses can align with an earlier anchor even when the
    # anchor's activation gradient to later states is structurally zero.
    ref_again, _ = model(*datasets[1])
    later_parameter_utilities = [float(torch.dot(flat_grad(ref_again[t], model, retain_graph=True), g_anchor))
                                 for t in range(anchor_position + 1, 8)]
    assert any(abs(x) > 1e-10 for x in later_parameter_utilities)

    validation, _ = model(*datasets[2])
    validation_base = float(validation.mean().detach())
    g_validation = flat_grad(validation.mean(), model).detach()
    q_u, kl_u = kl_matched_weights(exact['uniform_reference'])
    q_a, kl_a = kl_matched_weights(exact['answer_like_anchor'])
    weights = {'uniform_tokens': torch.ones(8) / 8, 'full_loss_utility': q_u, 'anchor_utility': q_a}
    updates = {}
    step_norm = 1e-3
    for name, q in weights.items():
        gradient = (q[:, None] * token_gradients).sum(0)
        displacement = -step_norm * gradient / gradient.norm()
        with torch.no_grad():
            vector_to_parameters(base_parameters + displacement, model.parameters())
            after, _ = model(*datasets[2])
            actual = float(after.mean()) - validation_base
            vector_to_parameters(base_parameters.clone(), model.parameters())
        updates[name] = {'weights': q.tolist(), 'update_l2_norm': float(displacement.norm()),
                         'predicted_validation_nll_delta': float(torch.dot(g_validation, displacement)),
                         'actual_validation_nll_delta': actual,
                         'weight_after_anchor_mass': float(q[anchor_position + 1:].sum())}
    assert torch.equal(parameters_to_vector(model.parameters()).detach(), base_parameters)
    report = {
        'scope': 'Random causal RNN mathematical control; no learned LLM, semantic labels, training performance or VCORE reproduction',
        'passed': True, 'device': 'cpu', 'dtype': 'float64', 'torch': torch.__version__, 'python': platform.python_version(),
        'seed': 20261105, 'main_probe_validation_are_disjoint_fixed_random_inputs': True,
        'reference_forward_count': 1, 'separate_reference_gradient_queries': 2,
        'exact_token_gradient_queries_for_toy_oracle': 8, 'perturbed_main_forward_count': 2,
        'finite_difference_epsilon': epsilon, 'finite_difference_max_abs_error': errors,
        'uniform_anchor_cosine': float(F.cosine_similarity(g_uniform, g_anchor, dim=0)),
        'late_activation_gradient_zero': True, 'late_shared_parameter_utilities': later_parameter_utilities,
        'kl_target': 0.05, 'kl_observed': [kl_u, kl_a], 'norm_matched_one_step': updates,
        'parameters_restored_exactly': True,
        'limitations': ['A local first-order utility is not a semantic causal contribution.',
                        'The one-step check uses exact temporary SGD displacements, not an Adam/LoRA implementation.',
                        'Post-anchor positions are temporal labels, not evidence that those tokens are redundant.',
                        'Two anchors need separate directional information; the shared forward is not one scalar backward for both.'],
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'elapsed_seconds': time.perf_counter() - started,
    }
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'finite_difference_max_abs_error': errors,
                      'late_shared_parameter_utilities': later_parameter_utilities,
                      'norm_matched_validation_deltas': {n: d['actual_validation_nll_delta'] for n, d in updates.items()},
                      'elapsed_seconds': report['elapsed_seconds']}))


if __name__ == '__main__':
    main()
