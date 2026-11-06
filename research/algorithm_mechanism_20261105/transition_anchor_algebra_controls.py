"""Tiny deterministic CPU algebra controls; no model or optimizer training.

Analytic counterexamples are specified before execution. One illustrative random
gradient matrix uses exactly the fixed seed 20261105, with no seed search.
"""

import hashlib
import json
import math
import random
from pathlib import Path

SEED = 20261105
OUT = Path(__file__).with_name("transition_anchor_algebra_controls.json")


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def mean(rows):
    return [sum(row[j] for row in rows)/len(rows) for j in range(len(rows[0]))]


def weighted(rows, weights):
    return [sum(weight*row[j] for weight, row in zip(weights, rows)) for j in range(len(rows[0]))]


def cosine(a, b):
    return dot(a, b)/(norm(a)*norm(b))


def softmax(scores, beta=1.0):
    shifted = [beta*(s-max(scores)) for s in scores]
    values = [math.exp(s) for s in shifted]
    return [value/sum(values) for value in values]


def kl_uniform(q):
    return sum(value*math.log(value*len(q)) for value in q if value > 0)


def summary(q):
    return {"q": q, "KL_q_uniform": kl_uniform(q),
            "Shannon_entropy": -sum(p*math.log(p) for p in q if p > 0),
            "ESS": 1/sum(p*p for p in q), "max_weight": max(q)}


