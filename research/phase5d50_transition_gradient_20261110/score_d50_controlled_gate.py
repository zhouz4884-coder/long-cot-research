"""Independently recount the frozen D5.0 controlled gate from paid runner readouts."""

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
RULES_SHA256 = "cb15953ddba7f7c88ad90aa6a379ac0e7e3a3c0c0cb259901dd0dbad4f753cbe"
SEAL_SHA256 = "02d50340b4797faa2a2a9849e28aa724eb49208d78b16c946cef36d57c98017d"
STAGES = {"baseline": "H:baseline", "zero_step": "H:zero_step", "repeat_initial": "H:repeat_initial"}
INCOMPLETE = "INCOMPLETE_CONTROLLED_GATE"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path, expected_sha):
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected_sha, f"Unexpected SHA-256 for {path.name}")
    return json.loads(raw)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "Nonfinite or invalid number")
    return value


def readout(by_role, expected):
    """Recompute both margin units from the underlying log probabilities."""
    output = {}
    require(set(by_role) == {row["role"] for row in expected.values()}, "Wrong holdout roles")
    for role, block in by_role.items():
        for row in block["cases"]:
            case_id = row["case_id"]
            require(case_id in expected and case_id not in output, f"Unfrozen or duplicate case {case_id}")
            freeze = expected[case_id]
            tokens = freeze["pair_candidate_tokens"]
            require(row["problem_id"] == freeze["problem_id"] and row["role"] == role == freeze["role"]
                    and row["correct_target_tokens"] == row["alternative_target_tokens"] == tokens > 0,
                    f"Mismatched holdout identity or token length for {case_id}")
            sequence = number(row["correct_logprob"]) - number(row["alternative_logprob"])
            normalized = sequence / tokens
            require(math.isclose(sequence, number(row["margin"]), abs_tol=1e-12)
                    and math.isclose(normalized, number(row["per_target_token_margin"]), abs_tol=1e-12),
                    f"Invalid margin bookkeeping for {case_id}")
            output[case_id] = {"sequence_nats": sequence, "nats_per_target_token": normalized}
    require(set(output) == set(expected), "Incomplete holdout readout")
    return output


def verify_paid_initial(result, expected):
    """Require separate forwards for each branch at all three initial readouts."""
    origin = result["parameter_base_sha256"]
    require(len(origin) == 64 and int(origin, 16) >= 0 and origin == result["parameter_final_sha256"],
            "Original adapter digest was not restored")
    require(result["heldout_initial_parameter_sha256"] == dict.fromkeys(STAGES, origin),
            "Initial-state readouts are not bound to the original adapter")
    target = Counter((case_id, branch, row["role"], row["pair_candidate_tokens"])
                     for case_id, row in expected.items() for branch in ("correct", "alternative"))
    ledger = result["paid_work"]["rows"]
    for key, stage in STAGES.items():
        rows = [row for row in ledger if row["stage"] == stage and row["kind"] == "FORWARD"]
        recorded = Counter((row["case_id"], row["branch"], row["role"], row["teacher_targets"]) for row in rows)
        require(recorded == target and all(row["grad_enabled"] is (key == "baseline") for row in rows),
                f"Missing or duplicated separately paid forward for {stage}")


def branches(result, rules, expected, base):
    arms = rules["arms"]
    settings = result["settings"]
    eta = number(settings["eta"])
    target_norm = number(result["matched_target_parameter_norm"])
    kl = number(settings["kl"])
    norm_tolerance = max(rules["matched_norm_absolute_tolerance"], rules["matched_norm_relative_tolerance"] * target_norm)
    require(eta > 0 and target_norm > 0 and kl >= 0, "Invalid common eta, update norm or KL")
    output = {mode: {} for mode in rules["modes"]}
    for arm in (*arms["controls"], arms["proposed"]):
        branch = result["branches"][arm]
        require(branch["status"] == "ATTEMPTED", f"Unavailable arm {arm}")
        expected_kl = 0 if arm == "uniform" else kl
        if arm != "uniform":
            require(result["reference_anchors"][arm]["status"] == "READY", f"Unusable reference direction for {arm}")
        require(math.isclose(number(branch["weight_summary"]["kl_from_uniform"]), expected_kl, abs_tol=1e-8),
                f"Incorrect KL for {arm}")
        for mode in output:
            step = branch[mode]
            status = step["status"]
            require(status in ("EVALUATED", "ZERO_UPDATE_REUSED_BASELINE"), f"Unevaluable step {arm}/{mode}")
            actual_norm = number(step["actual_update_norm"])
            require((status == "EVALUATED" and actual_norm > 0) or
                    (status == "ZERO_UPDATE_REUSED_BASELINE" and actual_norm == 0), f"Invalid actual step {arm}/{mode}")
            if mode == "raw_sgd":
                require(number(step["step_scale"]) == eta, f"Raw eta mismatch for {arm}")
            else:
                require(actual_norm > 0 and abs(actual_norm - target_norm) <= norm_tolerance,
                        f"Actual matched norm mismatch for {arm}")
            role_data = step["by_role"]
            before = readout({role: row["before"] for role, row in role_data.items()}, expected)
            after = readout({role: row["after"] for role, row in role_data.items()}, expected)
            require(before == base and (status == "EVALUATED" or before == after), f"Mismatched baseline for {arm}/{mode}")
            output[mode][arm] = after
    return output


