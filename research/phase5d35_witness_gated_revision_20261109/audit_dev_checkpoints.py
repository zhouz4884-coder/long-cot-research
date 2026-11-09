"""Verify the inherited D3 result and reproduce selected past-only DEV checkpoints."""

import argparse
import base64
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from math import lcm, prod
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
TOKENIZER = REPO / "outputs/d2_tokenizer_20261107"
BASELINE = "4dfdb426aa63"
CHECKPOINTS_FILE = ROOT / "D35_DEV_CHECKPOINTS.json"

# Anchor IDs identify specific observed paragraphs. Window names describe the
# selection rule and do not put the retrospective diagnosis into the input view.
SOURCE_SPECS = {
    "E12": {
        "path": "bank/native_results/worker_0/D3_E12_20261110/result.json",
        "anchors": {
            "ratio": (110, "r = -3"), "b1": (117, "b_1 = 1/2"),
            "difference": (121, "= 3 + 2 = 5"), "a1": (123, "= 1 - 1/2 = 1/2"),
            "parameter_bundle": (124, "a_1 = 1/2, d = 5, b_1 = 1/2, r = -3"),
            "constraint_1": (126, "a_1 + b_1 = 1/2 + 1/2 = 1"),
            "constraint_2": (127, "= (5.5) + (-1.5) = 4"),
            "constraint_3": (128, "= 10.5 + 4.5 = 15"),
            "constraint_4": (129, "= 15.5 + (-13.5) = 2"),
            "first_computed_candidate": (134, "c_5 = 20.5 + 40.5 = 61"),
            "first_committed_box": (145, r"\boxed{61}"),
            "late_commitment": (152, "the answer is 61"),
        },
        "windows": {
            "before_parameters_control": 120, "first_complete_parameters": 123, "parameters_available": 124,
            "all_four_checks_observed": 129, "first_computed_candidate": 134,
            "first_boxed_candidate": 145, "last_live_before_close": 152,
        },
        "thinking_terminal_step": 153,
    },
    "E15": {
        "path": "bank/native_results/worker_1/D3_E15_20261110/result.json",
        "anchors": {
            "incumbent_first_value": (194, "a six-digit number 303369"),
            "incumbent_feasible": (212, "303369 is valid"),
            "prior_maximum_claim": (311, "303369 is the maximum"),
            "first_constructive_candidate": (316, "the seven-digit number is 1011235"),
            "first_bad_comparison": (316, "that's smaller than 303369"),
            "repeat_candidate_digits": (451, "1, 0, 1, 1, 2, 3, 5"),
            "rechecked_candidate": (456, "the number 1011235 is valid"),
            "renewed_maximum_claim": (463, "303369 is the maximum"),
            "late_candidate": (467, "the answer is 303369"),
            "final_thinking_maximum_claim": (476, "the greatest fibbish number is 303369"),
        },
        "windows": {
            "before_observed_larger_candidate_control": 312,
            "first_observed_larger_candidate": 316,
            "after_reasserted_maximum": 464, "last_live_before_close": 468,
        },
        "thinking_terminal_step": 477,
    },
    "P02": {
        "path": "precheck/native_results/worker_1/D3_P02_20261109/result.json",
        "anchors": {
            "incomplete_mod17_root_claim": (114, "two solutions mod 17: 2 and 15"),
            "first_constructed_candidate": (127, "n=15 +17*7=15 +119=134"),
            "first_tentative_lift_claim": (128, "two solutions mod 17²: 155 and 134"),
            "first_unhedged_minimum_sentence": (131, "the minimal positive integer is 134"),
            "feasibility_check": (135, "134 is a solution"),
            "selected_incomplete_lift_claim": (137, "there are two solutions mod 17²"),
            "late_minimum_claim": (138, "134 is the minimal positive solution"),
        },
        "windows": {
            "before_134_control": 125, "first_134": 127,
            "tentative_minimum": 128, "unhedged_minimum_sentence": 131,
            "first_live_after_selected_lift_claim": 138, "last_live_before_close": 164,
        },
        "thinking_terminal_step": 165,
    },
    "E14": {
        "path": "bank/native_results/worker_0/D3_E14_20261110/result.json",
        "anchors": {
            "first_overbroad_lcm_claim": (152, "LCM(S \\ {m1, m2}) is not divisible by m1 or m2"),
            "observed_pair": (153, "m1 = 16 and m2 = 18"),
            "wrong_pair_check": (155, "LCM(S \\ {16, 18}) is not divisible by 18"),
            "observed_factorization": (195, "LCM(S \\ {16, 18}) = 2^3 * 3^3"),
            "late_tentative_count": (474, "the correct answer is 105"),
            "renewed_universal_claim": (475, "removing any two of them ensures"),
        },
        "windows": {
            "before_observed_pair_control": 152, "pair_available": 153,
            "pair_misclassified": 155, "factors_available": 195,
            "before_renewed_universal_control": 474, "after_renewed_universal": 475,
        },
        "thinking_terminal_step": 477,
    },
    "E06": {
        "path": "bank/native_results/worker_1/D3_E06_20261109/result.json",
        "anchors": {
            "observed_45_witness": (210, "N=25 + 20 = 45: greedy takes 1*25 + 2*10 = 3 coins"),
            "observed_45_recheck": (211, "45 is 25 + 20, which is 25 + 2*10"),
            "wrong_floor_partition": (252, "floor((R + 25)/10): R + 25 is 40-49"),
            "wrong_region_claim": (255, "for R in 5-9 or 15-24"),
            "wrong_exhaustive_classification": (263, "the greedy algorithm is not optimal"),
            "opposite_45_classification": (329, "N=45: 20 → not"),
            "first_415_count": (347, "24 (from 1-24) + 391 = 415"),
            "late_415_commitment": (635, "the correct answer is 415"),
        },
        "windows": {
            "before_45_control": 209, "first_observed_45": 210,
            "wrong_floor_partition": 252, "wrong_exhaustive_classification": 263,
            "explicit_45_contradiction": 329, "first_415_count": 347,
            "last_live_before_close": 635,
        },
        "thinking_terminal_step": 636,
    },
}


