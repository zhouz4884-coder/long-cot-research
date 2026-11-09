"""Freeze Gold-blind observations before any reference scores are opened."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
D35 = ROOT.parent / "phase5d35_witness_gated_revision_20261109"
BASELINE = "3067767577275cd5e2a28b8053acee6d407d6f1c"
OBSERVATIONS = ROOT / "D36_CROSS_PHASE_OBSERVATIONS.json"
SCORES = ROOT / "D36_CROSS_PHASE_SCORES.json"

for folder in (D3, D35):
    sys.path.append(str(folder))

import complete_answer as v1
import complete_answer_v2 as v2
from audit_dev_checkpoints import TOKENIZER, digest_ids, make_tokenizer
from candidate_archive import ObservedPrefix
from numeric_contradiction import scan_numeric_relations
from witness_contract import compile_contract, check_candidate
from witness_verifier import OBSERVED, Witness, WitnessGate


_OBJECTIVE = re.compile(r"(?:^|(?<=[.?!])\s+|\n\s*)(?P<ask>find|compute|determine|what is)\s+",
                        re.I)
_GENERIC_SUBJECT = re.compile(r"(?:the )?(?:(?:final|correct|requested) )?(?:answer|result|value)")
_COPULA = re.compile(r"(?P<subject>[^.!?;:]{1,160}?)\s+(?:is|equals)\s+(?P<answer>.+)\Z", re.I | re.S)
_EXPLICIT_EQUALS = re.compile(r"(?P<subject>[^=.!?;:]{1,100}?)\s*=\s*(?P<answer>.+)\Z", re.S)
_MATH_WRAPPERS = (("$$", "$$"), (r"\[", r"\]"), ("$", "$"), (r"\(", r"\)"))
_REOPEN = re.compile(r"\b(?:but wait|on second thought|actually|instead|reconsider|wrong)\b", re.I)
_ASSIGNMENT = re.compile(
    r"(?:^|(?<=[\n,$;(\[]))[ \t]*(?P<role>[A-Za-z]{1,4}(?:_\{?\d{1,3}\}?)?)"
    r"\s*=\s*(?P<value>[+-]?[0-9]{1,32}(?:/[0-9]{1,32})?)"
    r"(?![0-9A-Za-z_/]|\.[0-9]|[ \t]*[+*/^-])"
)
_ANCHOR_HORIZON = 2400


def sha(raw):
    return sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_bytes())


def verify_published(path):
    raw = path.read_bytes()
    git_name = path.relative_to(REPO).as_posix()
    upstream = subprocess.check_output(["git", "show", f"{BASELINE}:{git_name}"], cwd=REPO)
    if raw != upstream:
        raise ValueError(f"Frozen GitHub artifact differs: {git_name}")
    return raw


def persist(path, value):
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    return sha(payload)


def _normal_subject(text):
    text = v1._normalize(text).casefold()
    text = re.sub(r"\(in [^)]+\)", "", text)
    text = text.replace("_", "").replace("{", "").replace("}", "").replace("$", "")
    text = text.replace(r"\(", "").replace(r"\)", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([+*−-])\s*", r"\1", text)
    return text


def target_metadata(visible):
    question = visible["question"]
    matches = list(_OBJECTIVE.finditer(question))
    asked = question[matches[-1].end():].strip() if matches else ""
    return {"answer_kind": visible["answer_kind"], "requested_surface": asked,
            "requested_normalized": _normal_subject(asked),
            "question_sha256": sha(question.encode())}


def _subject_matches(subject, target, allow_generic):
    subject = _normal_subject(subject)
    requested = target["requested_normalized"]
    if allow_generic and _GENERIC_SUBJECT.fullmatch(subject):
        return True
    if not requested or not subject:
        return False
    if requested == subject:
        return True
    return requested.startswith(subject) and requested[len(subject)] in " .?,:;\n"


def _wrapped(text):
    cleaned = v1._trim_sentence(text)
    return next((cleaned[len(a):-len(b)].strip() for a, b in _MATH_WRAPPERS
                 if cleaned.startswith(a) and cleaned.endswith(b)), cleaned)


def _anchored_surface(payload, target, allow_generic):
    """Accept a complete target-bound boxed or numeric statement, never a substring."""
    body = _wrapped(payload)
    for splitter in (_COPULA, _EXPLICIT_EQUALS):
        found = splitter.fullmatch(body)
        if found is None or not _subject_matches(found["subject"], target, allow_generic):
            continue
        answer = v2.extract_final_answer(found["answer"], target["answer_kind"])
        if answer["status"] == "ok":
            return answer
    return None


def _selected(selection, status, source, start, end, method):
    return {"status": status, "selection": selection, "selection_method": method,
            "char_span": [start, end], "source": source}


def thinking_readout(text, target):
    """Choose the latest complete explicit target candidate within the terminal region."""
    text = text.rstrip()
    earliest = max(0, len(text) - _ANCHOR_HORIZON)
    kind = target["answer_kind"]
    labels = [m for m in v1._LABEL.finditer(text) if m.start() >= earliest]
    if labels:
        label = labels[-1]
        whole = text[label.start():]
        selection = v2.extract_final_answer(whole, kind)
        fallback = _anchored_surface(text[label.end():], target, allow_generic=True)
        if selection["status"] == "ok" or fallback is not None:
            return _selected(selection if selection["status"] == "ok" else fallback, "EXPLICIT_COMMIT",
                             whole, label.start(), len(text), "explicit_final_section")
        return _selected(selection, "MALFORMED_TARGET_CANDIDATE", whole, label.start(), len(text),
                         "malformed_explicit_final_section")

    boxes, unfinished = v1._boxes(text)
    if unfinished:
        return {"status": "MALFORMED_TARGET_CANDIDATE", "selection": None,
                "selection_method": "unterminated_box", "char_span": None, "source": None}
    lines = [(m.start(), m.group()) for m in re.finditer(r"(?m)^[^\n]+", text) if m.group().strip()]
    if lines:
        last_start, last_line = lines[-1]
        anchored = _anchored_surface(last_line, target, allow_generic=True)
        if anchored is not None and not _REOPEN.search(last_line):
            return _selected(anchored, "EXPLICIT_COMMIT", last_line, last_start, len(text), "terminal_target_statement")
    if boxes:
        start, end, value = boxes[-1]
        suffix = text[end:]
        if start >= earliest and re.fullmatch(r"[\s.!。$]*|\s*(?:\\\]|\\\))\s*\.?\s*", suffix):
            selection = v2.extract_final_answer(r"\boxed{" + value + "}", kind)
            if selection["status"] == "ok":
                return _selected(selection, "TENTATIVE_COMPLETE", text[start:end], start, end,
                                 "terminal_unanchored_box")
    return {"status": "NO_COMPLETE_TARGET_CANDIDATE", "selection": None,
            "selection_method": "no_complete_terminal_object", "char_span": None, "source": None}


def final_observation(text, target):
    """Preserve the frozen extraction and expose a narrower, target-linked display diagnostic."""
    official = v2.extract_final_answer(text, target["answer_kind"])
    if official["status"] == "ok":
        return official, {"status": "EXPLICIT_COMMIT", "selection": official, "selection_method": "frozen_v2"}
    lexical = thinking_readout(text, target)
    if lexical["status"] == "EXPLICIT_COMMIT":
        return official, lexical
    labels = list(v1._LABEL.finditer(text))
    if labels:
        terminal = text[labels[-1].end():].strip()
        pieces = re.split(r"\n\s*\n", terminal)
        tail = pieces[-1]
        anchored = _anchored_surface(tail, target, allow_generic=False)
        before = terminal[:len(terminal) - len(tail)]
        if anchored is not None and not v1._boxes(before)[0]:
            offset = text.rfind(tail)
            return official, _selected(anchored, "EXPLICIT_COMMIT", tail, offset, len(text), "target_anchored_final_display")
    return official, lexical


def numeric_same(left, right):
    if left is None or right is None or left["status"] != "ok" or right["status"] != "ok":
        return "UNCOMPARABLE"
    a, b = v1._fingerprint(left), v1._fingerprint(right)
    if a == b:
        return "SAME"
    if a[0] != b[0] or a[2] != b[2] or len(a[3]) != len(b[3]):
        return "DIFFERENT_OBJECT"
    if a[1] is not None and b[1] is not None and a[1] != b[1]:
        return "DIFFERENT_UNIT"
    if a[3] == b[3]:
        return "SAME_OMITTED_UNIT"
    if all(kind == "rational" for kind, _ in a[3] + b[3]):
        return "DIFFERENT_VALUE"
    return "UNCOMPARABLE_NONRATIONAL"


def scoped_value_reuse(text, selected):
    """Record explicit assignments, without treating equal literals as the same object."""
    if not selected or selected.get("status") != "ok" or selected.get("kind") != "scalar":
        return []
    wanted = v1._rational(selected["components"][0])
    if wanted is None:
        return []
    roles = {}
    for match in _ASSIGNMENT.finditer(text):
        if v1._rational(match["value"]) == wanted:
            roles.setdefault(match["role"], {"surface_role": match["role"], "span": list(match.span()),
                                             "source": match[0]})
    return list(roles.values()) if len(roles) > 1 else []


def certificate_for_change(visible, raw, observation, thought, comparison, tokenizer, tokenizer_sha):
    if comparison not in {"DIFFERENT_VALUE", "DIFFERENT_OBJECT"}:
        return {"action": "RETAIN_NATIVE", "reason": "no_comparable_different_object"}
    if observation["status"] != "EXPLICIT_COMMIT" or thought["kind"] != "scalar":
        return {"action": "RETAIN_NATIVE", "reason": "no_complete_explicit_thought_target"}
    contract = compile_contract(visible["question"])
    if contract is None:
        return {"action": "RETAIN_NATIVE", "reason": "no_trusted_task_contract"}
    expected = v1._rational(thought["components"][0])
    if expected is None:
        return {"action": "RETAIN_NATIVE", "reason": "non_exact_thought_value"}
    prefix = ObservedPrefix.from_tokens(
        raw["generated_ids"], lambda ids: tokenizer.decode(list(ids), skip_special_tokens=False),
        prompt_ids=raw["prompt_ids"], tokenizer_sha256=tokenizer_sha,
        trajectory_id=f"{visible['case_id']}_{raw['seed']}",
        question_sha256=sha(visible["question"].encode()),
    )
    gate = WitnessGate(contract, prefix)
    final = next((item for item in reversed(gate.records) if item.segment == "final"
                  and item.goal_claim_type == "FINAL_ANSWER_REVISION"), None)
    matching = (item for item in reversed(gate.records) if item.segment == "thinking"
                and item.goal_claim_type in {"EXACT_ANSWER", "FEASIBLE_CANDIDATE"}
                and v1._rational(str(item.value)) == expected)
    if final is not None:
        for candidate in matching:
            verified = gate.verify(final.candidate_id, Witness(OBSERVED, candidate.candidate_id))
            mathematical = verified.get("mathematical", {})
            if (verified["action"] == "VETO_DRAFT_AND_DELIVER_CERTIFIED"
                    and mathematical.get("proof_scope") == "FULL_OBJECTIVE"
                    and v1._rational(str(verified.get("released_value"))) == expected):
                return verified
    return {"action": "RETAIN_NATIVE", "reason": "no_replayable_full_objective_certificate_for_observed_value"}


def literal_controls():
    contract_path = D3 / "prepared_data/bank/visible.jsonl"
    cases = [json.loads(line) for line in verify_published(contract_path).splitlines()]
    e15, = (row for row in cases if row["case_id"] == "D3_E15")
    contract = compile_contract(e15["question"])
    expected = {10112358: "FEASIBLE_ONLY", 10112357: "INVALID_CANDIDATE"}
    results = {str(value): check_candidate(contract, value) for value in expected}
    if any(results[str(value)]["status"] != status for value, status in expected.items()):
        raise ValueError("E15 exact feasibility control failed")
    return results


def observe():
    freeze = json.loads(verify_published(D3 / "bank/GRADE_FREEZE.json"))
    retrieved = json.loads(verify_published(D3 / "BANK_RETRIEVAL.json"))
    sources = {row["path"]: row["sha256"] for row in retrieved["files"]}
    visible_raw = verify_published(D3 / "prepared_data/bank/visible.jsonl")
    visible = {row["case_id"]: row for row in map(json.loads, visible_raw.splitlines())}
    tokenizer = make_tokenizer()
    begin, = tokenizer.encode("<think>", add_special_tokens=False)
    close, = tokenizer.encode("</think>", add_special_tokens=False)
    tokenizer_sha = sha((TOKENIZER / "tokenizer.json").read_bytes())
    if len(freeze["records"]) != 32 or len(visible) != 16:
        raise ValueError("Unexpected native bank shape")
    observations = []
    keys = set()
    for spec in freeze["records"]:
        case, seed = spec["case_id"], spec["seed"]
        if (case, seed) in keys or spec["arm"] != "NativeContinue":
            raise ValueError("Duplicate or non-native bank row")
        keys.add((case, seed))
        raw_bytes = verify_published(D3 / spec["path"])
        digest = sha(raw_bytes)
        if digest != spec["sha256"] or digest != sources[spec["path"]]:
            raise ValueError("Native bank result mismatches freeze or retrieval")
        raw = json.loads(raw_bytes)
        ids = raw["generated_ids"]
        if (raw["case_id"] != case or raw["seed"] != seed or raw["EOS"] is not True
                or raw["think_closed"] is not True or raw["stop_reason"] != "EOS"
                or ids[0] != begin or ids.count(close) != 1
                or digest_ids(ids) != raw["generated_sha256"]
                or digest_ids(raw["prompt_ids"]) != raw["prompt_sha256"]
                or tokenizer.decode(ids, skip_special_tokens=False) != raw["text"]):
            raise ValueError("The original natural-EOS result or token boundary failed verification")
        cut = ids.index(close)
        thought_text = tokenizer.decode(ids[1:cut], skip_special_tokens=False)
        final_text = tokenizer.decode(ids[cut + 1:], skip_special_tokens=True)
        if final_text != raw["final_response"]:
            raise ValueError("Token-derived final differs from frozen original final text")
        target = target_metadata(visible[case])
        observed = thinking_readout(thought_text, target)
        thought = observed["selection"]
        official, diagnostic = final_observation(final_text, target)
        final = diagnostic.get("selection")
        comparison = numeric_same(thought, final)
        authorization = certificate_for_change(visible[case], raw, observed, thought, comparison,
                                                tokenizer, tokenizer_sha)
        literal_thought = scan_numeric_relations(thought_text)
        literal_final = scan_numeric_relations(final_text)
        observations.append({"case_id": case, "seed": seed, "source_path": spec["path"],
                             "source_sha256": digest, "think_close_generated_index": cut,
                             "think_text_sha256": sha(thought_text.encode()),
                             "final_text_sha256": sha(final_text.encode()), "target": target,
                             "thinking": observed, "frozen_final": official, "target_final": diagnostic,
                             "target_comparison": comparison, "strict_comparison": numeric_same(thought, official),
                             "distinct_named_contexts_for_thinking_literal": scoped_value_reuse(thought_text, thought),
                             "distinct_named_contexts_for_final_literal": scoped_value_reuse(final_text, final),
                             "gate": authorization, "thinking_numeric_relations": literal_thought,
                             "final_numeric_relations": literal_final})
    covered = Counter(row["case_id"] for row in observations)
    if set(covered) != set(visible) or set(covered.values()) != {2}:
        raise ValueError("Historical bank is not paired by question")
    scripts = (Path(__file__), ROOT / "numeric_contradiction.py", D3 / "complete_answer.py",
               D3 / "complete_answer_v2.py", D35 / "candidate_archive.py", D35 / "goal_claim_detector.py",
               D35 / "witness_contract.py", D35 / "witness_verifier.py")
    provenance = {p.relative_to(REPO).as_posix(): sha(p.read_bytes()) for p in scripts}
    report = {"status": "FROZEN_BEFORE_REFERENCE", "frozen_utc": utc(), "baseline_commit": BASELINE,
              "scoring_reference_opened": False, "historical_score_receipt_opened": False,
              "source_sha256": provenance, "tokenizer_sha256": tokenizer_sha,
              "visible_question_sha256": sha(visible_raw), "additional_gpu_seconds": 0,
              "e15_feasibility_controls": literal_controls(), "trajectories": observations}
    digest = persist(OBSERVATIONS, report)
    print(json.dumps({"status": report["status"], "observations_sha256": digest,
                      "trajectories": len(observations), "thought_status": Counter(r["thinking"]["status"] for r in observations),
                      "target_comparison": Counter(r["target_comparison"] for r in observations)}))


def _numeric_summary(rows):
    summary = {}
    for phase in ("thinking", "final"):
        groups = [row[f"{phase}_numeric_relations"] for row in rows]
        hits = [item for group in groups for item in group]
        flags = [item for item in hits if item["scope"] == "ASSERTED_EXACT" and not item["exact_truth"]]
        summary[phase] = {"parsed_relations": len(hits), "by_scope": Counter(item["scope"] for item in hits),
                          "trajectories_with_parsed_relation": sum(bool(group) for group in groups),
                          "trajectories_with_asserted_false_relation": sum(
                              any(item["scope"] == "ASSERTED_EXACT" and not item["exact_truth"] for item in group)
                              for group in groups),
                          "problems_with_asserted_false_relation": len({row["case_id"] for row, group in zip(rows, groups)
                              if any(item["scope"] == "ASSERTED_EXACT" and not item["exact_truth"] for item in group)}),
                          "asserted_false_relations": len(flags),
                          "other_scope_false_relations": sum(not item["exact_truth"] for item in hits) - len(flags),
                          "e15_observed_conflict_sources": [item for item in flags
                              if {item["left"], item["right"]} == {"1011235", "303369"}]}
    return summary


def score(observation_sha):
    frozen_raw = OBSERVATIONS.read_bytes()
    frozen = json.loads(frozen_raw)
    if (sha(frozen_raw) != observation_sha or frozen["status"] != "FROZEN_BEFORE_REFERENCE"
            or frozen["scoring_reference_opened"] or frozen["historical_score_receipt_opened"]):
        raise ValueError("A separately frozen Gold-blind selection is required")
    if any(sha((REPO / rel).read_bytes()) != digest for rel, digest in frozen["source_sha256"].items()):
        raise ValueError("Extraction source changed after observation freeze")
    grading = json.loads(verify_published(D3 / "bank/GRADE_FREEZE.json"))
    opened = utc()
    gold_raw = verify_published(D3 / "prepared_data/bank/eval_only.jsonl")
    if sha(gold_raw) != grading["eval_sha256"]:
        raise ValueError("Gold references do not match frozen score freeze")
    answers = {row["case_id"]: row for row in map(json.loads, gold_raw.splitlines())}
    inherited = json.loads(verify_published(D3 / "bank/SCORES.json"))
    original = {(row["case_id"], row["seed"]): row for row in inherited["scores"]}
    backend = v2.backend_status()
    if backend["status"] != "ok":
        raise ValueError(f"Pinned reference grading backend missing: {backend}")

    def grade_observation(row):
        case, seed = row["case_id"], row["seed"]
        gold = answers[case]["gold"]
        native = original[(case, seed)]
        official = row["frozen_final"]
        if (row["source_sha256"] != native["sha256"] or official != native["selection"]
                or native["grade"]["correct"] not in (True, False)):
            raise ValueError("Phase diagnostic changes an official frozen row")
        thought = row["thinking"]["selection"]
        target_final = row["target_final"].get("selection")
        def status(selection):
            if not selection or selection["status"] != "ok":
                return None
            return v2.grade_final_answer(selection, gold)["correct"]
        thought_ok = status(thought)
        target_final_ok = status(target_final)
        final_ok = native["grade"]["correct"]
        certified_override = row["gate"]["action"] == "VETO_DRAFT_AND_DELIVER_CERTIFIED"
        return {"case_id": case, "seed": seed, "official_final_correct": final_ok,
                "thinking_status": row["thinking"]["status"], "thinking_correct": thought_ok,
                "target_final_correct": target_final_ok, "frozen_final_status": official["status"],
                "target_comparison": row["target_comparison"], "strict_comparison": row["strict_comparison"],
                "gate_action": row["gate"]["action"],
                "certified_gate_correct": thought_ok if certified_override else final_ok,
                "blind_thought_only_correct": thought_ok is True,
                "blind_thought_else_native_correct": final_ok if thought_ok is None else thought_ok}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(grade_observation, frozen["trajectories"]))
    if len(results) != 32 or sum(r["official_final_correct"] for r in results) != 16:
        raise ValueError("The original bank score did not reproduce")
    matrix = lambda field: {
        "thinking_" + a + "_final_" + b: sum(r["thinking_correct"] is av and r[field] is bv for r in results)
        for a, av in (("correct", True), ("wrong", False), ("missing_or_unknown", None))
        for b, bv in (("correct", True), ("wrong", False), ("missing_or_unknown", None))}
    changed = [r for r in results if r["target_comparison"] in {"DIFFERENT_VALUE", "DIFFERENT_OBJECT", "DIFFERENT_UNIT"}]
    paths = defaultdict(list)
    for row in results:
        paths[row["case_id"]].append(row)
    native = "official_final_correct"
    arms = ("blind_thought_only_correct", "blind_thought_else_native_correct", "certified_gate_correct")
    summary = {
        name: {"correct": sum(row[name] is True for row in results),
               "rescued_native_wrong": sum(row[name] is True and not row[native] for row in results),
               "harmed_native_correct": sum(row[name] is not True and row[native] for row in results),
               "problem_clusters": dict(Counter(
                   f"{sum(row[name] is True for row in group) - sum(row[native] is True for row in group):+d}"
                   for group in paths.values()))}
        for name in arms
    }
    conditional = {"comparable_different_complete_candidate_trajectories": len(changed),
                   "different_candidate_problem_clusters": len({r["case_id"] for r in changed}),
                   "official_final_wrong_numerator": sum(not r[native] for r in changed),
                   "official_final_correct_numerator": sum(r[native] for r in changed),
                   "target_final_wrong_numerator": sum(r["target_final_correct"] is False for r in changed),
                   "target_final_correct_numerator": sum(r["target_final_correct"] is True for r in changed),
                   "target_final_unknown_numerator": sum(r["target_final_correct"] is None for r in changed)}
    output = {"status": "COMPLETE_HISTORICAL_DIAGNOSTIC", "first_reference_read_utc": opened,
              "frozen_observation_sha256": observation_sha, "grading_backend": backend, "additional_gpu_seconds": 0,
              "official_d3_final_correct": 16, "trajectories": 32, "distinct_problems": len(paths),
              "matrices": {"official_frozen_final": matrix(native), "target_final_diagnostic": matrix("target_final_correct")},
              "conditional_on_different_target": conditional, "arm_descriptive_comparison": summary,
              "target_comparison_counts": Counter(r["target_comparison"] for r in results),
              "scoped_numeric_reuse_trajectories": sum(bool(r["distinct_named_contexts_for_thinking_literal"]
                  or r["distinct_named_contexts_for_final_literal"]) for r in frozen["trajectories"]),
              "numeric_literal_summary": _numeric_summary(frozen["trajectories"]),
              "per_problem": dict(paths)}
    digest = persist(SCORES, output)
    print(json.dumps({key: value for key, value in output.items() if key not in ("per_problem", "numeric_literal_summary")}))
    print(json.dumps({"scores_sha256": digest, "numeric": output["numeric_literal_summary"]}))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("observe")
    grading = sub.add_parser("score")
    grading.add_argument("--observation-sha", required=True)
    args = parser.parse_args()
    if args.operation == "observe":
        observe()
    else:
        score(args.observation_sha)


if __name__ == "__main__":
    main()