def evaluate(result, rules, packet, seal):
    """Return an auditable decision without model access or training side effects."""
    try:
        require(result["status"] == "COMPLETE", f"Runner status {result['status']}")
        require(packet["token_packet_sha256"] == seal["combined_packet_sha256"], "Split seal targets a different packet")
        require(result["input_sha256"] == seal["parts"]["main"]["sha256"] and
                result["separate_holdout_sha256"] == seal["parts"]["holdout"]["sha256"],
                "Runner did not use the sealed main and holdout inputs")
        frozen = [row for row in packet["rows"] if row["partition"] == "H"]
        expected = {row["case_id"]: row for row in frozen}
        counts = Counter(row["role"] for row in frozen)
        require(len(expected) == len(frozen) == len({row["problem_id"] for row in frozen}) and
                counts == rules["expected_independent_problems_by_role"] == result["heldout_matched_pairs_by_role"],
                "Wrong number of independent holdout problems or roles")
        verify_paid_initial(result, expected)
        noise = rules["noise"]
        base, zero, repeat = [readout(result[key], expected) for key in noise["readouts"]]
        measured = branches(result, rules, expected, base)
    except (KeyError, ValueError, TypeError, OverflowError, AttributeError) as error:
        return {"status": INCOMPLETE, "reason": str(error)}

    proposed = rules["arms"]["proposed"]
    controls = rules["arms"]["controls"]
    unit = "nats_per_target_token"
    rows = []
    for case_id, frozen_row in expected.items():
        readings = [x[case_id][unit] for x in (base, zero, repeat)]
        spread = max(readings) - min(readings)
        threshold = max(noise["floor_nats_per_target_token"], noise["multiplier"] * spread)
        role = frozen_row["role"]
        row = {"case_id": case_id, "problem_id": frozen_row["problem_id"], "role": role,
               "target_tokens": frozen_row["pair_candidate_tokens"], "initial": base[case_id],
               "zero_step": zero[case_id], "repeat_initial": repeat[case_id],
               "observed_initial_spread": spread, "threshold": threshold, "modes": {}}
        for mode, arms in measured.items():
            after = {arm: cases[case_id] for arm, cases in arms.items()}
            delta = {arm: {key: value - base[case_id][key] for key, value in scores.items()}
                     for arm, scores in after.items()}
            comparisons = {control: delta[proposed][unit] - delta[control][unit] for control in controls}
            row["modes"][mode] = {
                "after": after, "delta": delta, "T_minus_control_nats_per_target_token": comparisons,
                "e_win": role == "E" and delta[proposed][unit] >= threshold and
                         all(value >= threshold for value in comparisons.values()),
                "absolute_harm": role in ("W", "C") and delta[proposed][unit] <= -threshold,
                "controls_materially_ahead": [arm for arm, value in comparisons.items() if value <= -threshold],
            }
        rows.append(row)
    e_wins = [row["problem_id"] for row in rows if all(item["e_win"] for item in row["modes"].values())]
    harms = {role: {mode: [row["problem_id"] for row in rows if row["role"] == role and
                          row["modes"][mode]["absolute_harm"]] for mode in measured} for role in ("W", "C")}
    enough = len(e_wins) >= rules["advancement"]["min_same_independent_e_problems_in_both_modes"]
    no_harm = not any(cases for modes in harms.values() for cases in modes.values())
    return {"status": "PASS_CONTROLLED_GATE" if enough and no_harm else "NO_GO_CONTROLLED_GATE",
            "problem_counts_by_role": dict(counts), "joint_e_wins": e_wins,
            "absolute_wc_harms": harms, "sufficient_joint_e_wins": enough, "no_material_wc_harm": no_harm,
            "rows": rows}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rules = read_json(HERE / "D50_GATE_RULES.json", RULES_SHA256)
    seal = read_json(HERE / "D50_CONTROLLED_HOLDOUT_SEAL.json", SEAL_SHA256)
    freeze = read_json(HERE / "D50_CONTROLLED_PACKET_FREEZE.json", rules["controlled_packet_freeze_sha256"])
    packet, = [row for row in freeze["packets"] if row["packet"] == rules["packet"]]
    result = read_json(args.result, args.expected_result_sha256.lower())
    decision = evaluate(result, rules, packet, seal)
    decision.update({"rules_sha256": RULES_SHA256, "holdout_seal_sha256": SEAL_SHA256,
                     "runner_result_sha256": args.expected_result_sha256.lower()})
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(decision, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(decision["status"], sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
