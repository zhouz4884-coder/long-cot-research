"""Paired teacher-forced one-step gradient diagnostic in a fixed parameter subspace."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from time import perf_counter_ns, process_time_ns

import torch
from torch import nn
from torch.nn import functional as F


ROLES = ("E", "W", "C")
ANCHORS = ("U", "A", "T")


class NumericalFailure(ValueError):
    pass


@dataclass(frozen=True)
class Sequence:
    ids: tuple[int, ...]
    target_start: int
    answer_positions: tuple[int, ...] = ()

    @property
    def targets(self):
        return len(self.ids)-self.target_start


@dataclass(frozen=True)
class Pair:
    correct: Sequence
    alternative: Sequence

    @property
    def matched_length(self):
        return self.correct.targets == self.alternative.targets


@dataclass(frozen=True)
class Example:
    case_id: str
    problem_id: str
    role: str
    teacher: Sequence | None
    pair: Pair | None


@dataclass(frozen=True)
class Settings:
    epsilons: tuple[float, float]
    eta: float
    kl: float
    match_norm: float | None = None
    max_probe_relative_l2: float = 0.15
    min_probe_cosine: float = 0.98
    zero_norm: float = 1e-12

    def validate(self):
        values = (*self.epsilons, self.eta, self.kl, self.max_probe_relative_l2, self.min_probe_cosine, self.zero_norm)
        if len(self.epsilons) != 2 or not all(math.isfinite(x) for x in values):
            raise ValueError("Expected two finite probe steps and finite one-step settings")
        if not (0 < self.epsilons[0] < self.epsilons[1] and self.eta > 0 and self.kl >= 0 and self.zero_norm >= 0
                and self.max_probe_relative_l2 >= 0 and -1 <= self.min_probe_cosine <= 1):
            raise ValueError("Invalid probe, update, or matched-KL settings")
        if self.match_norm is not None and (not math.isfinite(self.match_norm) or self.match_norm <= 0):
            raise ValueError("Explicit matched update norm must be finite and positive")


def _ids(raw):
    if type(raw) not in (list, tuple) or not raw or any(type(x) is not int or x < 0 for x in raw):
        raise ValueError("Expected a nonempty sequence of exact nonnegative token IDs")
    return tuple(raw)


def _sequence(ids, start, answer=()):
    ids = _ids(ids)
    if type(start) is not int or not 1 <= start < len(ids):
        raise ValueError("Target start must follow a nonempty causal context")
    if (type(answer) not in (list, tuple) or any(type(x) is not int or not start <= x < len(ids) for x in answer)
            or len(set(answer)) != len(answer)):
        raise ValueError("Answer mask uses distinct predicted-token indices in the teacher response")
    return Sequence(ids, start, tuple(answer))


def _text_sequence(tokenizer, prefix, response, answer_span=None):
    if tokenizer is None or type(prefix) is not str or type(response) is not str or not prefix or not response:
        raise ValueError("Text input requires a fast tokenizer and nonempty exact prefix/response")
    raw = tokenizer(prefix+response, add_special_tokens=False, return_offsets_mapping=True)
    offsets = tuple(tuple(x) for x in raw["offset_mapping"])
    boundary = len(prefix)
    if any(a < boundary < b for a, b in offsets):
        raise ValueError("A token crosses the frozen prompt/response text boundary")
    target = [i for i, (a, b) in enumerate(offsets) if a >= boundary and b > a]
    if not target or target != list(range(target[0], len(offsets))):
        raise ValueError("The tokenizer did not produce a contiguous teacher response")
    answer = []
    if answer_span is not None:
        if (type(answer_span) not in (list, tuple) or len(answer_span) != 2
                or any(type(x) is not int for x in answer_span) or not 0 <= answer_span[0] < answer_span[1] <= len(response)):
            raise ValueError("Invalid response-relative answer span")
        start, stop = (x+boundary for x in answer_span)
        for i in target:
            a, b = offsets[i]
            if a < stop and start < b:
                if not start <= a < b <= stop:
                    raise ValueError("A token crosses the frozen answer boundary")
                answer.append(i)
    return _sequence(raw["input_ids"], target[0], answer)


def _pair(raw, tokenizer):
    if type(raw) is not dict:
        raise ValueError("Pair must specify one shared prefix and both continuations")
    if "prefix_ids" in raw:
        prefix = _ids(raw["prefix_ids"])
        correct, alternative = (_sequence(prefix+_ids(raw[key]), len(prefix)) for key in ("correct_ids", "alternative_ids"))
    else:
        correct = _text_sequence(tokenizer, raw["prefix"], raw["correct"])
        alternative = _text_sequence(tokenizer, raw["prefix"], raw["alternative"])
    if correct.ids[:correct.target_start] != alternative.ids[:alternative.target_start]:
        raise ValueError("Correct and alternative have different tokenized prefixes")
    if correct.ids == alternative.ids:
        raise ValueError("Correct and alternative continuations are token-identical")
    return Pair(correct, alternative)


def load_packet(data, tokenizer=None, *, probe_only=False):
    """Validate exact tokenized data, or tokenize explicitly bounded text as a fallback."""
    if type(data) is not dict or (probe_only and "H" in data):
        raise ValueError("Probe-only runs require an input packet without H")
    split_names = ("B", "Bprime") if probe_only else ("B", "Bprime", "H")
    splits, previous_problems, all_case_ids = {}, set(), set()
    mismatched_pairs = []
    for name in split_names:
        raw = data[name]
        if type(raw) is not list or not raw:
            raise ValueError(f"Missing nonempty split {name}")
        within, examples = set(), []
        for row in raw:
            case, problem, role = (row[k] for k in ("case_id", "problem_id", "role"))
            if (type(case) is not str or not case or case in all_case_ids or type(problem) is not str or not problem
                    or role not in ROLES or problem in previous_problems
                    or (problem in within and not (name == "H" and data.get("allow_h_variants") is True))):
                raise ValueError("Expected explicit unique cases, E/W/C roles, and problem-isolated splits")
            all_case_ids.add(case)
            within.add(problem)
            teacher = None
            if name != "H":
                if "input_ids" in row:
                    teacher = _sequence(row["input_ids"], row["target_start"], row.get("answer_positions", ()))
                else:
                    teacher = _text_sequence(tokenizer, row["prefix"], row["response"], row.get("answer_span"))
            pair = None if name == "B" else _pair(row["pair"], tokenizer)
            if pair is not None and not pair.matched_length:
                mismatched_pairs.append({"split": name, "case_id": case, "role": role,
                                         "correct_tokens": pair.correct.targets, "alternative_tokens": pair.alternative.targets})
            examples.append(Example(case, problem, role, teacher, pair))
        previous_problems.update(within)
        if {x.role for x in examples} != set(ROLES):
            raise ValueError(f"Split {name} must contain all E/W/C roles")
        splits[name] = tuple(examples)
    if not all(any(x.teacher.answer_positions for x in splits["Bprime"] if x.role == role) for role in ROLES):
        raise ValueError("Answer mask has an unavailable E/W/C role")
    return splits, mismatched_pairs


def _norm(x):
    return float(torch.linalg.vector_norm(x.double()).item())


def _dot(x, y):
    return float(torch.dot(x.double(), y.double()).item())


def _cos(x, y):
    scale = _norm(x)*_norm(y)
    return None if scale == 0 else _dot(x, y)/scale


def _finite(x):
    return bool(torch.isfinite(x).all().item())


class Parameters:
    """Flatten only the declared trainable tensors, with exact value restoration."""

    def __init__(self, model):
        named = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
        if not named:
            raise ValueError("No trainable parameter subspace")
        self.names, self.params = zip(*named, strict=True)
        self.dtype, self.device = self.params[0].dtype, self.params[0].device
        if any(p.dtype != self.dtype or p.device != self.device or not p.is_floating_point() for p in self.params):
            raise ValueError("Expected a single floating dtype/device for trainable parameters")
        self.sizes = tuple(p.numel() for p in self.params)
        self.base = self.flatten(self.params).clone()
        self.restores = 0

    def flatten(self, values):
        return torch.cat([x.detach().reshape(-1) for x in values])

    def vector(self):
        return self.flatten(self.params)

    def zero(self):
        return torch.zeros_like(self.base)

    @torch.no_grad()
    def install(self, vector):
        for p, flat in zip(self.params, vector.split(self.sizes), strict=True):
            p.copy_(flat.reshape_as(p))

    def restored(self):
        return bool(torch.equal(self.vector().view(torch.uint8), self.base.view(torch.uint8)))

    def restore(self):
        self.install(self.base)
        self.restores += 1
        if not self.restored():
            raise RuntimeError("Trainable parameter bytes did not restore exactly")

    def sha256(self):
        return sha256(self.vector().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()


class Ledger:
    def __init__(self, device):
        self.device = device
        self.rows = []

    def start(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        return perf_counter_ns(), process_time_ns()

    def add(self, began, **fields):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        self.rows.append({**fields, "wall_ns": perf_counter_ns()-began[0], "process_cpu_ns": process_time_ns()-began[1]})

    def report(self):
        fwd = [x for x in self.rows if x["kind"] == "FORWARD"]
        bwd = [x for x in self.rows if x["kind"] == "BACKWARD"]
        return {"forward_calls": len(fwd), "backward_calls": len(bwd),
                "forward_input_tokens": sum(x["input_tokens"] for x in fwd),
                "forward_teacher_targets": sum(x["teacher_targets"] for x in fwd),
                "forward_causal_position_pairs": sum(x["causal_position_pairs"] for x in fwd),
                "wall_ns": sum(x["wall_ns"] for x in self.rows), "rows": self.rows}


class Diagnostic:
    def __init__(self, model):
        self.model = model.eval()
        self.p = Parameters(model)
        self.ledger = Ledger(self.p.device)

    def token_losses(self, example, sequence, stage, branch="teacher"):
        began = self.ledger.start()
        ids = torch.tensor(sequence.ids, dtype=torch.long, device=self.p.device).unsqueeze(0)
        logits = self.model(input_ids=ids, use_cache=False).logits
        active = logits[0, sequence.target_start-1:-1, :]
        if active.dtype in (torch.float16, torch.bfloat16):
            active = active.float()
        loss = F.cross_entropy(active, ids[0, sequence.target_start:], reduction="none")
        n = len(sequence.ids)
        self.ledger.add(began, kind="FORWARD", stage=stage, case_id=example.case_id, role=example.role,
                        branch=branch, grad_enabled=torch.is_grad_enabled(), input_tokens=n, teacher_targets=sequence.targets,
                        causal_position_pairs=n*(n+1)//2)
        if not _finite(loss):
            raise NumericalFailure(f"Nonfinite token CE in {stage}/{example.case_id}/{branch}")
        return loss

    def gradient(self, scalar, example, stage, branch="teacher", *, retain_graph=False):
        began = self.ledger.start()
        grads = torch.autograd.grad(scalar, self.p.params, allow_unused=True, retain_graph=retain_graph)
        values = [torch.zeros_like(p) if x is None else x for p, x in zip(self.p.params, grads, strict=True)]
        vector = self.p.flatten(values)
        self.ledger.add(began, kind="BACKWARD", stage=stage, case_id=example.case_id, role=example.role, branch=branch,
                        unused_parameters=sum(x is None for x in grads))
        if not _finite(vector):
            raise NumericalFailure(f"Nonfinite gradient in {stage}/{example.case_id}/{branch}")
        return vector

    @torch.no_grad()
    def train_losses(self, examples, stage):
        return torch.cat([self.token_losses(x, x.teacher, stage).detach().double().cpu() for x in examples])

    def train_gradient(self, examples, weights, stage):
        vector = self.p.zero()
        start = 0
        for x in examples:
            n = x.teacher.targets
            losses = self.token_losses(x, x.teacher, stage)
            weight = weights[start:start+n].detach().to(device=losses.device, dtype=losses.dtype)
            vector.add_(self.gradient(torch.dot(losses, weight), x, stage))
            start += n
        if start != len(weights):
            raise ValueError("Weighted train gradient does not match the exact support")
        if not _finite(vector):
            raise NumericalFailure(f"Nonfinite aggregate train gradient in {stage}")
        return vector

    def ce_direction(self, examples, anchor):
        choose_answer = anchor == "A"
        count = sum(len(x.teacher.answer_positions) if choose_answer else x.teacher.targets for x in examples)
        if count <= 0:
            raise ValueError("No effective CE targets")
        direction = self.p.zero()
        for x in examples:
            if choose_answer and not x.teacher.answer_positions:
                continue
            v = self.token_losses(x, x.teacher, "Bprime:"+anchor)
            if choose_answer:
                v = v[[j-x.teacher.target_start for j in x.teacher.answer_positions]]
            direction.add_(self.gradient(v.sum()/count, x, "Bprime:"+anchor))
        if not _finite(direction):
            raise NumericalFailure(f"Nonfinite aggregate CE reference direction {anchor}")
        return direction, count

    def pair_roles(self, examples, stage, *, gradients):
        values, directions, samples = {}, {}, {}
        for role in ROLES:
            rows = [x for x in examples if x.role == role and x.pair.matched_length]
            if not rows:
                raise ValueError(f"No matched-length primary pair for {stage}/{role}")
            sums = [0.0, 0.0]
            case_values = []
            vec = self.p.zero() if gradients else None
            samples[role] = len(rows)
            for x in rows:
                scores = []
                for index, (branch, sequence, sign) in enumerate((("correct", x.pair.correct, 1), ("alternative", x.pair.alternative, -1))):
                    loss = self.token_losses(x, sequence, stage, branch).sum()
                    value = float(loss.detach().item())
                    if not math.isfinite(value):
                        raise NumericalFailure(f"Nonfinite sequence NLL in {stage}/{x.case_id}/{branch}")
                    scores.append(-value)
                    sums[index] += value
                    if gradients:
                        vec.add_(self.gradient(loss*(sign/len(rows)), x, stage, branch))
                margin = scores[0]-scores[1]
                case_values.append({"case_id": x.case_id, "problem_id": x.problem_id, "role": role,
                                    "correct_target_tokens": x.pair.correct.targets, "alternative_target_tokens": x.pair.alternative.targets,
                                    "correct_logprob": scores[0], "alternative_logprob": scores[1],
                                    "margin": margin, "per_target_token_margin": margin/x.pair.correct.targets})
            a, b = (v/len(rows) for v in sums)
            values[role] = {"loss": a-b, "mean_correct_logprob": -a, "mean_alternative_logprob": -b, "cases": case_values}
            if gradients:
                if not _finite(vec):
                    raise NumericalFailure(f"Nonfinite aggregate pair gradient in {stage}/{role}")
                directions[role] = vec
        return values, directions, samples

    def probe(self, examples, direction, eps, stage, zero):
        norm = _norm(direction)
        if not math.isfinite(norm) or norm <= zero:
            raise NumericalFailure("Reference direction is nonfinite or too small")
        unit = direction / norm
        deltas, losses = [], []
        try:
            for sign in (1, -1):
                self.p.install(self.p.base+unit*(sign*eps))
                deltas.append(self.p.vector()-self.p.base)
                losses.append(self.train_losses(examples, stage+(":plus" if sign == 1 else ":minus")))
                self.p.restore()
        finally:
            if not self.p.restored():
                self.p.restore()
        values = (losses[0]-losses[1])*(norm/(2*eps))
        if not _finite(values):
            raise NumericalFailure("Nonfinite finite-difference token scores")
        detail = {"epsilon_unit_parameter_step": eps, "reference_norm": norm, "positive_actual_norm": _norm(deltas[0]),
                  "negative_actual_norm": _norm(deltas[1]), "perturbation_asymmetry_norm": _norm(deltas[0]+deltas[1]),
                  "scores": values.tolist()}
        return values, detail

    def token_oracle(self, examples, direction, limit=32):
        """Test-only exact per-token VJPs. A long real run must not call this."""
        if sum(x.teacher.targets for x in examples) > limit:
            raise ValueError("Tiny oracle token cap exceeded")
        results = []
        for x in examples:
            loss = self.token_losses(x, x.teacher, "tiny_oracle")
            for i, scalar in enumerate(loss):
                v = self.gradient(scalar, x, "tiny_oracle", retain_graph=i+1 < len(loss))
                results.append(_dot(v, direction))
        return torch.tensor(results, dtype=torch.float64)


def match_kl(scores, target):
    """Fit detached positive-temperature Gibbs weights on one exact support."""
    scores = scores.detach().double().cpu()
    if scores.ndim != 1 or not scores.numel() or not _finite(scores) or not math.isfinite(target) or target < 0:
        raise ValueError("Invalid matched-KL support or target")
    n = len(scores)
    prior_log = math.log(n)
    span = float((scores.max()-scores.min()).item())
    tied = int((scores == scores.max()).sum().item())
    cap = math.log(n/tied)
    if target == 0:
        return torch.full((n,), 1/n, dtype=torch.float64), {"status": "MATCHED", "target": target, "beta": 0.0,
                                                                    "support": n, "top_ties": tied, "finite_kl_supremum": cap}
    if span == 0 or target >= cap:
        return None, {"status": "UNATTAINABLE_FINITE_TEMPERATURE", "target": target, "support": n,
                      "top_ties": tied, "finite_kl_supremum": cap}
    normalized = (scores-scores.max())/span

    def at(beta):
        logq = torch.log_softmax(beta*normalized, dim=0)
        q = logq.exp()
        return q, float(torch.dot(q, logq+prior_log).item())

    lo, hi = 0.0, 1.0
    for _ in range(64):
        if at(hi)[1] >= target:
            break
        hi *= 2
    else:
        return None, {"status": "FINITE_TEMPERATURE_BRACKET_FAILED", "target": target, "support": n,
                      "top_ties": tied, "finite_kl_supremum": cap}
    for _ in range(72):
        mid = (lo+hi)/2
        if at(mid)[1] < target:
            lo = mid
        else:
            hi = mid
    beta = (lo+hi)/2
    q, measured = at(beta)
    return q.detach(), {"status": "MATCHED", "target": target, "actual": measured, "beta": beta/span,
                        "support": n, "top_ties": tied, "finite_kl_supremum": cap, "score_span": span}


def weight_summary(weights, train):
    selected = weights[weights > 0]
    entropy = -float(torch.dot(selected, selected.log()).item())
    mass = {r: 0.0 for r in ROLES}
    cursor = 0
    for x in train:
        n = x.teacher.targets
        mass[x.role] += float(weights[cursor:cursor+n].sum().item())
        cursor += n
    return {"entropy": entropy, "kl_from_uniform": math.log(len(weights))-entropy,
            "effective_sample_size": 1/float(torch.dot(weights, weights).item()), "max_weight": float(weights.max().item()),
            "role_mass": mass, "weights": weights.tolist()}


def vector_summary(parameters, vector):
    groups = {}
    for name, chunk in zip(parameters.names, vector.split(parameters.sizes), strict=True):
        key = "adapter_A" if name.endswith(".adapter_a") else "adapter_B" if name.endswith(".adapter_b") else "other"
        groups.setdefault(key, []).append(chunk)
    return {"norm": _norm(vector),
            "group_norms": {key: _norm(torch.cat(chunks)) for key, chunks in groups.items()}}


def _step(diagnostic, holdout, reference, h_gradient, gradient, step_scale, stage):
    p = diagnostic.p
    intended = -gradient*step_scale
    if not _finite(intended):
        return {"status": "NONFINITE_UPDATE"}
    try:
        p.install(p.base+intended)
        actual = p.vector()-p.base
        actual_norm = _norm(actual)
        if not _finite(actual):
            return {"status": "NONFINITE_INSTALLED_UPDATE"}
        if actual_norm == 0:
            current, status = reference, "ZERO_UPDATE_REUSED_BASELINE"
        else:
            with torch.no_grad():
                current, _, _ = diagnostic.pair_roles(holdout, stage, gradients=False)
            status = "EVALUATED"
        by_role = {}
        for role in ROLES:
            measured = current[role]["loss"]-reference[role]["loss"]
            linear = _dot(h_gradient[role], actual)
            by_role[role] = {"before": reference[role], "after": current[role], "delta_loss": measured,
                             "linear_delta_loss": linear, "residual": measured-linear, "delta_margin": -measured}
        mean = {field: sum(by_role[role][field] for role in ROLES)/len(ROLES)
                for field in ("delta_loss", "linear_delta_loss", "residual", "delta_margin")}
        return {"status": status, "step_scale": step_scale, "nominal_update_norm": _norm(intended),
                "actual_update_norm": actual_norm, "install_rounding_error_norm": _norm(actual-intended),
                "by_role": by_role, "equal_role_mean": mean}
    except NumericalFailure as error:
        return {"status": "NONFINITE_HOLDOUT_LOSS", "reason": str(error)}
    finally:
        p.restore()


def run_diagnostic(model, splits, mismatched_pairs, settings, *, probe_only=False):
    """Compute U/A/T directions and complete one-step branches from one exact base."""
    settings.validate()
    started = perf_counter_ns()
    missing = [(name, role) for name in ("Bprime",) if name in splits for role in ROLES
               if not any(x.role == role and x.pair.matched_length for x in splits[name])]
    if not probe_only:
        missing += [("H", role) for role in ROLES if not any(x.role == role and x.pair.matched_length for x in splits["H"])]
    if missing:
        return {"status": "INSUFFICIENT_MATCHED_ROLE_PAIRS", "missing_roles": missing,
                "excluded_length_mismatches": mismatched_pairs, "settings": asdict(settings)}

    d = Diagnostic(model)
    p = d.p
    if p.device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(p.device)
    origin = p.sha256()
    train, reference = splits["B"], splits["Bprime"]
    n = sum(x.teacher.targets for x in train)
    labels = [{"case_id": x.case_id, "role": x.role, "target_start": x.teacher.target_start,
               "target_count": x.teacher.targets} for x in train]
    if settings.kl > math.log(n):
        raise ValueError("KL target exceeds the whole exact support")

    reports, q_weights, directions, branch_reports = {}, {}, {}, {}
    gram, cosine, failure = None, None, None
    baseline = zero_step = repeat_initial = heldout_count = match_norm = None
    unchanged_hashes = {}
    try:
        for anchor in ("U", "A"):
            directions[anchor], count = d.ce_direction(reference, anchor)
            reports[anchor] = {"reference_ce_targets": count}
        t_values, t_roles, t_samples = d.pair_roles(reference, "Bprime:T", gradients=True)
        directions["T"] = torch.stack([t_roles[r] for r in ROLES]).mean(dim=0)
        reports["T"] = {"reference_pair_by_role": t_values, "matched_pair_count_by_role": t_samples,
                        "role_direction": {r: vector_summary(p, t_roles[r]) for r in ROLES}}
        del t_roles

        gram = {j: {k: _dot(directions[j], directions[k]) for k in ANCHORS} for j in ANCHORS}
        cosine = {j: {k: _cos(directions[j], directions[k]) for k in ANCHORS} for j in ANCHORS}
        q_weights["uniform"] = torch.full((n,), 1/n, dtype=torch.float64)
        for anchor in ANCHORS:
            info = reports[anchor]
            direction = directions[anchor]
            if not _finite(direction):
                info["status"] = "NONFINITE_REFERENCE_DIRECTION"
                continue
            info["reference_direction"] = vector_summary(p, direction)
            if info["reference_direction"]["norm"] <= settings.zero_norm:
                info["status"] = "ZERO_REFERENCE_DIRECTION"
                continue
            low, a = d.probe(train, direction, settings.epsilons[0], f"B:probe:{anchor}:small", settings.zero_norm)
            high, b = d.probe(train, direction, settings.epsilons[1], f"B:probe:{anchor}:large", settings.zero_norm)
            scale = max(_norm(low), _norm(high))
            relative = _norm(low-high)/scale if scale else None
            alignment = _cos(low, high)
            info.update(probes=[a, b], probe_relative_l2=relative, probe_cosine=alignment)
            if (relative is None or alignment is None or relative > settings.max_probe_relative_l2
                    or alignment < settings.min_probe_cosine):
                info["status"] = "NUMERICAL_PROBE_DISAGREEMENT"
                continue
            q, fit = match_kl(low, settings.kl)
            info["kl_calibration"] = fit
            if q is None:
                info["status"] = "UNMATCHED_KL"
                continue
            q_weights[anchor] = q
            info["status"] = "READY"

        if not probe_only:
            if not p.restored():
                raise RuntimeError("Holdout baseline did not start at the exact parameter snapshot")
            holdout = splits["H"]
            unchanged_hashes["baseline"] = p.sha256()
            baseline, h_gradient, heldout_count = d.pair_roles(holdout, "H:baseline", gradients=True)
            unchanged_hashes["zero_step"] = p.sha256()
            with torch.no_grad():
                zero_step, _, _ = d.pair_roles(holdout, "H:zero_step", gradients=False)
            uniform = d.train_gradient(train, q_weights["uniform"], "B:weighted:uniform")
            match_norm = settings.match_norm
            if match_norm is None:
                match_norm = settings.eta*_norm(uniform)
            for arm in ("uniform", *ANCHORS):
                if arm not in q_weights:
                    branch_reports[arm] = {"status": "UNAVAILABLE", "reason": reports[arm]["status"]}
                    continue
                q = q_weights[arm]
                g = uniform if arm == "uniform" else d.train_gradient(train, q, f"B:weighted:{arm}")
                norm = _norm(g)
                raw = _step(d, holdout, baseline, h_gradient, g, settings.eta, f"H:{arm}:raw")
                if norm <= settings.zero_norm or match_norm <= settings.zero_norm:
                    matched = {"status": "MATCHED_NORM_UNDEFINED", "reason": "ZERO_GRADIENT_OR_REFERENCE_NORM"}
                else:
                    matched = _step(d, holdout, baseline, h_gradient, g, match_norm/norm, f"H:{arm}:matched")
                branch_reports[arm] = {"status": "ATTEMPTED", "weight_summary": weight_summary(q, train),
                                       "weighted_gradient": vector_summary(p, g), "raw_sgd": raw, "matched_norm": matched}
            unchanged_hashes["repeat_initial"] = p.sha256()
            with torch.no_grad():
                repeat_initial, _, _ = d.pair_roles(holdout, "H:repeat_initial", gradients=False)
    except NumericalFailure as error:
        failure = str(error)
    finally:
        if not p.restored():
            p.restore()
    end = p.sha256()
    if end != origin or any(value != origin for value in unchanged_hashes.values()):
        raise RuntimeError("Final trainable parameter digest differs from the original snapshot")
    return {
        "status": "NUMERICAL_FAILURE_RETAINED" if failure is not None else "PROBE_ONLY_COMPLETE" if probe_only else "COMPLETE",
        "numerical_failure": failure,
        "settings": asdict(settings), "excluded_length_mismatches": mismatched_pairs,
        "train_support_count": n, "train_support_order": labels,
        "reference_anchors": reports, "reference_gram": gram, "reference_cosine": cosine,
        "probe_weight_summaries": {k: weight_summary(q, train) for k, q in q_weights.items()},
        "heldout_baseline_by_role": baseline, "heldout_matched_pairs_by_role": heldout_count,
        "heldout_zero_step_by_role": zero_step, "heldout_repeat_initial_by_role": repeat_initial,
        "heldout_initial_parameter_sha256": unchanged_hashes,
        "matched_target_parameter_norm": match_norm, "branches": branch_reports,
        "parameter_base_sha256": origin, "parameter_final_sha256": end, "bitwise_restore_count": p.restores,
        "trainable_parameter_names": p.names, "trainable_parameter_count": sum(p.sizes), "trainable_dtype": str(p.dtype),
        "paid_work": d.ledger.report(), "elapsed_wall_ns": perf_counter_ns()-started,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(p.device) if p.device.type == "cuda" else None,
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(p.device) if p.device.type == "cuda" else None,
    }


class LoRALinear(nn.Module):
    def __init__(self, base, rank, generator):
        super().__init__()
        self.base = base
        bound = 1/math.sqrt(base.in_features)
        initial = torch.empty((rank, base.in_features), dtype=torch.float32, device="cpu")
        initial.uniform_(-bound, bound, generator=generator)
        self.adapter_a = nn.Parameter(initial.to(base.weight.device))
        self.adapter_b = nn.Parameter(torch.zeros((base.out_features, rank), device=base.weight.device, dtype=torch.float32))

    def forward(self, inputs):
        base = self.base(inputs)
        update = F.linear(F.linear(inputs.float(), self.adapter_a), self.adapter_b)
        return base + update.to(base.dtype)


def attach_qv_lora(model, *, seed):
    model.requires_grad_(False)
    rng = torch.Generator(device="cpu").manual_seed(seed)
    modules = [(name, module) for name, module in model.named_modules()
               if type(module) is nn.Linear and name.rsplit(".", 1)[-1] in ("q_proj", "v_proj")]
    if len(modules) != 2*model.config.num_hidden_layers:
        raise ValueError("Model q_proj/v_proj module count differs from the pinned all-layer subspace")
    for path, original in modules:
        parent, _, leaf = path.rpartition(".")
        setattr(model.get_submodule(parent) if parent else model, leaf, LoRALinear(original, 4, rng))
    model.eval()
    return [name for name, _ in modules]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--input", type=Path, required=True)
    cli.add_argument("--holdout", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--model", required=True)
    cli.add_argument("--device", default="cuda:0")
    cli.add_argument("--dtype", choices=("float32", "bfloat16", "float16"), default="float32")
    cli.add_argument("--eta", type=float, required=True)
    cli.add_argument("--epsilons", nargs=2, type=float, required=True)
    cli.add_argument("--kl", type=float, required=True)
    cli.add_argument("--match-norm", type=float)
    cli.add_argument("--max-probe-relative-l2", type=float, default=0.15)
    cli.add_argument("--min-probe-cosine", type=float, default=0.98)
    cli.add_argument("--seed", type=int, default=20261110)
    cli.add_argument("--cpu-threads", type=int, default=1)
    cli.add_argument("--probe-only", action="store_true")
    args = cli.parse_args()
    if args.output.exists() or (args.holdout is not None and args.probe_only):
        cli.error("Expected a new output path, and probe-only forbids a holdout file")
    raw = args.input.read_bytes()
    payload = json.loads(raw)
    holdout_sha = None
    if args.holdout is not None:
        holdout_raw = args.holdout.read_bytes()
        holdout_sha = sha256(holdout_raw).hexdigest()
        holdout = json.loads(holdout_raw)
        if "H" in payload or type(holdout) is not dict or set(holdout) != {"H"}:
            cli.error("A separate holdout file must be the only H source and contain exactly H")
        payload["H"] = holdout["H"]
    settings = Settings(tuple(args.epsilons), args.eta, args.kl, args.match_norm,
                        args.max_probe_relative_l2, args.min_probe_cosine)
    settings.validate()
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    use_text = any("prefix" in row or ("pair" in row and "prefix" in row["pair"])
                   for key in ("B", "Bprime", "H") for row in payload.get(key, ()))
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False) if use_text else None
    splits, mismatches = load_packet(payload, tokenizer, probe_only=args.probe_only)
    torch.set_num_threads(args.cpu_threads)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    began = perf_counter_ns()
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, trust_remote_code=False,
                                                torch_dtype=getattr(torch, args.dtype), attn_implementation="sdpa",
                                                low_cpu_mem_usage=True).to(args.device)
    model.config.use_cache = False
    modules = attach_qv_lora(model, seed=args.seed)
    load_wall = perf_counter_ns()-began
    result = run_diagnostic(model, splits, mismatches, settings, probe_only=args.probe_only)
    result.update({
        "input_sha256": sha256(raw).hexdigest(), "separate_holdout_sha256": holdout_sha,
        "runner_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": {"torch": torch.__version__, "transformers": transformers.__version__, "device": args.device,
                    "base_dtype": args.dtype, "backend": "sdpa", "lora_rank": 4, "lora_scale": 1,
                    "lora_seed": args.seed, "adapter_modules": modules, "model_and_adapter_load_wall_ns": load_wall},
    })
    with args.output.open("xb") as stream:
        stream.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode())
    print(result["status"], sha256(args.output.read_bytes()).hexdigest(), flush=True)


if __name__ == "__main__":
    main()