def file_sha(path):
    return sha256(path.read_bytes()).hexdigest()


def digest_ids(ids):
    return sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_lines(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def git(*arguments):
    return subprocess.check_output(("git", *arguments), cwd=REPO)


def committed_sha(path):
    return sha256(git("show", f"{BASELINE}:{path.relative_to(REPO).as_posix()}")).hexdigest()


def check_committed(path):
    actual = file_sha(path)
    if actual != committed_sha(path):
        raise ValueError(f"Published baseline bytes changed: {path}")
    return actual


def assert_true(condition, context):
    if not condition:
        raise ValueError(context)


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def make_tokenizer():
    from transformers import AutoTokenizer

    manifest = read(TOKENIZER / "TOKENIZER_FETCH_MANIFEST.json")
    for entry in manifest["files"]:
        path = TOKENIZER / entry["path"]
        assert_true(path.stat().st_size == entry["bytes"] and file_sha(path) == entry["sha256"],
                    "Pinned tokenizer asset changed")
    return AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True, trust_remote_code=False)


def decode(tokenizer, ids):
    return tokenizer.decode(ids, skip_special_tokens=False)


def source_hashes():
    result = {}
    for name in ("BANK_RETRIEVAL.json", "PRECHECK_RETRIEVAL.json"):
        receipt = read(D3 / name)
        assert_true(receipt["status"] == "COMPLETE", "Inherited raw retrieval not closed")
        for row in receipt["files"]:
            if row["path"].endswith("/result.json"):
                path = D3 / row["path"]
                assert_true(file_sha(path) == row["sha256"] == committed_sha(path), "Inherited result changed")
                result[row["path"]] = row["sha256"]
    return result


