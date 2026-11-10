"""Post-score exact geometry check and unchanged-score sensitivity for 2016-I-9."""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from score_live import answer_readout, load_author_scorer

HERE = Path(__file__).resolve().parent
CASE = "2016-I-9"
ARMS = ("NativeContinue", "GenericReminder", "TypedObligation", "IndependentRestart")
BASELINES = ("NativeContinue", "GenericReminder", "IndependentRestart")
SOURCE = "https://www.isinj.com/mt-aime/2016AIME-ISolutions.pdf"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def audit(shard: Path, lab: Path, parser_path: Path) -> dict:
    live_path = HERE / "D44_LIVE_RESULTS.json"
    outcome_path = HERE / "D44_LIVE_OUTCOME_FREEZE.json"
    inputs_path = HERE / "D44_LIVE_INPUT_FREEZE_V2.json"
    cohort_path = HERE / "D44_LIVE_COHORT_FREEZE.json"
    live, outcome, inputs, cohort = map(load, (live_path, outcome_path, inputs_path, cohort_path))
    assert live["input_sha256"]["outcome"] == sha(outcome_path)
    assert live["input_sha256"]["reviewed_input"] == sha(inputs_path)
    assert cohort["question_source_shard_sha256"] == sha(shard)
    scored = next(row for row in live["rows"] if row["case_id"] == CASE)
    proposed = next(row for row in inputs["rows"] if row["case_id"] == CASE)
    assert proposed["question_sha256"] == scored["question_sha256"]
    assert proposed["obligation"]["args"] == [248, 728]
    assert scored["approved_condition_refutes_an_accepted_value"]
    found = pq.read_table(shard, columns=["problem_id", "problem", "accepted_answer_integers"],
                          filters=[("problem_id", "=", CASE)]).to_pylist()
    assert len(found) == 1 and found[0]["accepted_answer_integers"] == [744]
    assert hashlib.sha256(found[0]["problem"].encode()).hexdigest() == proposed["question_sha256"]
    bound_worker, = (w for w in outcome["workers"] if CASE in {r["case_id"] for r in w["cases"]})
    result_path = lab / "main_raw_results" / f'worker_{bound_worker["worker"]}' / CASE / "result.json"
    assert sha(result_path) == scored["terminal_result_sha256"]
    raw = load(result_path)
    parser = load_author_scorer(parser_path)
    choices = {arm: answer_readout(parser, raw["arms"][arm])[0] for arm in ARMS}
    assert choices == dict(zip(ARMS, (480, 480, 480, 744), strict=True))

    # At the official equality, sin(beta)^2=2/5 and cos(gamma)^2=3/5.
    bq_squared, qr_squared = 40**2 * Fraction(2, 5), 31**2 * Fraction(3, 5)
    assert bq_squared > qr_squared
    universal_area_upper = Fraction(248) + Fraction(31**2, 2)
    assert universal_area_upper < 744
    # If 248(1600-496√6)/(2561-992√6) were rational, these would coincide.
    rational_coefficients = Fraction(248 * 1600, 2561), Fraction(248 * 496, 992)
    assert rational_coefficients[0] != rational_coefficients[1]
    with localcontext() as ctx:
        ctx.prec = 42
        s = Decimal(6).sqrt()
        literal_maximum = 248 * (1600 - 496 * s) / (2561 - 992 * s)
        assert Decimal(728) < literal_maximum < Decimal("728.5")

    remaining = [row for row in live["rows"] if row["case_id"] != CASE]
    summary = {
        arm: {
            "correct": sum(row["arms"][arm]["correctness"] == "CORRECT" for row in remaining),
            "logical_forward_input_tokens": sum(
                row["arms"][arm]["logical_forward_work"]["forward_input_tokens"] for row in remaining),
            "logical_attention_pairs": sum(
                row["arms"][arm]["logical_forward_work"]["attention_pairs"] for row in remaining),
        }
        for arm in ARMS
    }
    strongest = min(BASELINES, key=lambda arm: (
        -summary[arm]["correct"], summary[arm]["logical_forward_input_tokens"],
        summary[arm]["logical_attention_pairs"], BASELINES.index(arm),
    ))
    def net(arm: str) -> int:
        pairs = [r["comparisons"][arm]["cost_censored_pair"] for r in remaining]
        return pairs.count("REPAIR") - pairs.count("HARM")
    assert len(remaining) == 7 and all(summary[arm]["correct"] == 7 for arm in ARMS)
    return {
        "status": "OFFICIAL_LABEL_CONFLICT_VERIFIED_POST_SCORE",
        "scope": "Diagnostic interpretation and exclusion sensitivity only. No relabeling, new model calls, or changes to the eight-case protocol.",
        "case_id": CASE, "question_sha256": proposed["question_sha256"], "official_solution_source": SOURCE,
        "frozen_score_sha256": sha(live_path), "official_accepted_integer": 744,
        "final_readouts": choices, "literal_placement_at_official_equality": {
            "BQ_squared": str(bq_squared), "QR_squared": str(qr_squared), "B_on_segment_QR": False,
        },
        "universal_real_area_upper_bound": str(universal_area_upper),
        "literal_segment_maximum_exact": "248(1600-496sqrt(6))/(2561-992sqrt(6))",
        "literal_segment_maximum_approx": str(literal_maximum),
        "literal_segment_maximum_is_integer": False,
        "sensitivity_excluding_conflicted_case": {
            "denominator": len(remaining), "by_arm": summary, "recomputed_strongest_baseline": strongest,
            "typed_cost_censored_net_vs_recomputed_strongest": net(strongest),
            "typed_cost_censored_net_vs_original_restart": net(live["strongest_baseline"]),
        },
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("source-shard", "lab", "author-scorer", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    report = audit(args.source_shard, args.lab, args.author_scorer)
    with args.output.open("xb") as stream:
        stream.write((json.dumps(report, indent=2) + "\n").encode())
    print(report["status"], report["sensitivity_excluding_conflicted_case"])


if __name__ == "__main__":
    main()
