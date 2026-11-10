"""Bind two thinking observations and the original native final independently."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import sys
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
D46 = HERE.parent / "phase5d46_point_infeasibility_20261110"
sys.path.insert(0, str(D46))
import extract_d46_points as prior


RULES_SHA = "fb75794632ace663a9015f450904045b070b672fe609daee38577b16e6827e56"
THINKING_EXTRACTOR_SHA = "468ec744124de579afafda682d2e00bb3caffe2ff0f710005d5c21d8a1139243"
EOS_MARKER = {"im_end": "<|im_end|>", "endoftext": "<|endoftext|>"}
CHANNEL_MARKERS = ("<think>", "</think>", "<|im_start|>", "<|im_end|>", "<|endoftext|>")


def thinking_rules(rules):
    raw = (D46 / "D46_OBSERVATION_RULES.json").read_bytes()
    prior.require(prior.digest(raw) == prior.RULES_SHA, "D46 thinking observation rules changed")
    frozen = json.loads(raw)
    prior.require(rules["source_draws"] == frozen["source_draws"]
                  and rules["reserved_draws"] == frozen["reserved_draws"]
                  and all(rules["early"][key] == frozen["early"][key] for key in ("characters", "lookback_characters"))
                  and rules["late"]["lookback_characters"] == frozen["late"]["lookback_characters"],
                  "D47 no longer shares both exact D46 thinking observation boundaries")
    return frozen


def ordinary_box(row):
    final = row["final"]
    return {key: final[key] for key in ("value", "char_span_in_response", "source_excerpt_sha256") if key in final}


def box_in_assertion(scope, box, offset):
    if scope["extraction_method"] == "adjacent_repeated_box":
        echo = scope["terminal_echo_receipt"]
        return all(echo[key] == box[key] for key in ("char_span_in_response", "source_excerpt_sha256"))
    if scope["extraction_method"] != "explicit_target_box":
        return False
    left, right = box["char_span_in_response"]
    lo, hi = scope["numeric_span"]
    start, end = scope["assertion_span"]
    return offset + start <= left < offset + lo < offset + hi < right <= offset + end


def final_point(scorer, sample, row, case, lookback):
    box = ordinary_box(row)
    base = {"segment": "final", "unit": case["unit"], "official_final_box_receipt": box,
            "ordinary_final_status": row["final"]["status"]}
    if row["termination"] == "LENGTH_CAP":
        return prior.unknown("FINAL_LENGTH_CAP", **base)
    if row["termination"] != "NATIVE_STOP":
        return prior.unknown("FINAL_TERMINATION_UNKNOWN", **base)
    if row["boundary"] != "CLOSED_THINKING":
        return prior.unknown("FINAL_THINKING_BOUNDARY_UNKNOWN", **base)
    if not row["native_final_eligible"]:
        return prior.unknown("FINAL_NO_ELIGIBLE_STRICT_SCALAR", **base)

    text = sample["response"]
    prior.require(text.count(prior.THINK_CLOSE) == 1, "D46 boundary receipt is inconsistent")
    start = text.index(prior.THINK_CLOSE) + len(prior.THINK_CLOSE)
    prefix = text[start:]
    terminal_marker = EOS_MARKER[sample["stop_condition"]]
    stripped_marker = prefix.endswith(terminal_marker)
    if stripped_marker:
        prefix = prefix.removesuffix(terminal_marker)
    base["stripped_exact_eos_suffix"] = stripped_marker
    base["observation_prefix_sha256"] = prior.digest(prefix.encode())
    base["observation_char_span_in_response"] = [start, start + len(prefix)]
    if any(marker in prefix for marker in CHANNEL_MARKERS):
        return prior.unknown("FINAL_CHANNEL_CONTROL_AMBIGUOUS", **base)

    scope = prior.observation(scorer, prefix, start, case, lookback, True)
    if scope["status"] != prior.BOUND:
        return {**scope, **base}
    if Fraction(**scope["rational"]) != Fraction(box["value"]):
        return prior.unknown("FINAL_SCOPED_SCALAR_DIFFERS_FROM_DELIVERED_BOX", **base,
                             scoped_value=scope["value"], scoped_assertion_sha256=scope["assertion_sha256"])
    if not box_in_assertion(scope, box, start):
        return prior.unknown("FINAL_BOX_NOT_BOUND_TO_SCOPED_ASSERTION", **base,
                             scoped_value=scope["value"], scoped_assertion_sha256=scope["assertion_sha256"])
    return {**scope, **base}


def extract(scorer, blind, cohort, cohort_sha, rules):
    start, cpu = perf_counter_ns(), thread_time_ns()
    prior.require(cohort["observation_rules_sha256"] == RULES_SHA, "D47 cohort observation-rule identity differs")
    prior_rules = thinking_rules(rules)
    cases = {row["case_id"]: row for row in cohort["rows"]}
    prior.require(all(type(case["unit"]) is str and 0 < len(case["unit"]) <= 96 and case["unit"].strip() == case["unit"]
                      for case in cases.values()), "A D47 original objective must have an exact declared unit")
    # D46 validates the complete frozen blind draw grid. Only its inherited rule identity is adapted locally.
    inherited = prior.extract(scorer, blind, {**cohort, "observation_rules_sha256": prior.RULES_SHA}, cohort_sha, prior_rules)
    rows = []
    lookback = rules["late"]["lookback_characters"]
    for sample, row in zip(blind["rows"], inherited["rows"], strict=True):
        prior.require(sample["sample_id"] == row["sample_id"], "Inherited trace order differs")
        case = cases[row["case_id"]]
        rows.append({**row, "unit": case["unit"], "final_point": final_point(scorer, sample, row, case, lookback)})
    return {**inherited, "status": "FROZEN_D47_DELIVERY_READOUT_WITHOUT_GOLD", "observation_rules_sha256": RULES_SHA,
            "inherited_thinking_rules_sha256": prior.RULES_SHA, "thinking_extractor_sha256": THINKING_EXTRACTOR_SHA,
            "scope": "Exact archived text coordinates. Early and late use D46 thinking only. Final spans are relative to the separately bounded final slice. No raw prefixes or labels emitted.",
            "final_scope_lookback_characters": lookback,
            "final_point_counts": dict(Counter(row["final_point"]["status"] for row in rows)),
            "cost": {"wall_ns": perf_counter_ns() - start, "cpu_ns": thread_time_ns() - cpu},
            "inherited_thinking_readout_cost": inherited["cost"], "rows": rows}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for flag in ("blind-input", "cohort-freeze", "author-scorer", "output"):
        cli.add_argument("--" + flag, type=Path, required=True)
    cli.add_argument("--observation-rules", type=Path, default=HERE / "D47_OBSERVATION_RULES.json")
    args = cli.parse_args()
    prior.require(not args.output.exists(), "Refuse to overwrite a frozen readout")
    rule_bytes = args.observation_rules.read_bytes()
    prior.require(prior.digest(rule_bytes) == RULES_SHA
                  and prior.digest((D46 / "extract_d46_points.py").read_bytes()) == THINKING_EXTRACTOR_SHA
                  and prior.digest((prior.D45 / "extract_d45_claims.py").read_bytes()) == prior.D45_LITERAL_SOURCE_SHA,
                  "D47 or inherited parser rules differ from the exact reviewed bytes")
    blind_bytes, cohort_bytes = args.blind_input.read_bytes(), args.cohort_freeze.read_bytes()
    report = extract(prior.load_author_scorer(args.author_scorer), json.loads(blind_bytes), json.loads(cohort_bytes),
                     prior.digest(cohort_bytes), json.loads(rule_bytes))
    report.update(blind_input_sha256=prior.digest(blind_bytes), extractor_sha256=prior.digest(Path(__file__).read_bytes()))
    prior.write_exclusive(args.output, report)
    print(json.dumps({key: report[key] for key in ("status", "early_counts", "late_counts", "final_point_counts", "paid_full_source_tokens")}))


if __name__ == "__main__":
    main()