def inherited_evidence(hashes):
    paths = ("BANK_RETRIEVAL.json", "PRECHECK_RETRIEVAL.json", "bank/SCORES.json",
             "bank/GRADE_FREEZE.json", "bank/SCORE_RECEIPT.json", "D3_DATA_FREEZE.json",
             "D3_METHOD_FREEZE.json", "D3_PAIRING_PROTOCOL.json", "quality/D3_PAIR_SELECTION.json",
             "diagnostics/bank/TYPED_EVENT_REPLAY.jsonl", "diagnostics/bank/TYPED_COVERAGE.json",
             "D3_NATIVE_INDEPENDENT_AUDIT.json", "D3_SCORE_INDEPENDENT_AUDIT.json",
             "D3_E12_DELIVERY_WITNESS.json", "D3_P02_PROGRAM_WITNESS.json",
             "prepared_data/bank/visible.jsonl", "prepared_data/precheck/visible.jsonl")
    sha_by_name = {path: check_committed(D3 / path) for path in paths}
    scores = read(D3 / "bank/SCORES.json")
    scoring = read(D3 / "bank/SCORE_RECEIPT.json")
    grade_freeze = read(D3 / "bank/GRADE_FREEZE.json")
    assert_true(scores["status"] == scoring["status"] == "COMPLETE" and
                sha_by_name["bank/SCORES.json"] == scoring["sha256"] and
                sha_by_name["bank/GRADE_FREEZE.json"] == scores["freeze_sha256"] == scoring["freeze_sha256"],
                "Frozen score receipt mismatch")
    frozen = {(r["case_id"], r["seed"]): r for r in grade_freeze["records"]}
    members = set()
    clustered = Counter()
    correct = 0
    for row in scores["scores"]:
        key = row["case_id"], row["seed"]
        assert_true(key not in members and row["EOS"] and
                    all(row[k] == v for k, v in frozen[key].items()) and hashes[row["path"]] == row["sha256"],
                    "Frozen score or result membership changed")
        members.add(key)
        grade = int(row["grade"]["correct"])
        correct += grade
        clustered[row["case_id"]] += grade
    assert_true(members == set(frozen) and len(members) == 32 and len(clustered) == correct == 16,
                "D3 inherited accuracy differs")
    pair = read(D3 / "quality/D3_PAIR_SELECTION.json")
    assert_true(pair["status"] == "FROZEN" and pair["quality_gate"] == "NO_ELIGIBLE_TARGET" and
                not pair["evaluation_answers_read"] and not pair["selected"] and
                pair["counts"]["eligible_events"] == 0 and pair["counts"]["eligible_distinct_problems"] == 0,
                "Published pairing denominator changed")
    replay = Counter()
    for row in json_lines(D3 / "diagnostics/bank/TYPED_EVENT_REPLAY.jsonl"):
        key = row["case_id"], row["seed"]
        event = row["event"]
        assert_true(key in members and row["source_result_sha256"] == frozen[key]["sha256"],
                    "Typed event belongs to another trajectory")
        replay["typed_surfaces"] += 1
        replay["structured_expressions"] += bool(event["statement"] and event["kind"] != "UNSUPPORTED")
        replay["free_variable_objects"] += bool(event["variables"])
        replay["executable_revisions"] += bool(row["executable_revision"])
        replay["authorized_actions"] += row["check"]["action"] not in ("NONE", None)
    assert_true(replay == {"typed_surfaces": 9710, "structured_expressions": 685, "free_variable_objects": 187,
                           "executable_revisions": 0, "authorized_actions": 0}, "Typed replay totals differ")
    raw = read(D3 / "D3_NATIVE_INDEPENDENT_AUDIT.json")
    assert_true(raw["aggregate"]["trajectories"] == raw["aggregate"]["EOS"] == 32, "Inherited EOS denominator differs")
    return {
        "status": "PASS", "baseline_commit": git("rev-parse", BASELINE).decode().strip(),
        "current_head": git("rev-parse", "HEAD").decode().strip(),
        "committed_inputs_sha256": sha_by_name, "verified_inherited_result_files": len(hashes),
        "formal_trajectories": 32, "formal_problems": 16, "formal_native_correct": correct,
        "per_question_correct_count_distribution": dict(sorted(Counter(clustered.values()).items())),
        "typed_replay": dict(replay), "formal_eligible_events": 0,
        "formal_native_gpu_minutes": raw["summed_worker_GPU_minutes"],
        "formal_evaluation_answer_file_opened": False,
    }