def bisect_scalar(function, lo, hi, target):
    for _ in range(110):
        mid = (lo+hi)/2
        if function(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def calibrate_positive_beta(scores, delta):
    maxima = sum(value == max(scores) for value in scores)
    ceiling = math.log(len(scores)/maxima)
    if delta == 0:
        return {"status": "finite", "beta": 0.0, "q": softmax(scores, 0)}
    if delta < 0 or delta >= ceiling:
        return {"status": "no_finite_positive_beta", "KL_limit_beta_to_infinity": ceiling}
    high = 1.0
    while kl_uniform(softmax(scores, high)) < delta:
        high *= 2
    beta = bisect_scalar(lambda b: kl_uniform(softmax(scores, b)), 0, high, delta)
    return {"status": "finite", "beta": beta, "q": softmax(scores, beta)}


def main():
    rng = random.Random(SEED)
    token_gradients = [[rng.gauss(0, 1) for _ in range(3)] for _ in range(8)]
    anchors = {"U": mean(token_gradients), "A": mean(token_gradients[6:8]),
               "prop": mean(token_gradients[:2])}
    gram = {left: {right: dot(a, b) for right, b in anchors.items()} for left, a in anchors.items()}
    cosines = {left: {right: cosine(a, b) for right, b in anchors.items()} for left, a in anchors.items()}

    delta = .3
    p = bisect_scalar(lambda p: kl_uniform([p, (1-p)/2, (1-p)/2]), 1/3, 1, delta)
    a = bisect_scalar(lambda a: kl_uniform([a, a, 1-2*a]), 1/3, .5, delta)
    q1, q2 = [p, (1-p)/2, (1-p)/2], [a, a, 1-2*a]
    same_kl = {"target_KL": delta, "distribution_A": summary(q1), "distribution_B": summary(q2),
               "absolute_KL_difference": abs(kl_uniform(q1)-kl_uniform(q2))}
    score_scale = [1, 3, -2, 0]
    match1 = calibrate_positive_beta(score_scale, delta)
    match2 = calibrate_positive_beta([10*x+7 for x in score_scale], delta)

    # q=softmax(scores) is nonuniform. Token gradients are valid gradients of
    # smooth squared losses at zero. Their q-weighted vector is exactly zero
    # in real arithmetic, even though the independent anchor is nonzero.
    qzero = [.1, .3, .6]
    logs = [math.log(p) for p in qzero]
    center = dot(qzero, logs)
    zero_gradients = [[logs[i]-center, [-6, 0, 1][i]] for i in range(3)]
    ref = [1, 0]
    zero_scores = [dot(ref, g) for g in zero_gradients]
    zero_weights = softmax(zero_scores)
    zero_update = weighted(zero_gradients, zero_weights)

    # Equal Euclidean parameter step norms, opposite validation effects.
    c = .1
    validation_loss = lambda theta: .5*(theta-1)**2
    equal_norm = {"c": c, "initial_validation_loss": validation_loss(0),
                  "step_plus": {"step_norm": c, "actual_delta": validation_loss(c)-validation_loss(0),
                                "first_order_delta": -c, "remainder": .5*c*c},
                  "step_minus": {"step_norm": c, "actual_delta": validation_loss(-c)-validation_loss(0),
                                 "first_order_delta": c, "remainder": .5*c*c}}

    # The linear-utility optimum need not be the normalized-step optimum.
    # Two weights on the same KL sphere give G=(100,100) and G=(1,0).
    qa, qb = [.8, .2], [.2, .8]
    main_grads = [[133.0, 400/3], [-32.0, -100/3]]
    ga, gb = weighted(main_grads, qa), weighted(main_grads, qb)
    raw_vs_normalized = {
        "q_A": qa, "q_B": qb, "KL_A": kl_uniform(qa), "KL_B": kl_uniform(qb),
        "token_gradients": main_grads, "anchor_gradient": [1, 0],
        "G_A": ga, "G_B": gb,
        "raw_alignment_A": ga[0], "raw_alignment_B": gb[0],
        "unit_alignment_A": ga[0]/norm(ga), "unit_alignment_B": gb[0]/norm(gb),
        "beta_for_linear_utility_maximizer_q_A": math.log(4)/165,
    }

    # LoRA A=diag(1,10), B=(0,0), alpha/r=1. Two equal-norm delta B vectors
    # from the same initialization yield tenfold different effective W changes.
    lora = {"A": [[1, 0], [0, 10]], "B": [[0, 0]], "alpha_over_r": 1,
            "step_B_1": {"delta_B": [c, 0], "parameter_step_norm": c, "effective_delta_W": [c, 0], "effective_norm": c},
            "step_B_2": {"delta_B": [0, c], "parameter_step_norm": c, "effective_delta_W": [0, 10*c], "effective_norm": 10*c}}

    # A correct-propagation-only loss rewards always adopting a revision.
    # The W control requires the opposite action; improvement is not protected.
    softplus = lambda x: max(x, 0)+math.log1p(math.exp(-abs(x)))
    theta0 = 0.0
    step = .1
    w_control = {"theta0": theta0, "delta_theta": step,
                 "correct_prop_loss_before": softplus(-theta0),
                 "correct_prop_loss_after": softplus(-(theta0+step)),
                 "reject_wrong_revision_loss_before": softplus(theta0),
                 "reject_wrong_revision_loss_after": softplus(theta0+step)}

    fd = []
    g = anchors["prop"]
    exact = [dot(g, v) for v in token_gradients]
    for epsilon in [1e-2, 1e-4, 1e-6]:
        observed = [(.5*dot(v, v)-.5*dot([v[j]-epsilon*g[j] for j in range(3)],
                                           [v[j]-epsilon*g[j] for j in range(3)]))/epsilon
                    for v in token_gradients]
        fd.append({"epsilon": epsilon, "max_abs_error": max(abs(x-y) for x,y in zip(observed, exact)),
                   "analytic_common_error": .5*epsilon*dot(g,g)})

    result = {
        "scope": "CPU algebra controls only; no language model, GPU, training, seed sweep or empirical performance claim",
        "fixed_random_seed": SEED,
        "analytic_collinear_anchors": {"g_U": [1, 0], "g_A": [1, 0], "g_prop": [1, 0], "all_pairwise_cosines": 1},
        "random_shared_gradient_control": {"token_gradients": token_gradients, "anchors": anchors, "Gram": gram, "cosines": cosines},
        "same_KL_different_ESS": same_kl,
        "same_KL_removes_positive_affine_score_scaling": {
            "scores": score_scale, "scaled_scores": [10*x+7 for x in score_scale],
            "base": match1, "scaled": match2,
            "max_abs_q_difference": max(abs(x-y) for x,y in zip(match1["q"], match2["q"]))},
        "unreachable_softmax_KL_cases": {
            "constant_scores_delta_point3": calibrate_positive_beta([1,1,1], .3),
            "two_maxima_delta_point5": calibrate_positive_beta([1,1,0], .5),
            "two_maxima_global_simplex_max_KL": math.log(3)},
        "nonuniform_q_zero_aggregate_gradient": {"token_gradients": zero_gradients, "reference_gradient": ref,
            "scores": zero_scores, "q": zero_weights, "KL": kl_uniform(zero_weights),
            "aggregate_gradient": zero_update, "aggregate_norm": norm(zero_update),
            "normalization_threshold": 1e-12, "norm_matched_action": "SKIP_UNDEFINED_ZERO_DIRECTION"},
        "same_parameter_norm_opposite_validation_changes": equal_norm,
        "linear_utility_optimum_not_normalized_step_optimum": raw_vs_normalized,
        "same_LoRA_parameter_norm_different_effective_changes": lora,
        "correct_prop_anchor_does_not_protect_W": w_control,
        "quadratic_finite_difference_control": fd,
    }
    checks = {
        "same_KL": same_kl["absolute_KL_difference"] < 1e-12,
        "different_ESS": abs(summary(q1)["ESS"]-summary(q2)["ESS"]) > 1e-3,
        "score_scale_calibration_invariant": result["same_KL_removes_positive_affine_score_scaling"]["max_abs_q_difference"] < 1e-12,
        "zero_update_norm_guard": norm(zero_update) < 1e-12,
        "opposite_loss_changes": equal_norm["step_plus"]["actual_delta"] < 0 < equal_norm["step_minus"]["actual_delta"],
        "linear_vs_normalized_ranking_reverses": ga[0] > gb[0] and ga[0]/norm(ga) < gb[0]/norm(gb),
        "prop_improves_but_W_worsens": w_control["correct_prop_loss_after"] < w_control["correct_prop_loss_before"] and w_control["reject_wrong_revision_loss_after"] > w_control["reject_wrong_revision_loss_before"],
    }
    result["algebra_checks"] = checks
    if not all(checks.values()):
        raise AssertionError(checks)
    result["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "checks": checks,
                      "same_KL_distributions": same_kl,
                      "anchor_cosines": cosines,
                      "zero_update_norm": norm(zero_update),
                      "W_loss_changes": {"prop": w_control["correct_prop_loss_after"]-w_control["correct_prop_loss_before"],
                                          "W": w_control["reject_wrong_revision_loss_after"]-w_control["reject_wrong_revision_loss_before"]}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