def cover_quote(tokenizer, ids, text, quote):
    assert_true(text.count(quote) == 1, f"Quote is not unique within observed step: {quote}")
    first = text.index(quote)
    last = first + len(quote)
    offsets = []
    for index in range(len(ids) + 1):
        part = decode(tokenizer, ids[:index])
        if text.startswith(part):
            offsets.append((len(part), index))
    left, start = max(pair for pair in offsets if pair[0] <= first)
    right, end = min(pair for pair in offsets if pair[0] >= last)
    assert_true(decode(tokenizer, ids[start:end]) == text[left:right], "Quote token coverage not exact")
    return (first, last), (start, end), (first - left, last - left)


def step_anchor(tokenizer, generated, step, quote):
    start, end = step["start"], step["end"]
    ids = generated[start:end]
    text = decode(tokenizer, ids)
    assert_true(text == step["text"], "Recorded step bytes differ from observed tokens")
    chars, span, local = cover_quote(tokenizer, ids, text, quote)
    quote_ids = ids[span[0]:span[1]]
    return {"step": step["step"], "paragraph_token_span": [start, end], "boundary": step["boundary"],
            "paragraph_ids_sha256": digest_ids(ids), "paragraph_text_sha256": sha256(text.encode()).hexdigest(),
            "quote": quote, "quote_char_span_in_paragraph": list(chars),
            "quote_covering_token_span": [start + span[0], start + span[1]],
            "quote_covering_token_ids": quote_ids, "quote_char_span_within_covering_tokens": list(local)}


def checkpoint(tokenizer, prompt, generated, step, event):
    end = step["end"]
    assert_true(step["boundary"] == "paragraph" and event["thinking_open"] and
                event["start"] == step["start"] and event["end"] == end and
                decode(tokenizer, generated[max(0, end - 8):end]).endswith("\n\n"),
                "Checkpoint is not an observed live paragraph")
    rng = base64.b64decode(event["rng_state_base64"], validate=True)
    assert_true(bool(rng), "Missing saved RNG bytes")
    return {"step": step["step"], "generated_count": end, "prefix_tokens": len(prompt) + end,
            "prefix_sha256": digest_ids(prompt + generated[:end]), "generated_prefix_sha256": digest_ids(generated[:end]),
            "rng_sha256": sha256(rng).hexdigest(), "rng_bytes": len(rng),
            "step_token_span": [step["start"], end], "event_types": event["types"]}


def legal_boundaries(tokenizer, prompt, generated, steps, max_end):
    # Match the frozen D2 planner, which tests the full decoded prefix, not
    # just the final double newline. Blank paragraphs inside TeX cannot be cuts.
    d2 = ROOT.parent / "phase5d2_quarantined_rebase_20261107"
    check_committed(d2 / "dual_frontier_rebase.py")
    sys.path.append(str(d2))
    from dual_frontier_rebase import _closed_paragraph, _opener_offset

    opener = _opener_offset(tokenizer, prompt, generated[:max_end])
    return sorted({opener, *(s["end"] for s in steps if s["boundary"] == "paragraph" and
                             s["end"] <= max_end and _closed_paragraph(decode(tokenizer, generated[:s["end"]])) )})


def build_cases(tokenizer, hashes):
    cases = {}
    for short, spec in SOURCE_SPECS.items():
        path = spec["path"]
        raw = read(D3 / path)
        prompt, generated = raw["prompt_ids"], raw["generated_ids"]
        assert_true(digest_ids(prompt) == raw["prompt_sha256"] and digest_ids(generated) == raw["generated_sha256"],
                    "Raw trajectory IDs changed")
        steps = {s["step"]: s for s in raw["steps"]}
        live = {e["step"]: e for e in raw["events"] if e["thinking_open"] and e.get("rng_state_base64")}
        anchors = {key: step_anchor(tokenizer, generated, steps[index], quote)
                   for key, (index, quote) in spec["anchors"].items()}
        legal = legal_boundaries(tokenizer, prompt, generated, steps.values(),
                                 max(steps[index]["end"] for index in spec["windows"].values()))
        windows = {}
        for name, index in spec["windows"].items():
            item = checkpoint(tokenizer, prompt, generated, steps[index], live[index])
            item["observed_anchor_ids"] = [key for key, row in anchors.items()
                                          if row["paragraph_token_span"][1] <= item["generated_count"]]
            end = item["generated_count"]
            item["observed_legal_boundary_tokens"] = [cut for cut in legal if cut <= end]
            item["checkpoint_is_legal_text_cut"] = end in legal
            item["legal_cut_before_observed_anchor"] = {
                key: max(cut for cut in item["observed_legal_boundary_tokens"]
                         if cut <= anchors[key]["paragraph_token_span"][0])
                for key in item["observed_anchor_ids"]
            }
            windows[name] = item
        close = steps[spec["thinking_terminal_step"]]
        assert_true(close["boundary"] == "think_close" and close["step"] not in live,
                    "Thinking close wrongly identified as live checkpoint")
        cases[short] = {"case_id": raw["case_id"], "seed": raw["seed"], "source_result_path": path,
                        "source_result_sha256": hashes[path], "anchors": anchors, "windows": windows}
    return cases


def observed_view(tokenizer, table, short, window):
    """Produce a prefix-only worker input without importing outcome diagnostics."""
    case = table["cases"][short]
    point = case["windows"][window]
    path = D3 / case["source_result_path"]
    assert_true(file_sha(path) == case["source_result_sha256"], "Fixture source changed")
    raw = read(path)
    prompt = raw["prompt_ids"]
    generated = raw["generated_ids"][:point["generated_count"]]
    event = next(e for e in raw["events"] if e["step"] == point["step"] and e["thinking_open"])
    assert_true(digest_ids(prompt + generated) == point["prefix_sha256"] and
                sha256(base64.b64decode(event["rng_state_base64"], validate=True)).hexdigest() == point["rng_sha256"],
                "Live source checkpoint identity changed")
    anchors = {key: case["anchors"][key] for key in point["observed_anchor_ids"]}
    assert_true(all(r["paragraph_token_span"][1] <= len(generated) for r in anchors.values()),
                "Checkpoint view would expose future anchors")
    steps = [s for s in raw["steps"] if s["end"] <= len(generated)]
    assert_true(all(s["boundary"] == "paragraph" and decode(tokenizer, generated[s["start"]:s["end"]]) == s["text"]
                    for s in steps), "Observed source step changed")
    bank = "precheck" if short == "P02" else "bank"
    visible = D3 / f"prepared_data/{bank}/visible.jsonl"
    question = next(q["question"] for q in json_lines(visible) if q["case_id"] == case["case_id"])
    return {"case_id": case["case_id"], "seed": case["seed"], "source_result_sha256": case["source_result_sha256"],
            "question": question, "checkpoint": point, "prompt_ids": prompt, "observed_generated_ids": generated,
            "rng_state_base64": event["rng_state_base64"], "observed_anchors": anchors, "observed_steps": steps}


def historical_diagnostics(cases):
    result = {}
    for short, case in cases.items():
        raw = read(D3 / case["source_result_path"])
        close = raw["steps"][SOURCE_SPECS[short]["thinking_terminal_step"]]
        picked = re.findall(r"\\boxed\{(\d+)\}", raw["final_response"])
        result[short] = {"case_id": case["case_id"], "seed": case["seed"], "final_box": int(picked[-1]),
                         "thinking_terminal_step": close["step"], "thinking_close_boundary": close["end"],
                         "final_response_sha256": sha256(raw["final_response"].encode()).hexdigest()}
    assert_true([result[k]["final_box"] for k in SOURCE_SPECS] == [45, 303369, 134, 105, 415],
                "Published development endpoints changed")
    # Offline diagnostics never enter an observed checkpoint view.
    witness = [1, 0, 1, 1, 2, 3, 5]
    assert_true(all(a + b <= c for a, b, c in zip(witness, witness[1:], witness[2:])) and 1011235 > 303369,
                "Observed dominance differs")
    def fibbish_suffix(previous, last, value):
        yield value
        for digit in range(previous + last, 10):
            yield from fibbish_suffix(last, digit, value * 10 + digit)
    maximum = max(v for left, right in product(range(1, 10), range(10))
                  for v in fibbish_suffix(left, right, left * 10 + right))
    assert_true(maximum == 10112369, "Offline fibbish maximum differs")
    assert_true(lcm(*set(range(1, 31)).difference({16, 18})) % 18 == 0, "Observed LCM witness differs")
    remaining = lcm(*range(1, 31))
    powers = []
    for prime in range(2, 31):
        factors = [1]
        while remaining % prime == 0:
            remaining //= prime
            factors.append(factors[-1] * prime)
        if len(factors) > 1:
            powers.append(factors)
    divisors = [prod(picked) for picked in product(*powers)]
    count = sum(sum(d % i == 0 for i in range(1, 31)) == 28 for d in divisors)
    assert_true(len(divisors) == 7680 and count == 23, "Offline LCM count differs")
    best = [0]
    for n in range(1, 1001):
        best.append(1 + min(best[n - coin] for coin in (1, 10, 25) if coin <= n))
    greedy = lambda n: n // 25 + n % 25 // 10 + n % 25 % 10
    assert_true(best[45] == greedy(45) == 3, "Observed coin witness differs")
    total = sum(greedy(n) == best[n] for n in range(1, 1001))
    assert_true(total == 610, "Offline coin count differs")
    roots = [n for n in range(289) if (pow(n, 4, 289) + 1) % 289 == 0]
    assert_true(roots == [110, 134, 155, 179], "P02 finite oracle differs")
    assert_true(all(all((pow(n, 4, prime**2) + 1) % (prime**2) != 0 for n in range(prime**2))
                    for prime in (2, 3, 5, 7, 11, 13)), "P02 least prime differs")
    exact_sequence = [Fraction(1, 2) + 5 * k + Fraction(1, 2) * (-3)**k for k in range(5)]
    assert_true(exact_sequence == [1, 4, 15, 2, 61], "E12 exact parameter check differs")
    result["P02"]["offline_only_smaller_value"] = min(roots)
    result["E15"]["offline_only_complete_maximum"] = maximum
    result["E14"]["offline_only_exact_count"] = count
    result["E06"]["offline_only_exact_count"] = total
    return {"scope": "Retrospective endpoints and oracle labels. Excluded from all worker checkpoint views.",
            "cases": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", nargs=2, metavar=("CASE", "WINDOW"))
    args = parser.parse_args()
    tokenizer = make_tokenizer()
    if args.view is not None:
        print(json.dumps(observed_view(tokenizer, read(CHECKPOINTS_FILE), *args.view), ensure_ascii=False))
        return
    hashes = source_hashes()
    inheritance = inherited_evidence(hashes)
    cases = build_cases(tokenizer, hashes)
    table = {"status": "FROZEN_DEV_FIXTURES", "source_baseline_commit": inheritance["baseline_commit"],
             "scope": "Manually selected historical development windows. Use --view CASE WINDOW for prefix-only worker inputs.",
             "cases": cases}
    for short, case in cases.items():
        for window in case["windows"]:
            observed_view(tokenizer, table, short, window)
    # Explicitly confirm development-only values are absent at their chosen windows.
    for short, window, value in (("E15", "last_live_before_close", "10112369"),
                                 ("P02", "first_live_after_selected_lift_claim", "110")):
        view = observed_view(tokenizer, table, short, window)
        text = decode(tokenizer, view["observed_generated_ids"])
        if short == "P02":
            # An unrelated numeral is insufficient to be a previously observed candidate.
            pattern = rf"(?:n|m)\s*=\s*{value}\b"
        else:
            pattern = rf"\b{value}\b"
        assert_true(not re.search(pattern, text), "An offline-only witness is already present at the selected checkpoint")
    write(ROOT / "INHERITED_D3_AUDIT.json", inheritance)
    write(CHECKPOINTS_FILE, table)
    write(ROOT / "D35_HISTORICAL_OUTCOME_DIAGNOSTICS.json", historical_diagnostics(cases))
    print(json.dumps({"status": "PASS", "case_count": len(cases), "windows": sum(
        len(case["windows"]) for case in cases.values()), "checkpoints_sha256": file_sha(CHECKPOINTS_FILE)}))


if __name__ == "__main__":
    main()
